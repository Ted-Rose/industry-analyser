"""Stateful scrape-job bookkeeping (docs/stateful_scrape_jobs_plan.md).

A ScrapeJob is one periodic scrape entrypoint (e.g.
'classified_ads.apartment_ads'). Each pass over the job's work items
creates a ScrapeJobRun scoped to a ``cycle_key`` (the UTC date by
default), and each finished unit of work leaves a ScrapeJobRunItem
row — so an interrupted run can resume by skipping the item keys
already DONE in the same cycle.
"""

import logging

from django.db import models

logger = logging.getLogger('scrape_jobs')


class ScrapeJob(models.Model):
    """A named scrape entrypoint checkpointed by ScrapeJobRunner."""

    slug = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_enabled = models.BooleanField(
        default=True,
        help_text=(
            'When off, the runner still records runs/items but never '
            'skips completed items — every pass is a full pass.'
        ),
    )
    stale_timeout_minutes = models.PositiveIntegerField(
        default=30,
        help_text=(
            'A RUNNING run whose heartbeat (updated_at) is older than '
            'this is marked ABANDONED by the next run of the job.'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'scrape_job'

    def __str__(self):
        return self.slug


class ScrapeJobItem(models.Model):
    """One unit of work inside a ScrapeJob.

    ``key`` is a scraper-defined string (region PK, keyword name,
    listing URL, 'channel:date'). Sync only ever creates rows and
    refreshes ``label`` — ``priority``/``is_active`` are admin knobs
    and are never overwritten (is_active is a kill-switch layered on
    top of the source queryset's own enable flag).
    """

    job = models.ForeignKey(
        ScrapeJob, on_delete=models.CASCADE, related_name='items'
    )
    key = models.CharField(max_length=500)
    label = models.CharField(max_length=255, blank=True)
    priority = models.IntegerField(
        default=0,
        help_text='Higher priority items are processed first.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'scrape_job_item'
        unique_together = ('job', 'key')
        ordering = ['-priority', 'id']

    def __str__(self):
        return f'{self.job.slug}:{self.key}'


class ScrapeJobRun(models.Model):
    """One execution of a ScrapeJob within a cycle."""

    RUNNING = 'RUNNING'
    SUCCESS = 'SUCCESS'
    FAILED = 'FAILED'
    ABANDONED = 'ABANDONED'
    PARTIAL = 'PARTIAL'
    STATUS_CHOICES = [
        (RUNNING, 'Running'),
        (SUCCESS, 'Success'),
        (FAILED, 'Failed'),
        (ABANDONED, 'Abandoned'),
        (PARTIAL, 'Partial'),
    ]

    EXECUTED_BY_CHOICES = [
        ('local', 'Local'),
        ('gcp_cloud_run', 'GCP Cloud Run'),
    ]

    job = models.ForeignKey(
        ScrapeJob, on_delete=models.CASCADE, related_name='runs'
    )
    cycle_key = models.CharField(
        max_length=50, db_index=True,
        help_text='Resume scope — UTC date by default (--cycle).',
    )
    execution_id = models.CharField(
        max_length=200, db_index=True,
        help_text=(
            'Cloud Run execution+task id, or local-<host>-<pid>.'
        ),
    )
    executed_by = models.CharField(
        max_length=20, choices=EXECUTED_BY_CHOICES
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=RUNNING
    )
    last_completed_item = models.ForeignKey(
        ScrapeJobItem, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text='Heartbeat — touched at every item checkpoint and '
                  'between pages inside an item.',
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'scrape_job_run'
        indexes = [models.Index(fields=['job', 'cycle_key'])]

    def __str__(self):
        return f'{self.job.slug} run #{self.pk} [{self.status}]'


class ScrapeJobRunItem(models.Model):
    """Per-item completion record for a run — the resume skip-set."""

    DONE = 'DONE'
    FAILED = 'FAILED'
    SKIPPED = 'SKIPPED'
    STATUS_CHOICES = [
        (DONE, 'Done'),
        (FAILED, 'Failed'),
        (SKIPPED, 'Skipped'),
    ]

    run = models.ForeignKey(
        ScrapeJobRun, on_delete=models.CASCADE, related_name='items'
    )
    item = models.ForeignKey(ScrapeJobItem, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    error_message = models.TextField(blank=True)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'scrape_job_run_item'
        unique_together = ('run', 'item')

    def __str__(self):
        return f'{self.run_id}:{self.item.key} [{self.status}]'
