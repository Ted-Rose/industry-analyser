"""Aggregates over ScrapeJobRun for the admin usage page (PR-5).

Groups runs by UTC day x job with per-status counts and average
duration; mirrors ai_providers/usage.py.
"""

import datetime
import logging

from django.db.models import (
    Avg, Count, DurationField, ExpressionWrapper, F, Q,
)
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import ScrapeJobRun, ScrapeJobRunItem

logger = logging.getLogger('scrape_jobs')

DEFAULT_USAGE_DAYS = 30


def utc_day_start(offset_days=0):
    """Start (00:00 UTC) of the day ``offset_days`` ago — 0 = today.

    ``TIME_ZONE`` is UTC, so a naive midnight replace is correct.
    """
    day_start = timezone.now().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return day_start - datetime.timedelta(days=offset_days)


def default_date_range():
    """(from_date, to_date) covering the last DEFAULT_USAGE_DAYS UTC
    days, inclusive."""
    to_date = timezone.localdate()
    return to_date - datetime.timedelta(days=DEFAULT_USAGE_DAYS - 1), \
        to_date


def parse_date(value):
    """Parse an ISO ``YYYY-MM-DD`` string; None on empty/invalid."""
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def _apply_date_range(queryset, date_from=None, date_to=None):
    if date_from is not None:
        queryset = queryset.filter(started_at__date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(started_at__date__lte=date_to)
    return queryset


_RUN_AGGREGATES = {
    'run_count': Count('pk'),
    'success_count': Count(
        'pk', filter=Q(status=ScrapeJobRun.SUCCESS)
    ),
    'partial_count': Count(
        'pk', filter=Q(status=ScrapeJobRun.PARTIAL)
    ),
    'failed_count': Count(
        'pk', filter=Q(status=ScrapeJobRun.FAILED)
    ),
    'abandoned_count': Count(
        'pk', filter=Q(status=ScrapeJobRun.ABANDONED)
    ),
    'avg_duration': Avg(
        ExpressionWrapper(
            F('completed_at') - F('started_at'),
            output_field=DurationField(),
        ),
        filter=Q(completed_at__isnull=False),
    ),
}


def runs_by_day(date_from=None, date_to=None):
    """ScrapeJobRun aggregates grouped by day x job.

    Returns a queryset of dicts with ``day`` (a ``date``),
    ``job_id``, ``job__slug``, per-status counts and ``avg_duration``
    (a timedelta over completed runs).
    """
    queryset = _apply_date_range(
        ScrapeJobRun.objects.all(), date_from, date_to
    )
    return (
        queryset.annotate(day=TruncDate('started_at'))
        .values('day', 'job_id', 'job__slug')
        .annotate(**_RUN_AGGREGATES)
        .order_by('-day', 'job__slug')
    )


def run_totals(date_from=None, date_to=None):
    """Single-row totals across the range (usage page header)."""
    queryset = _apply_date_range(
        ScrapeJobRun.objects.all(), date_from, date_to
    )
    return queryset.aggregate(**_RUN_AGGREGATES)


def item_totals(date_from=None, date_to=None):
    """ScrapeJobRunItem counts by status across the range."""
    queryset = ScrapeJobRunItem.objects.filter(
        run__in=_apply_date_range(
            ScrapeJobRun.objects.all(), date_from, date_to
        )
    )
    return queryset.aggregate(
        items_done=Count('pk', filter=Q(status=ScrapeJobRunItem.DONE)),
        items_failed=Count(
            'pk', filter=Q(status=ScrapeJobRunItem.FAILED)
        ),
        items_skipped=Count(
            'pk', filter=Q(status=ScrapeJobRunItem.SKIPPED)
        ),
    )
