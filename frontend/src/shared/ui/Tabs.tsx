import { KeyboardEvent, ReactNode, useRef } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { cx } from '../cx';

export interface NavTabItem {
  /** Route path — NavLink `to`. */
  to: string;
  label: ReactNode;
  /** NavLink `end` — exact-match for index routes. */
  end?: boolean;
  /**
   * Extra pathnames that also mark this tab active — a section
   * tab covering several sibling routes (the Reports tab on
   * /daily-sightings AND /rent-vs-buy).
   */
  activePaths?: string[];
}

export interface NavTabsProps {
  items: NavTabItem[];
  /** Accessible name for the nav landmark. */
  ariaLabel?: string;
  className?: string;
}

const TAB_LINK =
  'inline-flex items-center whitespace-nowrap border-b-2 ' +
  'px-3 py-2 text-sm font-medium transition-colors ' +
  'motion-safe:duration-120 ease-ia';

/**
 * In-app tab row bound to the router — plan §6 `NavTabs`.
 * Replaces vacancies' header buttons and classified_ads'
 * section links. The TopNav renders it ≥md inline and <md as
 * a scrollable strip.
 */
export function NavTabs({
  items,
  ariaLabel = 'Sections',
  className,
}: NavTabsProps) {
  const { pathname } = useLocation();
  if (items.length === 0) return null;
  return (
    <nav aria-label={ariaLabel} className={className}>
      <div className="flex gap-1">
        {items.map((item) => {
          const extraActive = item.activePaths?.some(
            (path) =>
              pathname === path ||
              pathname.startsWith(`${path}/`),
          );
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cx(
                  TAB_LINK,
                  isActive || extraActive
                    ? 'border-accent text-fg'
                    : 'border-transparent text-fg-muted ' +
                      'hover:border-border-strong hover:text-fg',
                )
              }
            >
              {item.label}
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}

export interface TabItem {
  id: string;
  label: ReactNode;
  disabled?: boolean;
}

export interface TabsProps {
  tabs: TabItem[];
  /** id of the selected tab. */
  active: string;
  onChange: (id: string) => void;
  ariaLabel?: string;
  className?: string;
}

/**
 * Non-router tab strip — plan §6 `Tabs` (role="tablist").
 * Roving tabindex + arrow-key navigation; the caller renders
 * the active tab's panel underneath.
 */
export function Tabs({
  tabs,
  active,
  onChange,
  ariaLabel,
  className,
}: TabsProps) {
  const listRef = useRef<HTMLDivElement>(null);

  const move = (event: KeyboardEvent, delta: number) => {
    const enabled = tabs.filter((tab) => !tab.disabled);
    const index = enabled.findIndex((tab) => tab.id === active);
    const next =
      enabled[(index + delta + enabled.length) % enabled.length];
    if (!next) return;
    onChange(next.id);
    listRef.current
      ?.querySelector<HTMLElement>(`[data-tab-id="${next.id}"]`)
      ?.focus();
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      move(event, 1);
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      move(event, -1);
    }
  };

  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={cx('flex gap-1 border-b border-border', className)}
    >
      {tabs.map((tab) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            data-tab-id={tab.id}
            aria-selected={selected}
            disabled={tab.disabled}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            className={cx(
              TAB_LINK,
              '-mb-px disabled:cursor-not-allowed ' +
                'disabled:opacity-50',
              selected
                ? 'border-accent text-fg'
                : 'border-transparent text-fg-muted ' +
                  'hover:border-border-strong hover:text-fg',
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

export default NavTabs;
