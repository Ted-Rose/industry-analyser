import { ElementType, ReactNode } from 'react';
import { cx } from '../cx';

export interface CardProps {
  /** Element or component to render — 'div', 'a', Link, 'section'… */
  as?: ElementType;
  /** 'none' wraps DataTables/forms flush; 'md' is p-4 sm:p-5. */
  padding?: 'none' | 'md';
  /** Hover affordance for card-as-link (index grids). */
  interactive?: boolean;
  className?: string;
  children?: ReactNode;
  [key: string]: unknown;
}

/**
 * The one surface — plan §6 `ui/Card`. Replaces `.filter-card`,
 * `.feed-card`, `.spoki-article`, `.summary-card`. `as` plus
 * rest-spread lets a card be a link (`as="a" href=…`) or a
 * router Link.
 */
export function Card({
  as,
  padding = 'md',
  interactive = false,
  className,
  children,
  ...rest
}: CardProps) {
  const Component = (as ?? 'div') as ElementType;
  return (
    <Component
      className={cx(
        'rounded-lg border border-border bg-surface shadow-xs',
        padding === 'md' && 'p-4 sm:p-5',
        interactive &&
          'transition-colors motion-safe:duration-120 ease-ia ' +
            'hover:border-border-strong hover:shadow-md',
        className,
      )}
      {...rest}
    >
      {children}
    </Component>
  );
}

export interface CardHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

/** Title / description / actions row at the top of a Card. */
export function CardHeader({
  title,
  description,
  actions,
  className,
}: CardHeaderProps) {
  return (
    <div
      className={cx(
        'flex flex-wrap items-start justify-between gap-2',
        className,
      )}
    >
      <div className="min-w-0">
        <h2 className="text-lg font-medium text-fg">{title}</h2>
        {description && (
          <p className="mt-0.5 text-sm text-fg-muted">
            {description}
          </p>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 items-center gap-1">
          {actions}
        </div>
      )}
    </div>
  );
}

export default Card;
