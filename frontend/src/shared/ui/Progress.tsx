import { ReactNode } from 'react';
import { cx } from '../cx';

export interface ProgressProps {
  value: number;
  max?: number;
  /** Visible label rendered beside/above the bar. */
  label?: ReactNode;
  /** Accessible name; defaults to the label's text or 'Progress'. */
  ariaLabel?: string;
  className?: string;
}

/**
 * Accessible progress bar — plan §6 `ui/Progress`. Replaces the
 * dashboard's plain-div `.progress-bar`. Track is surface-3,
 * fill accent (plan §4.2).
 */
export function Progress({
  value,
  max = 100,
  label,
  ariaLabel,
  className,
}: ProgressProps) {
  const clamped = Math.min(Math.max(value, 0), max);
  const pct = max > 0 ? (clamped / max) * 100 : 0;
  return (
    <div className={cx('min-w-0', className)}>
      <div
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-label={
          ariaLabel ??
          (typeof label === 'string' ? label : 'Progress')
        }
        className="h-2 w-full overflow-hidden rounded-full
          bg-surface-3"
      >
        <div
          className="h-full rounded-full bg-accent
            transition-[width] motion-safe:duration-260 ease-ia"
          style={{ width: `${pct}%` }}
        />
      </div>
      {label && (
        <p className="mt-1 text-xs text-fg-muted tabular-nums">
          {label}
        </p>
      )}
    </div>
  );
}

export default Progress;
