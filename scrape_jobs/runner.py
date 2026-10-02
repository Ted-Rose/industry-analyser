"""Cycle-scoped checkpointing runner (docs/stateful_scrape_jobs_plan.md).

One ScrapeJobRunner per command invocation. On construction it:

* get_or_creates the ScrapeJob row,
* sweeps stale RUNNING runs (heartbeat older than
  ``stale_timeout_minutes``) to ABANDONED,
* computes the cycle's completed item keys — the union of DONE
  ScrapeJobRunItems across all of the job's runs in this cycle —
  and creates a new RUNNING run.

Resume rule: completed keys are skipped for the whole cycle unless
``fresh`` was passed or the job is disabled — a finished pass is not
silently repeated; a deliberate same-cycle re-scrape uses ``--fresh``.

Per-item failure isolation relies on ``BaseScraper.run()`` throwing
``scrape_portal()`` exceptions back into the ``get_search_urls()``
generator — a ``try/except`` around the item's inner yields catches
it, ``item_failed()`` records it, and iteration continues with the
next item. A run that finishes with failed items ends PARTIAL.
"""

import logging
import os
import socket
from datetime import timedelta

from django.utils import timezone

from .models import (
    ScrapeJob,
    ScrapeJobItem,
    ScrapeJobRun,
    ScrapeJobRunItem,
)

logger = logging.getLogger('scrape_jobs')

# Emitted by item_failed(); the log-based alert policy
# 'scrape_item_failure' in terraform/monitoring.tf mails on it.
ITEM_FAILURE_MARKER = 'SCRAPE_ITEM_FAILED'

_TERMINAL_STATUSES = {
    ScrapeJobRun.SUCCESS,
    ScrapeJobRun.FAILED,
    ScrapeJobRun.ABANDONED,
    ScrapeJobRun.PARTIAL,
}


def detect_executed_by():
    """'gcp_cloud_run' on Cloud Run (jobs and services), else 'local'."""
    if any(
        os.getenv(var)
        for var in ('K_SERVICE', 'K_REVISION', 'GOOGLE_CLOUD_PROJECT')
    ):
        return 'gcp_cloud_run'
    return 'local'


def detect_execution_id():
    """Cloud Run execution+task id, or a local host/pid fallback."""
    execution = os.getenv('CLOUD_RUN_EXECUTION')
    if execution:
        task_index = os.getenv('CLOUD_RUN_TASK_INDEX', '0')
        return f'{execution}-{task_index}'
    return f'local-{socket.gethostname()}-{os.getpid()}'


def ensure_job(slug, description=''):
    """get_or_create the ScrapeJob row for ``slug``.

    ``description`` is synced from code on every call; all other
    fields (is_enabled, stale_timeout_minutes) are admin-owned.
    """
    job, created = ScrapeJob.objects.get_or_create(
        slug=slug, defaults={'description': description}
    )
    if not created and description and job.description != description:
        job.description = description
        job.save(update_fields=['description', 'updated_at'])
    return job


