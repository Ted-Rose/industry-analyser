"""django-ninja router for the receipts SPA (mounted at
/api/receipts/).

The single GET keeps the default django_auth — receipts are
private spending data, so the page and its payload both require
login. The dataset stays hard-coded to the ``admin`` user's
receipts; when that user does not exist
(e.g. a fresh dev database) the payload reports
``owner_exists=False`` with empty sections instead of 500ing.

One fat GET serves the whole page — the template rendered
everything in one pass, and serverless CONN_MAX_AGE=0 makes
granular calls the risk. Query/aggregate logic is the retired
``receipts.views.dashboard`` moved verbatim (helpers included) —
the only difference is date parsing: ninja 422s an unparseable
?date_from/?date_to instead of silently falling back to defaults.
"""
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from ninja import Router, Schema

from .models import Receipt, ReceiptItem

logger = logging.getLogger('receipts')

router = Router()

ADMIN_USERNAME = 'admin'
UNCATEGORIZED = 'Uncategorized'
TOP_CATEGORY_ITEMS = 20


# --- Schemas ---


class ReceiptItemOut(Schema):
    """One item row of the per-receipt <details> table."""
    raw_name: str
    is_fee: bool
    quantity: float
    unit: str
    unit_price: Optional[float]
    discount: float
    total: float


class ReceiptRowOut(Schema):
    """One row of the all-receipts table — a Receipt annotated with
    item_count and select_related('store')/prefetch('items')."""
    id: int
    purchased_at: Optional[datetime]
    store_name: Optional[str]
    document_number: str
    total: Optional[float]
    currency: str
    parse_status_label: str
    item_count: int
    items: List[ReceiptItemOut]

    @staticmethod
    def resolve_store_name(obj):
        return obj.store.name if obj.store else None

    @staticmethod
    def resolve_parse_status_label(obj):
        return obj.get_parse_status_display()

    @staticmethod
    def resolve_items(obj):
        return list(obj.items.all())


class TopItemOut(Schema):
    """One row of a category's collapsible top-items table — a dict
    from _by_category's first aggregate pass."""
    raw_name: str
    item_count: int
    total: float


class CategoryOut(Schema):
    """One collapsible category row — a dict from _by_category."""
    name: str
    item_count: int
    total: float
    monthly_avg: float
    top_items: List[TopItemOut]


class MonthlyRowOut(Schema):
    """One by-month row — a values() dict over TruncMonth."""
    month: datetime
    receipt_count: int
    total: float

    @staticmethod
    def resolve_total(obj):
        # Sum over all-NULL receipt totals → None; the template
        # rendered `|default:"0.00"`.
        return obj['total'] or Decimal('0.00')


class StoreRowOut(Schema):
    """One by-store row — a values('store__name') dict."""
    store_name: Optional[str]
    receipt_count: int
    total: float

    @staticmethod
    def resolve_store_name(obj):
        return obj['store__name']

    @staticmethod
    def resolve_total(obj):
        return obj['total'] or Decimal('0.00')


class SummaryOut(Schema):
    """The summary cards — the base.aggregate() dict with Nones
    coerced to 0/0.00 (the template's |default filters)."""
    total_spend: float
    receipt_count: int


class ReceiptsDashboardOut(Schema):
    """The whole receipts page payload — one fat GET."""
    owner_exists: bool
    summary: SummaryOut
    item_count: int
    months: int
    date_from: date
    date_to: date
    last_month_from: date
    last_month_to: date
    monthly: List[MonthlyRowOut]
    by_store: List[StoreRowOut]
    categories: List[CategoryOut]
    receipts: List[ReceiptRowOut]


# --- Helpers (moved verbatim from the retired views.py) ---


def _default_range(today):
    """Last-12-months default: same day one year ago → today."""
    try:
        start = today.replace(year=today.year - 1)
    except ValueError:                      # Feb 29 → Feb 28
        start = today.replace(year=today.year - 1, day=28)
    return start, today


def _date_range(date_from, date_to):
    """Resolve ?date_from/?date_to — ninja already parsed them into
    ``date`` objects (invalid strings 422); an inverted range still
    falls back to the last-12-months default."""
    today = timezone.localdate()
    def_from, def_to = _default_range(today)
    date_from = date_from or def_from
    date_to = date_to or def_to
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


# --- Ops ---


@router.get('/', response=ReceiptsDashboardOut)
def receipts_dashboard(
    request,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
):
    """The spending dashboard payload — the retired dashboard view
    minus render()."""
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

    date_from, date_to, today = _date_range(date_from, date_to)
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

    return ReceiptsDashboardOut(
        owner_exists=owner is not None,
        summary=SummaryOut(
            total_spend=summary['total_spend'] or Decimal('0.00'),
            receipt_count=summary['receipt_count'] or 0,
        ),
        item_count=item_count,
        months=months,
        date_from=date_from,
        date_to=date_to,
        last_month_from=last_month_from,
        last_month_to=last_month_to,
        monthly=list(monthly),
        by_store=list(by_store),
        categories=categories,
        receipts=list(receipts),
    )
