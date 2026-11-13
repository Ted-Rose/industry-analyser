import { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { cx } from '../cx';

export type PageWidth = 'page' | 'narrow' | 'prose';

const WIDTHS: Record<PageWidth, string> = {
  page: 'max-w-(--container-page)',
  narrow: 'max-w-(--container-narrow)',
  prose: 'max-w-(--container-prose)',
};

export interface PageContainerProps {
  /** 'page' data pages, 'narrow' forms/feeds, 'prose' articles. */
  width?: PageWidth;
  children: ReactNode;
  className?: string;
}

/**
 * Centered page column — plan §5 `PageContainer`. Replaces the
 * seven hand-rolled containers (`.vacancies-page`,
 * `.feed-container`, `.dash-panel`, …).
 */
export function PageContainer({
  width = 'page',
  children,
  className,
}: PageContainerProps) {
  return (
    <div
      className={cx(
        'mx-auto w-full px-4 py-6 sm:px-6 lg:px-8',
        WIDTHS[width],
        className,
      )}
    >
      {children}
    </div>
  );
}

export interface PageHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  /** In-app back link (detail pages → list). */
  back?: { to: string; label: string };
  /** Right-aligned actions; stacks below the title under sm. */
  actions?: ReactNode;
  className?: string;
}

/**
 * Page top block — plan §5 `PageHeader`: back link, h1 (2xl
 * semibold), muted description, right-aligned actions.
 */
export function PageHeader({
  title,
  description,
  back,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <header className={cx('mb-6', className)}>
      {back && (
        <Link
          to={back.to}
          className="mb-2 inline-flex items-center gap-1
            text-sm font-medium text-fg-muted
            hover:text-accent-text"
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
          {back.label}
        </Link>
      )}
      <div className="flex flex-col gap-3 sm:flex-row
        sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold text-fg">
            {title}
          </h1>
          {description && (
            <p className="mt-1 text-sm text-fg-muted">
              {description}
            </p>
          )}
        </div>
        {actions && (
          <div className="flex shrink-0 items-center gap-2">
            {actions}
          </div>
        )}
      </div>
    </header>
  );
}

export default PageContainer;
