"""JobClient — the runtime that sends AI requests for a job (5.4).

Usage::

    client = get_job_client(THEME_ANALYSIS, max_requests_per_run=None)
    result = client.generate(
        PromptSpec(template_key, template_text, input_text),
        role='cheap', options=GenerationOptions(...),
    )
    # a plain str is also accepted: stored as AIInput, layout 'raw'
    result.text / result.served_model / result.ai_request
    client.request_count          # attempts sent in this run

Configuration (assignments, caps, today's request count) is resolved
once per JobClient — a snapshot per run, so admin changes take effect
on the next client, not mid-run. Every attempt sent is logged as an
``AIRequest`` row and to the ``ai_providers`` logger.
"""

import dataclasses
import hashlib
import logging
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from ai_providers import errors
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
    AIRequest,
    rendered_prompt_sha256,
)
from ai_providers.prompts import render_prompt
from ai_providers.providers import PROVIDER_CLASSES
from ai_providers.types import GenerationOptions, PromptSpec

logger = logging.getLogger('ai_providers')

_MAX_BACKOFF_SECONDS = 60.0
_BACKOFF_JITTER = 0.2
_RESPONSE_TEXT_MAX_CHARS = 20000


@dataclass
class AIResult:
    """Returned by ``JobClient.generate()`` on success or blocked.

    ``requested_model``/``served_model`` are ``AIModel`` instances,
    ``ai_request`` the logged ``AIRequest`` row.
    """

    text: str | None
    status: str                     # 'success' | 'blocked'
    block_reason: str | None
    requested_model: AIModel
    served_model: AIModel
    ai_request: AIRequest


