import { ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import { cx } from '../cx';

export interface DisclosureProps {
  /** The always-visible <summary> content. */
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  /**
   * 'block' wraps the body in a padded bordered region
   * (tv airings); 'default' is a bare inline collapse.
   */
  variant?: 'default' | 'block';
  className?: string;
}

/**
 * Styled <details> + chevron — plan §6 `ui/Disclosure`.
 * Replaces receipts' `.cat` grid and tv's airings collapse.
 */
export function Disclosure({
  summary,
  children,
  defaultOpen = false,
  variant = 'default',
  className,
}: DisclosureProps) {
  return (
    <details
      open={defaultOpen || undefined}
      className={cx('group', className)}
    >
      <summary
        className="flex cursor-pointer list-none items-center
          gap-2 rounded-md px-1 py-1.5 text-sm font-medium
          text-fg hover:bg-surface-2
          [&::-webkit-details-marker]:hidden"
      >
        <ChevronRight
          className="size-4 shrink-0 text-fg-subtle
            transition-transform motion-safe:duration-180
            ease-ia group-open:rotate-90"
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1">{summary}</span>
      </summary>
      <div
        className={cx(
          variant === 'block' &&
            'ml-6 mt-1 rounded-md border border-border ' +
              'bg-surface-2 p-3',
          variant === 'default' && 'ml-6 mt-1',
        )}
      >
        {children}
      </div>
    </details>
  );
}

export default Disclosure;
