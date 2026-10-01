"""Shared dataclasses for the AI provider adapters (plan section 5.1)."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class GenerationOptions:
    json_mode: bool = False
    temperature: float | None = None
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class ImagePart:
    """Binary prompt content (image/PDF) for multimodal models."""
    data: bytes
    mime_type: str           # e.g. 'image/png', 'application/pdf'


@dataclass(frozen=True)
class PromptSpec:
    template_key: str        # e.g. 'blogs.theme.violence'
    template_text: str       # trusted instructions
    input_text: str          # untrusted content (article, ad, ...)
    layout: str = 'inline_v1'
    images: tuple[ImagePart, ...] = ()


@dataclass(frozen=True)
class RenderedPrompt:        # what adapters receive
    user: str
    system: str | None = None
    images: tuple[ImagePart, ...] = ()


@dataclass
class AIResponse:
    text: str | None
    served_model: str
    status: str = 'success'          # 'success' | 'blocked'
    block_reason: str | None = None
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class ModelInfo:                     # used by PR-5 catalog sync
    name: str
    display_name: str = ''
    context_length: int | None = None
    input_price_per_mtok: Decimal | None = None
    output_price_per_mtok: Decimal | None = None
    supports_json_mode: bool = False
