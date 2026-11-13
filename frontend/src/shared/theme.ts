/**
 * Theme helpers — plan §4.3.
 *
 * localStorage['theme'] holds 'auto' | 'light' | 'dark' — the same
 * key and values Django 5.2 admin uses, so one preference covers
 * the SPAs, landing, news and admin. `class="dark"` on <html> is
 * the resolved mode; `data-theme="<stored>"` keeps the admin
 * toggle in agreement. The no-flash bootstrap lives in
 * `_theme_head.html`; Django-rendered pages get the same
 * behaviour from the dependency-free `theme-toggle.js` static
 * file — keep the semantics here in sync with both.
 */

export type Theme = 'auto' | 'light' | 'dark';

export const THEME_STORAGE_KEY = 'theme';
export const THEME_ORDER: readonly Theme[] = [
  'auto',
  'light',
  'dark',
];

const DARK_QUERY = '(prefers-color-scheme: dark)';

/* Same-tab theme-change notification — `storage` events don't
   fire in the tab that wrote localStorage, so setTheme()
   dispatches this for subscribers (ThemeToggle's label/icon). */
const THEME_EVENT = 'ia-theme-change';

/* theme-color metas (emitted by _theme_head.html): #ffffff
   light, #18181b dark (plan §4.2). */
const THEME_COLORS: Record<'light' | 'dark', string> = {
  light: '#ffffff',
  dark: '#18181b',
};

function isTheme(value: string | null): value is Theme {
  return value === 'auto' || value === 'light' || value === 'dark';
}

/** The stored preference — 'auto' when unset or unreadable. */
export function getTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(stored) ? stored : 'auto';
  } catch {
    return 'auto';
  }
}

/** Whether `theme` resolves to dark right now. */
export function isDark(theme: Theme = getTheme()): boolean {
  return (
    theme === 'dark' ||
    (theme === 'auto' && window.matchMedia(DARK_QUERY).matches)
  );
}

/**
 * Point the dual theme-color metas at the resolved scheme.
 * 'auto' restores the media-gated pair so the browser chrome
 * keeps following the OS; an explicit pick pins the first meta
 * to the chosen color and disables the rest.
 */
function syncThemeColorMetas(theme: Theme, dark: boolean): void {
  const metas = document.querySelectorAll<HTMLMetaElement>(
    'meta[name="theme-color"]',
  );
  metas.forEach((meta, i) => {
    if (theme === 'auto') {
      const scheme = i === 0 ? 'light' : 'dark';
      meta.media = `(prefers-color-scheme: ${scheme})`;
      meta.content = THEME_COLORS[scheme];
    } else {
      meta.content = dark ? THEME_COLORS.dark : THEME_COLORS.light;
      meta.media = i === 0 ? 'all' : 'not all';
    }
  });
}

/** Apply `theme` to <html> (class, data-theme, theme-color). */
export function applyTheme(theme: Theme): void {
  const dark = isDark(theme);
  const root = document.documentElement;
  root.classList.toggle('dark', dark);
  root.dataset.theme = theme;
  syncThemeColorMetas(theme, dark);
}

/** Persist `theme` and apply it. */
export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* Storage can be unavailable (private mode) — apply anyway. */
  }
  applyTheme(theme);
  window.dispatchEvent(new Event(THEME_EVENT));
}

/**
 * Subscribe to stored-theme changes from any source — same-tab
 * setTheme()/cycleTheme() calls (via THEME_EVENT) and cross-tab
 * writes like the Django admin toggle (via `storage`). Returns
 * an unsubscribe function; pairs with useSyncExternalStore.
 */
export function subscribeTheme(
  listener: (theme: Theme) => void,
): () => void {
  const notify = () => listener(getTheme());
  const onStorage = (event: StorageEvent) => {
    if (event.key === THEME_STORAGE_KEY || event.key === null) {
      notify();
    }
  };
  window.addEventListener(THEME_EVENT, notify);
  window.addEventListener('storage', onStorage);
  return () => {
    window.removeEventListener(THEME_EVENT, notify);
    window.removeEventListener('storage', onStorage);
  };
}

/** Cycle auto → light → dark, the ThemeToggle behaviour. */
export function cycleTheme(): Theme {
  const next =
    THEME_ORDER[(THEME_ORDER.indexOf(getTheme()) + 1) %
      THEME_ORDER.length];
  setTheme(next);
  return next;
}

/**
 * Apply the stored theme and keep it in sync: re-resolve while
 * 'auto' when the OS scheme flips, and mirror `storage` events
 * across tabs (and the admin's own toggle). Returns an
 * unsubscribe function for teardown in tests.
 */
export function initTheme(): () => void {
  applyTheme(getTheme());

  const media = window.matchMedia(DARK_QUERY);
  const onMediaChange = () => {
    if (getTheme() === 'auto') applyTheme('auto');
  };
  const onStorage = (event: StorageEvent) => {
    if (event.key === THEME_STORAGE_KEY || event.key === null) {
      applyTheme(getTheme());
    }
  };

  media.addEventListener('change', onMediaChange);
  window.addEventListener('storage', onStorage);
  return () => {
    media.removeEventListener('change', onMediaChange);
    window.removeEventListener('storage', onStorage);
  };
}
