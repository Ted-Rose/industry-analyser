/**
 * Error thrown by the API client for non-2xx responses that are not
 * auth redirects. `body` holds the parsed JSON response (or raw text)
 * so callers can inspect `{"error": ..., "detail": ...}` payloads
 * returned by the Django API.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly statusText: string;
  readonly body: unknown;

  constructor(
    message: string,
    status: number,
    statusText = '',
    body?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.statusText = statusText;
    this.body = body;
  }
}

/**
 * Best-effort human-readable message for a failed request — the
 * API's uniform error shape is `{error, detail}` plus an optional
 * `code` slug. Shared by every app's mutation hooks.
 */
export function errorDetail(error: unknown): string {
  if (error instanceof ApiError) {
    const body = error.body;
    if (body && typeof body === 'object') {
      const b = body as { detail?: unknown };
      if (typeof b.detail === 'string' && b.detail) {
        return b.detail;
      }
    }
    return error.message;
  }
  return 'Network error — check your connection and try again.';
}
