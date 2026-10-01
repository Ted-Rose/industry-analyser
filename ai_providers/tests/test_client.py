"""Tests for PR-4: jobs.py (AIJobSpec/ensure_job/autodiscovery),
client.py (JobClient/get_job_client) and AIRequest.rendered_prompt().

All provider calls go through fake adapter classes injected into
PROVIDER_CLASSES — no network, no real SDKs, no API keys. time.sleep
is patched to a no-op so backoff/throttle never delay the tests.
"""

import dataclasses
import hashlib
import types as py_types
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from ai_providers import errors
from ai_providers.client import JobClient, get_job_client
from ai_providers.jobs import (
    AIJobSpec,
    autodiscover_job_specs,
    ensure_job,
)
from ai_providers.models import (
    AIInput,
    AIJob,
    AIJobModel,
    AIModel,
    AIPromptTemplate,
    AIProvider,
    AIRequest,
    rendered_prompt_sha256,
)
from ai_providers.prompts import render_prompt
from ai_providers.providers import PROVIDER_CLASSES
from ai_providers.providers.base import BaseAIProvider
from ai_providers.types import (
    AIResponse,
    GenerationOptions,
    ImagePart,
    PromptSpec,
)

API_KEY = 'TESTKEY-do-not-leak-123'

SPEC = AIJobSpec(
    slug='test.job',
    description='test job description',
    roles=('cheap', 'expensive'),
    default_assignments={
        'cheap': [('gemini', 'gemini-2.5-flash-lite')],
        'expensive': [('gemini', 'gemini-2.5-pro')],
    },
)


class FakeProvider(BaseAIProvider):
    """Scripted adapter: ``script`` maps model name -> a list of
    AIResponse/exception outcomes consumed one per call."""

    provider_type = 'fake'
    script = {}
    calls = []

    def generate(self, model, prompt, options):
        type(self).calls.append(
            {'model': model, 'prompt': prompt, 'options': options}
        )
        queue = type(self).script.get(model) or []
        outcome = (
            queue.pop(0) if queue
            else AIResponse(text='ok', served_model=model)
        )
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    @classmethod
    def called_models(cls):
        return [call['model'] for call in cls.calls]


class FakeGemini(FakeProvider):
    provider_type = 'gemini'
    script = {}
    calls = []


class FakeOpenRouter(FakeProvider):
    provider_type = 'openai_compatible'
    script = {}
    calls = []


def make_provider(slug='gemini', provider_type='gemini',
                  api_key_setting='GEMINI_API_KEY', **kwargs):
    defaults = {
        'slug': slug,
        'display_name': slug,
        'provider_type': provider_type,
        'api_key_setting': api_key_setting,
        'max_retries': 2,
        'backoff_base_seconds': 0.0,
    }
    defaults.update(kwargs)
    return AIProvider.objects.create(**defaults)


def make_model(provider, name='model-1', **kwargs):
    return AIModel.objects.create(provider=provider, name=name,
                                  **kwargs)


def make_job(slug='test.job', roles=('cheap', 'expensive'), **kwargs):
    defaults = {'slug': slug, 'declared_roles': list(roles)}
    defaults.update(kwargs)
    return AIJob.objects.create(**defaults)


def assign(job, model, role, priority=0, **kwargs):
    return AIJobModel.objects.create(
        job=job, model=model, role=role, priority=priority, **kwargs
    )


def make_request(job, model, role='cheap', **kwargs):
    defaults = {
        'job': job,
        'role': role,
        'requested_model': model,
        'attempt': 1,
        'status': 'success',
        'prompt_layout': 'raw',
        'prompt_chars': 4,
        'prompt_sha256': 'a' * 64,
    }
    defaults.update(kwargs)
    return AIRequest.objects.create(**defaults)


def prompt(input_text='some input', template_text='instructions',
           layout='inline_v1', key='test.template'):
    return PromptSpec(
        template_key=key,
        template_text=template_text,
        input_text=input_text,
        layout=layout,
    )


