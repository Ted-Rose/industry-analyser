"""Tests for PR-2: types, prompts, errors and provider adapters.

Every SDK client is mocked — no network, no API keys, no DB access
(SimpleTestCase only).
"""

import json
from types import SimpleNamespace
from unittest import mock

# Two HTTP libs: google-genai speaks httpx, the openai 3.x SDK uses
# httpx2. Neither is pinned in requirements.txt — both arrive
# transitively via the SDKs they drive.
import httpx
import httpx2
import openai
from django.test import SimpleTestCase
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from ai_providers import errors
from ai_providers.prompts import PROMPT_LAYOUTS, render_prompt
from ai_providers.providers import PROVIDER_CLASSES
from ai_providers.providers.gemini import GeminiProvider
from ai_providers.providers.openai_compat import (
    OpenAICompatibleProvider,
)
from ai_providers.types import (
    AIResponse,
    GenerationOptions,
    ImagePart,
    PromptSpec,
    RenderedPrompt,
)

API_KEY = 'TESTKEY-do-not-leak-123'

GEMINI_CLIENT = 'ai_providers.providers.gemini.genai.Client'
OPENAI_CLIENT = 'ai_providers.providers.openai_compat.OpenAI'


def gemini_response(text='generated text', model_version='gemini-x',
                    block_reason=None, finish_reason='STOP',
                    candidates=None, usage=True):
    if candidates is None:
        candidates = [SimpleNamespace(finish_reason=finish_reason)]
    feedback = (
        SimpleNamespace(block_reason=block_reason)
        if block_reason else None
    )
    usage_meta = (
        SimpleNamespace(prompt_token_count=11, candidates_token_count=7)
        if usage else None
    )
    return SimpleNamespace(
        text=text,
        model_version=model_version,
        prompt_feedback=feedback,
        candidates=candidates,
        usage_metadata=usage_meta,
    )


def openai_response(content='generated text', model='served-model',
                    finish_reason='stop', usage=True, error=None):
    if error is not None:
        return SimpleNamespace(error=error, choices=None, model=model,
                               usage=None)
    usage_obj = (
        SimpleNamespace(prompt_tokens=13, completion_tokens=9)
        if usage else None
    )
    choice = SimpleNamespace(
        finish_reason=finish_reason,
        message=SimpleNamespace(content=content),
    )
    return SimpleNamespace(
        choices=[choice],
        model=model,
        usage=usage_obj,
        error=None,
    )


def openai_request():
    return httpx2.Request(
        'POST', 'https://provider.example/v1/chat/completions'
    )


def openai_http_response(status, headers=None):
    return httpx2.Response(status, headers=headers or {},
                           request=openai_request())


class TypesTest(SimpleTestCase):
    def test_generation_options_defaults(self):
        options = GenerationOptions()
        self.assertFalse(options.json_mode)
        self.assertIsNone(options.temperature)
        self.assertIsNone(options.max_output_tokens)

    def test_prompt_spec_default_layout(self):
        spec = PromptSpec(
            template_key='k', template_text='t', input_text='i',
        )
        self.assertEqual(spec.layout, 'inline_v1')

    def test_ai_response_defaults(self):
        resp = AIResponse(text='x', served_model='m')
        self.assertEqual(resp.status, 'success')
        self.assertIsNone(resp.block_reason)
        self.assertIsNone(resp.input_tokens)


