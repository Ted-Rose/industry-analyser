"""Receipts spending dashboard (plain Django view + template).

Internal page hard-coded to the ``admin`` user's receipts — the
personal-spend dataset has exactly one owner, so no auth
machinery is added. When that user does not exist (e.g. a fresh
dev database) the page renders with an empty dataset instead of
500ing.
"""
import logging

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import render

from .models import Receipt, ReceiptItem

logger = logging.getLogger('receipts')

ADMIN_USERNAME = 'admin'


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
        receipts = Receipt.objects.none()
    else:
        receipts = (
            Receipt.objects.filter(user=owner)
            .select_related('store')
            .prefetch_related('items')
            .annotate(item_count=Count('items'))
            .order_by('-purchased_at')
        )

    summary = receipts.aggregate(
        total_spend=Sum('total'),
        receipt_count=Count('pk'),
    )
    item_count = ReceiptItem.objects.filter(
        receipt__in=receipts).count()
    monthly = (
        receipts.exclude(purchased_at__isnull=True)
        .annotate(month=TruncMonth('purchased_at'))
        .values('month')
        .annotate(receipt_count=Count('pk'), total=Sum('total'))
        .order_by('-month')
    )
    by_store = (
        receipts.values('store__name')
        .annotate(receipt_count=Count('pk'), total=Sum('total'))
        .order_by('-total')
    )

    return render(request, 'receipts/dashboard.html', {
        'owner': owner,
        'summary': summary,
        'item_count': item_count,
        'monthly': monthly,
        'by_store': by_store,
        'receipts': receipts,
    })
