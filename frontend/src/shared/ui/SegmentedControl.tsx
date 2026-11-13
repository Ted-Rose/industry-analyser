import { ReactNode } from 'react';
import { cx } from '../cx';

export interface SegmentedOption<T extends string = string> {
  value: T;
  label: ReactNode;
}

export interface SegmentedControlProps<
  T extends string = string,
> {
  value: T;
  onChange: (value: T) => void;
  options: SegmentedOption<T>[];
  /** Accessible group name. */
  ariaLabel: string;
  className?: string;
}

/**
 * Joined radio-strip — plan §6 `ui/SegmentedControl`. A real
 * radiogroup (role + aria-checked) for persistent selections.
 * NOT for one-shot actions (receipts presets stay Buttons) or
 * where tests expect links (RentVsBuy kind/group strips).
 */
export function SegmentedControl<T extends string = string>({
  value,
  onChange,
  options,
  ariaLabel,
  className,
}: SegmentedControlProps<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cx(
        'inline-flex items-center gap-0.5 rounded-md border ' +
          'border-border bg-surface-2 p-0.5',
        className,
      )}
    >
      {options.map((option) => {
        const checked = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={checked}
            onClick={() => onChange(option.value)}
            className={cx(
              'inline-flex items-center gap-1.5 rounded-sm px-3 ' +
                'py-1 text-sm font-medium transition-colors ' +
                'motion-safe:duration-120 ease-ia',
              checked
                ? 'bg-surface text-fg shadow-xs'
                : 'text-fg-muted hover:text-fg',
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export default SegmentedControl;
