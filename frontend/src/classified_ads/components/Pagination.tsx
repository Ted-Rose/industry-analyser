import { useSearchParams } from 'react-router-dom';

interface Props {
  page: number;
  numPages: number;
  hasPrevious: boolean;
  hasNext: boolean;
  /**
   * 'default' — the ads tables' shape: Previous / page numbers within
   *   ±2 of the current page / Next.
   * 'caps' — the region-ads-list shape: « ‹ numbers within ±3 › ».
   * 'compact' — the property-list shape: ← / "n / N" / →.
   */
  variant?: 'default' | 'caps' | 'compact';
}

/**
 * Pagination bar matching the retired templates' markup — written
 * into the `page` search param so filtered pages stay bookmarkable.
 */
export default function Pagination({
  page,
  numPages,
  hasPrevious,
  hasNext,
  variant = 'default',
}: Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  if (numPages <= 1) return null;

  const go = (n: number) => {
    const next = new URLSearchParams(searchParams);
    if (n <= 1) next.delete('page');
    else next.set('page', String(n));
    setSearchParams(next);
  };

  if (variant === 'compact') {
    return (
      <nav className="mt-3" aria-label="Page navigation">
        <ul className="pagination pagination-sm">
          {hasPrevious && (
            <li className="page-item">
              <button
                type="button"
                className="page-link"
                aria-label="Previous page"
                onClick={() => go(page - 1)}
              >
                ←
              </button>
            </li>
          )}
          <li className="page-item disabled">
            <span className="page-link">
              {page} / {numPages}
            </span>
          </li>
          {hasNext && (
            <li className="page-item">
              <button
                type="button"
                className="page-link"
                aria-label="Next page"
                onClick={() => go(page + 1)}
              >
                →
              </button>
            </li>
          )}
        </ul>
      </nav>
    );
  }

  const radius = variant === 'caps' ? 3 : 2;
  const windowPages: number[] = [];
  for (let n = page - radius; n <= page + radius; n += 1) {
    if (n >= 1 && n <= numPages) windowPages.push(n);
  }

  const prevLabel = variant === 'caps' ? '‹' : 'Previous';
  const nextLabel = variant === 'caps' ? '›' : 'Next';

  return (
    <nav className="mt-3" aria-label="Page navigation">
      <ul className="pagination pagination-sm justify-content-center flex-wrap">
        {hasPrevious && (
          <>
            {variant === 'caps' && (
              <li className="page-item">
                <button
                  type="button"
                  className="page-link"
                  aria-label="First page"
                  onClick={() => go(1)}
                >
                  «
                </button>
              </li>
            )}
            <li className="page-item">
              <button
                type="button"
                className="page-link"
                aria-label="Previous page"
                onClick={() => go(page - 1)}
              >
                {prevLabel}
              </button>
            </li>
          </>
        )}
        {windowPages.map((n) =>
          n === page ? (
            <li key={n} className="page-item active" aria-current="page">
              <span className="page-link">{n}</span>
            </li>
          ) : (
            <li key={n} className="page-item">
              <button
                type="button"
                className="page-link"
                onClick={() => go(n)}
              >
                {n}
              </button>
            </li>
          ),
        )}
        {hasNext && (
          <>
            <li className="page-item">
              <button
                type="button"
                className="page-link"
                aria-label="Next page"
                onClick={() => go(page + 1)}
              >
                {nextLabel}
              </button>
            </li>
            {variant === 'caps' && (
              <li className="page-item">
                <button
                  type="button"
                  className="page-link"
                  aria-label="Last page"
                  onClick={() => go(numPages)}
                >
                  »
                </button>
              </li>
            )}
          </>
        )}
      </ul>
    </nav>
  );
}
