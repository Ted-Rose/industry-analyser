import logging
from abc import ABC, abstractmethod
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

logger = logging.getLogger('core_scraper')


class BaseRefetchCommand(BaseCommand, ABC):
    """
    Abstract base class for refetch commands across all scraping apps.

    Provides common functionality for refetching and updating existing
    scraped data based on filters or specific IDs.

    Subclasses must implement:
    - get_model(): Return the Django model class
    - get_scraper_class(): Return the scraper class
    - get_default_update_fields(): Return list of fields to update
    """

    help = 'Refetch and update existing scraped data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--ids',
            nargs='+',
            help='Specific ad IDs to refetch',
        )
        parser.add_argument(
            '--filter',
            type=str,
            help=(
                'Django filter expression (e.g., '
                '"post_date__isnull=True" or "size__lt=20")'
            ),
        )
        parser.add_argument(
            '--fields',
            type=str,
            help=(
                'Comma-separated list of fields to update '
                '(default: all enrichment fields)'
            ),
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Maximum number of records to process',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Number of records to update in each batch (default: 100)',
        )

    @abstractmethod
    def get_model(self):
        """Return the Django model class to refetch."""
        pass

    @abstractmethod
    def get_scraper_class(self):
        """Return the scraper class to use for refetching."""
        pass

    @abstractmethod
    def get_default_update_fields(self):
        """
        Return list of fields to update by default.
        Should include fields populated during enrichment.
        """
        pass

    def parse_filter(self, filter_str):
        """
        Parse a filter string into Django Q object.

        Supports simple filters like:
        - "post_date__isnull=True"
        - "size__lt=20"
        - "district=Centrs"

        Args:
            filter_str (str): Filter expression

        Returns:
            Q: Django Q object
        """
        if not filter_str:
            return Q()

        try:
            if '=' not in filter_str:
                raise ValueError(
                    "Filter must be in format 'field__lookup=value'"
                )

            key, value = filter_str.split('=', 1)
            key = key.strip()
            value = value.strip()

            if value.lower() == 'true':
                value = True
            elif value.lower() == 'false':
                value = False
            elif value.lower() == 'none':
                value = None
            else:
                try:
                    value = int(value)
                except ValueError:
                    try:
                        value = float(value)
                    except ValueError:
                        pass

            return Q(**{key: value})

        except Exception as e:
            raise CommandError(f"Invalid filter expression: {e}")

    def handle(self, *args, **options):
        model = self.get_model()
        scraper_class = self.get_scraper_class()
        default_fields = self.get_default_update_fields()

        ids = options.get('ids')
        filter_str = options.get('filter')
        fields_str = options.get('fields')
        dry_run = options.get('dry_run', False)
        limit = options.get('limit')
        batch_size = options.get('batch_size', 100)

        if not ids and not filter_str:
            raise CommandError(
                'Must provide either --ids or --filter argument'
            )

        update_fields = (
            fields_str.split(',') if fields_str else default_fields
        )
        update_fields = [f.strip() for f in update_fields]

        queryset = model.all_objects.all() if hasattr(
            model, 'all_objects'
        ) else model.objects.all()

        if ids:
            queryset = queryset.filter(ad_id__in=ids)
            self.stdout.write(
                f"Filtering by {len(ids)} specific ID(s)"
            )
        elif filter_str:
            filter_q = self.parse_filter(filter_str)
            queryset = queryset.filter(filter_q)
            self.stdout.write(f"Filtering by: {filter_str}")

        if limit:
            queryset = queryset[:limit]

        total_count = queryset.count()

        if total_count == 0:
            self.stdout.write(
                self.style.WARNING('No records found matching criteria')
            )
            return

        self.stdout.write(
            f"Found {total_count} record(s) to refetch"
        )
        self.stdout.write(f"Fields to update: {', '.join(update_fields)}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    '\n=== DRY RUN MODE - No changes will be made ===\n'
                )
            )
            for record in queryset[:10]:
                self.stdout.write(
                    f"  - {record.ad_id}: {record.link}"
                )
            if total_count > 10:
                self.stdout.write(f"  ... and {total_count - 10} more")
            return

        scraper = scraper_class()

        success_count = 0
        error_count = 0
        batch = []

        self.stdout.write('\nRefetching records...')

        for i, record in enumerate(queryset, 1):
            try:
                updated_data = scraper.refetch_single(record)

                if updated_data:
                    updated_any = False
                    for field in update_fields:
                        if field in updated_data:
                            old_value = getattr(record, field, None)
                            new_value = updated_data[field]
                            if old_value != new_value:
                                setattr(record, field, new_value)
                                updated_any = True

                    if updated_any:
                        batch.append(record)

                    if len(batch) >= batch_size:
                        model.all_objects.bulk_update(
                            batch, update_fields
                        ) if hasattr(
                            model, 'all_objects'
                        ) else model.objects.bulk_update(
                            batch, update_fields
                        )
                        success_count += len(batch)
                        self.stdout.write(
                            f"  Updated {success_count}/{total_count} "
                            f"records..."
                        )
                        batch = []
                else:
                    error_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Failed to refetch: {record.ad_id}"
                        )
                    )

            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"  Error processing {record.ad_id}: {e}"
                    )
                )

        if batch:
            model.all_objects.bulk_update(
                batch, update_fields
            ) if hasattr(
                model, 'all_objects'
            ) else model.objects.bulk_update(batch, update_fields)
            success_count += len(batch)

        self.stdout.write(
            self.style.SUCCESS(
                f'\nRefetch complete: {success_count} updated, '
                f'{error_count} errors'
            )
        )
