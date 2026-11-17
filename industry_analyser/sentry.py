"""Sentry helpers for the ``industry_analyser`` project package.

The SDK is initialized in ``settings.py`` only when ``SENTRY_DSN``
is set — every ``capture_*`` call here is a safe no-op when it is
not (local dev, tests, CI, or a deploy made before the secret
exists), so call sites never need to guard.

Event-stream contract (documented in AGENTS.md):
    ``capture_internal_exception`` — caught bugs the code handles
        and continues past (uniform API 500s, failed run_all_jobs
        sub-jobs, failed scrape items): level error, tag
        ``error_code:internal_error``.
    ``capture_provider_exception`` — upstream failures we cannot
        fix (portal HTTP 429/5xx after retries, every assigned AI
        model failing, a dead scrape target): level warning, tag
        ``error_code`` from ``_PROVIDER_ERROR_CODES``. Expected
        outcomes (empty results, cap reached, blocked content) are
        never sent.
    ``capture_schema_lag`` — a query hit a column/table whose
        migration has not run yet (code deployed ahead of the
        migrate step): level warning, tag
        ``error_code:schema_lag``. Expected transient state, but
        kept observable in case the schema never catches up.

Two cross-cutting rules keep the streams actionable:

*   ``is_upstream_error`` classifies a caught exception — network/
    HTTP failures are scrape-target or provider problems (warning),
    everything else is our bug (error).
*   ``already_reported`` dedupes across wrapping: a ``CommandError``
    raised ``from`` (or inside the except block of) an
    already-captured exception must not spawn a second issue for
    the same failure — e.g. ``scrape_news`` captures its crash,
    wraps it in ``CommandError``, and ``news_pipeline``/
    ``run_all_jobs`` see the wrapper up the chain. The
    ``__context__`` hop is deliberate overreach: a *different*
    crash raised while handling a reported failure inherits the
    marked context and dedupes too — accepted, since a second
    crash during failure-handling is still one incident.
*   Dedup marks live in-process only. A ``run_all_jobs``
    'script'-kind entry runs a subprocess that reports its own
    crash, then the parent's ``CommandError('… exited with
    status N')`` files its own event — two events for one
    failure is correct there: the subprocess may have died
    before reporting, and the exit status is the parent's only
    signal.

A per-process cap bounds the ERROR stream's blast radius: a
systematic bug (a DB outage, a parse crash on every scrape
item) would otherwise file one event per failed item —
hundreds of near-identical error events grouping into a
single issue and burning quota for no extra signal. The first
``_INTERNAL_ERROR_CAP`` events per scope (the ``scrape_job``
tag, ``'internal'`` when untagged) send normally; the rest
are counted in ``_internal_suppressed`` and dropped, with a
warning logged when the cap first trips. WARNING-level
streams stay uncapped — provider-event volume is the outage
trend signal (see ``ai_providers/client.py``).
"""
import http.client
import imaplib
import logging
import socket
import ssl
from urllib.parse import urlparse

import google.api_core.exceptions
import requests.exceptions
import sentry_sdk
import urllib3.exceptions

logger = logging.getLogger('industry_analyser')

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

# Per-process cap on error-level captures, keyed on the
# ``scrape_job`` tag (``'internal'`` when untagged). See the
# module docstring — only the ERROR stream is capped; the
# WARNING provider stream's volume is the trend signal.
_INTERNAL_ERROR_CAP = 10
_internal_sent = {}
_internal_suppressed = {}

# Exception types that mean "the remote side failed", not "our code
# has a bug": urllib3 covers every fetch through BaseScraper's
# PoolManager (MaxRetryError, NewConnectionError, SSLError,
# LocationParseError...), http.client/socket/ssl/builtins cover the
# stdlib layers underneath and non-urllib3 fetchers;
# GoogleAPIError and RequestException cover the GCS/Tasks/OAuth
# client calls. Deliberately narrower than OSError —
# FileNotFoundError (a missing local config) is an internal bug,
# not an upstream outage.
_UPSTREAM_ERROR_TYPES = (
    urllib3.exceptions.HTTPError,
    http.client.HTTPException,
    google.api_core.exceptions.GoogleAPIError,
    requests.exceptions.RequestException,
    # Server-side IMAP disconnect (a BYE response) — the remote
    # dropped the session. ``imaplib.IMAP4.error`` stays out on
    # purpose: a refused login/select is a config bug and
    # correctly reports as internal.
    imaplib.IMAP4.abort,
    socket.timeout,
    socket.gaierror,
    ssl.SSLError,
    ConnectionError,
    TimeoutError,
)


