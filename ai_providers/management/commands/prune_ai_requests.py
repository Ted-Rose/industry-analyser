"""Delete old AIRequest rows and orphaned AIInput rows (PR-8 card).

An AIRequest is prunable when it is older than ``--older-than-days``
and **not referenced** by any foreign key (e.g.
``blogs.PageAnalysis.ai_request`` once PR-6 lands) — referencing
relations are discovered via ``AIRequest._meta.related_objects``, so
new consumers are picked up automatically. Afterwards, AIInput rows
no longer referenced by any AIRequest are removed too.
``AIPromptTemplate`` rows are never pruned.
"""

import datetime
import logging

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ai_providers.models import AIInput, AIRequest

logger = logging.getLogger('ai_providers')

DEFAULT_BATCH_SIZE = 1000


def referenced_request_pks():
    """Pks of AIRequest rows referenced by a FK/M2M from any model.

    Introspects ``AIRequest._meta.related_objects`` instead of
    hardcoding consumers, so e.g. ``blogs.PageAnalysis.ai_request``
    is honored automatically. ``_base_manager`` is used so relations
    on models with filtering default managers are still found.
    """
    pks = set()
    for rel in AIRequest._meta.related_objects:
        field = rel.field
        if field.many_to_many:
            through = rel.through
            column = field.m2m_reverse_field_name()
            values = through._base_manager.values_list(
                column, flat=True
            )
        else:
            values = (
                rel.related_model._base_manager
                .filter(**{f'{field.name}__isnull': False})
                .values_list(field.name, flat=True)
            )
        pks.update(values)
    return pks


def _delete_in_batches(queryset, batch_size):
    """Delete ``queryset`` batch-by-batch; returns rows deleted."""
    model = queryset.model
    deleted = 0
    while True:
        batch = list(queryset.values_list('pk', flat=True)[:batch_size])
        if not batch:
            return deleted
        model._base_manager.filter(pk__in=batch).delete()
        deleted += len(batch)


class Command(BaseCommand):
    help = (
        'Prune AIRequest rows older than N days (only those not '
        'referenced by any FK, e.g. blogs.PageAnalysis) and then '
        'delete AIInput rows no longer referenced by any AIRequest. '
        'AIPromptTemplate rows are never touched.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--older-than-days',
            type=int,
            required=True,
            help='Delete requests older than this many days '
                 '(e.g. 90).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be deleted without writing.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f'Delete batch size (default {DEFAULT_BATCH_SIZE}).',
        )

    def handle(self, *args, **options):
        days = options['older_than_days']
        if days < 0:
            raise CommandError('--older-than-days must be >= 0.')
        batch_size = options['batch_size']
        if batch_size < 1:
            raise CommandError('--batch-size must be >= 1.')
        cutoff = timezone.now() - datetime.timedelta(days=days)

        referenced = referenced_request_pks()
        old = AIRequest.objects.filter(created_at__lt=cutoff)
        prunable = old.exclude(pk__in=referenced)
        skipped = old.filter(pk__in=referenced).count()

        prefix = '[dry-run] ' if options['dry_run'] else ''
        if options['dry_run']:
            # Inputs whose only referencing requests are the prunable
            # ones (plus inputs already orphaned).
            surviving_inputs = (
                AIRequest.objects
                .exclude(pk__in=prunable.values('pk'))
                .exclude(input__isnull=True)
                .values('input_id')
            )
            orphan_count = (
                AIInput.objects.exclude(pk__in=surviving_inputs)
                .count()
            )
            self.stdout.write(self.style.SUCCESS(
                f'{prefix}{prunable.count()} AIRequest rows older '
                f'than {days} day(s) would be deleted; '
                f'{skipped} old rows kept (referenced by FK); '
                f'{orphan_count} AIInput rows would be deleted.'
            ))
            return

        deleted_requests = _delete_in_batches(prunable, batch_size)
        orphans = AIInput.objects.filter(requests__isnull=True)
        deleted_inputs = _delete_in_batches(orphans, batch_size)
        message = (
            f'{deleted_requests} AIRequest rows older than {days} '
            f'day(s) deleted; {skipped} old rows kept (referenced '
            f'by FK); {deleted_inputs} orphaned AIInput rows '
            f'deleted.'
        )
        logger.info('prune_ai_requests: %s', message)
        self.stdout.write(self.style.SUCCESS(message))
