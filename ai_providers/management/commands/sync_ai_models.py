"""Sync the model catalog of one AI provider (PR-5 card).

Fetches the provider's free model-listing endpoint and reconciles it
with the ``ai_model`` table: new models are registered (disabled
unless ``--enable-new``), existing rows get catalog-provided fields
refreshed. Nothing is disabled or deleted.
"""

from django.core.management.base import BaseCommand, CommandError

from ai_providers import errors
from ai_providers.catalog import sync_provider_models
from ai_providers.models import AIProvider


class Command(BaseCommand):
    help = (
        'Sync the model catalog for an AIProvider: sync_ai_models '
        'PROVIDER_SLUG [--enable-new] [--dry-run]. Calls the '
        'provider\'s free model-listing endpoint (requires the API '
        'key to be configured).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'provider_slug',
            help='Slug of an existing AIProvider row, e.g. '
                 "'openrouter' or 'gemini'.",
        )
        parser.add_argument(
            '--enable-new',
            action='store_true',
            help='Enable newly registered models (default: created '
                 'disabled).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would change without writing anything.',
        )

    def handle(self, *args, **options):
        slug = options['provider_slug']
        provider = AIProvider.objects.filter(slug=slug).first()
        if provider is None:
            raise CommandError(
                f"No AIProvider with slug '{slug}'. Create it in "
                f"admin or run 'seed_ai_config' first."
            )
        try:
            counts = sync_provider_models(
                provider,
                enable_new=options['enable_new'],
                dry_run=options['dry_run'],
            )
        except errors.AIError as e:
            raise CommandError(
                f'Catalog sync failed for {slug}: {e}'
            ) from e
        prefix = '[dry-run] ' if options['dry_run'] else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}{slug}: {counts["created"]} created, '
            f'{counts["updated"]} updated, '
            f'{counts["skipped"]} skipped.'
        ))
