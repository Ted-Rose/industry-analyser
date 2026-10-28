"""Master Cloud Run job: run all enabled sub-jobs sequentially.

``python manage.py run_all_jobs`` iterates the ``JOBS`` list below in
listed order — each entry runs only when its schedule predicate
matches today's UTC date. Comment a line out to disable a sub-job;
this file is the single source of truth for which jobs run in the
consolidated ``all-jobs`` Cloud Run job.

Schedules (evaluated against today's UTC date):
    daily                every day
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
    ('scrape_housing_ads', 'command', [], 'weekly:mon'),
    ('scrape_apartment_ads', 'command', [], 'weekly:mon'),
    ('scrape_vacancy', 'script',
     ['scripts/materialize_fetcher_config_and_scrape.py'], 'manual'),
    ('link_ads_to_properties', 'command', ['--older-than-days', '3'],
     'manual'),
    # ('sync_apartment_regions', 'command', [], 'manual'),
    # ('sync_housing_regions', 'command', [], 'manual'),
]

_WEEKDAYS = {
    'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3,
    'fri': 4, 'sat': 5, 'sun': 6,
}


def is_due(schedule, today):
    """True when ``schedule`` matches the UTC date ``today``.

    ``manual`` is never due — those entries run only via --only (and
    stay skipped under --force).
    """
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
        only = options['only']
        if only is not None and all(job[0] != only for job in JOBS):
            raise CommandError(f'no JOBS entry labelled {only!r}')

        failed = []
        for label, kind, argv, schedule in JOBS:
            if only is not None:
                due = label == only
            elif options['force']:
                due = schedule != 'manual'
            else:
                due = is_due(schedule, today)

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
            except (Exception, SystemExit):
                # SystemExit included so a sub-command calling
                # sys.exit() is recorded as a failure instead of
                # aborting the whole pass. KeyboardInterrupt and
                # GeneratorExit still propagate.
                logger.exception('job %s failed', label)
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
