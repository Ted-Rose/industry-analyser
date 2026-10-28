import * as Sentry from '@sentry/react';
import type { ErrorEvent, EventHint } from '@sentry/react';

/**
 * Sentry bootstrap for the SPA entries.
 *
 * The web DSN is server-rendered into the page: `_spa_shell`
 * writes `sentry.{dsn,environment,release}` into the
 * `#spa-bootstrap` json_script. `initSentry` reads that DOM node
 * DIRECTLY (rather than `useBootstrap`, a hook — it runs before
 * `createRoot`). `import.meta.env.VITE_SENTRY_DSN` overrides the
 * rendered DSN for playbook parity; with neither present the SDK
 * stays uninitialized and every capture call is a no-op.
 */

interface SentryBootstrap {
  dsn?: string;
  environment?: string;
  release?: string | null;
}

interface BootstrapPayload {
  sentry?: SentryBootstrap;
}

function readBootstrap(): BootstrapPayload {
  const el = document.getElementById('spa-bootstrap');
  if (!el || !el.textContent) return {};
  try {
    return JSON.parse(el.textContent) as BootstrapPayload;
  } catch {
    return {};
  }
}

// Stale tabs after a deploy fail chunk/CSS loads; these surface
// both as exceptions AND as message-only window.onerror events
// (no exception object), so the match covers `event.message` and
// the first exception value. ResizeObserver loop errors are a
// benign browser quirk.
const DROP_MESSAGE_PATTERNS = [
  /ChunkLoadError/,
  /Loading chunk \d+ failed/,
  /Loading CSS chunk/,
  /ResizeObserver loop/,
];

// TypeError network failures ("Failed to fetch", Firefox's
// "NetworkError when attempting to fetch resource", Safari's
// "Load failed") are connectivity conditions, not render bugs —
// kept, but tagged errorKind:network so they can be filtered out
// of the agent-fixable query.
const NETWORK_ERROR_PATTERN =
  /failed to fetch|networkerror|load failed/i;

function exceptionValue(event: ErrorEvent): string {
  return event.exception?.values?.[0]?.value ?? '';
}

function isNetworkTypeError(event: ErrorEvent, err: unknown): boolean {
  const type = event.exception?.values?.[0]?.type;
  const message = exceptionValue(event);
  const errMessage = err instanceof Error ? err.message : '';
  return (
    type === 'TypeError' &&
    (NETWORK_ERROR_PATTERN.test(message) ||
      NETWORK_ERROR_PATTERN.test(errMessage))
  );
}

/**
 * `beforeSend` filter for `Sentry.init`. Drops routine noise so
 * it does not burn event quota:
 *
 * - AbortError: fetch cancellation (navigation races, superseded
 *   requests) — real aborts are DOMExceptions, which are not
 *   Error subclasses, so both are checked. Filtered upstream in
 *   errorReporter too; kept here as belt-and-suspenders.
 * - Chunk/CSS load failures and ResizeObserver loops (see
 *   DROP_MESSAGE_PATTERNS).
 * Network TypeErrors are tagged errorKind:network, not dropped.
 */
export function sentryBeforeSend(
  event: ErrorEvent,
  hint: EventHint
): ErrorEvent | null {
  const err = hint.originalException;
  if (
    (err instanceof Error || err instanceof DOMException) &&
    err.name === 'AbortError'
  ) {
    return null;
  }
  const haystack = `${event.message ?? ''}\n${exceptionValue(event)}`;
  if (DROP_MESSAGE_PATTERNS.some((p) => p.test(haystack))) {
    return null;
  }
  if (isNetworkTypeError(event, err)) {
    event.tags = { ...event.tags, errorKind: 'network' };
    return event;
  }
  // Sentry's GlobalHandlers integration captures unhandled
  // rejections before this app's tagged captureException — which
  // Dedupe then drops, taking the `context` tag with it. Re-apply
  // the tag on the surviving event.
  const mechanism =
    event.exception?.values?.[0]?.mechanism?.type;
  if (
    mechanism === 'onunhandledrejection' &&
    event.tags?.context === undefined
  ) {
    event.tags = {
      ...event.tags,
      context: 'Unhandled promise rejection',
    };
  }
  return event;
}

/**
 * Initialize the browser SDK from the spa-bootstrap payload.
 * Safe to call in every entry — a missing/empty DSN leaves the
 * SDK uninitialized (tests, local dev, pre-secret deploys).
 */
export function initSentry(): void {
  const envDsn = import.meta.env.VITE_SENTRY_DSN as
    | string
    | undefined;
  const sentry = readBootstrap().sentry ?? {};
  const dsn = envDsn || sentry.dsn;
  if (!dsn) return;
  Sentry.init({
    dsn,
    environment: sentry.environment || import.meta.env.MODE,
    release: sentry.release || undefined,
    integrations: [
      Sentry.browserTracingIntegration(),
      // Free tier ~= 50 replays/mo: record only sessions that hit
      // an error (0 ambient sampling, 1.0 on-error). Text and
      // media are masked — page content is user-facing data.
      Sentry.replayIntegration({
        maskAllText: true,
        blockAllMedia: true,
      }),
    ],
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 1.0,
    // The SPA is same-origin with /api/ — propagate trace headers
    // only to our own origin.
    tracePropagationTargets: [location.origin],
    tracesSampleRate: 0.1,
    beforeSend: sentryBeforeSend,
  });
}
