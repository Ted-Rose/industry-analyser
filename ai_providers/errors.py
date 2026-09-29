"""AI provider error taxonomy (plan section 5.2).

JobClient (PR-4) decides retry / next-model / next-provider / stop
based on which subclass is raised. Every exception accepts an optional
``http_status`` keyword. Messages must be scrubbed of the API key
before the exception is raised or stored.
"""


class AIError(Exception):
    """Base class for every AI-layer error."""

    def __init__(self, message='', *, http_status=None):
        super().__init__(message)
        self.http_status = http_status


class AIRetryableError(AIError):
    """Transient failure — the request may succeed if sent again."""


class AIRateLimitError(AIRetryableError):
    """HTTP 429. ``retry_after`` is in seconds when the server sent it."""

    def __init__(self, message='', *, http_status=None, retry_after=None):
        super().__init__(message, http_status=http_status)
        self.retry_after = retry_after


class AIServerError(AIRetryableError):
    """HTTP 5xx, or a malformed/missing success body."""


class AITimeoutError(AIRetryableError):
    """Timeout or connection failure before a response arrived."""


class AIEmptyResponseError(AIRetryableError):
    """Response had no text and was not blocked — a retry may succeed."""


class AIModelError(AIError):
    """Model-level failure — skip to the next model."""


class AIBadRequestError(AIModelError):
    """HTTP 400/422 — the request shape was rejected by the provider."""


class AIModelNotFoundError(AIModelError):
    """HTTP 404 — the model id is unknown or unavailable."""


class AIProviderError(AIError):
    """Provider-level failure — skip all models of this provider."""


class AIAuthError(AIProviderError):
    """HTTP 401/403 — the API key is invalid or access is denied."""


class AIQuotaError(AIProviderError):
    """HTTP 402 — out of credits / quota."""


class AIProviderNotConfiguredError(AIProviderError):
    """Required configuration (e.g. the API key setting) is missing."""


class AIJobError(AIError):
    """Job-level failure — stop the caller."""


class AIJobDisabledError(AIJobError):
    """The job's ``is_enabled`` kill switch is off."""


class AIJobNotConfiguredError(AIJobError):
    """No active assignment exists for the requested role."""


class AIRequestCapReached(AIJobError):
    """Per-run or per-day request cap reached before sending."""


class AIAllModelsFailedError(AIJobError):
    """Every assigned model/provider failed. ``last_error`` is the
    final error that was seen."""

    def __init__(self, message='', *, http_status=None, last_error=None):
        super().__init__(message, http_status=http_status)
        self.last_error = last_error
