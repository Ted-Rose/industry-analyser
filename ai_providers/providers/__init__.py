"""Provider adapter registry (plan section 5.3)."""

from ai_providers.providers.gemini import GeminiProvider
from ai_providers.providers.openai_compat import (
    OpenAICompatibleProvider,
)

PROVIDER_CLASSES = {
    'gemini': GeminiProvider,
    'openai_compatible': OpenAICompatibleProvider,
}