def is_upstream_error(exc):
    """True when ``exc`` is a remote-side failure type.

    Callers deciding between ``capture_internal_exception`` (our
    bug — error level) and ``capture_provider_exception`` (the
    scrape target / API broke — warning level) branch on this.
    """
    return isinstance(exc, _UPSTREAM_ERROR_TYPES)


def _mark_captured(exc):
    """Flag ``exc`` as already sent — see ``already_reported``.

    ``BaseException`` is not guaranteed to allow arbitrary
    attributes on every implementation, so this never raises.
    """
    try:
        exc._sentry_captured = True
    except Exception:
        pass


def mark_handled(exc):
    """Flag ``exc`` as decided — captured or intentionally unsent.

    Same mark the ``capture_*`` helpers apply, for exceptions that
    are an *expected* run outcome (e.g. an ``AIRequestCapReached``
    aborting a sync): the caller still exits non-zero so the run
    fails loudly, but ``already_reported`` up the chain keeps the
    expected outcome out of the error queue.
    """
    _mark_captured(exc)


def already_reported(exc):
    """True when ``exc``'s cause/context chain was already captured.

    Commands report their original exception then wrap it in
    ``CommandError`` (``raise ... from e`` sets ``__cause__``; a
    bare ``raise`` inside the except sets ``__context__``). The
    orchestrating layers (``ScrapeJobRunner.item_failed``,
    ``run_all_jobs``) call this before capturing so one failure
    yields one Sentry event — the innermost, with the real
    traceback — instead of an extra issue per wrapper.

    A True result also marks ``exc`` itself, so wrappers further
    up the chain dedupe too.
    """
    seen = set()
    node = exc
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        if getattr(node, '_sentry_captured', False):
            _mark_captured(exc)
            return True
        # ``__cause__ or __context__`` follows ONE hop: an
        # explicit ``from`` wins over the implicit context, so a
        # wrapper ``from unreported`` raised inside the except
        # block of a *reported* exception misses the marked
        # context node entirely (``__cause__`` is followed,
        # ``__context__`` never visited). Latent — no current
        # call site chains a fresh cause over a reported
        # context.
        node = node.__cause__ or node.__context__
    return False


def _set_tags(scope, tags):
    for key, value in tags.items():
        scope.set_tag(key, str(value))


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


def capture_internal_exception(exc, **tags):
    """Report a caught internal bug at error level.

    Tagged ``error_code:internal_error`` so issue queries can split
    handled-but-buggy failures from unhandled 500s (which arrive
    untagged via ``DjangoIntegration``). Extra ``**tags`` (e.g.
    ``scrape_job``, ``scrape_item``) attach context to the event.

    Sends are capped at ``_INTERNAL_ERROR_CAP`` per ``scrape_job``
    scope per process — see the module docstring. A dropped call
    still marks ``exc`` so wrappers up the chain dedupe as usual.
    """
    scope_key = tags.get('scrape_job') or 'internal'
    if _internal_sent.get(scope_key, 0) >= _INTERNAL_ERROR_CAP:
        suppressed = _internal_suppressed.get(scope_key, 0) + 1
        _internal_suppressed[scope_key] = suppressed
        if suppressed == 1:
            logger.warning(
                'Sentry internal_error cap (%s) reached for scope '
                '%r — further failures this process are counted '
                'but not sent', _INTERNAL_ERROR_CAP, scope_key,
            )
        else:
            logger.info(
                'suppressed %s internal_error Sentry event(s) '
                'for scope %r', suppressed, scope_key,
            )
        _mark_captured(exc)
        return
    _internal_sent[scope_key] = _internal_sent.get(scope_key, 0) + 1
    with sentry_sdk.new_scope() as scope:
        scope.set_tag('error_code', 'internal_error')
        _set_tags(scope, tags)
        scope.set_level('error')
        sentry_sdk.capture_exception(exc)
    _mark_captured(exc)


def capture_provider_exception(exc, error_code, **tags):
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
        _set_tags(scope, tags)
        scope.set_level('warning')
        sentry_sdk.capture_exception(exc)
    _mark_captured(exc)


def capture_schema_lag(exc):
    """Report a still-pending-migration query at warning level.

    Deploy-window 503s are expected, but a *permanently* missing
    column (a failed ``run-migrations`` job, bad SQL) must not go
    dark — the ``error_code:schema_lag`` tag groups recurrences
    into one low-noise issue instead of leaving an unwatched
    warning log as the only trace.
    """
    with sentry_sdk.new_scope() as scope:
        scope.set_tag('error_code', 'schema_lag')
        scope.set_level('warning')
        sentry_sdk.capture_exception(exc)
    _mark_captured(exc)
