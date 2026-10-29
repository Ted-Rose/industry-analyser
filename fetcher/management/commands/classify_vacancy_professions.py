"""Backfill Profession tags on stored vacancies (plan §5).

Runs entirely on stored ``Vacancy.title`` values — no HTTP — so
it can run anywhere the DB is reachable. Upserts the taxonomy
rows from ``PROFESSION_NAMES`` once (idempotent — admin
edits/additions afterwards are never clobbered), then walks the
titled vacancies and syncs ``VacancyProfession`` through-rows in
batches. Every titled vacancy ends up with exactly one link
('other' when nothing matches); NULL-title legacy rows are
skipped entirely.

Usage:
    python manage.py classify_vacancy_professions --dry-run
    python manage.py classify_vacancy_professions \
        --batch-size 1000 --limit 5000
    python manage.py classify_vacancy_professions --reclassify
    python manage.py classify_vacancy_professions \
        --ids 1655039 1655040
"""
import logging
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fetcher.models import (
    Profession,
    Vacancy,
    VacancyProfession,
)
from fetcher.professions import PROFESSION_NAMES, classify

logger = logging.getLogger('fetcher')


class Command(BaseCommand):
    help = (
        'Classify vacancy titles into Profession rows and sync '
        'VacancyProfession links. Stored titles only — no HTTP.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report per-category counts; write nothing.',
        )
        parser.add_argument(
            '--batch-size', type=int, default=500,
            help='Vacancies processed per batch (default: 500).',
        )
        parser.add_argument(
            '--limit', type=int, default=None,
            help='Max vacancies to classify.',
        )
        parser.add_argument(
            '--ids', nargs='+', type=int, default=None,
            help='Only these vacancy_portal_ids.',
        )
        parser.add_argument(
            '--reclassify', action='store_true',
            help='Re-tag vacancies that already have a profession '
                 '(default: only untagged titled rows).',
        )

    def handle(self, *args, **options):
        if options['batch_size'] < 1:
            raise CommandError('--batch-size must be >= 1.')
        if options['limit'] is not None and options['limit'] < 1:
            raise CommandError('--limit must be >= 1.')
        dry_run = options['dry_run']
        if not dry_run:
            self._upsert_professions()

        qs = Vacancy.objects.exclude(
            title__isnull=True
        ).exclude(title='')
        if options['ids']:
            qs = qs.filter(vacancy_portal_id__in=options['ids'])
            found = set(
                qs.values_list('vacancy_portal_id', flat=True)
            )
            missing = sorted(set(options['ids']) - found)
            if missing:
                self.stdout.write(self.style.WARNING(
                    f'{len(missing)} vacancy_portal_id(s) not '
                    f'found or untitled: {missing}'
                ))
        elif not options['reclassify']:
            # Default: only titled vacancies with no link yet.
            qs = qs.filter(professions__isnull=True)
        qs = qs.order_by('pk')
        if options['limit']:
            qs = qs[:options['limit']]

        categories = Counter()
        processed = 0
        linked = 0
        batch = []
        for vacancy in qs.iterator(
            chunk_size=options['batch_size']
        ):
            name = classify(vacancy.title or '')
            categories[name] += 1
            batch.append((vacancy.pk, name))
            processed += 1
            if len(batch) >= options['batch_size']:
                linked += self._sync_batch(batch, dry_run)
                batch = []
                self.stdout.write(
                    f'  ... classified {processed}'
                )
        if batch:
            linked += self._sync_batch(batch, dry_run)

        self.stdout.write('Per-category counts:')
        for name, count in sorted(
            categories.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            self.stdout.write(f'  {name}: {count}')
        verb = 'would write' if dry_run else 'wrote'
        message = (
            f'{processed} vacancy(ies) classified; '
            f'{verb} {linked} profession link(s)'
        )
        logger.info('classify_vacancy_professions: %s', message)
        self.stdout.write(self.style.SUCCESS(f'done: {message}'))

    def _upsert_professions(self):
        """Create any missing taxonomy rows — never clobbers
        admin edits or extra rows."""
        existing = set(
            Profession.objects.values_list('name', flat=True)
        )
        missing = [
            Profession(name=name)
            for name in PROFESSION_NAMES
            if name not in existing
        ]
        if missing:
            Profession.objects.bulk_create(
                missing, ignore_conflicts=True
            )
            self.stdout.write(
                f'Created {len(missing)} Profession row(s).'
            )

    def _sync_batch(self, batch, dry_run):
        """Sync through-rows for [(vacancy_pk, profession_name)].

        Returns how many links were (or would be) written —
        inserts the missing row and removes any stale ones
        (stale links only exist under --reclassify; the default
        queryset is already link-free)."""
        desired = dict(batch)  # vacancy_pk -> profession name
        # vacancy_pk -> set of current profession names
        existing = {}
        for vacancy_pk, name in VacancyProfession.objects.filter(
            vacancy_id__in=desired
        ).values_list('vacancy_id', 'profession__name'):
            existing.setdefault(vacancy_pk, set()).add(name)

        changed = {
            pk for pk, name in desired.items()
            if existing.get(pk, set()) != {name}
        }
        if dry_run:
            return len(changed)
        if not changed:
            return 0
        professions = {
            p.name: p.id
            for p in Profession.objects.filter(
                name__in={desired[pk] for pk in changed}
            )
        }
        # A vacancy lands on exactly one link: delete the stale
        # set outright, then insert the desired row (idempotent
        # via unique_together + ignore_conflicts). Atomic — a
        # mid-batch failure must not leave vacancies link-free.
        with transaction.atomic():
            VacancyProfession.objects.filter(
                vacancy_id__in=changed
            ).delete()
            VacancyProfession.objects.bulk_create(
                [
                    VacancyProfession(
                        vacancy_id=pk,
                        profession_id=professions[desired[pk]],
                    )
                    for pk in changed
                ],
                ignore_conflicts=True,
            )
        return len(changed)
