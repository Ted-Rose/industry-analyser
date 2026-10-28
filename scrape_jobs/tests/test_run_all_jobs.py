"""run_all_jobs unit tests — schedule predicates and flag behavior.

No real sub-jobs run: Command._run_entry / subprocess.call /
call_command are mocked out.
"""

import io
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from scrape_jobs.management.commands.run_all_jobs import (
    JOBS,
    Command,
    is_due,
)

MODULE = 'scrape_jobs.management.commands.run_all_jobs'


@contextmanager
def _patched_today(day):
    """Pin the command's idea of 'today' (UTC) to ``day``."""
    with mock.patch(f'{MODULE}.datetime') as mock_dt:
        mock_dt.now.return_value = datetime(
            day.year, day.month, day.day, tzinfo=timezone.utc
        )
        yield


class SchedulePredicateTests(SimpleTestCase):

    def test_daily_always_due(self):
        self.assertTrue(is_due('daily', date(2026, 10, 28)))

    def test_manual_never_due(self):
        self.assertFalse(is_due('manual', date(2026, 10, 28)))

    def test_weekly_matches_weekday(self):
        monday = date(2026, 10, 19)
        self.assertTrue(is_due('weekly:mon', monday))
        self.assertFalse(is_due('weekly:tue', monday))
        self.assertTrue(is_due('weekly:sun', date(2026, 10, 25)))

    def test_dom_odd(self):
        self.assertTrue(is_due('dom:odd', date(2026, 10, 19)))
        self.assertFalse(is_due('dom:odd', date(2026, 10, 20)))
        self.assertTrue(is_due('dom:odd', date(2026, 10, 31)))

    def test_dom_specific_day(self):
        self.assertTrue(is_due('dom:3', date(2026, 10, 3)))
        self.assertFalse(is_due('dom:3', date(2026, 10, 4)))

    def test_last_day_of_month(self):
        self.assertTrue(
            is_due('last_day_of_month', date(2026, 10, 31))
        )
        self.assertFalse(
            is_due('last_day_of_month', date(2026, 10, 30))
        )
        # February in leap and non-leap years.
        self.assertTrue(
            is_due('last_day_of_month', date(2024, 2, 29))
        )
        self.assertTrue(
            is_due('last_day_of_month', date(2026, 2, 28))
        )
        self.assertFalse(
            is_due('last_day_of_month', date(2026, 2, 27))
        )

    def test_unknown_schedule_raises(self):
        with self.assertRaises(ValueError):
            is_due('bogus', date(2026, 10, 19))

    def test_all_jobs_schedules_parse(self):
        for _label, _kind, _argv, schedule in JOBS:
            is_due(schedule, date(2026, 10, 19))


class RunAllJobsTests(SimpleTestCase):

    @staticmethod
    def _labels(run_mock):
        return [call.args[0] for call in run_mock.call_args_list]

    def _handle(self, **kwargs):
        out = io.StringIO()
        with mock.patch.object(Command, '_run_entry') as run:
            call_command('run_all_jobs', stdout=out, **kwargs)
        return run, out.getvalue()

    def test_normal_pass_runs_only_due_entries_in_order(self):
        # 2026-10-19 is a Monday with an odd day-of-month:
        # weekly:mon + dom:odd due; last_day_of_month + manual not.
        with _patched_today(date(2026, 10, 19)):
            run, _ = self._handle()
        self.assertEqual(
            self._labels(run),
            ['scrape_tv_programs', 'scrape_housing_ads',
             'scrape_apartment_ads'],
        )

    def test_dry_run_prints_plan_and_runs_nothing(self):
        with _patched_today(date(2026, 10, 19)):
            run, out = self._handle(dry_run=True)
        run.assert_not_called()
        self.assertIn('RUN  scrape_tv_programs', out)
        self.assertIn('RUN  scrape_housing_ads', out)
        self.assertIn('skip sync_receipt_emails', out)
        self.assertIn('skip link_ads_to_properties', out)
        self.assertIn('skip scrape_vacancy', out)
        for label, _kind, _argv, _schedule in JOBS:
            self.assertIn(label, out)

    def test_only_runs_one_entry_ignoring_schedule(self):
        run, _ = self._handle(only='link_ads_to_properties')
        self.assertEqual(self._labels(run), ['link_ads_to_properties'])
        call = run.call_args_list[0]
        self.assertEqual(call.args[1], 'command')
        self.assertEqual(call.args[2], ['--older-than-days', '3'])

    def test_only_unknown_label_errors(self):
        with self.assertRaises(CommandError):
            self._handle(only='nosuchjob')

    def test_force_runs_all_non_manual_entries(self):
        run, _ = self._handle(force=True)
        self.assertEqual(
            self._labels(run),
            ['sync_receipt_emails', 'scrape_tv_programs',
             'scrape_housing_ads', 'scrape_apartment_ads'],
        )

    def test_failure_continues_and_exits_nonzero(self):
        with _patched_today(date(2026, 10, 19)):
            with mock.patch.object(Command, '_run_entry') as run:
                run.side_effect = [RuntimeError('boom'), None, None]
                with self.assertRaises(CommandError) as ctx:
                    call_command('run_all_jobs')
        self.assertEqual(
            self._labels(run),
            ['scrape_tv_programs', 'scrape_housing_ads',
             'scrape_apartment_ads'],
        )
        self.assertIn('scrape_tv_programs', str(ctx.exception))

    def test_command_entry_dispatches_call_command(self):
        with mock.patch(f'{MODULE}.call_command') as cc:
            call_command('run_all_jobs', only='scrape_tv_programs')
        cc.assert_called_once_with('scrape_tv_programs')

    def test_script_entry_runs_via_subprocess(self):
        with mock.patch(
            f'{MODULE}.subprocess.call', return_value=0
        ) as sp:
            call_command('run_all_jobs', only='scrape_vacancy')
        sp.assert_called_once()
        argv = sp.call_args.args[0]
        self.assertEqual(argv[0], sys.executable)
        self.assertTrue(
            argv[1].endswith(
                'scripts/materialize_fetcher_config_and_scrape.py'
            )
        )

    def test_script_nonzero_exit_marks_job_failed(self):
        with mock.patch(f'{MODULE}.subprocess.call', return_value=1):
            with self.assertRaises(CommandError):
                call_command('run_all_jobs', only='scrape_vacancy')
