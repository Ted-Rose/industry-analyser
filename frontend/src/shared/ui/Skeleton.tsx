import { ReactNode } from 'react';
import { cx } from '../cx';

export interface SkeletonProps {
  className?: string;
}

/** Single pulse bar/block — compose into loading layouts. */
export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      className={cx(
        'rounded-md bg-surface-2 motion-safe:animate-pulse',
        className,
      )}
    />
  );
}

export type LoadingVariant = 'table' | 'cards' | 'stats';

export interface LoadingStateProps {
  variant?: LoadingVariant;
  /** Row/card count hint (defaults per variant). */
  rows?: number;
  /** Visible + sr-only label. */
  label?: ReactNode;
  className?: string;
}

/**
 * First-load placeholder — plan §6 `ui/Skeleton`/`LoadingState`.
 * Picks skeleton shapes matching the final layout so the swap
 * doesn't jump; role="status" + aria-busy for AT.
 */
export function LoadingState({
  variant = 'table',
  rows,
  label = 'Loading…',
  className,
}: LoadingStateProps) {
  const count =
    rows ?? (variant === 'stats' ? 4 : variant === 'cards' ? 3 : 5);
  return (
    <div
      role="status"
      aria-busy="true"
      className={cx('space-y-3', className)}
    >
      <span className="sr-only">{label}</span>
      {variant === 'stats' && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {Array.from({ length: count }, (_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      )}
      {variant === 'cards' &&
        Array.from({ length: count }, (_, i) => (
          <Skeleton key={i} className="h-28 w-full" />
        ))}
      {variant === 'table' && (
        <div className="rounded-lg border border-border
          bg-surface">
          <Skeleton className="m-3 h-4 w-1/3" />
          {Array.from({ length: count }, (_, i) => (
            <div
              key={i}
              className="border-t border-border px-3 py-3"
            >
              <Skeleton className="h-4 w-full" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default Skeleton;
