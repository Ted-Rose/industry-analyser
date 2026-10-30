"""Sentry helpers for the ``industry_analyser`` project package.

The SDK is initialized in ``settings.py`` only when ``SENTRY_DSN``
is set — every ``capture_*`` call here is a safe no-op when it is
not (local dev, tests, CI, or a deploy made before the secret
exists), so call sites never need to guard.

Event-stream contract (documented in AGENTS.md):
    ``capture_internal_exception`` — caught bugs the code handles
        and continues past (uniform API 500s, failed run_all_jobs
        sub-jobs): level error, tag ``error_code:internal_error``.
    ``capture_provider_exception`` — upstream failures we cannot
        fix (portal HTTP 429/5xx after retries, every assigned AI
        model failing): level warning, tag ``error_code`` from
        ``_PROVIDER_ERROR_CODES``. Expected outcomes (empty
        results, cap reached, blocked content) are never sent.
"""
from urllib.parse import urlparse

import sentry_sdk

# Paths whose request bodies can carry credentials: admin login
# posts passwords under /admin/login/ (covered by the /admin/
# prefix), the /api/accounts/ register/login bodies carry
# passwords, and receipts endpoints may touch IMAP/Gmail
# credentials.
# ``sentry_before_send`` strips the parsed body for these paths so
# secrets can never reach Sentry. Defense in depth on top of
# ``send_default_pii=False`` and Sentry's server-side scrubbers —
# URL, method, and headers are kept so the event stays debuggable.
_SENSITIVE_PATH_PREFIXES = (
    '/admin/',
    '/api/accounts/',
    '/api/receipts/',
)

# Allowed ``error_code`` values for ``capture_provider_exception`` —
# the queryable contract for "upstream broke, not our bug".
_PROVIDER_ERROR_CODES = frozenset({'rate_limited', 'provider_error'})


def sentry_before_send(event, hint):
    """Scrub sensitive request data before a Sentry event sends.

    Fails closed: when the request path cannot be determined (a
    missing or malformed ``url`` never yields a ``/``-leading path)
    the body is stripped anyway — a false positive only costs
    debuggability, a false negative leaks credentials.
    """
    request = event.get('request')
    if not isinstance(request, dict):
        return event
    path = urlparse(request.get('url') or '').path
    if (
        not path.startswith('/')
        or path.startswith(_SENSITIVE_PATH_PREFIXES)
    ):
        request.pop('data', None)
    return event


def capture_internal_exception(exc):
    """Report a caught internal bug at error level.

    Tagged ``error_code:internal_error`` so issue queries can split
    handled-but-buggy failures from unhandled 500s (which arrive
    untagged via ``DjangoIntegration``).
    """
    with sentry_sdk.new_scope() as scope:
        scope.set_tag('error_code', 'internal_error')
        scope.set_level('error')
        sentry_sdk.capture_exception(exc)


def capture_provider_exception(exc, error_code):
    """Report an upstream failure at warning level.

    ``error_code`` must be one of ``_PROVIDER_ERROR_CODES``
    (``rate_limited`` for HTTP-429-style exhaustion,
    ``provider_error`` for everything else) — anything else raises
    ``ValueError`` so the tag vocabulary stays closed.
    """
    if error_code not in _PROVIDER_ERROR_CODES:
        raise ValueError(
            f'error_code must be one of '
            f'{sorted(_PROVIDER_ERROR_CODES)}, got {error_code!r}'
        )
    with sentry_sdk.new_scope() as scope:
        scope.set_tag('error_code', error_code)
        scope.set_level('warning')
        sentry_sdk.capture_exception(exc)
