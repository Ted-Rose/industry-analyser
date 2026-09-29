"""OpenAI-compatible adapter using the openai SDK (plan 5.3).

Works for OpenRouter, Groq, Mistral, Cerebras, OpenAI, ... — any API
exposing ``/chat/completions`` behind ``base_url``.
"""

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

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
from ai_providers.types import AIResponse

_MODERATION_CODES = frozenset({
    'content_policy_violation',
    'content_filter',
    'moderation',
})


def _body_indicates_moderation(body) -> bool:
    """True when a 403 body looks like a moderation refusal rather
    than an auth failure (OpenRouter returns 403 for flagged input)."""
    if not isinstance(body, dict):
        return False
    error = body.get('error')
    if not isinstance(error, dict):
        return 'moderation' in str(error or body).lower()
    code = str(error.get('code') or '').lower()
    message = str(error.get('message') or '').lower()
    if code in _MODERATION_CODES or 'moderation' in code:
        return True
    if 'moderation' in message or 'flag' in message:
        return True
    metadata = error.get('metadata')
    return isinstance(metadata, dict) and bool(metadata.get('reasons'))


class OpenAICompatibleProvider(BaseAIProvider):
    provider_type = 'openai_compatible'

    def __init__(self, api_key, base_url='', extra_headers=None,
                 timeout=60):
        super().__init__(api_key, base_url, extra_headers, timeout)
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url or None,
            default_headers=self.extra_headers or None,
            timeout=self.timeout,
            max_retries=0,
        )

    def generate(self, model, prompt, options):
        kwargs = self._build_kwargs(model, prompt, options)
        try:
            response = self._client.chat.completions.create(**kwargs)
        except RateLimitError as e:
            raise AIRateLimitError(
                self._scrub_message(e),
                http_status=getattr(e, 'status_code', None) or 429,
                retry_after=self._retry_after_seconds(
                    getattr(getattr(e, 'response', None), 'headers', None)
                ),
            ) from e
        except APITimeoutError as e:
            raise AITimeoutError(self._scrub_message(e)) from e
        except APIConnectionError as e:
            raise AITimeoutError(self._scrub_message(e)) from e
        except InternalServerError as e:
            raise AIServerError(
                self._scrub_message(e),
                http_status=getattr(e, 'status_code', None),
            ) from e
        except AuthenticationError as e:
            raise AIAuthError(
                self._scrub_message(e),
                http_status=getattr(e, 'status_code', None) or 401,
            ) from e
        except PermissionDeniedError as e:
            if _body_indicates_moderation(getattr(e, 'body', None)):
                return AIResponse(
                    text=None,
                    served_model=model,
                    status='blocked',
                    block_reason=self._scrub_message(e),
                )
            raise AIAuthError(
                self._scrub_message(e),
                http_status=getattr(e, 'status_code', None) or 403,
            ) from e
        except NotFoundError as e:
            raise AIModelNotFoundError(
                self._scrub_message(e),
                http_status=getattr(e, 'status_code', None) or 404,
            ) from e
        except (BadRequestError, UnprocessableEntityError) as e:
            raise AIBadRequestError(
                self._scrub_message(e),
                http_status=getattr(e, 'status_code', None),
            ) from e
        except APIStatusError as e:
            status = getattr(e, 'status_code', None)
            if status == 402:
                raise AIQuotaError(
                    self._scrub_message(e), http_status=status,
                ) from e
            if status and status >= 500:
                raise AIServerError(
                    self._scrub_message(e), http_status=status,
                ) from e
            raise AIBadRequestError(
                self._scrub_message(e), http_status=status,
            ) from e
        return self._to_response(model, response)

    def _build_kwargs(self, model, prompt, options):
        messages = []
        if prompt.system is not None:
            messages.append({'role': 'system', 'content': prompt.system})
        messages.append({'role': 'user', 'content': prompt.user})
        kwargs = {'model': model, 'messages': messages}
        if options.json_mode:
            kwargs['response_format'] = {'type': 'json_object'}
        if options.temperature is not None:
            kwargs['temperature'] = options.temperature
        if options.max_output_tokens is not None:
            kwargs['max_tokens'] = options.max_output_tokens
        return kwargs

    def _to_response(self, model, response):
        # Some providers return HTTP 200 with an 'error' object in
        # the body (OpenRouter), or a body with no choices at all.
        error_obj = getattr(response, 'error', None)
        if error_obj:
            raise AIServerError(self._scrub_message(error_obj))
        choices = getattr(response, 'choices', None)
        if not choices:
            raise AIServerError(
                f'OpenAI-compatible response had no choices '
                f'(model={model})'
            )
        choice = choices[0]
        finish_reason = getattr(choice, 'finish_reason', None)
        usage = getattr(response, 'usage', None)
        input_tokens = getattr(usage, 'prompt_tokens', None)
        output_tokens = getattr(usage, 'completion_tokens', None)
        served_model = getattr(response, 'model', None) or model
        if finish_reason == 'content_filter':
            return AIResponse(
                text=None,
                served_model=served_model,
                status='blocked',
                block_reason='content_filter',
                finish_reason=finish_reason,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        message = getattr(choice, 'message', None)
        text = getattr(message, 'content', None)
        if not text:
            raise AIEmptyResponseError(
                f'OpenAI-compatible response had empty content '
                f'(model={model}, finish_reason={finish_reason})'
            )
        return AIResponse(
            text=text,
            served_model=served_model,
            finish_reason=finish_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
