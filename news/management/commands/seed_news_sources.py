from django.core.management.base import BaseCommand

from news.feeds import ensure_seeded


class Command(BaseCommand):
    help = (
        'Seed NewsSource rows from NEWS_FEEDS and NewsTopic rows '
        'from TOPICS (idempotent; never overwrites admin edits)'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Report what would be created without writing',
        )

    def handle(self, *args, **options):
        stats = ensure_seeded(dry_run=options['dry_run'])
        self.stdout.write(
            self.style.SUCCESS(
                f"News seed complete: {stats['sources_created']} "
                f"source(s), {stats['topics_created']} topic(s) "
                f"created"
            )
        )
