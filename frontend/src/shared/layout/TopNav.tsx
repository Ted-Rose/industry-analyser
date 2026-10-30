import { LogIn, LogOut } from 'lucide-react';
import { pushToast } from '../toasts';
import { getCsrfToken } from '../api/client';
import { useBootstrap } from '../hooks/useBootstrap';
import AppSwitcher from './AppSwitcher';
import NavTabs, { type NavTabItem } from '../ui/Tabs';
import ThemeToggle from '../ui/ThemeToggle';
import { cx } from '../cx';

export interface TopNavProps {
  appTitle: string;
  /** In-app sections — NavTabs inline ≥md, scrollable <md. */
  navItems?: NavTabItem[];
  className?: string;
}

/** POST the Django admin logout form via fetch, then go home. */
async function logout(): Promise<void> {
  const csrf = getCsrfToken();
  try {
    const response = await fetch('/admin/logout/', {
      method: 'POST',
      headers: csrf ? { 'X-CSRFToken': csrf } : {},
      credentials: 'same-origin',
    });
    if (!response.ok && response.status !== 0) {
      throw new Error(`status ${response.status}`);
    }
    window.location.assign('/');
  } catch (error) {
    pushToast('Log out failed — please try again.', 'danger');
  }
}

function loginHref(): string {
  const next = window.location.pathname + window.location.search;
  return `/admin/login/?next=${encodeURIComponent(next)}`;
}

/**
 * Global chrome bar — plan §5 `TopNav`: skip link, "Industry
 * Analyser" home link (full page load), AppSwitcher, NavTabs
 * (inline ≥md, scrollable strip below the bar <md), ThemeToggle
 * and the session block (username + logout POST, or Log in).
 * No tab row renders when `navItems` is empty.
 */
export function TopNav({ appTitle, navItems = [], className }: TopNavProps) {
  const { user, is_authenticated: isAuthenticated } =
    useBootstrap();

  return (
    <header className={cx('sticky top-0 z-30', className)}>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute
          focus:left-4 focus:top-3 focus:z-50 focus:rounded-md
          focus:bg-surface focus:px-3 focus:py-2 focus:text-sm
          focus:font-medium focus:text-accent-text focus:shadow-md"
      >
        Skip to content
      </a>
      <div className="border-b border-border bg-surface/80
        backdrop-blur">
        <div className="mx-auto flex h-14 w-full
          max-w-(--container-page) items-center gap-2
          px-4 sm:px-6 lg:px-8">
          <a
            href="/"
            className="shrink-0 text-sm font-semibold
              tracking-tight text-fg hover:text-accent-text"
          >
            Industry Analyser
          </a>
          <AppSwitcher appTitle={appTitle} />
          {navItems.length > 0 && (
            <NavTabs
              items={navItems}
              className="hidden min-w-0 flex-1 md:flex"
            />
          )}
          <div className="ml-auto flex shrink-0 items-center
            gap-1">
            <ThemeToggle />
            {isAuthenticated ? (
              <>
                <span className="hidden max-w-32 truncate px-1
                  text-sm text-fg-muted sm:inline">
                  {user}
                </span>
                <button
                  type="button"
                  onClick={() => void logout()}
                  className="inline-flex items-center gap-1.5
                    rounded-md px-2.5 py-1.5 text-sm font-medium
                    text-fg-muted hover:bg-surface-2 hover:text-fg"
                >
                  <LogOut className="size-4" aria-hidden="true" />
                  <span className="hidden sm:inline">Log out</span>
                </button>
              </>
            ) : (
              <a
                href={loginHref()}
                className="inline-flex items-center gap-1.5
                  rounded-md px-2.5 py-1.5 text-sm font-medium
                  text-fg-muted hover:bg-surface-2 hover:text-fg"
              >
                <LogIn className="size-4" aria-hidden="true" />
                Log in
              </a>
            )}
          </div>
        </div>
      </div>
      {navItems.length > 0 && (
        <div className="overflow-x-auto border-b border-border
          bg-surface/80 px-2 backdrop-blur md:hidden">
          <NavTabs items={navItems} />
        </div>
      )}
    </header>
  );
}

export default TopNav;
