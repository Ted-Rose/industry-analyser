"""Master Cloud Run job: run all enabled sub-jobs sequentially.

``python manage.py run_all_jobs`` iterates the ``JOBS`` list below in
listed order — each entry runs only when its schedule predicate
matches today's UTC date. Comment a line out to disable a sub-job;
this file is the single source of truth for which jobs run in the
consolidated ``all-jobs`` Cloud Run job.

Schedules (evaluated against today's UTC date):
    daily                every day
    local:<schedule>     like <schedule>, but only on local
                         executions — never due on GCP Cloud
                         Run, not even under --force (news
                         feeds must be scraped locally only)
    weekly:<mon..sun>    once a week on that weekday
    dom:odd              odd days of the month (cron ``*/2`` dom)
    dom:<N>              day N of the month
    last_day_of_month    last calendar day of the month
    manual               never in a normal pass; only via --only
"""

import calendar
import logging
import subprocess
import sys
from datetime import datetime, timezone

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from industry_analyser.sentry import capture_internal_exception
from scrape_jobs.runner import detect_executed_by

logger = logging.getLogger('scrape_jobs')

# One sub-job per line: (label, kind, argv, schedule).
#   kind 'command' → call_command(label, *argv)
#   kind 'script'  → subprocess [sys.executable, BASE_DIR/argv[0],
#                     *argv[1:]] — for jobs whose entry point is a
#                     script, not a management command.
# Entries run sequentially in listed order; comment a line out to
# disable that sub-job.
JOBS = [
    # Receipts first: it was scheduled an hour earlier than the rest
    # upstream for free-tier Gemini quota headroom.
    ('sync_receipt_emails', 'command', ['--last-day-only'],
     'last_day_of_month'),
    ('scrape_tv_programs', 'command', [], 'dom:odd'),
    ('scrape_housing_ads', 'command', [], 'dom:odd'),
    ('scrape_apartment_ads', 'command', [], 'dom:odd'),
    ('scrape_vacancy', 'script',
     ['scripts/materialize_fetcher_config_and_scrape.py'], 'manual'),
    # Linking runs on the same odd-day pass, right after the
    # classified-ads scrapes above (scrape_vacancy stays manual).
    ('link_ads_to_properties', 'command', ['--older-than-days', '3'],
     'dom:odd'),
    # News digest pipeline: scrape feeds, cluster into stories,
    # build the daily digest — in that order. local:daily —
    # the feeds are scraped from the maintainer's machine;
    # Cloud Run must never run them.
    ('scrape_news', 'command', [], 'local:daily'),
    ('link_news_stories', 'command', [], 'local:daily'),
    ('build_news_digest', 'command', [], 'local:daily'),
    # ('sync_apartment_regions', 'command', [], 'manual'),
    # ('sync_housing_regions', 'command', [], 'manual'),
]

_WEEKDAYS = {
    'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3,
    'fri': 4, 'sat': 5, 'sun': 6,
}


def is_due(schedule, today, executed_by=None):
    """True when ``schedule`` matches the UTC date ``today``.

    ``manual`` is never due — those entries run only via --only (and
    stay skipped under --force). ``local:<schedule>`` wraps any
    other schedule: it is due only when the inner schedule matches
    AND the pass runs locally — ``executed_by`` defaults to
    ``detect_executed_by()``, and 'gcp_cloud_run' is never due.
    """
    if schedule.startswith('local:'):
        inner = schedule.split(':', 1)[1]
        if not inner or inner.startswith('local:'):
            raise ValueError(
                f'invalid schedule {schedule!r}: empty or '
                'nested local: schedules are not allowed'
            )
        # Evaluate the inner spec first so a typo'd
        # 'local:bogus' still raises — on Cloud Run an
        # executor-gated skip would otherwise hide it and
        # leave a silently-dead entry.
        inner_due = is_due(inner, today, executed_by)
        if executed_by is None:
            executed_by = detect_executed_by()
        return inner_due and executed_by == 'local'
    if schedule == 'daily':
        return True
    if schedule == 'manual':
        return False
    if schedule == 'last_day_of_month':
        last = calendar.monthrange(today.year, today.month)[1]
        return today.day == last
    if schedule.startswith('dom:'):
        dom = schedule.split(':', 1)[1]
        if dom == 'odd':
            return today.day % 2 == 1
        try:
            day = int(dom)
        except ValueError:
            raise ValueError(
                f'invalid schedule {schedule!r}: {dom!r} is '
                'not an integer day-of-month'
            ) from None
        if not 1 <= day <= 31:
            raise ValueError(
                f'invalid schedule {schedule!r}: day {day} '
                'out of range'
            )
        return today.day == day
    if schedule.startswith('weekly:'):
        name = schedule.split(':', 1)[1]
        if name not in _WEEKDAYS:
            raise ValueError(
                f'invalid schedule {schedule!r}: unknown '
                f'weekday {name!r}'
            )
        return today.weekday() == _WEEKDAYS[name]
    raise ValueError(f'unknown schedule {schedule!r}')


