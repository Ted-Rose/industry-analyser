"""Send exactly one AI request through the JobClient (PR-4 card).

The client is built around an *existing* AIJob row looked up by
``--job`` — no default assignments are seeded and arbitrary slugs
never create jobs. ``max_requests_per_run=1`` guarantees at most one
provider call is sent.
"""

from django.core.management.base import BaseCommand, CommandError

from ai_providers import errors
from ai_providers.client import get_job_client
from ai_providers.models import AIJob


class Command(BaseCommand):
    help = (
        'Send exactly one request through JobClient for an existing '
        'AIJob: --job SLUG --role ROLE [--prompt TEXT]. Prints '
        'status/model/tokens/cost. WARNING: this calls the real '
        'provider API (potentially paid).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--job',
            required=True,
            help='Slug of an existing AIJob row.',
        )
        parser.add_argument(
            '--role',
            required=True,
            help='Role to use; must be in the job\'s declared_roles.',
        )
        parser.add_argument(
            '--prompt',
            default='Reply with the word: ok',
            help='Prompt text, sent as a raw-layout prompt.',
        )

    def handle(self, *args, **options):
        slug = options['job']
        job = AIJob.objects.filter(slug=slug).first()
        if job is None:
            raise CommandError(
                f"No AIJob with slug '{slug}'. Create it in admin "
                f"or run 'seed_ai_config' first."
            )
        try:
            client = get_job_client(job, max_requests_per_run=1)
            result = client.generate(options['prompt'], options['role'])
        except errors.AIError as e:
            raise CommandError(str(e)) from e
        request = result.ai_request
        self.stdout.write(self.style.SUCCESS(
            f'status={result.status} '
            f'requested={result.requested_model} '
            f'served={result.served_model} '
            f'tokens={request.input_tokens}/{request.output_tokens} '
            f'cost_usd={request.cost_usd} '
            f'latency_ms={request.latency_ms}'
        ))
        if result.status == 'blocked':
            self.stdout.write(f'block_reason={result.block_reason}')
        else:
            self.stdout.write(
                f'response={request.response_text[:200]!r}'
            )
