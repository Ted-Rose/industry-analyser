from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class AIProvider(models.Model):
    """An AI vendor (Google Gemini, OpenRouter, ...).

    API keys are never stored in the DB; `api_key_setting` holds the
    *name* of a Django setting containing the key.
    """

    slug = models.SlugField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    provider_type = models.CharField(
        max_length=30,
        choices=[
            ('gemini', 'Google Gemini'),
            ('openai_compatible', 'OpenAI-compatible'),
        ],
    )
    base_url = models.URLField(blank=True)
    api_key_setting = models.CharField(max_length=100)
    extra_headers = models.JSONField(default=dict, blank=True)
    request_timeout_seconds = models.PositiveIntegerField(default=60)
    max_retries = models.PositiveSmallIntegerField(default=2)
    backoff_base_seconds = models.FloatField(default=2.0)
    min_request_interval_seconds = models.FloatField(default=0)
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ai_provider'

    def __str__(self):
        return self.slug

    @property
    def has_api_key(self):
        """True when the referenced Django setting is non-empty.

        The key itself is never displayed or logged.
        """
        return bool(getattr(settings, self.api_key_setting, ''))

    def clean(self):
        super().clean()
        errors = {}
        if (
            self.provider_type == 'openai_compatible'
            and not self.base_url
        ):
            errors['base_url'] = (
                'Required for OpenAI-compatible providers.'
            )
        allowed = getattr(settings, 'AI_API_KEY_SETTINGS', ())
        if self.api_key_setting and self.api_key_setting not in allowed:
            errors['api_key_setting'] = (
                'Must be one of settings.AI_API_KEY_SETTINGS '
                f'({", ".join(allowed)}).'
            )
        if errors:
            raise ValidationError(errors)


class AIModel(models.Model):
    """A single model offered by an AIProvider; `name` is the exact
    API model id."""

    provider = models.ForeignKey(
        AIProvider, on_delete=models.PROTECT, related_name='models'
    )
    name = models.CharField(max_length=200)
    display_name = models.CharField(max_length=200, blank=True)
    is_enabled = models.BooleanField(default=True)
    auto_registered = models.BooleanField(default=False)
    supports_json_mode = models.BooleanField(default=False)
    input_price_per_mtok = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    output_price_per_mtok = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    context_length = models.PositiveIntegerField(
        null=True, blank=True
    )
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'ai_model'
        unique_together = ('provider', 'name')

    def __str__(self):
        return f'{self.provider.slug}:{self.name}'


class AIJob(models.Model):
    """A named AI consumer declared in code, e.g.
    'blogs.theme_analysis'."""

    slug = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    declared_roles = models.JSONField(default=list)
    is_enabled = models.BooleanField(default=True)
    max_requests_per_run = models.PositiveIntegerField(
        null=True, blank=True
    )
    max_requests_per_day = models.PositiveIntegerField(
        null=True, blank=True
    )
    store_inputs = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ai_job'

    def __str__(self):
        return self.slug


class AIJobModel(models.Model):
    """One row per job+role+model; priority orders fallback."""

    job = models.ForeignKey(
        AIJob, on_delete=models.CASCADE, related_name='assignments'
    )
    model = models.ForeignKey(
        AIModel, on_delete=models.PROTECT, related_name='assignments'
    )
    role = models.CharField(max_length=50)
    priority = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'ai_job_model'
        unique_together = ('job', 'role', 'model')
        ordering = ['job', 'role', 'priority', 'id']

    def __str__(self):
        return f'{self.job.slug} [{self.role}] {self.model}'

    def clean(self):
        super().clean()
        errors = {}
        if self.job_id:
            declared = self.job.declared_roles or []
            if self.role not in declared:
                errors['role'] = (
                    f"'{self.role}' is not a declared role of job "
                    f"'{self.job.slug}' "
                    f'(declared: {", ".join(map(str, declared))}).'
                )
        if self.is_active and self.model_id:
            model = self.model
            if not model.is_enabled:
                errors['model'] = (
                    'Active assignments require an enabled model.'
                )
            elif not model.provider.is_enabled:
                errors['model'] = (
                    'Active assignments require an enabled provider.'
                )
        if errors:
            raise ValidationError(errors)


class AIPromptTemplate(models.Model):
    """Versioned instruction text; a new row is created only when the
    text changes, so this doubles as prompt version history."""

    key = models.CharField(max_length=200)
    sha256 = models.CharField(max_length=64)
    text = models.TextField()
    first_seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ai_prompt_template'
        unique_together = ('key', 'sha256')

    def __str__(self):
        return f'{self.key}@{self.sha256[:12]}'


class AIInput(models.Model):
    """Content-addressed untrusted input (e.g. article text); identical
    inputs are stored once."""

    sha256 = models.CharField(max_length=64, unique=True)
    text = models.TextField()
    chars = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ai_input'

    def __str__(self):
        return self.sha256[:12]


class AIRequest(models.Model):
    """One row per attempt that was sent to a provider."""

    job = models.ForeignKey(
        AIJob, on_delete=models.PROTECT, related_name='requests'
    )
    role = models.CharField(max_length=50)
    requested_model = models.ForeignKey(
        AIModel, on_delete=models.PROTECT, related_name='+'
    )
    served_model = models.ForeignKey(
        AIModel, on_delete=models.PROTECT, null=True, related_name='+'
    )
    attempt = models.PositiveSmallIntegerField()
    status = models.CharField(
        max_length=20,
        choices=[
            ('success', 'Success'),
            ('blocked', 'Blocked'),
            ('error', 'Error'),
        ],
    )
    error_type = models.CharField(max_length=100, blank=True)
    error_message = models.CharField(max_length=1000, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True)
    finish_reason = models.CharField(max_length=50, blank=True)
    block_reason = models.CharField(max_length=200, blank=True)
    input_tokens = models.PositiveIntegerField(null=True)
    output_tokens = models.PositiveIntegerField(null=True)
    cost_usd = models.DecimalField(
        max_digits=12, decimal_places=6, null=True
    )
    latency_ms = models.PositiveIntegerField(null=True)
    prompt_template = models.ForeignKey(
        AIPromptTemplate, on_delete=models.PROTECT, null=True,
        related_name='requests'
    )
    input = models.ForeignKey(
        AIInput, on_delete=models.PROTECT, null=True,
        related_name='requests'
    )
    prompt_layout = models.CharField(max_length=30)
    options = models.JSONField(default=dict)
    prompt_chars = models.PositiveIntegerField()
    prompt_sha256 = models.CharField(max_length=64)
    response_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'ai_request'
        indexes = [
            models.Index(fields=['job', 'created_at']),
            models.Index(fields=['requested_model', 'created_at']),
        ]

    def __str__(self):
        return (
            f'{self.job.slug} {self.role} {self.requested_model} '
            f'attempt {self.attempt} [{self.status}]'
        )
