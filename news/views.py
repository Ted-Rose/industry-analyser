"""Digest pages — plain Django templates (MVP UI; the React SPA
and ninja API are out of scope for this feature)."""
from datetime import datetime

from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .models import NewsDigest


def digest_list(request):
    digests = (
        NewsDigest.objects.order_by('-date')
        .prefetch_related('items')
    )
    return render(
        request, 'news/digest_list.html', {'digests': digests}
    )


def digest_detail(request, date):
    try:
        day = datetime.strptime(date, '%Y-%m-%d').date()
    except ValueError:
        raise Http404('Invalid date format') from None
    digest = get_object_or_404(NewsDigest, date=day)
    items = (
        digest.items
        .select_related('story__topic')
        .prefetch_related('story__articles__source')
        .order_by('rank')
    )
    return render(
        request,
        'news/digest_detail.html',
        {'digest': digest, 'items': items},
    )
