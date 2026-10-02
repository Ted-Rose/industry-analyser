import { ApiError } from './errors';

/**
 * Shared fetch wrapper for the Django API.
 *
 * - Sends cookies same-origin and never follows redirects inside
 *   `fetch` (`redirect: 'manual'`) — a 302 to a login page must never
 *   be followed by XHR.
 * - Sends `X-CSRFToken` (from the `csrftoken` cookie) on unsafe
 *   methods; Django session auth enforces it.
 * - On `401` with `authorization_url` or `login_url` in the JSON body,
 *   navigates the page to that URL and returns a promise that never
 *   resolves — the browser is leaving anyway, and callers should not
 *   treat it as a normal error.
 * - Other non-2xx responses throw a typed `ApiError`.
 */

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'TRACE']);

interface AuthRedirectBody {
  authorization_url?: string;
  login_url?: string;
}

export function getCsrfToken(): string | undefined {
  const match = /(?:^|;\s*)csrftoken=([^;]*)/.exec(document.cookie);
  return match ? decodeURIComponent(match[1]) : undefined;
}

export interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  /** Object bodies are JSON-encoded automatically. */
  body?: BodyInit | Record<string, unknown> | unknown[] | null;
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function authRedirectUrl(body: unknown): string | undefined {
  if (typeof body !== 'object' || body === null) return undefined;
  const b = body as AuthRedirectBody;
  return b.authorization_url ?? b.login_url;
}

/**
 * Only plain objects and arrays get JSON-encoded. Every valid
 * `BodyInit` (FormData, Blob, ArrayBuffer + views like Uint8Array,
 * URLSearchParams, ReadableStream, strings) passes through untouched
 * so `fetch` can set the right Content-Type itself.
 */
function shouldJsonEncode(body: unknown): boolean {
  if (Array.isArray(body)) return true;
  if (typeof body !== 'object' || body === null) return false;
  const proto: unknown = Object.getPrototypeOf(body);
  return proto === Object.prototype || proto === null;
}

/** Full-page navigation — extracted so tests can observe it. */
function navigate(url: string): void {
  window.location.assign(url);
}

export async function apiFetch<T = unknown>(
  url: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const { body, headers: initHeaders, ...rest } = options;
  const method = (rest.method ?? 'GET').toUpperCase();

  const headers = new Headers(initHeaders);
  if (!SAFE_METHODS.has(method)) {
    const csrf = getCsrfToken();
    if (csrf && !headers.has('X-CSRFToken')) {
      headers.set('X-CSRFToken', csrf);
    }
  }

  let payload: BodyInit | undefined;
  if (body != null) {
    if (shouldJsonEncode(body)) {
      payload = JSON.stringify(body);
      if (!headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json');
      }
    } else {
      payload = body as BodyInit;
    }
  }

  const response = await fetch(url, {
    ...rest,
    method,
    headers,
    body: payload,
    credentials: 'same-origin',
    redirect: 'manual',
  });

  // With `redirect: 'manual'` a 30x response comes back as an
  // opaque-redirect stub (status 0, empty body) — session expiry on
  // non-ninja endpoints (@login_required → 302 to /admin/login/),
  // APPEND_SLASH redirects, middleware redirects. Treat it like the
  // auth path: bounce the browser to login instead of throwing a
  // meaningless status-0 ApiError.
  if (response.type === 'opaqueredirect' || response.status === 0) {
    const next = window.location.pathname + window.location.search;
    navigate(`/admin/login/?next=${encodeURIComponent(next)}`);
    return new Promise<T>(() => {});
  }

  const parsed = await parseBody(response);

  if (response.status === 401) {
    const target = authRedirectUrl(parsed);
    if (target) {
      navigate(target);
      // The browser is leaving the page — don't let callers continue
      // as if the request failed normally.
      return new Promise<T>(() => {});
    }
  }

  if (!response.ok) {
    throw new ApiError(
      `Request failed: ${response.status} ${response.statusText}`,
      response.status,
      response.statusText,
      parsed,
    );
  }

  return parsed as T;
}

export function apiGet<T = unknown>(url: string): Promise<T> {
  return apiFetch<T>(url);
}

export function apiPost<T = unknown>(
  url: string,
  body?: ApiRequestOptions['body'],
): Promise<T> {
  return apiFetch<T>(url, { method: 'POST', body });
}

export function apiPut<T = unknown>(
  url: string,
  body?: ApiRequestOptions['body'],
): Promise<T> {
  return apiFetch<T>(url, { method: 'PUT', body });
}

export function apiPatch<T = unknown>(
  url: string,
  body?: ApiRequestOptions['body'],
): Promise<T> {
  return apiFetch<T>(url, { method: 'PATCH', body });
}

export function apiDelete<T = unknown>(url: string): Promise<T> {
  return apiFetch<T>(url, { method: 'DELETE' });
}
