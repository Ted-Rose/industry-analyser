"""Usage aggregation queries over AIRequest (PR-8 card).

Groups attempts by UTC day x job x served model and exposes small
totals helpers for the admin usage page and the AIJob/AIModel admin
columns.
"""

import datetime
import logging

from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from ai_providers.models import AIInput, AIRequest

logger = logging.getLogger('ai_providers')

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
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(created_at__date__lte=date_to)
    return queryset


_USAGE_AGGREGATES = {
    'request_count': Count('pk'),
    'error_count': Count('pk', filter=Q(status='error')),
    'blocked_count': Count('pk', filter=Q(status='blocked')),
    'input_tokens': Sum('input_tokens'),
    'output_tokens': Sum('output_tokens'),
    'cost_usd': Sum('cost_usd'),
}


def requests_by_day(date_from=None, date_to=None):
    """AIRequest aggregates grouped by day x job x served model.

    Returns a queryset of dicts with keys ``day`` (a ``date``),
    ``job_id``, ``job__slug``, ``served_model_id``,
    ``served_model__name``, ``served_model__provider__slug`` (null
    served model on failed requests groups as ``None``) plus
    ``request_count``, ``error_count``, ``blocked_count``,
    ``input_tokens``, ``output_tokens`` and ``cost_usd``.
    """
    queryset = _apply_date_range(
        AIRequest.objects.all(), date_from, date_to
    )
    return (
        queryset.annotate(day=TruncDate('created_at'))
        .values(
            'day',
            'job_id',
            'job__slug',
            'served_model_id',
            'served_model__name',
            'served_model__provider__slug',
        )
        .annotate(**_USAGE_AGGREGATES)
        .order_by('-day', 'job__slug', 'served_model__name')
    )


def usage_totals(date_from=None, date_to=None):
    """Single-row totals across the range (the usage page header)."""
    queryset = _apply_date_range(
        AIRequest.objects.all(), date_from, date_to
    )
    return queryset.aggregate(**_USAGE_AGGREGATES)


def input_storage_totals():
    """AIInput row count and total chars — the storage line shown on
    the usage page."""
    return AIInput.objects.aggregate(
        input_count=Count('pk'),
        input_chars=Sum('chars'),
    )