class PromptLayoutsTest(SimpleTestCase):
    def test_layout_names_are_fixed(self):
        self.assertEqual(
            set(PROMPT_LAYOUTS), {'inline_v1', 'system_v1', 'raw'},
        )

    def test_inline_v1_golden(self):
        rendered = render_prompt('INSTR', 'CONTENT', 'inline_v1')
        self.assertEqual(rendered.user, 'INSTR\n\n---\n\nCONTENT')
        self.assertIsNone(rendered.system)

    def test_inline_v1_matches_blogs_concatenation_byte_identical(self):
        instructions = 'line1\nline2\n'
        content = 'article <b>text</b> äö\n'
        rendered = render_prompt(instructions, content, 'inline_v1')
        self.assertEqual(
            rendered.user,
            instructions + "\n\n---\n\n" + content,
        )

    def test_system_v1_golden(self):
        rendered = render_prompt('INSTR', 'CONTENT', 'system_v1')
        self.assertEqual(rendered.system, 'INSTR')
        self.assertEqual(rendered.user, '<input>\nCONTENT\n</input>')

    def test_raw_golden(self):
        rendered = render_prompt('IGNORED', 'CONTENT', 'raw')
        self.assertEqual(rendered.user, 'CONTENT')
        self.assertIsNone(rendered.system)

    def test_unknown_layout_raises_clear_error(self):
        with self.assertRaises(ValueError) as ctx:
            render_prompt('t', 'i', 'nope_v9')
        self.assertIn('Unknown prompt layout', str(ctx.exception))
        self.assertIn('inline_v1', str(ctx.exception))


class ErrorsTest(SimpleTestCase):
    def test_every_exception_accepts_http_status(self):
        subclasses = [
            errors.AIRetryableError,
            errors.AIRateLimitError,
            errors.AIServerError,
            errors.AITimeoutError,
            errors.AIEmptyResponseError,
            errors.AIModelError,
            errors.AIBadRequestError,
            errors.AIModelNotFoundError,
            errors.AIProviderError,
            errors.AIAuthError,
            errors.AIQuotaError,
            errors.AIProviderNotConfiguredError,
            errors.AIJobError,
            errors.AIJobDisabledError,
            errors.AIJobNotConfiguredError,
            errors.AIRequestCapReached,
            errors.AIAllModelsFailedError,
        ]
        for cls in subclasses:
            with self.subTest(cls=cls.__name__):
                exc = cls('msg', http_status=500)
                self.assertEqual(exc.http_status, 500)
                self.assertIsInstance(exc, errors.AIError)

    def test_hierarchy(self):
        self.assertTrue(
            issubclass(errors.AIRateLimitError, errors.AIRetryableError))
        self.assertTrue(
            issubclass(errors.AIBadRequestError, errors.AIModelError))
        self.assertTrue(
            issubclass(errors.AIAuthError, errors.AIProviderError))
        self.assertTrue(
            issubclass(errors.AIRequestCapReached, errors.AIJobError))

    def test_retry_after_attribute(self):
        exc = errors.AIRateLimitError('slow', retry_after=2.5)
        self.assertEqual(exc.retry_after, 2.5)
        self.assertIsNone(errors.AIRateLimitError('x').retry_after)

    def test_all_models_failed_last_error(self):
        last = errors.AITimeoutError('t')
        exc = errors.AIAllModelsFailedError('all failed',
                                            last_error=last)
        self.assertIs(exc.last_error, last)


class RegistryTest(SimpleTestCase):
    def test_provider_classes(self):
        self.assertEqual(
            set(PROVIDER_CLASSES), {'gemini', 'openai_compatible'},
        )
        self.assertIs(PROVIDER_CLASSES['gemini'], GeminiProvider)
        self.assertIs(
            PROVIDER_CLASSES['openai_compatible'],
            OpenAICompatibleProvider,
        )


