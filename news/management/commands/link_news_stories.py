from django.core.management.base import BaseCommand

from news.clustering import link_unmatched_articles


class Command(BaseCommand):
    help = (
        'Cluster recent unmatched articles into NewsStory rows '
        '(Jaccard title similarity)'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=2,
            help='How many days back to consider unmatched '
                 'articles (default: 2)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Compute clusters without writing',
        )

    def handle(self, *args, **options):
        stats = link_unmatched_articles(
            days=options['days'],
            dry_run=options['dry_run'],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"linked={stats['linked']} "
                f"new_stories={stats['new_stories']}"
            )
        )
