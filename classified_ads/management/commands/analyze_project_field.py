from django.core.management.base import BaseCommand
from django.db.models import Count
from classified_ads.models import (
    ApartmentForRent,
    ApartmentForSale,
    Project,
)


class Command(BaseCommand):
    help = 'Analyze project normalization status'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(
            '\n=== PROJECT NORMALIZATION ANALYSIS ==='
        ))

        self.stdout.write(self.style.SUCCESS(
            '\n--- Normalized Projects ---'
        ))
        projects = Project.objects.annotate(
            rent_count=Count('apartmentforrent_ads'),
            sale_count=Count('apartmentforsale_ads')
        ).order_by('-rent_count', '-sale_count')

        for project in projects:
            total = project.rent_count + project.sale_count
            self.stdout.write(
                f'{project.name:30s} | '
                f'Total: {total:5d} '
                f'(Rent: {project.rent_count:4d}, '
                f'Sale: {project.sale_count:4d})'
            )

        for model, name in [
            (ApartmentForRent, 'ApartmentForRent'),
            (ApartmentForSale, 'ApartmentForSale')
        ]:
            self.analyze_model(model, name)

    def analyze_model(self, model, name):
        self.stdout.write(self.style.WARNING(f'\n--- {name} ---'))

        total = model.all_objects.count()
        normalized = model.all_objects.filter(
            project__isnull=False
        ).count()
        unmapped = total - normalized

        self.stdout.write(f'Total records: {total}')
        self.stdout.write(
            f'Normalized: {normalized} '
            f'({normalized / total * 100:.1f}%)'
        )
        self.stdout.write(
            f'Unmapped: {unmapped} '
            f'({unmapped / total * 100:.1f}%)'
        )

        if unmapped > 0:
            self.stdout.write('\nUnmapped project_raw values:')
            unmapped_values = (
                model.all_objects
                .filter(project__isnull=True)
                .values('project_raw')
                .annotate(count=Count('id'))
                .order_by('-count')
            )
            for i, item in enumerate(unmapped_values[:20], 1):
                raw = item['project_raw']
                count = item['count']
                self.stdout.write(f'{i:2d}. "{raw}" - {count} ads')
