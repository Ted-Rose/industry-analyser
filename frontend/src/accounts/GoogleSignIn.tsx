import { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useBootstrap } from '../shared/hooks/useBootstrap';
import Button from '../shared/ui/Button';
import { safeNext } from './next';

/**
 * "Sign in with Google" section for the Login/Register pages —
 * a plain link (OAuth needs a top-level navigation, not an XHR)
 * to GET /google/signin/, plus an unchecked-by-default checkbox
 * that appends `tasks=1` so the same consent also grants the
 * news-digest Google Tasks scope (least privilege — the grant
 * is never implicit). `?next=` round-trips through safeNext so
 * the post-login landing stays same-origin. The whole section
 * is hidden when the bootstrap payload reports the OAuth client
 * unconfigured.
 */
export default function GoogleSignIn() {
  const { search } = useLocation();
  const bootstrap = useBootstrap();
  const [tasks, setTasks] = useState(false);

  if (!bootstrap.google_oauth_configured) return null;

  const params = new URLSearchParams({ next: safeNext(search) });
  if (tasks) params.set('tasks', '1');

  return (
    <div className="mt-4">
      <div
        className="mb-3 flex items-center gap-2 text-xs
          text-fg-muted"
      >
        <span className="h-px flex-1 bg-border" aria-hidden="true" />
        or
        <span className="h-px flex-1 bg-border" aria-hidden="true" />
      </div>
      <Button
        as="a"
        href={`/google/signin/?${params.toString()}`}
        variant="secondary"
        className="w-full"
      >
        Sign in with Google
      </Button>
      <label
        className="mt-3 flex items-center gap-2 text-sm
          text-fg-muted"
      >
        <input
          type="checkbox"
          checked={tasks}
          onChange={(e) => setTasks(e.target.checked)}
        />
        Also allow Google Tasks access (news digest)
      </label>
    </div>
  );
}
