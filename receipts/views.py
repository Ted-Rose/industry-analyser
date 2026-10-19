"""Receipts spending dashboard (plain Django view + template).

Internal page hard-coded to the ``admin`` user's receipts — the
personal-spend dataset has exactly one owner, so no auth
machinery is added. When that user does not exist (e.g. a fresh
dev database) the page renders with an empty dataset instead of
500ing.
"""
import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import render
from django.utils import timezone

from .models import Receipt, ReceiptItem

logger = logging.getLogger('receipts')

ADMIN_USERNAME = 'admin'
UNCATEGORIZED = 'Uncategorized'
TOP_CATEGORY_ITEMS = 20


def _parse_date(value):
    """Parse a 'YYYY-MM-DD' GET param; None when absent/invalid."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _default_range(today):
    """Last-12-months default: same day one year ago → today."""
    try:
        start = today.replace(year=today.year - 1)
    except ValueError:                      # Feb 29 → Feb 28
        start = today.replace(year=today.year - 1, day=28)
    return start, today


def _date_range(request):
    """Resolve ?date_from/?date_to; invalid or inverted input
    falls back to the last-12-months default."""
    today = timezone.localdate()
    def_from, def_to = _default_range(today)
    date_from = _parse_date(request.GET.get('date_from')) or def_from
    date_to = _parse_date(request.GET.get('date_to')) or def_to
    if date_from > date_to:
        date_from, date_to = def_from, def_to
    return date_from, date_to, today


def _months_covered(date_from, date_to):
    """Calendar months the range touches (min 1) — the monthly
    average divisor for the category section."""
    months = ((date_to.year - date_from.year) * 12
              + date_to.month - date_from.month + 1)
    return max(1, months)


def _by_category(items, months):
    """Spend grouped by ReceiptItem.category — rows carry the
    monthly average plus the top-N items for the collapsible
    detail block."""
    top_items = defaultdict(list)
    for row in (
        items.values('category__name', 'raw_name')
        .annotate(item_count=Count('pk'), total=Sum('total'))
        .order_by('-total')
    ):
        key = row['category__name'] or UNCATEGORIZED
        if len(top_items[key]) < TOP_CATEGORY_ITEMS:
            top_items[key].append(row)

    categories = []
    for row in (
        items.values('category__name')
        .annotate(item_count=Count('pk'), total=Sum('total'))
        .order_by('-total')
    ):
        name = row['category__name'] or UNCATEGORIZED
        total = row['total'] or Decimal('0.00')
        categories.append({
            'name': name,
            'item_count': row['item_count'],
            'total': total,
            'monthly_avg': (total / months).quantize(
                Decimal('0.01')),
            'top_items': top_items[name],
        })
    return categories


def dashboard(request):
    """Render the receipts spending dashboard for ``admin``."""
    try:
        owner = get_user_model().objects.get(
            username=ADMIN_USERNAME)
    except get_user_model().DoesNotExist:
        logger.warning(
            'receipts dashboard: user %r not found',
            ADMIN_USERNAME,
        )
        owner = None
        base = Receipt.objects.none()
    else:
        base = Receipt.objects.filter(user=owner)

    date_from, date_to, today = _date_range(request)
    base = base.filter(
        purchased_at__date__gte=date_from,
        purchased_at__date__lte=date_to,
    )
    # 'Last month' quick preset = previous calendar month.
    last_month_to = today.replace(day=1) - timedelta(days=1)
    last_month_from = last_month_to.replace(day=1)
    months = _months_covered(date_from, date_to)

    # Aggregates must run on ``base`` — the item_count annotation
    # below joins receipt_item, and a Sum/Count over that join
    # multiplies each receipt by its item count.
    receipts = (
        base.select_related('store')
        .prefetch_related('items')
        .annotate(item_count=Count('items'))
        .order_by('-purchased_at')
    )
    summary = base.aggregate(
        total_spend=Sum('total'),
        receipt_count=Count('pk'),
    )
    items = ReceiptItem.objects.filter(receipt__in=base)
    item_count = items.count()
    categories = _by_category(items, months)
    monthly = (
        base.exclude(purchased_at__isnull=True)
        .annotate(month=TruncMonth('purchased_at'))
        .values('month')
        .annotate(receipt_count=Count('pk'), total=Sum('total'))
        .order_by('-month')
    )
    by_store = (
        base.values('store__name')
        .annotate(receipt_count=Count('pk'), total=Sum('total'))
        .order_by('-total')
    )

    return render(request, 'receipts/dashboard.html', {
        'owner': owner,
        'summary': summary,
        'item_count': item_count,
        'monthly': monthly,
        'by_store': by_store,
        'categories': categories,
        'months': months,
        'receipts': receipts,
        'date_from': date_from,
        'date_to': date_to,
        'last_month_from': last_month_from,
        'last_month_to': last_month_to,
    })
