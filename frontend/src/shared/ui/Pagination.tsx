import { ReactNode } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cx } from '../cx';
import { usePageParam } from '../hooks/usePageParam';

export interface PaginationProps {
  page: number;
  numPages: number;
  /**
   * Called with the next page. Defaults to writing the `page`
   * search param via usePageParam.
   */
  onPageChange?: (page: number) => void;
  /** Right-hand ≥sm summary line ("Showing 1–50 of 1,284"). */
  summary?: ReactNode;
  className?: string;
}

// ≥40px touch targets below sm (the compact ‹ n / m › strip is
// the mobile control); ≥sm keeps the compact h-8/min-w-8 sizing
// only on fine pointers — touch devices keep ≥40px at any width.
const BTN =
  'inline-flex h-10 min-w-10 items-center justify-center ' +
  'rounded-md border border-border px-2 text-sm tabular-nums ' +
  'transition-colors motion-safe:duration-120 ease-ia ' +
  'disabled:cursor-not-allowed disabled:opacity-40 ' +
  'enabled:hover:bg-surface-2 ' +
  'sm:pointer-fine:h-8 sm:pointer-fine:min-w-8';

/**
 * The one pagination — plan §6 `ui/Pagination`. ‹ › plus a
 * ±2 numbered window ≥sm; a compact ‹ "n / m" › strip below
 * sm. No « » (ruling §8.13). Renders nothing for a single page.
 */
export function Pagination({
  page,
  numPages,
  onPageChange,
  summary,
  className,
}: PaginationProps) {
  const [, setPageParam] = usePageParam();
  if (numPages <= 1) return null;
  const go = onPageChange ?? setPageParam;

  const windowPages: number[] = [];
  for (let n = page - 2; n <= page + 2; n += 1) {
    if (n >= 1 && n <= numPages) windowPages.push(n);
  }

  const prev = (
    <button
      type="button"
      className={BTN}
      aria-label="Previous page"
      disabled={page <= 1}
      onClick={() => go(page - 1)}
    >
      <ChevronLeft className="size-4" aria-hidden="true" />
    </button>
  );
  const next = (
    <button
      type="button"
      className={BTN}
      aria-label="Next page"
      disabled={page >= numPages}
      onClick={() => go(page + 1)}
    >
      <ChevronRight className="size-4" aria-hidden="true" />
    </button>
  );

  return (
    <div
      className={cx(
        'flex flex-col items-center gap-2 sm:flex-row',
        summary ? 'sm:justify-between' : 'sm:justify-end',
        className,
      )}
    >
      {summary && (
        <p className="order-2 text-sm text-fg-muted
          tabular-nums sm:order-1">
          {summary}
        </p>
      )}
      <nav
        aria-label="Page navigation"
        className="order-1 sm:order-2"
      >
        {/* Compact: ‹ n / m › */}
        <div className="flex items-center gap-2 sm:hidden">
          {prev}
          <span className="text-sm text-fg-muted tabular-nums">
            {page} / {numPages}
          </span>
          {next}
        </div>
        {/* Full: ‹ ±2 numbered › */}
        <div className="hidden items-center gap-1 sm:flex">
          {prev}
          {windowPages.map((n) =>
            n === page ? (
              <span
                key={n}
                aria-current="page"
                className={cx(
                  BTN,
                  'border-accent bg-accent-subtle ' +
                    'font-medium text-accent-text',
                )}
              >
                {n}
              </span>
            ) : (
              <button
                key={n}
                type="button"
                className={BTN}
                aria-label={`Page ${n}`}
                onClick={() => go(n)}
              >
                {n}
              </button>
            ),
          )}
          {next}
        </div>
      </nav>
    </div>
  );
}

export default Pagination;
