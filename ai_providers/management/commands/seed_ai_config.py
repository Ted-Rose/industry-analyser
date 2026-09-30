"""Seed AI configuration: provider presets + discovered job specs.

Idempotent — creates missing rows only, never overwrites existing
ones (admin edits are safe).
"""

from django.core.management.base import BaseCommand

from ai_providers.jobs import autodiscover_job_specs, ensure_job
from ai_providers.models import AIJob, AIProvider
from ai_providers.presets import PROVIDER_PRESETS


class Command(BaseCommand):
    help = (
        'Create missing AIProvider rows from PROVIDER_PRESETS and '
        'run ensure_job() for every AIJobSpec found in '
        '<app>/ai_jobs.py modules. Idempotent; never overwrites.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would change without writing anything.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        prefix = '[dry-run] ' if dry_run else ''

        providers_missing = 0
        for slug, preset in PROVIDER_PRESETS.items():
            if AIProvider.objects.filter(slug=slug).exists():
                self.stdout.write(f'provider {slug}: unchanged')
                continue
            if not dry_run:
                AIProvider.objects.create(slug=slug, **preset)
            providers_missing += 1
            self.stdout.write(f'provider {slug}: {prefix}created')

        specs = autodiscover_job_specs()
        jobs_new = 0
        jobs_synced = 0
        for spec in specs:
            existing = AIJob.objects.filter(slug=spec.slug).first()
            if dry_run:
                self.stdout.write(
                    f'job {spec.slug}: '
                    f'{self._dry_run_state(existing, spec)}'
                )
                continue
            ensure_job(spec)
            if existing is None:
                jobs_new += 1
                state = 'created'
            else:
                jobs_synced += 1
                state = 'synced'
            self.stdout.write(f'job {spec.slug}: {state}')

        self.stdout.write(self.style.SUCCESS(
            f'{prefix}done: providers {providers_missing} missing/'
            f'{len(PROVIDER_PRESETS)} presets; jobs {jobs_new} '
            f'created, {jobs_synced} synced/{len(specs)} specs.'
        ))

    @staticmethod
    def _dry_run_state(existing, spec):
        if existing is None:
            return 'would create (+default assignments)'
        if (
            existing.description != spec.description
            or list(existing.declared_roles or []) != list(spec.roles)
        ):
            return 'would sync description/roles'
        return 'unchanged'
