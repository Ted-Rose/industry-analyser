"""Google Gemini adapter using the google-genai SDK (plan 5.3)."""

import json

import httpx
import pydantic
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from ai_providers.errors import (
    AIAuthError,
    AIBadRequestError,
    AIEmptyResponseError,
    AIModelNotFoundError,
    AIQuotaError,
    AIRateLimitError,
    AIServerError,
    AITimeoutError,
)
from ai_providers.providers.base import BaseAIProvider
from ai_providers.types import AIResponse, ModelInfo

_BLOCKED_FINISH_REASONS = frozenset({
    'SAFETY',
    'PROHIBITED_CONTENT',
    'BLOCKLIST',
    'SPII',
})


def _reason_name(reason) -> str:
    """'SAFETY' for FinishReason.SAFETY / BlockReason values."""
    return getattr(reason, 'name', None) or str(reason)


class GeminiProvider(BaseAIProvider):
    provider_type = 'gemini'

    def __init__(self, api_key, base_url='', extra_headers=None,
                 timeout=60):
        super().__init__(api_key, base_url, extra_headers, timeout)
        # google-genai 1.67.0 never retries unless HttpOptions
        # .retry_options is set (verified in _api_client.retry_args:
        # None -> tenacity stop_after_attempt(1)). We leave it unset
        # so generate() stays a single attempt; retries live in
        # JobClient (PR-4).
        http_options = genai_types.HttpOptions(timeout=timeout * 1000)
        if self.base_url:
            http_options.base_url = self.base_url
        if self.extra_headers:
            http_options.headers = dict(self.extra_headers)
        self._client = genai.Client(
            api_key=self.api_key,
            http_options=http_options,
        )

    def generate(self, model, prompt, options):
        config = self._build_config(prompt, options)
        try:
            response = self._client.models.generate_content(
                model=model,
                contents=prompt.user,
                config=config,
            )
        except genai_errors.APIError as e:
            raise self._map_api_error(e) from e
        except (json.JSONDecodeError, pydantic.ValidationError,
                genai_errors.UnknownApiResponseError) as e:
            # A 200 body that is not JSON, or fails pydantic
            # validation inside the SDK — a malformed/missing success
            # body, not an error status (plan 5.2 AIServerError).
            raise AIServerError(self._scrub_message(e)) from e
        except httpx.HTTPError as e:
            # Network/timeout failures propagate unwrapped by the SDK.
            raise AITimeoutError(self._scrub_message(e)) from e
        return self._to_response(model, response)

    def list_models(self):
        """Model catalog via ``client.models.list()`` (PR-5).

        Keeps only models whose ``supported_actions`` include
        'generateContent' (the Gemini API's
        ``supportedGenerationMethods`` field), strips the 'models/'
        resource prefix off ``name`` and maps ``input_token_limit``
        to ``context_length``. The endpoint reports no prices.
        """
        try:
            pager = self._client.models.list()
            # The Pager fetches lazily while iterating, so the loop
            # must stay inside the try for error mapping.
            infos = []
            for model in pager:
                info = self._model_info(model)
                if info is not None:
                    infos.append(info)
            return infos
        except genai_errors.APIError as e:
            raise self._map_api_error(e) from e
        except (json.JSONDecodeError, pydantic.ValidationError,
                genai_errors.UnknownApiResponseError) as e:
            raise AIServerError(self._scrub_message(e)) from e
        except httpx.HTTPError as e:
            raise AITimeoutError(self._scrub_message(e)) from e

    @staticmethod
    def _model_info(model):
        """SDK ``Model`` -> ``ModelInfo``, or None when the model
        cannot generateContent or has no usable name."""
        actions = getattr(model, 'supported_actions', None) or []
        if 'generateContent' not in actions:
            return None
        name = getattr(model, 'name', '') or ''
        if name.startswith('models/'):
            name = name[len('models/'):]
        if not name:
            return None
        return ModelInfo(
            name=name,
            display_name=getattr(model, 'display_name', '') or '',
            context_length=getattr(model, 'input_token_limit', None),
        )

    def _build_config(self, prompt, options):
        kwargs = {}
        if prompt.system is not None:
            kwargs['system_instruction'] = prompt.system
        if options.json_mode:
            kwargs['response_mime_type'] = 'application/json'
        if options.temperature is not None:
            kwargs['temperature'] = options.temperature
        if options.max_output_tokens is not None:
            kwargs['max_output_tokens'] = options.max_output_tokens
        if not kwargs:
            return None
        return genai_types.GenerateContentConfig(**kwargs)

    def _to_response(self, model, response):
        served_model = response.model_version or model
        usage = response.usage_metadata
        input_tokens = getattr(usage, 'prompt_token_count', None)
        output_tokens = getattr(usage, 'candidates_token_count', None)
        candidates = response.candidates or []
        finish_reason = (
            getattr(candidates[0], 'finish_reason', None)
            if candidates else None
        )
        finish_name = _reason_name(finish_reason) if finish_reason else ''
        common = {
            'served_model': served_model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'finish_reason': finish_name or None,
        }
        feedback = response.prompt_feedback
        block_reason = (
            getattr(feedback, 'block_reason', None) if feedback else None
        )
        if block_reason:
            return AIResponse(
                text=None,
                status='blocked',
                block_reason=_reason_name(block_reason),
                **common,
            )
        if finish_name in _BLOCKED_FINISH_REASONS:
            return AIResponse(
                text=None,
                status='blocked',
                block_reason=finish_name,
                **common,
            )
        text = response.text
        if not text:
            raise AIEmptyResponseError(
                f'Gemini returned no text (model={model}, '
                f'finish_reason={finish_name or "none"})'
            )
        return AIResponse(text=text, **common)

    def _map_api_error(self, error):
        code = getattr(error, 'code', None)
        message = self._scrub_message(
            getattr(error, 'message', None) or error
        )
        response = getattr(error, 'response', None)
        headers = getattr(response, 'headers', None)
        if code == 429:
            return AIRateLimitError(
                message,
                http_status=code,
                retry_after=self._retry_after_seconds(headers),
            )
        if code in (401, 403):
            return AIAuthError(message, http_status=code)
        if code == 402:
            return AIQuotaError(message, http_status=code)
        if code == 404:
            return AIModelNotFoundError(message, http_status=code)
        if code == 400 or code == 422:
            return AIBadRequestError(message, http_status=code)
        if code == 408:
            # Request Timeout is transient (the SDK's own retry list
            # includes it) — retryable, not a bad request.
            return AITimeoutError(message, http_status=code)
        if code and code >= 500:
            return AIServerError(message, http_status=code)
        if code and code >= 400:
            # Any other 4xx (e.g. 409) is a rejected request shape.
            return AIBadRequestError(message, http_status=code)
        return AIServerError(message, http_status=code or None)
