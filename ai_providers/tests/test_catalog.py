"""Tests for PR-5: adapter list_models(), catalog sync_provider_
models(), the sync_ai_models command and the AIProvider admin
"Sync model catalog" action.

All SDK clients are mocked — no network, no API keys.
"""

from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest import mock

import httpx
import httpx2
import openai
from django.contrib import messages
from django.contrib.admin.sites import AdminSite
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from google.genai import errors as genai_errors

from ai_providers import errors
from ai_providers.admin import AIProviderAdmin
from ai_providers.catalog import sync_provider_models
from ai_providers.models import AIModel, AIProvider
from ai_providers.providers import PROVIDER_CLASSES
from ai_providers.providers.base import BaseAIProvider
from ai_providers.providers.gemini import GeminiProvider
from ai_providers.providers.openai_compat import (
    OpenAICompatibleProvider,
)
from ai_providers.types import ModelInfo

API_KEY = 'TESTKEY-do-not-leak-123'

GEMINI_CLIENT = 'ai_providers.providers.gemini.genai.Client'
OPENAI_CLIENT = 'ai_providers.providers.openai_compat.OpenAI'


def gemini_model(name, display_name='', input_token_limit=None,
                 supported_actions=('generateContent',)):
    """A google-genai ``Model`` stand-in."""
    return SimpleNamespace(
        name=name,
        display_name=display_name,
        input_token_limit=input_token_limit,
        supported_actions=list(supported_actions)
        if supported_actions is not None else None,
    )


def openai_model(model_id, **extra):
    """An openai SDK ``Model`` stand-in; ``extra`` plays the role of
    pydantic model_extra fields (OpenRouter pricing etc.)."""
    return SimpleNamespace(id=model_id, **extra)


class GeminiListModelsTest(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch(GEMINI_CLIENT)
        self.client_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.client = self.client_cls.return_value
        self.provider = GeminiProvider(api_key=API_KEY)

    def test_filters_and_normalizes(self):
        self.client.models.list.return_value = [
            gemini_model(
                'models/gemini-2.5-pro',
                display_name='Gemini 2.5 Pro',
                input_token_limit=1048576,
                supported_actions=[
                    'generateContent', 'countTokens',
                ],
            ),
            gemini_model(
                'models/text-embedding-004',
                supported_actions=['embedContent'],
            ),
            gemini_model(
                'models/no-actions',
                supported_actions=None,
            ),
        ]
        infos = self.provider.list_models()
        self.assertEqual(len(infos), 1)
        info = infos[0]
        self.assertEqual(info.name, 'gemini-2.5-pro')
        self.assertEqual(info.display_name, 'Gemini 2.5 Pro')
        self.assertEqual(info.context_length, 1048576)
        self.assertIsNone(info.input_price_per_mtok)
        self.assertIsNone(info.output_price_per_mtok)

    def test_name_without_prefix_is_kept(self):
        self.client.models.list.return_value = [
            gemini_model('gemini-2.5-flash-lite'),
        ]
        infos = self.provider.list_models()
        self.assertEqual([i.name for i in infos],
                         ['gemini-2.5-flash-lite'])

    def test_api_error_mapped(self):
        self.client.models.list.side_effect = genai_errors.APIError(
            code=401,
            response_json={'error': {'message': 'bad key'}},
        )
        with self.assertRaises(errors.AIAuthError):
            self.provider.list_models()

    def test_network_error_mapped(self):
        self.client.models.list.side_effect = httpx.TimeoutException(
            'timed out'
        )
        with self.assertRaises(errors.AITimeoutError):
            self.provider.list_models()


class OpenAIListModelsTest(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch(OPENAI_CLIENT)
        self.client_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.client = self.client_cls.return_value
        self.provider = OpenAICompatibleProvider(
            api_key=API_KEY,
            base_url='https://openrouter.example/api/v1',
        )

    def test_openrouter_fields(self):
        self.client.models.list.return_value = [
            openai_model(
                'google/gemini-2.5-flash-lite',
                name='Google: Gemini 2.5 Flash Lite',
                context_length=1048576,
                pricing={
                    'prompt': '0.0000001',
                    'completion': '0.0000004',
                },
                supported_parameters=[
                    'response_format', 'temperature',
                ],
            ),
            openai_model(
                'acme/weird',
                context_length='not-an-int',
                pricing={'prompt': '-1', 'completion': 'n/a'},
            ),
        ]
        infos = self.provider.list_models()
        self.assertEqual(len(infos), 2)
        info = infos[0]
        self.assertEqual(info.name, 'google/gemini-2.5-flash-lite')
        self.assertEqual(
            info.display_name, 'Google: Gemini 2.5 Flash Lite'
        )
        self.assertEqual(info.context_length, 1048576)
        # Per-token USD strings -> per-1M-token Decimals.
        self.assertEqual(
            info.input_price_per_mtok, Decimal('0.1000')
        )
        self.assertEqual(
            info.output_price_per_mtok, Decimal('0.4000')
        )
        self.assertTrue(info.supports_json_mode)
        weird = infos[1]
        self.assertIsNone(weird.context_length)
        self.assertIsNone(weird.input_price_per_mtok)
        self.assertIsNone(weird.output_price_per_mtok)
        self.assertFalse(weird.supports_json_mode)

    def test_plain_openai_bare_ids(self):
        self.client.models.list.return_value = [
            openai_model('gpt-4o', created=1, object='model',
                         owned_by='openai'),
        ]
        infos = self.provider.list_models()
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0].name, 'gpt-4o')
        self.assertEqual(infos[0].display_name, '')
        self.assertIsNone(infos[0].context_length)

    def test_entry_without_id_skipped(self):
        self.client.models.list.return_value = [
            {'pricing': {'prompt': '1'}},  # dict without id
            openai_model('ok/model'),
        ]
        infos = self.provider.list_models()
        self.assertEqual([i.name for i in infos], ['ok/model'])

    def test_api_error_mapped(self):
        request = httpx2.Request(
            'GET', 'https://openrouter.example/api/v1/models'
        )
        self.client.models.list.side_effect = openai.RateLimitError(
            'slow',
            response=httpx2.Response(
                429, headers={'retry-after': '3'}, request=request
            ),
            body=None,
        )
        with self.assertRaises(errors.AIRateLimitError) as ctx:
            self.provider.list_models()
        self.assertEqual(ctx.exception.retry_after, 3.0)