class ScrapeJobRunner:
    """One instance per command invocation."""

    def __init__(
        self,
        slug,
        cycle_key=None,
        fresh=False,
        resume_from=None,
        description='',
        dry_run=False,
    ):
        self.slug = slug
        self.cycle_key = cycle_key or timezone.localdate().isoformat()
        self.fresh = fresh
        self.resume_from = resume_from
        self.dry_run = dry_run
        self.failed_item_count = 0
        self._partial = False

        if dry_run:
            # No bookkeeping writes at all: the job row stays
            # in-memory, item/run methods only log.
            self.job = ScrapeJob(slug=slug)
            self.run = None
            self.completed_keys = set()
            logger.info(
                '[dry-run] %s cycle=%s — no job/run/item writes',
                slug, self.cycle_key,
            )
            return

        self.job = ensure_job(slug, description)
        self._sweep_stale_runs()
        self.completed_keys = self._cycle_completed_keys()
        self.run = ScrapeJobRun.objects.create(
            job=self.job,
            cycle_key=self.cycle_key,
            execution_id=detect_execution_id(),
            executed_by=detect_executed_by(),
            status=ScrapeJobRun.RUNNING,
        )
        logger.info(
            'Scrape run #%s started: job=%s cycle=%s execution=%s '
            '(%d item key(s) already done this cycle)',
            self.run.pk, slug, self.cycle_key, self.run.execution_id,
            len(self.completed_keys),
        )

    def _sweep_stale_runs(self):
        """RUNNING runs with a heartbeat older than the job's stale
        timeout are presumed dead — mark them ABANDONED."""
        cutoff = timezone.now() - timedelta(
            minutes=self.job.stale_timeout_minutes
        )
        stale = self.job.runs.filter(
            status=ScrapeJobRun.RUNNING, updated_at__lt=cutoff
        )
        swept = stale.update(
            status=ScrapeJobRun.ABANDONED,
            error_message='Heartbeat went stale — presumed dead.',
            completed_at=timezone.now(),
        )
        if swept:
            logger.warning(
                '%s: marked %d stale RUNNING run(s) ABANDONED',
                self.slug, swept,
            )

    def _cycle_completed_keys(self):
        """Item keys already DONE in this cycle (the skip-set).

        Empty when --fresh or when the job is disabled (a full pass
        is the rollback mode). DONE keys stay skipped for the whole
        cycle — a SUCCESS run does not reset them; a deliberate
        same-cycle re-scrape uses --fresh.
        """
        if self.fresh or not self.job.is_enabled:
            return set()
        cycle_runs = self.job.runs.filter(cycle_key=self.cycle_key)
        keys = set(
            ScrapeJobRunItem.objects.filter(
                run__in=cycle_runs, status=ScrapeJobRunItem.DONE,
            ).values_list('item__key', flat=True)
        )
        if keys:
            logger.info(
                '%s: resuming cycle %s — %d item key(s) done: %s',
                self.slug, self.cycle_key, len(keys),
                sorted(keys)[:20],
            )
        return keys

    def sync_items(self, entries):
        """Upsert ScrapeJobItem rows from the job's source objects.

        ``entries``: iterable of ``(key, label, priority, obj)`` —
        ``obj`` is the domain object the caller wants back (Region,
        Keyword, listing config, ...); it rides along as ``item.obj``.

        Rows are created on first sight with the given
        label/priority; afterwards only ``label`` is refreshed —
        ``priority``/``is_active`` are admin-owned. Items whose key is
        absent from ``entries`` (source row vanished) are marked
        is_active=False; the domain model itself is never touched.
        """
        entries = list(entries)
        if self.dry_run:
            items = []
            for key, label, priority, obj in entries:
                item = ScrapeJobItem(
                    job=self.job, key=key, label=label,
                    priority=priority,
                )
                item.obj = obj
                items.append(item)
            return items

        seen_keys = {entry[0] for entry in entries}
        items = []
        for key, label, priority, obj in entries:
            item, created = ScrapeJobItem.objects.get_or_create(
                job=self.job, key=key,
                defaults={'label': label, 'priority': priority},
            )
            if not created and item.label != label:
                item.label = label
                item.save(update_fields=['label', 'updated_at'])
            item.obj = obj
            items.append(item)

        deactivated = (
            self.job.items.filter(is_active=True)
            .exclude(key__in=seen_keys)
            .update(is_active=False)
        )
        if deactivated:
            logger.info(
                '%s: deactivated %d item(s) whose source vanished',
                self.slug, deactivated,
            )
        return items

    def pending_items(self, items):
        """``items``, ordered for processing, minus what is done.

        Order is (-priority, id) — matching ScrapeJobItem.Meta — and
        skips inactive items plus keys in the cycle's completed set.
        ``resume_from`` (debug override) drops every item before that
        key and ignores the completed set; unknown keys raise.
        """
        ordered = sorted(
            items,
            key=lambda i: (-i.priority, i.id if i.id else 0),
        )
        if self.resume_from is not None:
            keys = [i.key for i in ordered]
            if self.resume_from not in keys:
                raise ValueError(
                    f'--resume-from key {self.resume_from!r} is not '
                    f'an item of job {self.slug!r}'
                )
            ordered = ordered[keys.index(self.resume_from):]
            logger.info(
                '%s: --resume-from %r — %d item(s) in scope',
                self.slug, self.resume_from, len(ordered),
            )
            return [i for i in ordered if i.is_active]

        pending = [
            i for i in ordered
            if i.is_active and i.key not in self.completed_keys
        ]
        logger.info(
            '%s: %d of %d item(s) pending this pass',
            self.slug, len(pending), len(ordered),
        )
        return pending

    def item_done(self, item):
        """Record ``item`` DONE for this run and heartbeat the run."""
        logger.info('%s item done: %s', self.slug, item.key)
        if self.dry_run:
            return
        ScrapeJobRunItem.objects.update_or_create(
            run=self.run, item=item,
            defaults={
                'status': ScrapeJobRunItem.DONE,
                'error_message': '',
            },
        )
        self.run.last_completed_item = item
        self.run.save(
            update_fields=['last_completed_item', 'updated_at']
        )

    def item_failed(self, item, exc):
        """Record ``item`` FAILED, emit the SCRAPE_ITEM_FAILED marker
        (the log-based alert policy mails on it), and heartbeat — the
        caller then continues with the next item."""
        self.failed_item_count += 1
        logger.error(
            '%s job=%s item=%s err=%s',
            ITEM_FAILURE_MARKER, self.slug, item.key, exc,
            exc_info=True,
        )
        if self.dry_run:
            return
        ScrapeJobRunItem.objects.update_or_create(
            run=self.run, item=item,
            defaults={
                'status': ScrapeJobRunItem.FAILED,
                'error_message': str(exc)[:2000],
            },
        )
        self.touch()

    def mark_partial(self):
        """Force PARTIAL at finish() — for early stops that are not
        item failures (e.g. the blogs AI request cap)."""
        self._partial = True

    def touch(self):
        """Heartbeat — one cheap UPDATE; called per item checkpoint
        and between pages inside an item."""
        if self.run is not None:
            self.run.save(update_fields=['updated_at'])

    def finish(self, status=None, error=''):
        """Close the run. Default status: PARTIAL when any item failed
        (or mark_partial() was called), else SUCCESS."""
        if status is None:
            status = (
                ScrapeJobRun.PARTIAL
                if self._partial or self.failed_item_count
                else ScrapeJobRun.SUCCESS
            )
        if status not in _TERMINAL_STATUSES:
            raise ValueError(f'invalid terminal status {status!r}')
        if self.dry_run:
            logger.info(
                '[dry-run] %s run would finish %s', self.slug, status
            )
            return
        self.run.status = status
        self.run.error_message = error
        self.run.completed_at = timezone.now()
        self.run.save(
            update_fields=[
                'status', 'error_message', 'completed_at',
                'updated_at',
            ]
        )
        logger.info(
            'Scrape run #%s finished %s: job=%s cycle=%s '
            '(failed items: %d)%s',
            self.run.pk, status, self.slug, self.cycle_key,
            self.failed_item_count,
            f' — {error[:200]}' if error else '',
        )
