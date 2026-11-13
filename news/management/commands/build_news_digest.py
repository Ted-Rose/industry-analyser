from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from news.digest import build_digest


class Command(BaseCommand):
    help = (
        'Build the ranked daily news digest (top unique stories '
        'by coverage x topic weight)'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default=None,
            help='Digest date YYYY-MM-DD; default today (UTC). '
                 'With --days this is the LAST day built',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=1,
            help='Backfill: build digests for this many '
                 'consecutive days ending at --date '
                 '(default: 1 — single day)',
        )
        parser.add_argument(
            '--top-n',
            type=int,
            default=20,
            dest='top_n',
            help='Number of stories in the digest (default: 20)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Print the digest without writing it',
        )

    def handle(self, *args, **options):
        if options['date']:
            try:
                day = datetime.strptime(
                    options['date'], '%Y-%m-%d'
                ).date()
            except ValueError:
                raise CommandError(
                    f"invalid --date {options['date']!r}: "
                    'expected YYYY-MM-DD'
                ) from None
        else:
            day = timezone.localdate()

        days = options['days']
        if days < 1:
            raise CommandError('--days must be >= 1')

        # Oldest first so the output reads chronologically.
        for offset in range(days - 1, -1, -1):
            result = build_digest(
                day - timedelta(days=offset),
                top_n=options['top_n'],
                dry_run=options['dry_run'],
            )
            self._print(result)

    def _print(self, result):
        self.stdout.write(f"Digest {result['date']}:")
        for rank, headline, rationale in result['items']:
            self.stdout.write(
                f"  {rank}. {headline} ({rationale})"
            )
        if not result['items']:
            self.stdout.write('  (no qualifying stories)')
