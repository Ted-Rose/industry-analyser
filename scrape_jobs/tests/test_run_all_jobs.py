"""run_all_jobs unit tests — schedule predicates and flag behavior.

No real sub-jobs run: Command._run_entry / subprocess.call /
call_command are mocked out.
"""

import io
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone
from unittest import mock

from django.conf import settings
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

    def test_invalid_weekly_schedule_raises_value_error(self):
        for schedule in ('weekly:bogus', 'weekly:', 'weekly:monday'):
            with self.assertRaises(ValueError, msg=schedule):
                is_due(schedule, date(2026, 10, 19))

    def test_invalid_dom_schedule_raises_value_error(self):
        for schedule in ('dom:abc', 'dom:', 'dom:1x',
                         'dom:0', 'dom:32', 'dom:-1'):
            with self.assertRaises(ValueError, msg=schedule):
                is_due(schedule, date(2026, 10, 19))

    def test_all_jobs_schedules_parse(self):
        for _label, _kind, _argv, schedule in JOBS:
            is_due(schedule, date(2026, 10, 19), 'local')


class LocalScheduleTests(SimpleTestCase):
    """local:<schedule> — the inner predicate applies only on
    local executions; 'gcp_cloud_run' is never due."""

    def test_local_daily_due_for_local_executor(self):
        self.assertTrue(
            is_due('local:daily', date(2026, 10, 19), 'local')
        )

    def test_local_daily_never_due_on_gcp(self):
        self.assertFalse(
            is_due(
                'local:daily', date(2026, 10, 19),
                'gcp_cloud_run',
            )
        )

    def test_local_wraps_inner_schedule(self):
        # The inner calendar predicate still applies locally.
        self.assertTrue(
            is_due('local:dom:odd', date(2026, 10, 19), 'local')
        )
        self.assertFalse(
            is_due('local:dom:odd', date(2026, 10, 20), 'local')
        )

    def test_local_inner_spec_still_validated_on_gcp(self):
        # A typo'd inner spec must raise even where the entry
        # could never run — otherwise it dies silently.
        with self.assertRaises(ValueError):
            is_due(
                'local:bogus', date(2026, 10, 19),
                'gcp_cloud_run',
            )

    def test_local_cannot_nest_or_be_empty(self):
        for schedule in ('local:local:daily', 'local:'):
            with self.assertRaises(ValueError, msg=schedule):
                is_due(schedule, date(2026, 10, 19), 'local')

    def test_executor_defaults_to_detected(self):
        with mock.patch(
            f'{MODULE}.detect_executed_by',
            return_value='gcp_cloud_run',
        ):
            self.assertFalse(
                is_due('local:daily', date(2026, 10, 19))
            )


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
        # Every daily entry is due on a local pass;
        # last_day_of_month (sync_receipt_emails) is not. The
        # local:daily news jobs are due locally as well.
        with _patched_today(date(2026, 10, 19)):
            run, _ = self._handle()
        self.assertEqual(
            self._labels(run),
            ['scrape_tv_programs', 'scrape_housing_ads',
             'scrape_apartment_ads', 'scrape_vacancy',
             'link_ads_to_properties', 'scrape_news',
             'link_news_stories', 'build_news_digest'],
        )

    def test_dry_run_prints_plan_and_runs_nothing(self):
        with _patched_today(date(2026, 10, 19)):
            with mock.patch(
                f'{MODULE}.detect_executed_by',
                return_value='local',
            ):
                run, out = self._handle(dry_run=True)
        run.assert_not_called()
        self.assertIn('executor: local', out)
        self.assertIn('RUN  scrape_tv_programs', out)
        self.assertIn('RUN  scrape_housing_ads', out)
        self.assertIn('RUN  scrape_apartment_ads', out)
        self.assertIn('RUN  link_ads_to_properties', out)
        self.assertIn('RUN  scrape_vacancy', out)
        self.assertIn('RUN  scrape_news', out)
        self.assertIn('RUN  link_news_stories', out)
        self.assertIn('RUN  build_news_digest', out)
        self.assertIn('skip sync_receipt_emails', out)
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

    def test_only_takes_precedence_over_force(self):
        # With both flags, --only wins: a single entry runs,
        # ignoring its schedule.
        run, _ = self._handle(only='scrape_vacancy', force=True)
        self.assertEqual(self._labels(run), ['scrape_vacancy'])

    def test_force_runs_all_non_manual_entries(self):
        run, _ = self._handle(force=True)
        self.assertEqual(
            self._labels(run),
            ['sync_receipt_emails', 'scrape_tv_programs',
             'scrape_housing_ads', 'scrape_apartment_ads',
             'scrape_vacancy', 'link_ads_to_properties',
             'scrape_news', 'link_news_stories',
             'build_news_digest'],
        )

    def test_failure_continues_and_exits_nonzero(self):
        with _patched_today(date(2026, 10, 19)):
            with mock.patch.object(Command, '_run_entry') as run:
                run.side_effect = [RuntimeError('boom')] + [None] * 7
                with self.assertRaises(CommandError) as ctx:
                    call_command('run_all_jobs')
        self.assertEqual(
            self._labels(run),
            ['scrape_tv_programs', 'scrape_housing_ads',
             'scrape_apartment_ads', 'scrape_vacancy',
             'link_ads_to_properties', 'scrape_news',
             'link_news_stories', 'build_news_digest'],
        )
        self.assertIn('scrape_tv_programs', str(ctx.exception))

    def test_failure_reports_to_sentry_and_continues(self):
        # Each sub-job failure is captured as an internal_error
        # event; with no SENTRY_DSN the capture call is a no-op,
        # so the loop is unaffected either way.
        with _patched_today(date(2026, 10, 19)):
            with mock.patch.object(Command, '_run_entry') as run:
                run.side_effect = [RuntimeError('boom')] + [None] * 7
                with mock.patch(
                    f'{MODULE}.capture_internal_exception'
                ) as capture:
                    with self.assertRaises(CommandError):
                        call_command('run_all_jobs')
        capture.assert_called_once()
        self.assertIsInstance(
            capture.call_args.args[0], RuntimeError
        )

    def test_system_exit_in_subjob_does_not_abort_pass(self):
        # A sub-command calling sys.exit() is recorded as a failure,
        # not allowed to abort the remaining entries.
        with _patched_today(date(2026, 10, 19)):
            with mock.patch.object(Command, '_run_entry') as run:
                run.side_effect = [SystemExit(1)] + [None] * 7
                with self.assertRaises(CommandError) as ctx:
                    call_command('run_all_jobs')
        self.assertEqual(
            self._labels(run),
            ['scrape_tv_programs', 'scrape_housing_ads',
             'scrape_apartment_ads', 'scrape_vacancy',
             'link_ads_to_properties', 'scrape_news',
             'link_news_stories', 'build_news_digest'],
        )
        self.assertIn('scrape_tv_programs', str(ctx.exception))

    def test_bad_specs_fail_up_front_and_are_skipped(self):
        # Malformed entries are validated before anything runs:
        # they count as failures and are skipped, while valid
        # entries still run — the failure doesn't depend on where
        # the bad spec sits in JOBS. --force is used on purpose:
        # it never calls is_due, so a bad schedule would otherwise
        # go unnoticed.
        jobs = [
            ('ok_first', 'command', [], 'daily'),
            ('bad_schedule', 'command', [], 'weekly:funday'),
            ('bad_kind', 'bogus', [], 'daily'),
            ('bad_script_argv', 'script', [], 'daily'),
            ('bad_tuple', 'command'),
            ('ok_last', 'command', [], 'daily'),
        ]
        with mock.patch(f'{MODULE}.JOBS', jobs):
            with mock.patch.object(Command, '_run_entry') as run:
                with self.assertRaises(CommandError) as ctx:
                    call_command('run_all_jobs', force=True)
        self.assertEqual(
            self._labels(run), ['ok_first', 'ok_last']
        )
        for bad in ('bad_schedule', 'bad_kind', 'bad_script_argv',
                    'bad_tuple'):
            self.assertIn(bad, str(ctx.exception), msg=bad)

    def test_degenerate_entries_fail_cleanly(self):
        # Entries that aren't a 4-tuple at all, or whose label
        # isn't a string, are recorded as failures via a clean
        # CommandError — never an uncaught TypeError from job[0]
        # or ', '.join(failed) — while valid entries still run.
        jobs = [
            ('ok_first', 'command', [], 'daily'),
            42,
            (123, 'command', [], 'daily'),
            ('ok_last', 'command', [], 'daily'),
        ]
        with mock.patch(f'{MODULE}.JOBS', jobs):
            with mock.patch.object(Command, '_run_entry') as run:
                with self.assertRaises(CommandError) as ctx:
                    call_command('run_all_jobs', force=True)
        self.assertEqual(
            self._labels(run), ['ok_first', 'ok_last']
        )
        self.assertIn('42', str(ctx.exception))
        self.assertIn('123', str(ctx.exception))

        # The --only pre-scan reads entry labels before validation
        # too — it must not crash on a non-subscriptable entry.
        with mock.patch(f'{MODULE}.JOBS', jobs):
            with mock.patch.object(Command, '_run_entry') as run:
                with self.assertRaises(CommandError) as ctx:
                    call_command('run_all_jobs', only='ok_first')
        self.assertEqual(self._labels(run), ['ok_first'])
        self.assertIn('42', str(ctx.exception))

    def test_dry_run_also_validates_specs(self):
        jobs = [('bad', 'command', [], 'dom:funday')]
        with mock.patch(f'{MODULE}.JOBS', jobs):
            with self.assertRaises(CommandError):
                call_command('run_all_jobs', dry_run=True)

    def test_command_entry_dispatches_call_command(self):
        with mock.patch(f'{MODULE}.call_command') as cc:
            call_command('run_all_jobs', only='scrape_tv_programs')
        cc.assert_called_once_with(
            'scrape_tv_programs', '--days-past', '1'
        )

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
        self.assertEqual(list(argv[2:]), ['--no-ocr'])
        self.assertEqual(
            sp.call_args.kwargs['cwd'], str(settings.BASE_DIR)
        )

    def test_script_nonzero_exit_marks_job_failed(self):
        with mock.patch(f'{MODULE}.subprocess.call', return_value=1):
            with self.assertRaises(CommandError):
                call_command('run_all_jobs', only='scrape_vacancy')

    def test_local_pass_includes_news_jobs(self):
        # A local pass runs every `daily` entry plus the
        # local:daily news jobs (only last_day_of_month is not
        # due on the 20th).
        with _patched_today(date(2026, 10, 20)):
            with mock.patch(
                f'{MODULE}.detect_executed_by',
                return_value='local',
            ):
                run, _ = self._handle()
        self.assertEqual(
            self._labels(run),
            ['scrape_tv_programs', 'scrape_housing_ads',
             'scrape_apartment_ads', 'scrape_vacancy',
             'link_ads_to_properties', 'scrape_news',
             'link_news_stories', 'build_news_digest'],
        )

    def test_gcp_pass_skips_news_jobs(self):
        # On Cloud Run only the plain `daily` entries are due —
        # the local:daily news jobs never run there.
        with _patched_today(date(2026, 10, 20)):
            with mock.patch(
                f'{MODULE}.detect_executed_by',
                return_value='gcp_cloud_run',
            ):
                run, _ = self._handle()
        self.assertEqual(
            self._labels(run),
            ['scrape_tv_programs', 'scrape_housing_ads',
             'scrape_apartment_ads', 'scrape_vacancy',
             'link_ads_to_properties'],
        )

    def test_gcp_dry_run_shows_news_skipped(self):
        with _patched_today(date(2026, 10, 20)):
            with mock.patch(
                f'{MODULE}.detect_executed_by',
                return_value='gcp_cloud_run',
            ):
                run, out = self._handle(dry_run=True)
        run.assert_not_called()
        self.assertIn('executor: gcp_cloud_run', out)
        self.assertIn('RUN  scrape_vacancy', out)
        self.assertIn('skip scrape_news', out)
        self.assertIn('skip link_news_stories', out)
        self.assertIn('skip build_news_digest', out)

    def test_force_still_skips_local_jobs_on_gcp(self):
        # --force overrides the calendar, not the executor —
        # local:daily news jobs must never run on Cloud Run.
        with mock.patch(
            f'{MODULE}.detect_executed_by',
            return_value='gcp_cloud_run',
        ):
            run, _ = self._handle(force=True)
        self.assertNotIn('scrape_news', self._labels(run))
        self.assertNotIn('link_news_stories', self._labels(run))
        self.assertNotIn('build_news_digest', self._labels(run))

    def test_only_still_overrides_the_gate(self):
        # --only is the deliberate operator escape hatch —
        # it ignores the schedule, including local:*.
        with mock.patch(
            f'{MODULE}.detect_executed_by',
            return_value='gcp_cloud_run',
        ):
            run, _ = self._handle(only='scrape_news')
        self.assertEqual(self._labels(run), ['scrape_news'])
