"""Web views for scrape_jobs — the root jobs dashboard."""

import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from . import usage

logger = logging.getLogger('scrape_jobs')


@login_required
def dashboard(request):
    """Jobs dashboard: per-job progress over each job's latest
    cycle, plus a day x job run table. ``?from=``/``?to=`` ISO dates
    bound the daily table (default: the last
    ``usage.DEFAULT_USAGE_DAYS`` days)."""
    default_from, default_to = usage.default_date_range()
    date_from = usage.parse_date(request.GET.get('from'))
    date_to = usage.parse_date(request.GET.get('to'))
    if date_from is None:
        date_from = default_from
    if date_to is None:
        date_to = default_to
    return render(request, 'scrape_jobs/dashboard.html', {
        'jobs': usage.job_overview(),
        'rows': usage.runs_by_day(date_from, date_to),
        'totals': usage.run_totals(date_from, date_to),
        'date_from': date_from,
        'date_to': date_to,
    })
