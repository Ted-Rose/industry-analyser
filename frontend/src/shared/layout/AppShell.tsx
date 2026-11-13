import { ReactNode, useEffect } from 'react';
import { initTheme } from '../theme';
import Toasts from '../components/Toasts';
import TopNav from './TopNav';
import type { NavTabItem } from '../ui/Tabs';

export interface AppShellProps {
  /** Current mount's name — AppSwitcher's closed label. */
  appTitle: string;
  /**
   * In-app sections for NavTabs. Empty/omitted renders no tab
   * row at all (dashboard, receipts).
   */
  navItems?: NavTabItem[];
  children: ReactNode;
}

/**
 * The SPA frame — plan §5 `AppShell`: sticky TopNav +
 * <main id="main"> + <Toasts/>. Mount once per SPA in App.tsx
 * around <Routes>; apps that adopt it drop their own Toasts
 * mount and nav markup.
 *
 * Also owns initTheme() — the no-flash script in
 * _theme_head.html paints the first frame, and this wires the
 * live 'auto' follow + cross-tab sync afterwards (PR-1 review
 * flagged it as previously unwired).
 */
export function AppShell({
  appTitle,
  navItems,
  children,
}: AppShellProps) {
  useEffect(() => initTheme(), []);

  return (
    <>
      <TopNav appTitle={appTitle} navItems={navItems} />
      <main id="main" tabIndex={-1}>
        {children}
      </main>
      <Toasts />
    </>
  );
}

export default AppShell;