def _entry_label(job):
    """Best-effort string label for a JOBS entry — never raises.

    Used on paths that run before (or while recovering from) entry
    validation, so a degenerate entry — a bare ``42``, a non-string
    label — can't crash the pass with a TypeError or poison the
    ``', '.join(failed)`` error message.
    """
    if isinstance(job, (list, tuple)) and job:
        return str(job[0])
    return repr(job)


def _validate_job_spec(
    label, kind, argv, schedule, today, executed_by,
):
    """Raise ValueError when a JOBS entry's spec is malformed.

    Checked up front for every entry — including under --force,
    which never calls is_due — so a typo'd schedule or kind fails
    its entry before anything runs instead of crashing the pass
    halfway through.
    """
    if not isinstance(label, str) or not label:
        raise ValueError(
            f'label must be a non-empty string, got {label!r}'
        )
    if kind not in ('command', 'script'):
        raise ValueError(f'{label}: unknown kind {kind!r}')
    if (not isinstance(argv, (list, tuple))
            or not all(isinstance(arg, str) for arg in argv)):
        raise ValueError(
            f'{label}: argv must be a list of strings'
        )
    if kind == 'script' and not argv:
        raise ValueError(
            f'{label}: script entries need a non-empty argv'
        )
    if not isinstance(schedule, str):
        raise ValueError(
            f'{label}: schedule must be a string, got '
            f'{schedule!r}'
        )
    # raises ValueError on a bad spec
    is_due(schedule, today, executed_by)


class Command(BaseCommand):
    help = (
        'Run every enabled JOBS entry whose schedule matches '
        'today (UTC), sequentially in listed order.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--only',
            metavar='LABEL',
            default=None,
            help='Run only the entry labelled LABEL, ignoring its '
                 'schedule (the only way to run manual entries)',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Run all enabled non-manual entries ignoring '
                 'their schedules',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Print what would run today without running it',
        )

    def handle(self, *args, **options):
        today = datetime.now(timezone.utc).date()
        # Resolve once per pass — the executor is an
        # environment fact that cannot change mid-run, and a
        # single snapshot keeps validation and due checks
        # consistent.
        executed_by = detect_executed_by()
        only = options['only']
        if only is not None and all(
                _entry_label(job) != only for job in JOBS):
            raise CommandError(f'no JOBS entry labelled {only!r}')

        # Validate every spec up front so a bad entry fails before
        # anything runs rather than aborting the pass mid-way —
        # and surfaces under --force/--dry-run, which never call
        # is_due otherwise. Bad entries count as failures and are
        # skipped; valid entries still run.
        failed = []
        entries = []
        for job in JOBS:
            try:
                label, kind, argv, schedule = job
                _validate_job_spec(
                    label, kind, argv, schedule, today,
                    executed_by,
                )
            except (TypeError, ValueError):
                logger.exception('invalid JOBS entry: %r', job)
                failed.append(_entry_label(job))
                continue
            entries.append((label, kind, argv, schedule))

        if options['dry_run']:
            self.stdout.write(f'executor: {executed_by}')

        for label, kind, argv, schedule in entries:
            if only is not None:
                due = label == only
            elif options['force']:
                # --force overrides the calendar, not the
                # executor — 'local:*' entries still never
                # run on Cloud Run.
                due = schedule != 'manual' and (
                    not schedule.startswith('local:')
                    or executed_by == 'local'
                )
            else:
                due = is_due(schedule, today, executed_by)

            if options['dry_run']:
                verb = 'RUN ' if due else 'skip'
                self.stdout.write(
                    f'{verb} {label} ({kind} {argv!r}, {schedule})'
                )
                continue
            if not due:
                logger.info('skipping %s (schedule %s)', label, schedule)
                continue

            logger.info('starting %s', label)
            try:
                self._run_entry(label, kind, argv)
            except (Exception, SystemExit) as e:
                # SystemExit included so a sub-command calling
                # sys.exit() is recorded as a failure instead of
                # aborting the whole pass. KeyboardInterrupt and
                # GeneratorExit still propagate.
                logger.exception('job %s failed', label)
                capture_internal_exception(e)
                failed.append(label)
                continue
            logger.info('finished %s', label)

        if failed:
            raise CommandError('failed jobs: ' + ', '.join(failed))

    def _run_entry(self, label, kind, argv):
        if kind == 'command':
            call_command(label, *argv)
            return
        if kind == 'script':
            script = str(settings.BASE_DIR / argv[0])
            rc = subprocess.call(
                [sys.executable, script, *argv[1:]],
                cwd=str(settings.BASE_DIR),
            )
            if rc != 0:
                raise CommandError(
                    f'{label} exited with status {rc}'
                )
            return
        raise CommandError(f'{label}: unknown kind {kind!r}')