@override_settings(GEMINI_API_KEY=API_KEY, OPENROUTER_API_KEY=API_KEY)
@mock.patch('time.sleep', lambda *args, **kwargs: None)
class JobClientTestCase(TestCase):
    """Base: patched PROVIDER_CLASSES, fresh fake state per test."""

    def setUp(self):
        super().setUp()
        FakeGemini.script = {}
        FakeGemini.calls = []
        FakeOpenRouter.script = {}
        FakeOpenRouter.calls = []
        patcher = mock.patch.dict(
            PROVIDER_CLASSES,
            {
                'gemini': FakeGemini,
                'openai_compatible': FakeOpenRouter,
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.provider = make_provider()
        self.model = make_model(self.provider, name='m1')
        self.job = make_job()
        assign(self.job, self.model, 'cheap')

    def job_client(self, **kwargs):
        """A JobClient over the setUp job (self.client stays the
        Django test client)."""
        return JobClient(self.job, **kwargs)


class GenerateTests(JobClientTestCase):

    def test_success_returns_result_and_writes_request(self):
        with self.assertLogs('ai_providers', level='INFO'):
            result = self.job_client().generate(
                prompt(), 'cheap', GenerationOptions(temperature=0.1)
            )
        self.assertEqual(result.text, 'ok')
        self.assertEqual(result.status, 'success')
        self.assertIsNone(result.block_reason)
        self.assertEqual(result.requested_model, self.model)
        self.assertEqual(result.served_model, self.model)
        request = result.ai_request
        self.assertEqual(request.job, self.job)
        self.assertEqual(request.role, 'cheap')
        self.assertEqual(request.requested_model, self.model)
        self.assertEqual(request.attempt, 1)
        self.assertEqual(request.status, 'success')
        self.assertEqual(request.prompt_layout, 'inline_v1')
        self.assertEqual(
            request.options,
            {
                'json_mode': False,
                'temperature': 0.1,
                'max_output_tokens': None,
            },
        )
        self.assertIsNotNone(request.latency_ms)
        self.assertEqual(FakeGemini.called_models(), ['m1'])

    def test_request_count_tracks_attempts_sent(self):
        FakeGemini.script = {
            'm1': [errors.AIServerError('boom'),
                   errors.AIServerError('boom2'),
                   AIResponse(text='ok', served_model='m1')],
        }
        client = self.job_client()
        result = client.generate(prompt(), 'cheap')
        self.assertEqual(result.status, 'success')
        self.assertEqual(client.request_count, 3)
        self.assertEqual(AIRequest.objects.count(), 3)

    def test_fallback_order_by_priority(self):
        model2 = make_model(self.provider, name='m2')
        assign(self.job, model2, 'cheap', priority=1)
        FakeGemini.script = {
            'm1': [errors.AIBadRequestError('bad')],
        }
        result = self.job_client().generate(prompt(), 'cheap')
        self.assertEqual(result.served_model, model2)
        self.assertEqual(FakeGemini.called_models(), ['m1', 'm2'])

    def test_priority_order_not_creation_order(self):
        # m2 is assigned later but with a lower priority value, so it
        # is tried before m1 (ordering is priority, then id).
        AIJobModel.objects.filter(job=self.job).update(priority=1)
        model2 = make_model(self.provider, name='m2')
        assign(self.job, model2, 'cheap', priority=0)
        FakeGemini.script = {
            'm2': [errors.AIModelNotFoundError('gone')],
        }
        result = self.job_client().generate(prompt(), 'cheap')
        self.assertEqual(FakeGemini.called_models(), ['m2', 'm1'])
        self.assertEqual(result.served_model, self.model)

    def test_retryable_error_retries_then_next_model(self):
        model2 = make_model(self.provider, name='m2')
        assign(self.job, model2, 'cheap', priority=1)
        FakeGemini.script = {
            # max_retries=2 -> three attempts on m1, then m2.
            'm1': [errors.AIRateLimitError('slow down'),
                   errors.AITimeoutError('timeout'),
                   errors.AIServerError('500')],
        }
        result = self.job_client().generate(prompt(), 'cheap')
        self.assertEqual(result.served_model, model2)
        self.assertEqual(
            FakeGemini.called_models(), ['m1', 'm1', 'm1', 'm2']
        )
        attempts = list(
            AIRequest.objects.order_by('id').values_list(
                'requested_model__name', 'attempt', 'status'
            )
        )
        self.assertEqual(
            attempts,
            [
                ('m1', 1, 'error'),
                ('m1', 2, 'error'),
                ('m1', 3, 'error'),
                ('m2', 1, 'success'),
            ],
        )

    def test_model_error_goes_to_next_model_immediately(self):
        model2 = make_model(self.provider, name='m2')
        assign(self.job, model2, 'cheap', priority=1)
        FakeGemini.script = {
            'm1': [errors.AIModelNotFoundError('404')],
        }
        self.job_client().generate(prompt(), 'cheap')
        # One call only on m1 — AIModelError does not retry.
        self.assertEqual(FakeGemini.called_models(), ['m1', 'm2'])

    def test_provider_error_skips_provider_for_client_lifetime(self):
        other_provider = make_provider(
            slug='openrouter',
            provider_type='openai_compatible',
            api_key_setting='OPENROUTER_API_KEY',
            base_url='https://openrouter.ai/api/v1',
        )
        model_a2 = make_model(self.provider, name='m1b')
        model_b = make_model(other_provider, name='b1')
        assign(self.job, model_a2, 'cheap', priority=1)
        assign(self.job, model_b, 'cheap', priority=2)
        FakeGemini.script = {
            'm1': [errors.AIAuthError('bad key')],
        }
        client = self.job_client()
        result = client.generate(prompt(), 'cheap')
        # m1's provider error marks gemini dead: m1b is skipped even
        # though it is the next assignment; openrouter's b1 is used.
        self.assertEqual(result.served_model, model_b)
        self.assertEqual(FakeGemini.called_models(), ['m1'])
        self.assertEqual(FakeOpenRouter.called_models(), ['b1'])
        # Later generate() calls on the same client still skip gemini.
        client.generate(prompt(), 'cheap')
        self.assertEqual(FakeGemini.called_models(), ['m1'])
        self.assertEqual(FakeOpenRouter.called_models(), ['b1', 'b1'])

    def test_all_models_failed_raises(self):
        FakeGemini.script = {
            'm1': [errors.AIModelNotFoundError('gone')],
        }
        with self.assertRaises(errors.AIAllModelsFailedError) as ctx:
            self.job_client().generate(prompt(), 'cheap')
        self.assertIsInstance(
            ctx.exception.last_error, errors.AIModelNotFoundError
        )

    def test_unknown_role_raises_not_configured(self):
        with self.assertRaises(errors.AIJobNotConfiguredError):
            self.job_client().generate(prompt(), 'expensive')
        self.assertEqual(FakeGemini.calls, [])
        self.assertEqual(AIRequest.objects.count(), 0)

    def test_inactive_assignment_is_skipped(self):
        AIJobModel.objects.filter(job=self.job).update(is_active=False)
        with self.assertRaises(errors.AIJobNotConfiguredError):
            self.job_client().generate(prompt(), 'cheap')

    def test_blocked_response_returns_result(self):
        FakeGemini.script = {
            'm1': [AIResponse(
                text=None,
                served_model='m1',
                status='blocked',
                block_reason='SAFETY',
            )],
        }
        result = self.job_client().generate(prompt(), 'cheap')
        self.assertEqual(result.status, 'blocked')
        self.assertIsNone(result.text)
        self.assertEqual(result.block_reason, 'SAFETY')
        self.assertEqual(result.ai_request.status, 'blocked')
        self.assertEqual(result.ai_request.block_reason, 'SAFETY')

    def test_disabled_model_is_filtered_from_snapshot(self):
        self.model.is_enabled = False
        self.model.save()
        with self.assertRaises(errors.AIJobNotConfiguredError):
            self.job_client().generate(prompt(), 'cheap')

    def test_disabled_provider_is_filtered_from_snapshot(self):
        self.provider.is_enabled = False
        self.provider.save()
        with self.assertRaises(errors.AIJobNotConfiguredError):
            self.job_client().generate(prompt(), 'cheap')

    def test_disabled_job_raises_at_construction(self):
        self.job.is_enabled = False
        self.job.save()
        with self.assertRaises(errors.AIJobDisabledError):
            self.job_client()

    def test_json_mode_gated_per_assignment(self):
        """options.json_mode reaches only models flagged
        supports_json_mode — a fallback without the flag is called
        with json_mode=False (PR-16 review)."""
        self.model.supports_json_mode = True
        self.model.save()
        model2 = make_model(self.provider, name='m2')
        assign(self.job, model2, 'cheap', priority=1)
        FakeGemini.script = {
            'm1': [errors.AIBadRequestError('bad')],
        }
        result = self.job_client().generate(
            prompt(), 'cheap', GenerationOptions(json_mode=True)
        )
        self.assertEqual(result.served_model, model2)
        calls = FakeGemini.calls
        self.assertTrue(calls[0]['options'].json_mode)
        self.assertFalse(calls[1]['options'].json_mode)
        requests = AIRequest.objects.order_by('id')
        self.assertTrue(requests[0].options['json_mode'])
        self.assertFalse(requests[1].options['json_mode'])

    def test_json_mode_enabled_on_capable_fallback(self):
        """The inverse: the caller requests json_mode, the first
        model lacks the flag, a capable fallback still gets
        json_mode=True."""
        model2 = make_model(
            self.provider, name='m2', supports_json_mode=True
        )
        assign(self.job, model2, 'cheap', priority=1)
        FakeGemini.script = {
            'm1': [errors.AIBadRequestError('bad')],
        }
        result = self.job_client().generate(
            prompt(), 'cheap', GenerationOptions(json_mode=True)
        )
        self.assertEqual(result.served_model, model2)
        calls = FakeGemini.calls
        self.assertFalse(calls[0]['options'].json_mode)
        self.assertTrue(calls[1]['options'].json_mode)

    def test_supports_json_mode_any_capable_assignment(self):
        """supports_json_mode(role) is True when any assignment's
        model supports it, not just the first."""
        self.assertFalse(self.job_client().supports_json_mode('cheap'))
        model2 = make_model(
            self.provider, name='m2', supports_json_mode=True
        )
        assign(self.job, model2, 'cheap', priority=1)
        self.assertTrue(self.job_client().supports_json_mode('cheap'))

    def test_snapshot_isolation_from_admin_changes(self):
        client = self.job_client()
        # Admin change after construction has no effect this run.
        AIJobModel.objects.filter(job=self.job).update(is_active=False)
        result = client.generate(prompt(), 'cheap')
        self.assertEqual(result.status, 'success')
        # A new client sees the change.
        with self.assertRaises(errors.AIJobNotConfiguredError):
            JobClient(self.job).generate(prompt(), 'cheap')

    def test_images_reach_adapter_and_logged_as_options_meta(self):
        """PromptSpec.images flows through render_prompt to the
        adapter unchanged; AIRequest.options records per-image
        sha256/mime_type/bytes (never the bytes themselves) while
        prompt_sha256 still covers only the text parts."""
        image = ImagePart(data=b'PNGDATA', mime_type='image/png')
        spec = PromptSpec(
            template_key='test.template',
            template_text='instructions',
            input_text='some input',
            layout='inline_v1',
            images=(image,),
        )
        result = self.job_client().generate(spec, 'cheap')
        self.assertEqual(result.status, 'success')
        seen = FakeGemini.calls[0]['prompt'].images
        self.assertEqual(seen, (image,))
        images_meta = result.ai_request.options['images']
        self.assertEqual(len(images_meta), 1)
        self.assertEqual(images_meta[0]['mime_type'], 'image/png')
        self.assertEqual(images_meta[0]['bytes'], 7)
        self.assertEqual(
            images_meta[0]['sha256'],
            hashlib.sha256(b'PNGDATA').hexdigest(),
        )
        self.assertNotIn('PNGDATA', str(result.ai_request.options))
        expected = render_prompt(
            'instructions', 'some input', 'inline_v1'
        )
        self.assertEqual(
            result.ai_request.prompt_sha256,
            rendered_prompt_sha256(expected.system, expected.user),
        )


class CapTests(JobClientTestCase):

    def _always_failing(self):
        FakeGemini.script = {
            'm1': [
                errors.AIServerError(f'e{i}') for i in range(20)
            ],
        }

    def test_run_cap_argument(self):
        self._always_failing()
        client = self.job_client(max_requests_per_run=2)
        with self.assertRaises(errors.AIRequestCapReached):
            client.generate(prompt(), 'cheap')
        self.assertEqual(FakeGemini.called_models(), ['m1', 'm1'])
        self.assertEqual(client.request_count, 2)

    def test_run_cap_job_field(self):
        self.job.max_requests_per_run = 1
        self.job.save()
        self._always_failing()
        client = self.job_client()
        with self.assertRaises(errors.AIRequestCapReached):
            client.generate(prompt(), 'cheap')
        self.assertEqual(len(FakeGemini.calls), 1)

    def test_run_cap_is_min_of_job_and_argument(self):
        self.job.max_requests_per_run = 5
        self.job.save()
        self._always_failing()
        client = self.job_client(max_requests_per_run=2)
        with self.assertRaises(errors.AIRequestCapReached):
            client.generate(prompt(), 'cheap')
        self.assertEqual(len(FakeGemini.calls), 2)

    def test_day_cap_counts_existing_rows(self):
        self.job.max_requests_per_day = 1
        self.job.save()
        make_request(self.job, self.model)
        client = self.job_client()
        with self.assertRaises(errors.AIRequestCapReached):
            client.generate(prompt(), 'cheap')
        self.assertEqual(FakeGemini.calls, [])
        self.assertEqual(client.request_count, 0)

    def test_day_cap_includes_this_run(self):
        self.job.max_requests_per_day = 2
        self.job.save()
        client = self.job_client()
        client.generate(prompt(), 'cheap')          # 1st send ok
        client.generate(prompt(), 'cheap')          # 2nd send ok
        with self.assertRaises(errors.AIRequestCapReached):
            client.generate(prompt(), 'cheap')      # would be 3rd/day
        self.assertEqual(len(FakeGemini.calls), 2)


class ServedModelAndCostTests(JobClientTestCase):

    def test_served_model_auto_registered(self):
        FakeGemini.script = {
            'm1': [AIResponse(text='ok', served_model='m1-20250601')],
        }
        result = self.job_client().generate(prompt(), 'cheap')
        served = AIModel.objects.get(
            provider=self.provider, name='m1-20250601'
        )
        self.assertTrue(served.auto_registered)
        self.assertTrue(served.is_enabled)
        self.assertEqual(result.served_model, served)
        self.assertEqual(result.ai_request.served_model, served)
        self.assertEqual(result.requested_model, self.model)

    def test_last_used_at_updated_on_success(self):
        self.assertIsNone(self.model.last_used_at)
        self.job_client().generate(prompt(), 'cheap')
        self.model.refresh_from_db()
        self.assertIsNotNone(self.model.last_used_at)

    def test_last_used_at_updated_on_blocked(self):
        FakeGemini.script = {
            'm1': [AIResponse(
                text=None, served_model='m1', status='blocked',
            )],
        }
        self.job_client().generate(prompt(), 'cheap')
        self.model.refresh_from_db()
        self.assertIsNotNone(self.model.last_used_at)

    def test_cost_usd_math(self):
        self.model.input_price_per_mtok = Decimal('2.0')
        self.model.output_price_per_mtok = Decimal('4.0')
        self.model.save()
        FakeGemini.script = {
            'm1': [AIResponse(
                text='ok', served_model='m1',
                input_tokens=1000, output_tokens=500,
            )],
        }
        result = self.job_client().generate(prompt(), 'cheap')
        # (1000*2 + 500*4) / 1e6 = 0.004
        self.assertEqual(
            result.ai_request.cost_usd, Decimal('0.004000')
        )

    def test_cost_usd_null_when_price_unknown(self):
        FakeGemini.script = {
            'm1': [AIResponse(
                text='ok', served_model='m1',
                input_tokens=100, output_tokens=50,
            )],
        }
        result = self.job_client().generate(prompt(), 'cheap')
        self.assertIsNone(result.ai_request.cost_usd)
        self.assertEqual(result.ai_request.input_tokens, 100)
        self.assertEqual(result.ai_request.output_tokens, 50)

    def test_response_text_truncated_to_20000(self):
        FakeGemini.script = {
            'm1': [AIResponse(text='x' * 30000, served_model='m1')],
        }
        result = self.job_client().generate(prompt(), 'cheap')
        self.assertEqual(len(result.ai_request.response_text), 20000)

    def test_error_message_scrubbed_of_api_key(self):
        model2 = make_model(self.provider, name='m2')
        assign(self.job, model2, 'cheap', priority=1)
        FakeGemini.script = {
            'm1': [errors.AIServerError(f'key {API_KEY} invalid')],
        }
        self.job_client().generate(prompt(), 'cheap')
        error_rows = AIRequest.objects.filter(status='error')
        self.assertTrue(error_rows.exists())
        for row in error_rows:
            self.assertNotIn(API_KEY, row.error_message)
            self.assertIn('<redacted>', row.error_message)


class AdapterResolutionTests(JobClientTestCase):

    @override_settings(GEMINI_API_KEY='')
    def test_missing_api_key_is_provider_error(self):
        with self.assertRaises(errors.AIAllModelsFailedError) as ctx:
            self.job_client().generate(prompt(), 'cheap')
        self.assertIsInstance(
            ctx.exception.last_error,
            errors.AIProviderNotConfiguredError,
        )
        # Adapter construction failed: nothing was sent, no rows.
        self.assertEqual(FakeGemini.calls, [])
        self.assertEqual(AIRequest.objects.count(), 0)

    @override_settings(GEMINI_API_KEY='')
    def test_missing_key_falls_back_to_next_provider(self):
        other = make_provider(
            slug='openrouter',
            provider_type='openai_compatible',
            api_key_setting='OPENROUTER_API_KEY',
            base_url='https://openrouter.ai/api/v1',
        )
        model_b = make_model(other, name='b1')
        assign(self.job, model_b, 'cheap', priority=1)
        result = self.job_client().generate(prompt(), 'cheap')
        self.assertEqual(result.served_model, model_b)
        self.assertEqual(FakeOpenRouter.called_models(), ['b1'])

    def test_unknown_provider_type_is_provider_error(self):
        self.provider.provider_type = 'mystery'
        self.provider.save()
        with self.assertRaises(errors.AIAllModelsFailedError) as ctx:
            self.job_client().generate(prompt(), 'cheap')
        self.assertIsInstance(
            ctx.exception.last_error,
            errors.AIProviderNotConfiguredError,
        )


class BackoffAndThrottleTests(JobClientTestCase):

    def test_throttle_sleeps_between_sends(self):
        self.provider.min_request_interval_seconds = 5
        self.provider.save()
        FakeGemini.script = {
            'm1': [errors.AIServerError('boom'),
                   AIResponse(text='ok', served_model='m1')],
        }
        with mock.patch('time.sleep') as sleep_mock:
            self.job_client().generate(prompt(), 'cheap')
        # Two sleep calls: backoff (~0s, base is 0.0) then throttle.
        waits = [call.args[0] for call in sleep_mock.call_args_list]
        self.assertEqual(len(waits), 2)
        self.assertTrue(any(0 < wait <= 5 for wait in waits))

    def test_backoff_honours_retry_after(self):
        FakeGemini.script = {
            'm1': [errors.AIRateLimitError('rl', retry_after=7.5),
                   AIResponse(text='ok', served_model='m1')],
        }
        with mock.patch('time.sleep') as sleep_mock:
            self.job_client().generate(prompt(), 'cheap')
        waits = [call.args[0] for call in sleep_mock.call_args_list]
        self.assertEqual(len(waits), 1)
        # max(retry_after=7.5, base*2**0=0) with ±20% jitter.
        self.assertGreaterEqual(waits[0], 7.5 * 0.8)
        self.assertLessEqual(waits[0], 7.5 * 1.2)


class EnsureJobTests(TestCase):
    """ensure_job() semantics — no client needed."""

    def test_creates_job_providers_models_assignments(self):
        job = ensure_job(SPEC)
        self.assertEqual(job.slug, 'test.job')
        self.assertEqual(job.description, 'test job description')
        self.assertEqual(job.declared_roles, ['cheap', 'expensive'])
        provider = AIProvider.objects.get(slug='gemini')
        self.assertEqual(provider.provider_type, 'gemini')
        cheap = AIJobModel.objects.get(job=job, role='cheap')
        self.assertEqual(cheap.model.name, 'gemini-2.5-flash-lite')
        self.assertEqual(cheap.priority, 0)
        self.assertTrue(cheap.is_active)
        self.assertFalse(cheap.model.auto_registered)
        expensive = AIJobModel.objects.get(job=job, role='expensive')
        self.assertEqual(expensive.model.name, 'gemini-2.5-pro')

    def test_default_assignment_priorities_follow_list_order(self):
        spec = AIJobSpec(
            slug='multi.job',
            description='',
            roles=('default',),
            default_assignments={
                'default': [
                    ('gemini', 'first'),
                    ('openrouter', 'second'),
                    ('gemini', 'third'),
                ],
            },
        )
        ensure_job(spec)
        ordered = list(
            AIJobModel.objects.filter(job__slug='multi.job')
            .order_by('priority')
            .values_list('model__name', 'priority')
        )
        self.assertEqual(
            ordered, [('first', 0), ('second', 1), ('third', 2)]
        )

    def test_initial_applied_only_on_creation(self):
        job = ensure_job(SPEC, initial={'max_requests_per_run': 10})
        self.assertEqual(job.max_requests_per_run, 10)
        job = ensure_job(SPEC, initial={'max_requests_per_run': 5})
        self.assertEqual(job.max_requests_per_run, 10)

    def test_syncs_description_and_roles_not_assignments(self):
        job = ensure_job(SPEC)
        # Simulate an admin edit: deactivate the seeded assignment
        # and change the description by hand.
        AIJobModel.objects.filter(job=job).update(is_active=False)
        job.description = 'admin note'
        job.save()
        spec2 = AIJobSpec(
            slug=SPEC.slug,
            description='new description',
            roles=('cheap', 'expensive', 'extra'),
            default_assignments={
                'cheap': [('openrouter', 'other-model')],
            },
        )
        job = ensure_job(spec2)
        self.assertEqual(job.description, 'new description')
        self.assertEqual(
            job.declared_roles, ['cheap', 'expensive', 'extra']
        )
        # Admin choices are never overwritten: still 2 assignments,
        # still inactive, no 'other-model' assignment created.
        self.assertEqual(job.assignments.count(), 2)
        self.assertFalse(
            job.assignments.filter(is_active=True).exists()
        )
        self.assertFalse(
            AIModel.objects.filter(name='other-model').exists()
        )

    def test_unknown_provider_slug_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        spec = AIJobSpec(
            slug='bad.job',
            description='',
            roles=('default',),
            default_assignments={'default': [('nosuchvendor', 'x')]},
        )
        with self.assertRaises(ImproperlyConfigured):
            ensure_job(spec)


class AutodiscoveryTests(TestCase):

    def _module(self, name, **attrs):
        module = py_types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        return module

    def _specs(self, *modules):
        with mock.patch(
            'ai_providers.jobs._iter_ai_jobs_modules',
            return_value=iter(list(modules)),
        ):
            return autodiscover_job_specs()

    def test_collects_job_specs_list_and_bare_instances(self):
        spec_a = AIJobSpec(slug='a.job', description='', roles=('r',))
        spec_b = AIJobSpec(slug='b.job', description='', roles=('r',))
        spec_c = AIJobSpec(slug='c.job', description='', roles=('r',))
        module = self._module(
            'app.ai_jobs',
            JOB_SPECS=[spec_a, spec_b, 'not-a-spec'],
            EXTRA_SPEC=spec_c,
            unrelated=42,
        )
        self.assertEqual(self._specs(module), [spec_a, spec_b, spec_c])

    def test_same_spec_in_list_and_attribute_collected_once(self):
        spec = AIJobSpec(slug='a.job', description='', roles=('r',))
        module = self._module(
            'app.ai_jobs', JOB_SPECS=[spec], THE_SPEC=spec
        )
        self.assertEqual(self._specs(module), [spec])

    def test_duplicate_slug_first_module_wins(self):
        spec_a = AIJobSpec(slug='a.job', description='1', roles=('r',))
        spec_b = AIJobSpec(slug='a.job', description='2', roles=('r',))
        mod1 = self._module('app1.ai_jobs', A=spec_a)
        mod2 = self._module('app2.ai_jobs', B=spec_b)
        self.assertEqual(self._specs(mod1, mod2), [spec_a])


class GetJobClientTests(JobClientTestCase):

    def test_spec_argument_ensures_job(self):
        AIJobModel.objects.all().delete()
        AIJob.objects.all().delete()  # remove setUp job
        client = get_job_client(SPEC)
        self.assertEqual(client.job.slug, 'test.job')
        # ensure_job seeded the default cheap assignment.
        result = client.generate(prompt(), 'cheap')
        self.assertEqual(
            result.requested_model.name, 'gemini-2.5-flash-lite'
        )

    def test_slug_argument_uses_existing_row_no_seeding(self):
        client = get_job_client('test.job')
        self.assertEqual(client.job.pk, self.job.pk)
        result = client.generate(prompt(), 'cheap')
        self.assertEqual(result.served_model, self.model)

    def test_slug_falls_back_to_autodiscovered_spec(self):
        AIJobModel.objects.all().delete()
        AIJob.objects.all().delete()
        with mock.patch(
            'ai_providers.client.autodiscover_job_specs',
            return_value=[SPEC],
        ):
            client = get_job_client('test.job')
        self.assertEqual(client.job.slug, 'test.job')
        self.assertTrue(
            AIJobModel.objects.filter(job__slug='test.job').exists()
        )

    def test_unknown_slug_raises_not_configured(self):
        AIJob.objects.all().delete()
        with mock.patch(
            'ai_providers.client.autodiscover_job_specs',
            return_value=[],
        ):
            with self.assertRaises(errors.AIJobNotConfiguredError):
                get_job_client('ghost.job')

    def test_accepts_aijob_instance(self):
        client = get_job_client(self.job)
        self.assertEqual(client.job.pk, self.job.pk)


class PromptStorageTests(JobClientTestCase):

    def test_same_input_across_roles_and_retries_stored_once(self):
        model2 = make_model(self.provider, name='m2')
        assign(self.job, model2, 'expensive')
        FakeGemini.script = {
            'm1': [errors.AIServerError('x'),
                   AIResponse(text='ok', served_model='m1')],
            'm2': [errors.AIServerError('x'),
                   AIResponse(text='ok', served_model='m2')],
        }
        client = self.job_client()
        client.generate(prompt(), 'cheap')
        client.generate(prompt(), 'expensive')
        self.assertEqual(AIInput.objects.count(), 1)
        self.assertEqual(AIPromptTemplate.objects.count(), 1)
        self.assertEqual(AIRequest.objects.count(), 4)
        ai_input = AIInput.objects.get()
        self.assertTrue(
            all(r.input_id == ai_input.id
                for r in AIRequest.objects.all())
        )

    def test_edited_template_creates_new_version_row(self):
        client = self.job_client()
        client.generate(prompt(template_text='v1'), 'cheap')
        client.generate(prompt(template_text='v2'), 'cheap')
        self.assertEqual(AIPromptTemplate.objects.count(), 2)
        self.assertEqual(
            set(AIPromptTemplate.objects.values_list(
                'key', flat=True
            )),
            {'test.template'},
        )
        self.assertEqual(AIInput.objects.count(), 1)

    def test_store_inputs_false_keeps_hash_and_length_only(self):
        self.job.store_inputs = False
        self.job.save()
        result = self.job_client().generate(
            prompt(input_text='secret'), 'cheap'
        )
        request = result.ai_request
        self.assertIsNone(request.input_id)
        self.assertEqual(AIInput.objects.count(), 0)
        # Hash + length still recorded for integrity.
        self.assertGreater(request.prompt_chars, 0)
        self.assertEqual(len(request.prompt_sha256), 64)
        self.assertIsNone(request.rendered_prompt())

    def test_plain_str_prompt_uses_raw_layout_no_template(self):
        result = self.job_client().generate('just say hi', 'cheap')
        request = result.ai_request
        self.assertEqual(request.prompt_layout, 'raw')
        self.assertIsNone(request.prompt_template_id)
        self.assertEqual(request.input.text, 'just say hi')
        self.assertEqual(AIPromptTemplate.objects.count(), 0)
        rendered = request.rendered_prompt()
        self.assertEqual(rendered.user, 'just say hi')
        self.assertIsNone(rendered.system)

    def test_rendered_prompt_round_trips_every_layout(self):
        for layout in ('inline_v1', 'system_v1', 'raw'):
            with self.subTest(layout=layout):
                template_text = (
                    '' if layout == 'raw' else 'instructions'
                )
                spec = PromptSpec(
                    template_key=f'key.{layout}',
                    template_text=template_text,
                    input_text='the input',
                    layout=layout,
                )
                result = self.job_client().generate(spec, 'cheap')
                rebuilt = result.ai_request.rendered_prompt()
                expected = render_prompt(
                    template_text, 'the input', layout
                )
                self.assertIsNotNone(rebuilt)
                self.assertEqual(rebuilt.user, expected.user)
                self.assertEqual(rebuilt.system, expected.system)

    def test_rendered_prompt_none_on_hash_mismatch(self):
        result = self.job_client().generate(prompt(), 'cheap')
        request = result.ai_request
        request.prompt_sha256 = '0' * 64
        request.save()
        with self.assertLogs('ai_providers', level='WARNING'):
            self.assertIsNone(request.rendered_prompt())

    def test_rendered_prompt_none_without_template_for_layout(self):
        request = make_request(
            self.job, self.model, prompt_layout='inline_v1',
        )
        request.input = AIInput.objects.create(
            sha256='b' * 64, text='x', chars=1
        )
        request.save()
        # No template + non-raw layout: cannot reconstruct.
        self.assertIsNone(request.rendered_prompt())

    def test_prompt_sha256_matches_helper(self):
        result = self.job_client().generate(prompt(), 'cheap')
        request = result.ai_request
        expected = render_prompt(
            'instructions', 'some input', 'inline_v1'
        )
        self.assertEqual(
            request.prompt_sha256,
            rendered_prompt_sha256(expected.system, expected.user),
        )


class AdminRenderedPromptTests(JobClientTestCase):

    def test_admin_detail_shows_rendered_prompt_and_links(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        result = self.job_client().generate(prompt(), 'cheap')
        user = get_user_model().objects.create_superuser(
            username='admin', email='a@x.com', password='x'
        )
        self.client.force_login(user)
        url = reverse(
            'admin:ai_providers_airequest_change',
            args=[result.ai_request.pk],
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('instructions', content)
        self.assertIn('some input', content)
        self.assertIn('Rendered prompt', content)
        self.assertIn(
            reverse(
                'admin:ai_providers_aiprompttemplate_change',
                args=[result.ai_request.prompt_template_id],
            ),
            content,
        )
        self.assertIn(
            reverse(
                'admin:ai_providers_aiinput_change',
                args=[result.ai_request.input_id],
            ),
            content,
        )


class MiscTests(TestCase):
    """Small checks not needing the JobClient fixture."""

    def test_aijob_spec_is_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            SPEC.slug = 'x'

    def test_rendered_prompt_sha256_is_stable(self):
        a = rendered_prompt_sha256('sys', 'usr')
        self.assertEqual(a, rendered_prompt_sha256('sys', 'usr'))
        self.assertEqual(len(a), 64)
        self.assertNotEqual(a, rendered_prompt_sha256(None, 'usr'))