class JobClient:
    """Sends prompts to the models assigned to one AIJob."""

    def __init__(self, job, max_requests_per_run=None):
        if not job.is_enabled:
            raise errors.AIJobDisabledError(
                f"AI job '{job.slug}' is disabled "
                f'(is_enabled=False).'
            )
        self.job = job
        self._assignments = defaultdict(list)
        for assignment in (
            AIJobModel.objects
            .filter(
                job=job,
                is_active=True,
                model__is_enabled=True,
                model__provider__is_enabled=True,
            )
            .select_related('model__provider')
            .order_by('priority', 'id')
        ):
            self._assignments[assignment.role].append(assignment)
        caps = [
            cap for cap in (
                job.max_requests_per_run, max_requests_per_run
            )
            if cap is not None
        ]
        self._run_cap = min(caps) if caps else None
        today_start = timezone.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # Today's count is loaded once and incremented in memory —
        # concurrent runs may overshoot slightly (soft cap).
        self._sent_today = AIRequest.objects.filter(
            job=job, created_at__gte=today_start
        ).count()
        self._request_count = 0
        self._adapters = {}           # provider.id -> adapter | error
        self._dead_providers = set()  # provider ids, client lifetime
        self._last_send_at = {}       # provider.id -> monotonic ts

    @property
    def request_count(self):
        """Attempts actually sent in this run (failures included)."""
        return self._request_count

    def supports_json_mode(self, role):
        """True when any of the role's active assignments' models
        has ``AIModel.supports_json_mode`` set.

        Reflects the assignment snapshot taken at construction —
        admin changes apply to the next JobClient, not mid-run.
        Returns False for a role with no active assignment.
        ``generate()`` still gates ``json_mode`` per assignment, so
        a True here never pushes the option onto a model that does
        not support it.
        """
        assignments = self._assignments.get(role) or []
        return any(
            assignment.model.supports_json_mode
            for assignment in assignments
        )

    def generate(self, prompt, role, options=None):
        """Send `prompt` via the first working assignment for `role`.

        `prompt` is a ``PromptSpec`` or a plain ``str`` (the latter is
        stored as an ``AIInput`` with layout ``'raw'`` and no
        template). Returns ``AIResult`` on success/blocked; raises
        ``AIJobNotConfiguredError``, ``AIRequestCapReached`` or
        ``AIAllModelsFailedError``.
        """
        if options is None:
            options = GenerationOptions()
        spec = self._coerce_prompt(prompt)
        assignments = self._assignments.get(role) or []
        if not assignments:
            raise errors.AIJobNotConfiguredError(
                f"AI job '{self.job.slug}' has no active assignment "
                f"for role '{role}' — add one in the AIJobModel "
                f'inline at /admin/ai_providers/aijob/'
                f'{self.job.pk}/change/.'
            )
        rendered = render_prompt(
            spec.template_text, spec.input_text, spec.layout,
            images=spec.images,
        )
        prompt_chars = len(rendered.user or '') + len(
            rendered.system or ''
        )
        # Image bytes are never stored — digests land on
        # AIRequest.options['images'] for provenance.
        images_meta = [
            {
                'sha256': hashlib.sha256(image.data).hexdigest(),
                'mime_type': image.mime_type,
                'bytes': len(image.data),
            }
            for image in spec.images
        ] or None
        prompt_sha256 = rendered_prompt_sha256(
            rendered.system, rendered.user
        )
        prompt_parts = None  # lazily registered before the 1st send
        last_error = None
        for assignment in assignments:
            provider = assignment.model.provider
            if provider.id in self._dead_providers:
                continue
            # json_mode is sent only to models whose assignment flags
            # them capable — a fallback without supports_json_mode
            # must not receive response_format/response_mime_type.
            effective_options = dataclasses.replace(
                options,
                json_mode=bool(
                    options.json_mode
                    and assignment.model.supports_json_mode
                ),
            )
            for attempt in range(1, provider.max_retries + 2):
                self._check_caps()
                try:
                    adapter = self._adapter_for(provider)
                except errors.AIProviderError as e:
                    last_error = e
                    self._dead_providers.add(provider.id)
                    break
                if prompt_parts is None:
                    prompt_parts = self._register_prompt_parts(spec)
                template, ai_input = prompt_parts
                self._throttle(provider)
                self._last_send_at[provider.id] = time.monotonic()
                self._request_count += 1
                started = time.monotonic()
                try:
                    response = adapter.generate(
                        assignment.model.name, rendered,
                        effective_options,
                    )
                except errors.AIError as e:
                    latency_ms = int(
                        (time.monotonic() - started) * 1000
                    )
                    self._write_request(
                        assignment=assignment,
                        attempt=attempt,
                        status='error',
                        response=None,
                        error=e,
                        latency_ms=latency_ms,
                        template=template,
                        ai_input=ai_input,
                        layout=spec.layout,
                        options=effective_options,
                        images_meta=images_meta,
                        prompt_chars=prompt_chars,
                        prompt_sha256=prompt_sha256,
                    )
                    last_error = e
                    if isinstance(e, errors.AIProviderError):
                        self._dead_providers.add(provider.id)
                        break
                    if isinstance(e, errors.AIRetryableError):
                        if attempt <= provider.max_retries:
                            delay = self._backoff(provider, e, attempt)
                            time.sleep(delay)
                            continue
                    break  # retries exhausted or model-level error
                except Exception as e:
                    # Unexpected adapter bug: still log the attempt,
                    # then let it propagate (not a model failure).
                    latency_ms = int(
                        (time.monotonic() - started) * 1000
                    )
                    self._write_request(
                        assignment=assignment,
                        attempt=attempt,
                        status='error',
                        response=None,
                        error=e,
                        latency_ms=latency_ms,
                        template=template,
                        ai_input=ai_input,
                        layout=spec.layout,
                        options=effective_options,
                        images_meta=images_meta,
                        prompt_chars=prompt_chars,
                        prompt_sha256=prompt_sha256,
                    )
                    raise
                latency_ms = int((time.monotonic() - started) * 1000)
                served = self._served_model(
                    provider, response.served_model,
                    assignment.model.name,
                )
                ai_request = self._write_request(
                    assignment=assignment,
                    attempt=attempt,
                    status=response.status,
                    response=response,
                    error=None,
                    latency_ms=latency_ms,
                    template=template,
                    ai_input=ai_input,
                    layout=spec.layout,
                    options=effective_options,
                    images_meta=images_meta,
                    prompt_chars=prompt_chars,
                    prompt_sha256=prompt_sha256,
                    served=served,
                )
                self._touch_last_used(assignment.model, served)
                return AIResult(
                    text=response.text,
                    status=response.status,
                    block_reason=response.block_reason,
                    requested_model=assignment.model,
                    served_model=served,
                    ai_request=ai_request,
                )
        raise errors.AIAllModelsFailedError(
            f"All assigned models failed for job '{self.job.slug}' "
            f"role '{role}'. Last error: {last_error}",
            last_error=last_error,
        )

    @staticmethod
    def _coerce_prompt(prompt):
        """Plain str -> PromptSpec with layout 'raw', no template."""
        if isinstance(prompt, str):
            return PromptSpec(
                template_key='',
                template_text='',
                input_text=prompt,
                layout='raw',
            )
        return prompt

    def _check_caps(self):
        """AIRequestCapReached before any send past a cap.

        Caps count attempts sent (failures included). The day cap is
        soft: today's count is snapshotted at construction.
        """
        if (
            self._run_cap is not None
            and self._request_count >= self._run_cap
        ):
            raise errors.AIRequestCapReached(
                f"AI job '{self.job.slug}' reached its per-run "
                f'request cap ({self._request_count}/'
                f'{self._run_cap}).'
            )
        day_cap = self.job.max_requests_per_day
        sent_today = self._sent_today + self._request_count
        if day_cap is not None and sent_today >= day_cap:
            raise errors.AIRequestCapReached(
                f"AI job '{self.job.slug}' reached its per-day "
                f'request cap ({sent_today}/{day_cap}, UTC day; '
                f'soft cap).'
            )

    def _adapter_for(self, provider):
        """Cached provider adapter; AIProviderNotConfiguredError when
        the key setting is empty or the type unknown."""
        cached = self._adapters.get(provider.id)
        if cached is not None:
            if isinstance(cached, Exception):
                raise cached
            return cached
        try:
            adapter = self._build_adapter(provider)
        except errors.AIProviderNotConfiguredError as e:
            self._adapters[provider.id] = e
            raise
        self._adapters[provider.id] = adapter
        return adapter

    @staticmethod
    def _build_adapter(provider):
        cls = PROVIDER_CLASSES.get(provider.provider_type)
        if cls is None:
            raise errors.AIProviderNotConfiguredError(
                f"Provider '{provider.slug}' has unknown "
                f"provider_type '{provider.provider_type}'."
            )
        api_key = getattr(settings, provider.api_key_setting, '')
        if not api_key:
            raise errors.AIProviderNotConfiguredError(
                f"Provider '{provider.slug}' has no API key: "
                f'setting {provider.api_key_setting} is empty.'
            )
        return cls(
            api_key=api_key,
            base_url=provider.base_url,
            extra_headers=provider.extra_headers,
            timeout=provider.request_timeout_seconds,
        )

    def _register_prompt_parts(self, spec):
        """get_or_create the AIPromptTemplate and AIInput once per
        generate() call, before the first send."""
        template = None
        if spec.layout != 'raw':
            template, _ = AIPromptTemplate.objects.get_or_create(
                key=spec.template_key,
                sha256=hashlib.sha256(
                    spec.template_text.encode('utf-8')
                ).hexdigest(),
                defaults={'text': spec.template_text},
            )
        ai_input = None
        if self.job.store_inputs:
            text = spec.input_text
            ai_input, _ = AIInput.objects.get_or_create(
                sha256=hashlib.sha256(
                    text.encode('utf-8')
                ).hexdigest(),
                defaults={'text': text, 'chars': len(text)},
            )
        return template, ai_input

    def _throttle(self, provider):
        """Client-side rate limiting: enforce the provider's
        min_request_interval_seconds between sends."""
        interval = provider.min_request_interval_seconds
        if interval <= 0:
            return
        last = self._last_send_at.get(provider.id)
        if last is None:
            return
        wait = interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _backoff(provider, error, attempt):
        """max(retry_after, base * 2**(attempt-1)) ±20% jitter, ≤60s."""
        base = provider.backoff_base_seconds * (2 ** (attempt - 1))
        retry_after = getattr(error, 'retry_after', None) or 0
        delay = max(retry_after, base)
        delay *= 1 + random.uniform(-_BACKOFF_JITTER, _BACKOFF_JITTER)
        return min(_MAX_BACKOFF_SECONDS, delay)

    @staticmethod
    def _served_model(provider, served_name, fallback_name):
        """Auto-register the model the provider reports serving."""
        model, _ = AIModel.objects.get_or_create(
            provider=provider,
            name=served_name or fallback_name,
            defaults={'auto_registered': True},
        )
        return model

    @staticmethod
    def _touch_last_used(*models):
        now = timezone.now()
        seen = set()
        for model in models:
            if model.pk in seen:
                continue
            seen.add(model.pk)
            AIModel.objects.filter(pk=model.pk).update(
                last_used_at=now
            )

    @staticmethod
    def _cost_usd(model, response):
        """tokens * prices / 1e6, or None unless both prices and both
        token counts are known."""
        if (
            response.input_tokens is None
            or response.output_tokens is None
            or model.input_price_per_mtok is None
            or model.output_price_per_mtok is None
        ):
            return None
        cost = (
            response.input_tokens * model.input_price_per_mtok
            + response.output_tokens * model.output_price_per_mtok
        ) / Decimal(1_000_000)
        return cost.quantize(Decimal('0.000001'))

    @staticmethod
    def _scrub(text, api_key):
        """Defensive API-key scrubbing (adapters already scrub)."""
        if api_key:
            return text.replace(api_key, '<redacted>')
        return text

    def _write_request(self, *, assignment, attempt, status, response,
                       error, latency_ms, template, ai_input, layout,
                       options, prompt_chars, prompt_sha256,
                       images_meta=None, served=None):
        """Persist one AIRequest row for the attempt just sent."""
        provider = assignment.model.provider
        api_key = getattr(settings, provider.api_key_setting, '')
        options_dict = dataclasses.asdict(options)
        if images_meta:
            options_dict['images'] = images_meta
        row = AIRequest(
            job=self.job,
            role=assignment.role,
            requested_model=assignment.model,
            served_model=served,
            attempt=attempt,
            status=status,
            latency_ms=latency_ms,
            prompt_template=template,
            input=ai_input,
            prompt_layout=layout,
            options=options_dict,
            prompt_chars=prompt_chars,
            prompt_sha256=prompt_sha256,
        )
        if response is not None:
            price_model = served or assignment.model
            row.finish_reason = response.finish_reason or ''
            row.block_reason = (response.block_reason or '')[:200]
            row.input_tokens = response.input_tokens
            row.output_tokens = response.output_tokens
            row.cost_usd = self._cost_usd(price_model, response)
            row.response_text = (response.text or '')[
                :_RESPONSE_TEXT_MAX_CHARS
            ]
        if error is not None:
            row.error_type = type(error).__name__
            row.error_message = self._scrub(
                str(error), api_key
            )[:1000]
            row.http_status = getattr(error, 'http_status', None)
        row.save()
        logger.info(
            'ai_request job=%s role=%s model=%s attempt=%s '
            'status=%s latency_ms=%s tokens=%s/%s requests=%s/%s',
            self.job.slug,
            assignment.role,
            assignment.model.name,
            attempt,
            status,
            latency_ms,
            row.input_tokens if row.input_tokens is not None else '-',
            row.output_tokens
            if row.output_tokens is not None else '-',
            self._request_count,
            self._run_cap if self._run_cap is not None else 'inf',
        )
        return row