class GeminiProviderTest(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch(GEMINI_CLIENT)
        self.client_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.client = self.client_cls.return_value
        self.provider = GeminiProvider(
            api_key=API_KEY, base_url='https://g.example',
            extra_headers={'X-Test': '1'}, timeout=30,
        )

    def generate(self, prompt=None, options=None):
        return self.provider.generate(
            'gemini-2.5-flash-lite',
            prompt or RenderedPrompt(user='USER TEXT'),
            options or GenerationOptions(),
        )

    def test_client_configured_once(self):
        # One genai.Client per provider instance, timeout in ms.
        self.client_cls.assert_called_once_with(
            api_key=API_KEY,
            http_options=mock.ANY,
        )
        http_options = self.client_cls.call_args.kwargs['http_options']
        self.assertEqual(http_options.timeout, 30000)
        self.assertEqual(http_options.base_url, 'https://g.example')
        self.assertEqual(http_options.headers, {'X-Test': '1'})
        # SDK retries must stay off (verified default for 1.67.0).
        self.assertIsNone(http_options.retry_options)

    def test_success(self):
        self.client.models.generate_content.return_value = (
            gemini_response(text='{"a": 1}', model_version='gemini-2.5f')
        )
        resp = self.generate()
        self.assertEqual(resp.status, 'success')
        self.assertEqual(resp.text, '{"a": 1}')
        self.assertEqual(resp.served_model, 'gemini-2.5f')
        self.assertEqual(resp.input_tokens, 11)
        self.assertEqual(resp.output_tokens, 7)
        self.assertEqual(resp.finish_reason, 'STOP')
        call = self.client.models.generate_content.call_args
        self.assertEqual(call.kwargs['model'], 'gemini-2.5-flash-lite')
        self.assertEqual(call.kwargs['contents'], 'USER TEXT')
        self.assertIsNone(call.kwargs['config'])

    def test_served_model_falls_back_to_requested(self):
        self.client.models.generate_content.return_value = (
            gemini_response(model_version=None)
        )
        resp = self.generate()
        self.assertEqual(resp.served_model, 'gemini-2.5-flash-lite')

    def test_build_contents_text_only_returns_user_str(self):
        contents = GeminiProvider._build_contents(
            RenderedPrompt(user='U')
        )
        self.assertEqual(contents, 'U')

    def test_build_contents_with_image_is_parts_then_text(self):
        prompt = RenderedPrompt(
            user='U',
            images=(ImagePart(data=b'IMG', mime_type='image/png'),),
        )
        contents = GeminiProvider._build_contents(prompt)
        self.assertIsInstance(contents, list)
        self.assertIsInstance(contents[0], genai_types.Part)
        self.assertEqual(contents[-1], 'U')

    def test_system_json_mode_and_sampling_passed_through(self):
        self.client.models.generate_content.return_value = (
            gemini_response()
        )
        prompt = RenderedPrompt(user='U', system='SYS')
        options = GenerationOptions(
            json_mode=True, temperature=0.2, max_output_tokens=128,
        )
        self.generate(prompt, options)
        config = self.client.models.generate_content.call_args.kwargs[
            'config']
        self.assertEqual(config.system_instruction, 'SYS')
        self.assertEqual(config.response_mime_type, 'application/json')
        self.assertEqual(config.temperature, 0.2)
        self.assertEqual(config.max_output_tokens, 128)

    def test_prompt_level_block(self):
        self.client.models.generate_content.return_value = (
            gemini_response(
                text=None,
                block_reason=genai_types.BlockedReason.SAFETY,
                candidates=[],
            )
        )
        resp = self.generate()
        self.assertEqual(resp.status, 'blocked')
        self.assertEqual(resp.block_reason, 'SAFETY')
        self.assertIsNone(resp.text)

    def test_candidate_level_block(self):
        for reason in ('SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST',
                       'SPII'):
            with self.subTest(reason=reason):
                self.client.models.generate_content.return_value = (
                    gemini_response(
                        text=None,
                        finish_reason=genai_types.FinishReason[reason],
                    )
                )
                resp = self.generate()
                self.assertEqual(resp.status, 'blocked')
                self.assertEqual(resp.block_reason, reason)
                self.assertEqual(resp.finish_reason, reason)

    def test_non_blocked_finish_reason_is_success(self):
        self.client.models.generate_content.return_value = (
            gemini_response(
                finish_reason=genai_types.FinishReason.MAX_TOKENS,
            )
        )
        resp = self.generate()
        self.assertEqual(resp.status, 'success')
        self.assertEqual(resp.finish_reason, 'MAX_TOKENS')

    def test_empty_text_raises_empty_response(self):
        self.client.models.generate_content.return_value = (
            gemini_response(text=None)
        )
        with self.assertRaises(errors.AIEmptyResponseError):
            self.generate()

    def test_api_error_status_mapping(self):
        cases = [
            (400, errors.AIBadRequestError),
            (401, errors.AIAuthError),
            (402, errors.AIQuotaError),
            (403, errors.AIAuthError),
            (404, errors.AIModelNotFoundError),
            (408, errors.AITimeoutError),
            (422, errors.AIBadRequestError),
            (429, errors.AIRateLimitError),
            (500, errors.AIServerError),
            (503, errors.AIServerError),
        ]
        for code, cls in cases:
            with self.subTest(code=code):
                self.client.models.generate_content.side_effect = (
                    genai_errors.APIError(
                        code=code,
                        response_json={
                            'error': {'message': f'fail {code}'},
                        },
                    )
                )
                with self.assertRaises(cls) as ctx:
                    self.generate()
                self.assertEqual(ctx.exception.http_status, code)
                # A single attempt: no SDK-level retry in generate().
                self.assertEqual(
                    self.client.models.generate_content.call_count, 1)
                self.client.models.generate_content.reset_mock(
                    side_effect=True)

    def test_unknown_error_code_maps_to_server_error(self):
        # Missing or unexpected codes fall through to AIServerError.
        for code in (None, 302):
            with self.subTest(code=code):
                self.client.models.generate_content.side_effect = (
                    genai_errors.APIError(
                        code=code,
                        response_json={
                            'error': {'message': 'weird'},
                        },
                    )
                )
                with self.assertRaises(errors.AIServerError):
                    self.generate()
                self.client.models.generate_content.reset_mock(
                    side_effect=True)

    def test_malformed_body_maps_to_server_error(self):
        # A 200 body that is not JSON or fails response validation
        # escapes google-genai 1.67.0 as a raw ValueError-family
        # error — it must still map into the taxonomy.
        sdk_errors = [
            json.JSONDecodeError('Expecting value', 'doc', 0),
            genai_errors.UnknownApiResponseError('not json'),
        ]
        for sdk_error in sdk_errors:
            with self.subTest(sdk=type(sdk_error).__name__):
                self.client.models.generate_content.side_effect = (
                    sdk_error)
                with self.assertRaises(errors.AIServerError):
                    self.generate()
                self.assertEqual(
                    self.client.models.generate_content.call_count, 1)
                self.client.models.generate_content.reset_mock(
                    side_effect=True)

    def test_rate_limit_retry_after(self):
        response = SimpleNamespace(headers={'retry-after': '4'})
        self.client.models.generate_content.side_effect = (
            genai_errors.APIError(
                code=429,
                response_json={'error': {'message': 'quota'}},
                response=response,
            )
        )
        with self.assertRaises(errors.AIRateLimitError) as ctx:
            self.generate()
        self.assertEqual(ctx.exception.retry_after, 4.0)

    def test_network_error_maps_to_timeout(self):
        self.client.models.generate_content.side_effect = (
            httpx.TimeoutException('timed out')
        )
        with self.assertRaises(errors.AITimeoutError):
            self.generate()

    def test_error_message_scrubs_api_key(self):
        self.client.models.generate_content.side_effect = (
            genai_errors.APIError(
                code=400,
                response_json={
                    'error': {'message': f'key {API_KEY} rejected'},
                },
            )
        )
        with self.assertRaises(errors.AIBadRequestError) as ctx:
            self.generate()
        self.assertNotIn(API_KEY, str(ctx.exception))
        self.assertIn('<redacted>', str(ctx.exception))


class OpenAICompatibleProviderTest(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch(OPENAI_CLIENT)
        self.client_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.client = self.client_cls.return_value
        self.provider = OpenAICompatibleProvider(
            api_key=API_KEY,
            base_url='https://openrouter.example/api/v1',
            extra_headers={'X-Title': 'industry-analyser'},
            timeout=45,
        )

    def generate(self, prompt=None, options=None):
        return self.provider.generate(
            'acme/model-1',
            prompt or RenderedPrompt(user='USER TEXT'),
            options or GenerationOptions(),
        )

    def create_call(self):
        return self.client.chat.completions.create

    def test_client_configured_once(self):
        self.client_cls.assert_called_once_with(
            api_key=API_KEY,
            base_url='https://openrouter.example/api/v1',
            default_headers={'X-Title': 'industry-analyser'},
            timeout=45,
            max_retries=0,
        )

    def test_success(self):
        self.create_call().return_value = openai_response(
            content='{"a": 1}', model='acme/model-1-served',
        )
        resp = self.generate()
        self.assertEqual(resp.status, 'success')
        self.assertEqual(resp.text, '{"a": 1}')
        self.assertEqual(resp.served_model, 'acme/model-1-served')
        self.assertEqual(resp.input_tokens, 13)
        self.assertEqual(resp.output_tokens, 9)
        call = self.create_call().call_args
        self.assertEqual(call.kwargs['model'], 'acme/model-1')
        self.assertEqual(
            call.kwargs['messages'],
            [{'role': 'user', 'content': 'USER TEXT'}],
        )
        self.assertNotIn('response_format', call.kwargs)

    def test_system_json_mode_and_sampling_passed_through(self):
        self.create_call().return_value = openai_response()
        prompt = RenderedPrompt(user='U', system='SYS')
        options = GenerationOptions(
            json_mode=True, temperature=0.3, max_output_tokens=64,
        )
        self.generate(prompt, options)
        call = self.create_call().call_args
        self.assertEqual(
            call.kwargs['messages'],
            [
                {'role': 'system', 'content': 'SYS'},
                {'role': 'user', 'content': 'U'},
            ],
        )
        self.assertEqual(
            call.kwargs['response_format'], {'type': 'json_object'})
        self.assertEqual(call.kwargs['temperature'], 0.3)
        self.assertEqual(call.kwargs['max_tokens'], 64)

    def test_content_filter_finish_reason_blocked(self):
        self.create_call().return_value = openai_response(
            content=None, finish_reason='content_filter',
        )
        resp = self.generate()
        self.assertEqual(resp.status, 'blocked')
        self.assertEqual(resp.block_reason, 'content_filter')
        self.assertEqual(resp.finish_reason, 'content_filter')
        self.assertIsNone(resp.text)

    def test_403_moderation_body_returns_blocked(self):
        body = {
            'error': {
                'message': 'Input flagged by moderation',
                'code': 'content_policy_violation',
            },
        }
        self.create_call().side_effect = openai.PermissionDeniedError(
            'Forbidden', response=openai_http_response(403), body=body,
        )
        resp = self.generate()
        self.assertEqual(resp.status, 'blocked')
        self.assertIsNone(resp.text)

    def test_403_non_moderation_maps_to_auth(self):
        self.create_call().side_effect = openai.PermissionDeniedError(
            'Forbidden', response=openai_http_response(403),
            body={'error': {'message': 'invalid key', 'code': 403}},
        )
        with self.assertRaises(errors.AIAuthError) as ctx:
            self.generate()
        self.assertEqual(ctx.exception.http_status, 403)

    def test_error_object_in_body_is_server_error(self):
        self.create_call().return_value = openai_response(
            error={'code': 502, 'message': 'upstream died'},
        )
        with self.assertRaises(errors.AIServerError):
            self.generate()

    def test_empty_choices_is_server_error(self):
        self.create_call().return_value = openai_response()
        self.create_call().return_value.choices = []
        with self.assertRaises(errors.AIServerError):
            self.generate()

    def test_empty_content_raises_empty_response(self):
        self.create_call().return_value = openai_response(content=None)
        with self.assertRaises(errors.AIEmptyResponseError):
            self.generate()
        self.create_call().return_value = openai_response(content='')
        with self.assertRaises(errors.AIEmptyResponseError):
            self.generate()

    def test_error_status_mapping(self):
        request = openai_request()

        def status_error(cls, status, body=None):
            return cls(
                f'fail {status}',
                response=openai_http_response(status),
                body=body,
            )

        cases = [
            (openai.RateLimitError('rl', response=openai_http_response(
                429), body=None), errors.AIRateLimitError),
            (openai.APITimeoutError(request), errors.AITimeoutError),
            (openai.APIConnectionError(
                message='down', request=request),
             errors.AITimeoutError),
            (status_error(openai.InternalServerError, 500),
             errors.AIServerError),
            (status_error(openai.AuthenticationError, 401),
             errors.AIAuthError),
            (status_error(openai.APIStatusError, 402),
             errors.AIQuotaError),
            (status_error(openai.APIStatusError, 408),
             errors.AITimeoutError),
            (status_error(openai.NotFoundError, 404),
             errors.AIModelNotFoundError),
            (status_error(openai.BadRequestError, 400),
             errors.AIBadRequestError),
            (status_error(openai.UnprocessableEntityError, 422),
             errors.AIBadRequestError),
        ]
        for sdk_error, cls in cases:
            with self.subTest(cls=cls.__name__,
                              sdk=type(sdk_error).__name__):
                self.create_call().side_effect = sdk_error
                with self.assertRaises(cls):
                    self.generate()
                self.assertEqual(self.create_call().call_count, 1)
                self.create_call().reset_mock(side_effect=True)

    def test_validation_error_maps_to_server_error(self):
        # A 200 body that fails pydantic validation raises
        # APIResponseValidationError — an openai.APIError but NOT an
        # APIStatusError (openai 3.17.0), so the status catch-all
        # alone does not cover it.
        sdk_errors = [
            openai.APIResponseValidationError(
                response=openai_http_response(200), body=None,
            ),
            openai.APIError(
                'boom', request=openai_request(), body=None,
            ),
        ]
        for sdk_error in sdk_errors:
            with self.subTest(sdk=type(sdk_error).__name__):
                self.create_call().side_effect = sdk_error
                with self.assertRaises(errors.AIServerError):
                    self.generate()
                self.assertEqual(self.create_call().call_count, 1)
                self.create_call().reset_mock(side_effect=True)

    def test_retry_after_header_parsed(self):
        response = openai_http_response(429, {'Retry-After': '2.5'})
        self.create_call().side_effect = openai.RateLimitError(
            'slow down', response=response, body=None,
        )
        with self.assertRaises(errors.AIRateLimitError) as ctx:
            self.generate()
        self.assertEqual(ctx.exception.retry_after, 2.5)

    def test_retry_after_missing_or_invalid(self):
        for headers in ({}, {'Retry-After': 'not-a-number'}):
            with self.subTest(headers=headers):
                response = openai_http_response(429, headers)
                self.create_call().side_effect = openai.RateLimitError(
                    'rl', response=response, body=None,
                )
                with self.assertRaises(errors.AIRateLimitError) as ctx:
                    self.generate()
                self.assertIsNone(ctx.exception.retry_after)

    def test_error_message_scrubs_api_key(self):
        self.create_call().side_effect = openai.BadRequestError(
            f'key {API_KEY} is malformed',
            response=openai_http_response(400),
            body=None,
        )
        with self.assertRaises(errors.AIBadRequestError) as ctx:
            self.generate()
        self.assertNotIn(API_KEY, str(ctx.exception))
        self.assertIn('<redacted>', str(ctx.exception))

    def test_blocked_response_scrubs_api_key(self):
        body = {'error': {'code': 'moderation', 'message': 'flagged'}}
        self.create_call().side_effect = openai.PermissionDeniedError(
            f'moderation for key {API_KEY}',
            response=openai_http_response(403),
            body=body,
        )
        resp = self.generate()
        self.assertEqual(resp.status, 'blocked')
        self.assertNotIn(API_KEY, resp.block_reason)
