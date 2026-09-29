"""Base class for provider adapters (plan section 5.3)."""

import abc

from ai_providers.types import AIResponse, GenerationOptions, RenderedPrompt


class BaseAIProvider(abc.ABC):
    """One vendor SDK wrapper. Never sleeps, retries, logs the API
    key, or touches the DB — ``generate()`` is a single attempt."""

    provider_type: str = ''

    def __init__(self, api_key, base_url='', extra_headers=None,
                 timeout=60):
        self.api_key = api_key or ''
        self.base_url = base_url or ''
        self.extra_headers = dict(extra_headers or {})
        self.timeout = timeout

    @abc.abstractmethod
    def generate(self, model: str, prompt: RenderedPrompt,
                 options: GenerationOptions) -> AIResponse:
        """Single attempt. No retries, no sleeping, no DB access.

        Map every vendor error to ai_providers.errors; map every
        refusal/safety block to ``AIResponse(status='blocked')``.
        """

    def list_models(self):
        """Return a list of ModelInfo; implemented in PR-5."""
        raise NotImplementedError

    def _scrub_message(self, message) -> str:
        """Return ``message`` as text with the API key removed, so
        error strings are safe to store in AIRequest / logs."""
        text = '' if message is None else str(message)
        if self.api_key:
            text = text.replace(self.api_key, '<redacted>')
        return text

    @staticmethod
    def _retry_after_seconds(headers):
        """Parse a numeric ``Retry-After`` header value, else None."""
        if not headers:
            return None
        value = headers.get('retry-after')
        if value is None:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return None