def get_job_client(spec_or_slug, max_requests_per_run=None):
    """Build a JobClient for an AIJobSpec, an AIJob, or a job slug.

    * ``AIJobSpec`` → ``ensure_job(spec)``: the AIJob row is
      created/synced and, on first creation only, the spec's default
      assignments are seeded.
    * ``AIJob`` → used as-is (no seeding); intended for callers that
      already resolved the row, e.g. ``ai_smoke_test``.
    * ``str`` slug → the existing AIJob row is used as-is; if none
      exists, autodiscovered AIJobSpecs are searched for the slug and
      ensured. With no row and no spec, AIJobNotConfiguredError is
      raised — arbitrary slugs never auto-create jobs.
    """
    if isinstance(spec_or_slug, AIJobSpec):
        job = ensure_job(spec_or_slug)
    elif isinstance(spec_or_slug, AIJob):
        job = spec_or_slug
    else:
        slug = str(spec_or_slug)
        job = AIJob.objects.filter(slug=slug).first()
        if job is None:
            for spec in autodiscover_job_specs():
                if spec.slug == slug:
                    job = ensure_job(spec)
                    break
        if job is None:
            raise errors.AIJobNotConfiguredError(
                f"No AIJob row and no AIJobSpec found for slug "
                f"'{slug}'."
            )
    return JobClient(job, max_requests_per_run=max_requests_per_run)
