from datetime import datetime

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
            help='Digest date YYYY-MM-DD; default today (UTC)',
        )
        parser.add_argument(
            '--top-n',
            type=int,
            default=5,
            dest='top_n',
            help='Number of stories in the digest (default: 5)',
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

        result = build_digest(
            day, top_n=options['top_n'], dry_run=options['dry_run'],
        )
        self.stdout.write(f"Digest {result['date']}:")
        for rank, headline, rationale in result['items']:
            self.stdout.write(
                f"  {rank}. {headline} ({rationale})"
            )
        if not result['items']:
            self.stdout.write('  (no qualifying stories)')
