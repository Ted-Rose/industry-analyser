/**
 * `?next=` handling for the auth pages — the 401 handshake's
 * login_url carries the SPA page the user came from
 * (`/accounts/login/?next=<spa_url>`). Only a same-origin
 * pathname is a legal redirect target: the candidate must start
 * with '/' AND parse to this origin. Parsing matters — a bare
 * regex on the string misses WHATWG-parser quirks: backslashes
 * normalize to '/' for special schemes (`/\evil.example`
 * resolves as `//evil.example`) and tab/newline bytes are
 * stripped mid-string (`/<TAB>/evil.example` → same). The
 * origin check catches both (`https://…`, `javascript:…` and
 * `//evil.com` also miss).
 */
export function safeNext(search: string): string {
  const next = new URLSearchParams(search).get('next');
  if (!next || !next.startsWith('/')) return '/';
  try {
    const parsed = new URL(next, window.location.origin);
    if (parsed.origin === window.location.origin) return next;
  } catch {
    // Unparsable remainder (e.g. `//` or `/`) — fail closed.
  }
  return '/';
}

/** Full-page navigation — extracted so tests can observe it. */
export function navigate(url: string): void {
  window.location.assign(url);
}