class FakeCatalogAdapter(BaseAIProvider):
    """Scripted adapter for sync tests; class attrs hold the state."""

    provider_type = 'fake'
    catalog = []
    error = None

    def generate(self, model, prompt, options):
        raise NotImplementedError

    def list_models(self):
        error = type(self).error
        if error is not None:
            raise error
        return list(type(self).catalog)


def make_provider(slug='gemini', provider_type='gemini',
                  api_key_setting='GEMINI_API_KEY', **kwargs):
    defaults = {
        'slug': slug,
        'display_name': slug,
        'provider_type': provider_type,
        'api_key_setting': api_key_setting,
    }
    defaults.update(kwargs)
    return AIProvider.objects.create(**defaults)


@override_settings(GEMINI_API_KEY=API_KEY, OPENROUTER_API_KEY=API_KEY)
class CatalogSyncTestCase(TestCase):
    """Base: 'gemini' provider_type mapped to FakeCatalogAdapter."""

    def setUp(self):
        super().setUp()
        FakeCatalogAdapter.catalog = []
        FakeCatalogAdapter.error = None
        patcher = mock.patch.dict(
            PROVIDER_CLASSES, {'gemini': FakeCatalogAdapter},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.provider = make_provider()


class SyncProviderModelsTest(CatalogSyncTestCase):
    def test_creates_new_models_disabled_by_default(self):
        FakeCatalogAdapter.catalog = [
            ModelInfo(
                name='m1',
                display_name='Model One',
                context_length=1000,
                input_price_per_mtok=Decimal('0.1'),
                output_price_per_mtok=Decimal('0.4'),
                supports_json_mode=True,
            ),
            ModelInfo(name='m2'),
        ]
        counts = sync_provider_models(self.provider)
        self.assertEqual(
            counts, {'created': 2, 'updated': 0, 'skipped': 0}
        )
        m1 = AIModel.objects.get(provider=self.provider, name='m1')
        self.assertTrue(m1.auto_registered)
        self.assertFalse(m1.is_enabled)
        self.assertTrue(m1.supports_json_mode)
        self.assertEqual(m1.display_name, 'Model One')
        self.assertEqual(m1.context_length, 1000)
        self.assertEqual(m1.input_price_per_mtok, Decimal('0.1'))
        self.assertEqual(m1.output_price_per_mtok, Decimal('0.4'))
        self.assertTrue(
            AIModel.objects.filter(
                provider=self.provider, name='m2'
            ).exists()
        )

    def test_enable_new(self):
        FakeCatalogAdapter.catalog = [ModelInfo(name='m1')]
        sync_provider_models(self.provider, enable_new=True)
        self.assertTrue(
            AIModel.objects.get(
                provider=self.provider, name='m1'
            ).is_enabled
        )

    def test_idempotent_second_run_skips(self):
        FakeCatalogAdapter.catalog = [
            ModelInfo(name='m1', display_name='One'),
            ModelInfo(name='m2'),
        ]
        sync_provider_models(self.provider)
        counts = sync_provider_models(self.provider)
        self.assertEqual(
            counts, {'created': 0, 'updated': 0, 'skipped': 2}
        )
        self.assertEqual(AIModel.objects.count(), 2)

    def test_updates_existing_row_fields(self):
        existing = AIModel.objects.create(
            provider=self.provider,
            name='m1',
            is_enabled=False,
            auto_registered=False,
            display_name='Old name',
            input_price_per_mtok=Decimal('9'),
            output_price_per_mtok=Decimal('9'),
        )
        FakeCatalogAdapter.catalog = [
            ModelInfo(
                name='m1',
                display_name='New name',
                context_length=500,
                input_price_per_mtok=Decimal('0.25'),
                output_price_per_mtok=Decimal('9'),
            ),
        ]
        counts = sync_provider_models(self.provider)
        self.assertEqual(
            counts, {'created': 0, 'updated': 1, 'skipped': 0}
        )
        existing.refresh_from_db()
        self.assertEqual(existing.display_name, 'New name')
        self.assertEqual(existing.context_length, 500)
        self.assertEqual(
            existing.input_price_per_mtok, Decimal('0.25')
        )
        # Same price -> not overwritten, and flags are untouched.
        self.assertEqual(
            existing.output_price_per_mtok, Decimal('9')
        )
        self.assertFalse(existing.is_enabled)
        self.assertFalse(existing.auto_registered)

    def test_never_disables_or_deletes(self):
        AIModel.objects.create(
            provider=self.provider, name='keep-me',
            is_enabled=True,
        )
        AIModel.objects.create(
            provider=self.provider, name='m1', is_enabled=True,
        )
        FakeCatalogAdapter.catalog = [ModelInfo(name='m1')]
        counts = sync_provider_models(self.provider)
        self.assertEqual(
            counts, {'created': 0, 'updated': 0, 'skipped': 1}
        )
        self.assertEqual(AIModel.objects.count(), 2)
        self.assertTrue(
            AIModel.objects.get(name='keep-me').is_enabled
        )
        self.assertTrue(
            AIModel.objects.get(name='m1').is_enabled
        )

    def test_dry_run_writes_nothing(self):
        AIModel.objects.create(
            provider=self.provider, name='m1',
            display_name='old',
        )
        FakeCatalogAdapter.catalog = [
            ModelInfo(name='m1', display_name='new', context_length=7),
            ModelInfo(name='m2'),
        ]
        counts = sync_provider_models(self.provider, dry_run=True)
        self.assertEqual(
            counts, {'created': 1, 'updated': 1, 'skipped': 0}
        )
        self.assertFalse(
            AIModel.objects.filter(name='m2').exists()
        )
        row = AIModel.objects.get(name='m1')
        self.assertEqual(row.display_name, 'old')
        self.assertIsNone(row.context_length)

    def test_empty_catalog(self):
        counts = sync_provider_models(self.provider)
        self.assertEqual(
            counts, {'created': 0, 'updated': 0, 'skipped': 0}
        )

    def test_blank_names_ignored(self):
        FakeCatalogAdapter.catalog = [
            ModelInfo(name=''), ModelInfo(name='  '),
        ]
        counts = sync_provider_models(self.provider)
        self.assertEqual(
            counts, {'created': 0, 'updated': 0, 'skipped': 0}
        )
        self.assertEqual(AIModel.objects.count(), 0)

    def test_adapter_error_propagates(self):
        FakeCatalogAdapter.error = errors.AIAuthError('denied')
        with self.assertRaises(errors.AIAuthError):
            sync_provider_models(self.provider)

    def test_missing_api_key_propagates(self):
        with override_settings(GEMINI_API_KEY=''):
            with self.assertRaises(
                errors.AIProviderNotConfiguredError
            ):
                sync_provider_models(self.provider)

    def test_unknown_provider_type_propagates(self):
        provider = make_provider(slug='weird', provider_type='wat')
        with self.assertRaises(errors.AIProviderNotConfiguredError):
            sync_provider_models(provider)


class SyncAiModelsCommandTest(CatalogSyncTestCase):
    def test_unknown_slug(self):
        with self.assertRaises(CommandError) as ctx:
            call_command('sync_ai_models', 'nope')
        self.assertIn('nope', str(ctx.exception))

    def test_success_prints_summary(self):
        FakeCatalogAdapter.catalog = [
            ModelInfo(name='m1'), ModelInfo(name='m2'),
        ]
        out = StringIO()
        call_command('sync_ai_models', 'gemini', stdout=out)
        self.assertIn('gemini: 2 created, 0 updated, 0 skipped',
                      out.getvalue())
        self.assertEqual(AIModel.objects.count(), 2)

    def test_dry_run_prints_prefix_and_writes_nothing(self):
        FakeCatalogAdapter.catalog = [ModelInfo(name='m1')]
        out = StringIO()
        call_command(
            'sync_ai_models', 'gemini', '--dry-run', stdout=out,
        )
        self.assertIn('[dry-run]', out.getvalue())
        self.assertEqual(AIModel.objects.count(), 0)

    def test_adapter_error_becomes_command_error(self):
        FakeCatalogAdapter.error = errors.AIAuthError('bad key')
        with self.assertRaises(CommandError) as ctx:
            call_command('sync_ai_models', 'gemini')
        self.assertIn('gemini', str(ctx.exception))
        self.assertIn('bad key', str(ctx.exception))


class AdminActionTest(CatalogSyncTestCase):
    def setUp(self):
        super().setUp()
        self.model_admin = AIProviderAdmin(AIProvider, AdminSite())

    def run_action(self, queryset):
        with mock.patch.object(
            self.model_admin, 'message_user'
        ) as message_user:
            self.model_admin.sync_model_catalog(
                request=mock.Mock(), queryset=queryset,
            )
        return message_user

    def test_action_registered(self):
        self.assertIn('sync_model_catalog', self.model_admin.actions)

    def test_success_message_with_counts(self):
        FakeCatalogAdapter.catalog = [
            ModelInfo(name='m1'), ModelInfo(name='m2'),
        ]
        message_user = self.run_action(
            AIProvider.objects.filter(pk=self.provider.pk)
        )
        self.assertEqual(message_user.call_count, 1)
        args, kwargs = message_user.call_args
        self.assertIn('2 created, 0 updated, 0 skipped', args[1])
        self.assertEqual(kwargs['level'], messages.SUCCESS)
        self.assertEqual(AIModel.objects.count(), 2)

    def test_failure_is_per_provider(self):
        other = make_provider(slug='gemini-2')

        def fake_sync(provider, **kwargs):
            if provider.slug == 'gemini-2':
                raise errors.AIAuthError('denied')
            return {'created': 1, 'updated': 0, 'skipped': 0}

        with mock.patch(
            'ai_providers.admin.sync_provider_models',
            side_effect=fake_sync,
        ):
            message_user = self.run_action(AIProvider.objects.all())
        self.assertEqual(message_user.call_count, 2)
        levels = {
            call.kwargs['level'] for call in message_user.call_args_list
        }
        self.assertEqual(levels, {messages.SUCCESS, messages.ERROR})
        error_call = [
            c for c in message_user.call_args_list
            if c.kwargs['level'] == messages.ERROR
        ][0]
        self.assertIn('gemini-2', error_call.args[1])
        self.assertIn('denied', error_call.args[1])
