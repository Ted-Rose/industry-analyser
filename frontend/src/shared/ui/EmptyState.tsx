import { ReactNode } from 'react';
import { Inbox } from 'lucide-react';
import { cx } from '../cx';

export interface EmptyStateProps {
  /** lucide icon (or any node); defaults to Inbox. */
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  /** e.g. a "Clear filters" Button. */
  action?: ReactNode;
  className?: string;
}

/**
 * Centered empty state — plan §6 `ui/EmptyState`. Replaces every
 * "No …" text row and muted colSpan cell.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cx(
        'flex flex-col items-center gap-2 px-4 py-10 text-center',
        className,
      )}
    >
      <span className="text-fg-subtle" aria-hidden="true">
        {icon ?? <Inbox className="size-8" />}
      </span>
      <p className="text-sm font-medium text-fg">{title}</p>
      {description && (
        <p className="max-w-md text-sm text-fg-muted">
          {description}
        </p>
      )}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

export default EmptyState;
