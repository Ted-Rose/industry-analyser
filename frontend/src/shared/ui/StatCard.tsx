import { ReactNode } from 'react';
import { cx } from '../cx';
import Card from './Card';

export type StatTone =
  | 'default'
  | 'success'
  | 'warning'
  | 'danger'
  | 'info';

const VALUE_TONES: Record<StatTone, string> = {
  default: 'text-fg',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  info: 'text-info',
};

export interface StatCardProps {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: StatTone;
  className?: string;
}

/**
 * Single KPI card — plan §6 `ui/StatCard`. Replaces
 * `.summary-value` and receipts' `.summary .card`. The value is
 * 2xl semibold tabular-nums per the type scale.
 */
export function StatCard({
  label,
  value,
  hint,
  tone = 'default',
  className,
}: StatCardProps) {
  return (
    <Card className={className}>
      <p className="text-sm text-fg-muted">{label}</p>
      <p
        className={cx(
          'mt-1 text-2xl font-semibold tabular-nums',
          VALUE_TONES[tone],
        )}
      >
        {value}
      </p>
      {hint && (
        <p className="mt-1 text-xs text-fg-subtle">{hint}</p>
      )}
    </Card>
  );
}

export interface StatGridProps {
  children: ReactNode;
  className?: string;
}

/** grid-cols-2 md:grid-cols-4 row of StatCards. */
export function StatGrid({ children, className }: StatGridProps) {
  return (
    <div
      className={cx(
        'grid grid-cols-2 gap-3 md:grid-cols-4 sm:gap-4',
        className,
      )}
    >
      {children}
    </div>
  );
}

export default StatCard;
