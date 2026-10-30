/**
 * `?next=` handling for the auth pages — the 401 handshake's
 * login_url carries the SPA page the user came from
 * (`/accounts/login/?next=<spa_url>`). Only a same-origin
 * pathname is a legal redirect target: anything that doesn't
 * start with a single '/' falls back to '/' — the open-redirect
 * guard (`//evil.com`, `https://…`, `javascript:…` all miss).
 */
export function safeNext(search: string): string {
  const next = new URLSearchParams(search).get('next');
  if (next && /^\/(?!\/)/.test(next)) return next;
  return '/';
}

/** Full-page navigation — extracted so tests can observe it. */
export function navigate(url: string): void {
  window.location.assign(url);
}
