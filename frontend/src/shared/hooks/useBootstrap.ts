import { useMemo } from 'react';

/**
 * One app mount as discovered by `views._landing_entries()` —
 * the same list the / landing page renders. Shipped in the
 * spa-bootstrap payload so the shell TopNav's AppSwitcher never
 * hardcodes the app list.
 */
export interface BootstrapAppEntry {
  url: string;
  title: string;
  desc: string;
  cta: boolean;
  login_required: boolean;
}

/**
 * Payload rendered by `spa_shell.html` via
 * `{{ bootstrap|json_script:"spa-bootstrap" }}`. Views pass at
 * least `user` (null when anonymous), `apps`, `is_staff` and
 * `is_authenticated`; app-specific keys may be added by the
 * shell view later.
 */
export interface BootstrapPayload {
  user?: string | null;
  /** The auto-discovered app mounts — the same list the /
   *  landing page renders. The shell TopNav builds its
   *  AppSwitcher off this instead of a hardcoded list. */
  apps?: BootstrapAppEntry[];
  /** Session flags the shell injects on every render — anonymous
   *  pages carry false for both. Optional so older shells and
   *  tests that stub the payload don't have to set them. */
  is_authenticated?: boolean;
  is_staff?: boolean;
  [key: string]: unknown;
}

/** Reads the `#spa-bootstrap` json_script payload once. */
export function useBootstrap(): BootstrapPayload {
  return useMemo(() => {
    const el = document.getElementById('spa-bootstrap');
    if (!el || !el.textContent) return {};
    try {
      return JSON.parse(el.textContent) as BootstrapPayload;
    } catch {
      return {};
    }
  }, []);
}

export default useBootstrap;
