"""Backfill ``Program.show`` for legacy airing rows
(tv_show_normalization_plan.md §7).

Every ``Program`` row whose ``show`` is null gets mapped onto a
canonical ``Show`` via the same dedup key the scraper uses
(normalized title + description + season/episode). Shows are created
with ``enrichment_status='pending'`` — or ``'enriched'`` when the
legacy row already carries an ``imdb_id`` — and enrichment is left
to ``enrich_tv_shows``.

Idempotent: only ``show IS NULL`` rows are touched, so a re-run is a
no-op. Rows that would collide on ``(show, channel, start_time)``
keep a null ``show`` and are reported instead of violating the
unique constraint.
"""

import logging
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from tv_programs.classification import EXCLUDED_LOCAL_SHOWS
from tv_programs.dedup import annotate_result, normalize_title
from tv_programs.models import Program, Show

logger = logging.getLogger('tv_programs')

DEFAULT_BATCH_SIZE = 500


class Command(BaseCommand):
    help = (
        'Map legacy Program rows (show IS NULL) onto canonical Show '
        'rows keyed by dedup_key. Idempotent; --dry-run prints the '
        'expected Show count without writing.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print expected Show count without writing.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f'Programs processed per query (default '
                 f'{DEFAULT_BATCH_SIZE}).',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        if batch_size < 1:
            raise CommandError('--batch-size must be >= 1.')
        dry_run = options['dry_run']
        prefix = '[dry-run] ' if dry_run else ''

        self._excluded = {
            normalize_title(t).casefold() for t in EXCLUDED_LOCAL_SHOWS
        }

        pending = Program.objects.filter(show__isnull=True)
        total = pending.count()
        self.stdout.write(f'{total} program(s) without a show')

        if dry_run:
            keys = set()
            for title_lv, description_lv in pending.values_list(
                'title_lv', 'description_lv'
            ).iterator():
                keys.add(
                    annotate_result({
                        'title_lv': title_lv,
                        'description_lv': description_lv or '',
                    })['dedup_key']
                )
            self.stdout.write(self.style.SUCCESS(
                f'{prefix}{total} program(s) -> {len(keys)} show(s)'
            ))
            return

        # Colliding rows keep show NULL and stay "pending" — track and
        # exclude them so the loop terminates and counts stay exact.
        self._skipped_pks = set()
        total_linked = 0
        total_shows = 0
        total_collisions = 0
        while True:
            batch = list(
                pending.exclude(pk__in=self._skipped_pks)
                .select_related('channel')
                .order_by('start_time', 'id')[:batch_size]
            )
            if not batch:
                break
            linked, created, collisions = self._link_batch(batch)
            total_linked += linked
            total_shows += created
            total_collisions += collisions
            self.stdout.write(
                f'linked {linked} program(s), {created} new show(s), '
                f'{collisions} collision(s) this batch'
            )

        message = (
            f'{total_linked} program(s) linked, {total_shows} '
            f'show(s) created, {total_collisions} collision(s) '
            f'left unlinked'
        )
        logger.info('backfill_program_shows: %s', message)
        self.stdout.write(self.style.SUCCESS(f'done: {message}'))

    def _link_batch(self, batch):
        """Resolve/create Shows for one batch and bulk-update the
        airings. Returns (linked, shows_created, collisions)."""
        shows_cache = {}
        for prog in batch:
            info = annotate_result({
                'title_lv': prog.title_lv,
                'description_lv': prog.description_lv or '',
                'image_url': prog.image_url,
            })
            prog._dedup_info = info
            key = info['dedup_key']
            if key in shows_cache:
                continue
            shows_cache[key] = Show.objects.filter(
                dedup_key=key
            ).first()

        created_keys = set()
        updates = []
        collisions = 0
        taken = self._taken_triples(batch)
        for prog in batch:
            info = prog._dedup_info
            show = shows_cache[info['dedup_key']]
            if show is None:
                show = Show.objects.create(
                    **self._show_defaults(prog, info)
                )
                shows_cache[info['dedup_key']] = show
                created_keys.add(info['dedup_key'])
            triple = (show.pk, prog.channel_id, prog.start_time)
            if triple in taken:
                collisions += 1
                self._skipped_pks.add(prog.pk)
                logger.warning(
                    'program %s collides on (show, channel, '
                    'start_time) — leaving show null', prog.pk
                )
                continue
            prog.show = show
            updates.append(prog)
            taken.add(triple)
        if updates:
            Program.objects.bulk_update(updates, ['show'])
        return len(updates), len(created_keys), collisions

    @staticmethod
    def _taken_triples(batch):
        """(show, channel, start_time) tuples already stored for the
        shows/channels/times in this batch."""
        keys = {p._dedup_info['dedup_key'] for p in batch}
        show_ids = set(
            Show.objects.filter(dedup_key__in=keys).values_list(
                'pk', flat=True
            )
        )
        return set(
            Program.objects.filter(
                show_id__in=show_ids,
                channel_id__in={p.channel_id for p in batch},
                start_time__in={p.start_time for p in batch},
            ).values_list('show_id', 'channel_id', 'start_time')
        )

    def _show_defaults(self, prog, info):
        imdb_id = prog.imdb_id or None
        imdb_url = None
        if imdb_id:
            if prog.url and 'imdb.com' in prog.url:
                imdb_url = prog.url
            else:
                imdb_url = f'https://www.imdb.com/title/{imdb_id}/'
        try:
            imdb_rating = (
                Decimal(str(prog.imdb_rating))
                if prog.imdb_rating not in (None, '')
                else None
            )
        except InvalidOperation:
            imdb_rating = None
        excluded = (
            info['title_norm'].casefold() in self._excluded
            or (info['series_title'] or '').casefold() in self._excluded
        )
        return {
            'title_lv': info['title_norm'],
            'series_title': info['series_title'],
            'series_season': info['season'],
            'series_episode': info['episode'],
            'description_lv': info['desc_norm'] or None,
            'dedup_key': info['dedup_key'],
            'title_eng': prog.title_eng,
            'description_eng': prog.description_eng,
            'imdb_id': imdb_id,
            'imdb_url': imdb_url,
            'imdb_rating': imdb_rating,
            'pg_rating': prog.pg_rating,
            'image_url': prog.image_url or None,
            'content_type': prog.content_type,
            'classification_confidence': (
                prog.classification_confidence or 0.0
            ),
            'classification_reasoning': prog.classification_reasoning,
            'enrichment_status': (
                'enriched' if imdb_id else 'pending'
            ),
            'enrichment_source': (
                prog.enrichment_source or ('omdb' if imdb_id else None)
            ),
            'title_match_ratio': prog.title_match_ratio or 0,
            'is_excluded': bool(excluded),
        }
