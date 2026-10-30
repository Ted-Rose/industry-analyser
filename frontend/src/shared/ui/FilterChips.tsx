import type { ReactNode } from 'react';
import { X } from 'lucide-react';
import { cx } from '../cx';

export interface FilterChip {
  /** Chip text — e.g. 'Channel: LTV1'. */
  label: ReactNode;
  onRemove: () => void;
}

export interface FilterChipsProps {
  chips: FilterChip[];
  /** When set, renders a "Clear all" action after the chips. */
  onClearAll?: () => void;
  className?: string;
}

/**
 * Applied-filter chips row — plan §6 `ui/FilterChips`. Sits under
 * a collapsed FilterBar so active filters stay visible when the
 * form is closed.
 */
export function FilterChips({
  chips,
  onClearAll,
  className,
}: FilterChipsProps) {
  if (chips.length === 0) return null;
  return (
    <div
      className={cx('flex flex-wrap items-center gap-1.5', className)}
    >
      {chips.map((chip, index) => (
        <span
          key={index}
          className="inline-flex items-center gap-1 rounded-full
            bg-accent-subtle py-0.5 pl-2.5 pr-1 text-xs
            text-accent-text"
        >
          {chip.label}
          <button
            type="button"
            aria-label={
              typeof chip.label === 'string'
                ? `Remove filter: ${chip.label}`
                : 'Remove filter'
            }
            onClick={chip.onRemove}
            // size-10 + -m-2.5: a 40px hit area (plan §4.5)
            // that still lays out as the old size-5 glyph.
            className="inline-flex size-10 -m-2.5 items-center
              justify-center rounded-full hover:bg-accent/20"
          >
            <X className="size-3" aria-hidden="true" />
          </button>
        </span>
      ))}
      {onClearAll && (
        <button
          type="button"
          onClick={onClearAll}
          // min-h-10 + -my-2.5: 40px vertical hit area without
          // stretching the chip row.
          className="inline-flex min-h-10 -my-2.5 items-center
            px-1.5 text-xs font-medium text-fg-muted
            hover:text-fg"
        >
          Clear all
        </button>
      )}
    </div>
  );
}

export default FilterChips;
