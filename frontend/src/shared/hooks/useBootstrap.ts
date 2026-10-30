import { useMemo } from 'react';

/**
 * Payload rendered by `spa_shell.html` via
 * `{{ bootstrap|json_script:"spa-bootstrap" }}`. Views pass at least
 * `user` (null when anonymous); app-specific keys may be added by the
 * shell view later.
 */
export interface BootstrapPayload {
  user?: string | null;
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
