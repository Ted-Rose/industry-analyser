import { ReactNode, useId, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { cx } from '../cx';
import Checkbox from './Checkbox';

export interface CheckboxListOption {
  value: string;
  label: ReactNode;
}

export interface CheckboxListProps {
  options: CheckboxListOption[];
  /** Currently checked values. */
  value: string[];
  onChange: (next: string[]) => void;
  /** CSS max-height for the scroll region (default 12rem). */
  maxHeight?: string;
  /** Adds a filter input above the options. */
  searchable?: boolean;
  /** Placeholder for the search input. */
  searchPlaceholder?: string;
  /** Accessible group name for the fieldset. */
  legend?: string;
  className?: string;
}

/**
 * Scrollable multi-select list — plan §6 `ui/CheckboxList`.
 * Replaces `.checkbox-scroll-list` x4 and `.region-checkbox-list`.
 * Optional search narrows the rendered options; the "n selected"
 * counter always reflects the full `value`, not the filter.
 */
export function CheckboxList({
  options,
  value,
  onChange,
  maxHeight = '12rem',
  searchable = false,
  searchPlaceholder = 'Search…',
  legend,
  className,
}: CheckboxListProps) {
  const searchId = useId();
  const [query, setQuery] = useState('');
  const selected = useMemo(() => new Set(value), [value]);
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((option) =>
      // String(option.label) on a ReactNode yields
      // "[object Object]" — match node labels by value instead.
      (typeof option.label === 'string'
        ? option.label
        : option.value
      )
        .toLowerCase()
        .includes(q),
    );
  }, [options, query]);

  const toggle = (optionValue: string, checked: boolean) => {
    const next = new Set(selected);
    if (checked) {
      next.add(optionValue);
    } else {
      next.delete(optionValue);
    }
    // Preserve the original option order in the emitted value.
    onChange(
      options
        .map((option) => option.value)
        .filter((optionValue2) => next.has(optionValue2)),
    );
  };

  return (
    <fieldset className={cx('min-w-0', className)}>
      {legend && <legend className="sr-only">{legend}</legend>}
      <div className="rounded-md border border-border bg-surface">
        {searchable && (
          <div className="relative border-b border-border">
            <Search
              className="pointer-events-none absolute left-2.5
                top-1/2 size-4 -translate-y-1/2 text-fg-subtle"
              aria-hidden="true"
            />
            <input
              id={searchId}
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={searchPlaceholder}
              aria-label={searchPlaceholder}
              className="w-full bg-transparent py-2 pl-8 pr-3
                text-lg sm:text-sm text-fg
                placeholder:text-fg-subtle"
            />
          </div>
        )}
        <div
          className="space-y-1 overflow-y-auto p-2"
          style={{ maxHeight }}
        >
          {visible.map((option) => (
            <Checkbox
              key={option.value}
              label={option.label}
              checked={selected.has(option.value)}
              onChange={(event) =>
                toggle(option.value, event.target.checked)
              }
            />
          ))}
          {visible.length === 0 && (
            <p className="px-1 py-2 text-sm text-fg-subtle">
              No matches.
            </p>
          )}
        </div>
        <p className="border-t border-border px-3 py-1.5
          text-xs text-fg-subtle tabular-nums">
          {value.length} selected
        </p>
      </div>
    </fieldset>
  );
}

export default CheckboxList;
