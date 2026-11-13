import { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { cx } from '../cx';
import { useBootstrap } from '../hooks/useBootstrap';
import Badge from '../ui/Badge';

export interface AppSwitcherProps {
  /** Current mount's title — the closed-state label. */
  appTitle: string;
  className?: string;
}

/**
 * Current app + chevron → dropdown of every SPA mount — plan §5.
 * The app list comes from the bootstrap payload's `apps` (the
 * same `_landing_entries()` list `/` renders), so new mounts
 * appear without a code change. Links are full-page `<a>` —
 * each mount is a separate SPA bundle.
 */
export function AppSwitcher({ appTitle, className }: AppSwitcherProps) {
  const { apps = [] } = useBootstrap();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (
        event.target instanceof Node &&
        !rootRef.current?.contains(event.target)
      ) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  if (apps.length === 0) return null;

  return (
    <div ref={rootRef} className={cx('relative', className)}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1.5 rounded-md
          px-2.5 py-1.5 text-sm font-medium text-fg
          hover:bg-surface-2"
      >
        <span className="max-w-40 truncate">{appTitle}</span>
        <ChevronDown
          className={cx(
            'size-4 text-fg-subtle transition-transform ' +
              'motion-safe:duration-180 ease-ia',
            open && 'rotate-180',
          )}
          aria-hidden="true"
        />
      </button>
      {open && (
        // Plain disclosure list — no menu/menuitem roles, since
        // there is no arrow-key menu navigation; ordinary tab
        // order through the links is the correct semantics.
        <ul
          className="absolute left-0 top-full z-40 mt-1
            w-64 list-none overflow-hidden rounded-lg border
            border-border bg-surface p-0 py-1 shadow-md"
        >
          {apps.map((app) => (
            <li key={app.url}>
              <a
                href={app.url}
                className="flex items-center justify-between gap-2
                  px-3 py-2 text-sm text-fg hover:bg-surface-2"
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">
                    {app.title}
                  </span>
                  {app.desc && (
                    <span className="block truncate text-xs
                      text-fg-subtle">
                      {app.desc}
                    </span>
                  )}
                </span>
                {app.login_required && (
                  <Badge variant="outline" size="sm">
                    login required
                  </Badge>
                )}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default AppSwitcher;
