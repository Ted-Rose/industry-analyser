"""OpenAI-compatible adapter using the openai SDK (plan 5.3).

Works for OpenRouter, Groq, Mistral, Cerebras, OpenAI, ... — any API
exposing ``/chat/completions`` behind ``base_url``.
"""

from decimal import Decimal, InvalidOperation

from openai import (
    APIConnectionError,
    APIError,
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
from ai_providers.types import AIResponse, ModelInfo

_MODERATION_CODES = frozenset({
    'content_policy_violation',
    'content_filter',
    'moderation',
})


def _catalog_field(model, key):
    """Read a possibly vendor-specific field off an SDK ``Model``.

    Works for attribute-style objects (the openai SDK keeps extra
    JSON keys in ``model_extra`` and exposes them as attributes) and
    for plain dicts, so responses that fail model construction still
    yield what they carry.
    """
    if isinstance(model, dict):
        return model.get(key)
    return getattr(model, key, None)


def _price_per_mtok(pricing, key):
    """OpenRouter ``pricing`` values are USD-per-token strings;
    convert to USD per 1M tokens. ``None`` when absent, invalid or
    negative (OpenRouter uses ``-1`` for "no fixed price")."""
    if not isinstance(pricing, dict):
        return None
    raw = pricing.get(key)
    if raw in (None, ''):
        return None
    try:
        per_token = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    if per_token < 0:
        return None
    return (per_token * Decimal(1_000_000)).quantize(
        Decimal('0.0001')
    )


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
        response = self._request(
            lambda: self._client.chat.completions.create(**kwargs),
            model,
        )
        if isinstance(response, AIResponse):
            return response  # 403 moderation refusal, already mapped
        return self._to_response(model, response)

    def list_models(self):
        """Model catalog via ``client.models.list()`` (PR-5).

        The SDK's ``Model`` is built with ``extra='allow'``, so
        vendor-specific fields (OpenRouter ``pricing``,
        ``context_length``, ``name``, ``supported_parameters``) land
        in ``model_extra`` and are readable as attributes; plain
        OpenAI endpoints return bare ids and yield a minimal
        ``ModelInfo``.
        """
        page = self._request(lambda: self._client.models.list(), '')
        if isinstance(page, AIResponse):
            # A 403 moderation-style refusal on the listing endpoint
            # (OpenRouter) — it cannot produce a catalog.
            raise AIServerError(
                self._scrub_message(
                    page.block_reason or 'models list blocked'
                )
            )
        infos = []
        for model in page:
            info = self._model_info(model)
            if info is not None:
                infos.append(info)
        return infos

    def _request(self, call, model):
        """Run one SDK call, mapping vendor errors to errors.py.

        Returns either the raw SDK response or, for a 403
        moderation-style refusal, an ``AIResponse(status='blocked')``
        (``model`` fills ``served_model`` on that path).
        """
        try:
            return call()
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
            if status == 408:
                # Request Timeout is transient — retryable, not a
                # bad request.
                raise AITimeoutError(
                    self._scrub_message(e), http_status=status,
                ) from e
            if status and status >= 500:
                raise AIServerError(
                    self._scrub_message(e), http_status=status,
                ) from e
            # Any other status-carrying error (e.g. 409) is treated
            # as a rejected request shape — non-retryable.
            raise AIBadRequestError(
                self._scrub_message(e), http_status=status,
            ) from e
        except APIError as e:
            # Non-status SDK errors, e.g. APIResponseValidationError
            # when a 200 body fails pydantic validation — a
            # malformed/missing success body (plan 5.2 AIServerError).
            raise AIServerError(self._scrub_message(e)) from e

    @staticmethod
    def _model_info(model):
        """SDK ``Model`` -> ``ModelInfo``, or None without an id."""
        name = _catalog_field(model, 'id')
        if not name:
            return None
        context_length = _catalog_field(model, 'context_length')
        if context_length is not None:
            try:
                context_length = int(context_length)
            except (TypeError, ValueError):
                context_length = None
        pricing = _catalog_field(model, 'pricing')
        supported = _catalog_field(model, 'supported_parameters') or []
        return ModelInfo(
            name=name,
            display_name=_catalog_field(model, 'name') or '',
            context_length=context_length,
            input_price_per_mtok=_price_per_mtok(pricing, 'prompt'),
            output_price_per_mtok=_price_per_mtok(
                pricing, 'completion'
            ),
            supports_json_mode='response_format' in supported,
        )

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
            # 'max_tokens' is accepted by OpenRouter/Groq/Mistral;
            # newer OpenAI models want 'max_completion_tokens'
            # instead — revisit if a job targets OpenAI directly.
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
