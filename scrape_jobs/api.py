"""django-ninja router for the dashboard SPA (mounted at
/api/dashboard/).

The dashboard is the only non-public SPA — the page it replaces was
@login_required, so the GET op keeps the default django_auth
(session + CSRF). Anonymous callers get a JSON 401 whose
`login_url`'s `next` resolves to '/' via SPA_BASES ('dashboard' is
the documented exception: the API lives under /api/dashboard/ but
the SPA mounts at the site root).

Query/aggregate logic mirrors the retired
scrape_jobs.views.dashboard view: per-job cycle progress plus a
day x job run table bounded by ?date_from=/&date_to= ISO dates
(default: the last usage.DEFAULT_USAGE_DAYS days). The retired
template form used ?from=/&to= — the SPA keeps reading those names
from the page URL for old bookmarks and maps them onto
date_from/date_to here.
"""
from datetime import date, datetime
from typing import List, Optional

from ninja import Router, Schema

from . import usage

router = Router()


# --- Schemas ---


class JobRefOut(Schema):
    """The ScrapeJob slice a jobs-table row needs."""
    slug: str
    description: str
    is_enabled: bool


class LastRunOut(Schema):
    """A job's most recent run — the status/last-run/duration cells."""
    id: int
    status: str
    executed_by: str
    started_at: datetime
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]

    @staticmethod
    def resolve_duration_seconds(obj):
        # Was `completed_at|timeuntil:started_at` in the template —
        # the SPA formats seconds instead.
        if obj.completed_at is None:
            return None
        return (obj.completed_at - obj.started_at).total_seconds()


class JobRowOut(Schema):
    """One jobs-table row — a dict from usage.job_overview()."""
    job: JobRefOut
    cycle_key: Optional[str]
    item_total: int
    item_active: int
    cycle_done: int
    cycle_failed: int
    progress_pct: Optional[int]
    running: bool
    last_run: Optional[LastRunOut]


class DayRowOut(Schema):
    """One day x job row — a dict from usage.runs_by_day()."""
    day: date
    job_slug: str
    run_count: int
    success_count: int
    partial_count: int
    failed_count: int
    abandoned_count: int
    avg_duration_seconds: Optional[float]

    @staticmethod
    def resolve_job_slug(obj):
        return obj['job__slug']

    @staticmethod
    def resolve_avg_duration_seconds(obj):
        delta = obj['avg_duration']
        return delta.total_seconds() if delta is not None else None


class RunTotalsOut(Schema):
    """The daily-runs subtitle totals — a usage.run_totals() dict."""
    run_count: int
    success_count: int
    partial_count: int
    failed_count: int
    abandoned_count: int
    avg_duration_seconds: Optional[float]

    @staticmethod
    def resolve_avg_duration_seconds(obj):
        delta = obj['avg_duration']
        return delta.total_seconds() if delta is not None else None


class DashboardOut(Schema):
    """The whole dashboard page payload — one fat GET per the
    rewrite plan (jobs table + daily table + filter echo)."""
    jobs: List[JobRowOut]
    rows: List[DayRowOut]
    totals: RunTotalsOut
    date_from: date
    date_to: date


# --- Ops ---


@router.get('/', response=DashboardOut)
def dashboard(
    request,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
):
    """Dashboard payload — mirrors the retired dashboard view's GET
    logic verbatim (defaults fill in when a bound is absent)."""
    default_from, default_to = usage.default_date_range()
    if date_from is None:
        date_from = default_from
    if date_to is None:
        date_to = default_to
    return DashboardOut(
        jobs=list(usage.job_overview()),
        rows=list(usage.runs_by_day(date_from, date_to)),
        totals=usage.run_totals(date_from, date_to),
        date_from=date_from,
        date_to=date_to,
    )
