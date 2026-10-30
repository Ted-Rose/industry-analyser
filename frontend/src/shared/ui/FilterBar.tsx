import {
  FormEvent,
  ReactNode,
  useId,
  useState,
} from 'react';
import { SlidersHorizontal } from 'lucide-react';
import { cx } from '../cx';
import Button from './Button';

export type FilterBarCollapsible = 'mobile' | 'always' | false;

export interface FilterBarProps {
  /** Called after preventDefault — apply draft state to the URL. */
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  /** When set, renders a ghost Reset button. */
  onReset?: () => void;
  /** Count of user-set URL params — shown on the toggle. */
  activeCount?: number;
  /**
   * 'mobile': collapse behind a "Filters (n)" toggle below md
   * (always open ≥md). 'always': toggle at every width.
   * false (default): never collapsible.
   */
  collapsible?: FilterBarCollapsible;
  /** Extra buttons after Apply/Reset (receipts presets). */
  actions?: ReactNode;
  submitLabel?: string;
  resetLabel?: string;
  toggleLabel?: string;
  children: ReactNode;
  className?: string;
}

/**
 * The one filter form — plan §6 `ui/FilterBar`. Replaces
 * `.filter-card` / `.filter-form` / row-col grids. role="search"
 * gives it a landmark; children lay out on a responsive
 * 1/2/4-column grid that wraps to as many rows as needed.
 */
export function FilterBar({
  onSubmit,
  onReset,
  activeCount = 0,
  collapsible = false,
  actions,
  submitLabel = 'Apply',
  resetLabel = 'Reset',
  toggleLabel = 'Filters',
  children,
  className,
}: FilterBarProps) {
  const regionId = useId();
  const [open, setOpen] = useState(false);
  const collapses = collapsible !== false;
  const mobileOnly = collapsible === 'mobile';

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit(event);
  };

  const countBadge =
    activeCount > 0 ? ` (${activeCount})` : '';

  return (
    <form
      role="search"
      aria-label="Filters"
      onSubmit={handleSubmit}
      className={cx(
        'rounded-lg border border-border bg-surface p-4 shadow-xs',
        className,
      )}
    >
      {collapses && (
        <button
          type="button"
          aria-expanded={open}
          aria-controls={regionId}
          onClick={() => setOpen((value) => !value)}
          className={cx(
            'inline-flex items-center gap-2 rounded-md px-2 py-1.5 ' +
              'text-sm font-medium text-fg-muted hover:bg-surface-2 ' +
              'hover:text-fg',
            mobileOnly && 'md:hidden',
          )}
        >
          <SlidersHorizontal className="size-4" aria-hidden="true" />
          {`${toggleLabel}${countBadge}`}
        </button>
      )}
      <div
        id={regionId}
        className={cx(
          'grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4',
          collapses && 'mt-3',
          // Never emit `grid` and `hidden` together — the winner
          // would depend on stylesheet order. mobileOnly keeps the
          // region open ≥md via the md:grid override.
          collapses && !open ? 'hidden' : 'grid',
          mobileOnly && 'md:grid',
        )}
      >
        {children}
        <div
          className="flex items-end gap-2 sm:col-span-2
            lg:col-span-4"
        >
          <Button type="submit">{submitLabel}</Button>
          {onReset && (
            <Button
              type="button"
              variant="ghost"
              onClick={onReset}
            >
              {resetLabel}
            </Button>
          )}
          {actions}
        </div>
      </div>
    </form>
  );
}

export default FilterBar;
