"""Backfill PageAnalysis.ai_model for legacy rows (PR-7 card).

Rows written before the ``ai_model`` FK existed carry the served
model's API id in the ``model`` string column and a null ``ai_model``.
For each distinct ``model`` value — excluding ``content_analyzer``
(the media-heavy heuristic; no AI call stands behind those rows) —
this command ``get_or_create``s an ``AIModel`` under the ``gemini``
provider (``auto_registered=True``) and sets ``ai_model`` on the
matching rows in ``--batch-size`` UPDATE chunks. A missing ``gemini``
provider row is created from ``PROVIDER_PRESETS`` (same seeding path
as ``ensure_job()``), so ``seed_ai_config`` is not a prerequisite.

``ai_request`` stays null — there is no historic request data.

Idempotent: only rows with ``ai_model IS NULL`` are touched, so a
re-run updates nothing. ``--dry-run`` prints per-model counts
without writing.
"""

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from ai_providers.models import AIModel, AIProvider
from ai_providers.presets import PROVIDER_PRESETS
from blogs.models import PageAnalysis

logger = logging.getLogger('blogs')

DEFAULT_BATCH_SIZE = 500
GEMINI_PROVIDER_SLUG = 'gemini'
HEURISTIC_MODEL = 'content_analyzer'


class Command(BaseCommand):
    help = (
        'Set PageAnalysis.ai_model on legacy rows by mapping each '
        'distinct PageAnalysis.model string to an AIModel under the '
        'gemini provider (auto-registered). Rows with model='
        'content_analyzer keep a null ai_model. Idempotent; '
        'ai_request stays null.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print per-model counts without writing anything.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f'Rows updated per query (default {DEFAULT_BATCH_SIZE}).',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        if batch_size < 1:
            raise CommandError('--batch-size must be >= 1.')
        dry_run = options['dry_run']
        prefix = '[dry-run] ' if dry_run else ''

        pending = PageAnalysis.objects.filter(ai_model__isnull=True)
        counts = dict(
            pending.exclude(model=HEURISTIC_MODEL)
            .values_list('model')
            .annotate(total=Count('pk'))
            .order_by('model')
        )
        skipped = pending.filter(model=HEURISTIC_MODEL).count()

        provider = AIProvider.objects.filter(
            slug=GEMINI_PROVIDER_SLUG
        ).first()
        if provider is None:
            preset = PROVIDER_PRESETS.get(GEMINI_PROVIDER_SLUG)
            if preset is None:
                raise CommandError(
                    f'No "{GEMINI_PROVIDER_SLUG}" AIProvider row and '
                    'no PROVIDER_PRESETS entry — run seed_ai_config.'
                )
            if dry_run:
                self.stdout.write(
                    f'{prefix}provider {GEMINI_PROVIDER_SLUG}: '
                    'would be created from PROVIDER_PRESETS'
                )
            else:
                provider = AIProvider.objects.create(
                    slug=GEMINI_PROVIDER_SLUG, **dict(preset)
                )
                self.stdout.write(
                    f'provider {GEMINI_PROVIDER_SLUG}: created from '
                    'PROVIDER_PRESETS'
                )

        total_updated = 0
        for name, row_count in counts.items():
            exists = (
                provider is not None
                and AIModel.objects.filter(
                    provider=provider, name=name
                ).exists()
            )
            if dry_run:
                state = 'existing AIModel' if exists else 'new AIModel'
                self.stdout.write(
                    f'{prefix}model {name}: {row_count} row(s) '
                    f'-> {state}'
                )
                continue
            ai_model, created = AIModel.objects.get_or_create(
                provider=provider,
                name=name,
                defaults={'auto_registered': True},
            )
            updated = self._backfill_model(name, ai_model, batch_size)
            total_updated += updated
            state = 'created' if created else 'existing'
            self.stdout.write(
                f'model {name}: {updated} row(s) updated '
                f'({state} AIModel {ai_model})'
            )

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                f'{prefix}{len(counts)} model(s), '
                f'{sum(counts.values())} row(s) would be updated; '
                f'{skipped} {HEURISTIC_MODEL} row(s) left null'
            ))
            return
        message = (
            f'{len(counts)} model(s), {total_updated} row(s) updated; '
            f'{skipped} {HEURISTIC_MODEL} row(s) left null'
        )
        logger.info('backfill_page_analysis_ai_models: %s', message)
        self.stdout.write(self.style.SUCCESS(f'done: {message}'))

    @staticmethod
    def _backfill_model(model_name, ai_model, batch_size):
        """UPDATE matching rows in pk batches; returns rows updated.

        The ``ai_model__isnull`` filter is re-evaluated per batch, so
        rows concurrently written by the scraper are picked up (or
        skipped if they already got an FK).
        """
        updated = 0
        while True:
            batch = list(
                PageAnalysis.objects
                .filter(model=model_name, ai_model__isnull=True)
                .values_list('pk', flat=True)[:batch_size]
            )
            if not batch:
                return updated
            PageAnalysis.objects.filter(pk__in=batch).update(
                ai_model=ai_model
            )
            updated += len(batch)
