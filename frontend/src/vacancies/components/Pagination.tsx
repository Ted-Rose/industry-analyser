import { useSearchParams } from 'react-router-dom';

interface Props {
  page: number;
  numPages: number;
  hasPrevious: boolean;
  hasNext: boolean;
}

/**
 * The template pagination: « first / ‹ prev / page numbers within
 * ±2 of the current page / › next / » last — written into the `page`
 * search param so filtered pages stay bookmarkable.
 */
export default function Pagination({
  page,
  numPages,
  hasPrevious,
  hasNext,
}: Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  if (numPages <= 1) return null;

  const go = (n: number) => {
    const next = new URLSearchParams(searchParams);
    if (n <= 1) next.delete('page');
    else next.set('page', String(n));
    setSearchParams(next);
  };

  // Template window: page_num > page-3 and page_num < page+3 —
  // the active page renders in position as a non-clickable span.
  const windowPages: number[] = [];
  for (let n = page - 2; n <= page + 2; n += 1) {
    if (n >= 1 && n <= numPages) windowPages.push(n);
  }

  return (
    <nav className="mt-3" aria-label="Page navigation">
      <ul className="pagination pagination-sm justify-content-center">
        {hasPrevious && (
          <>
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
            <li className="page-item">
              <button
                type="button"
                className="page-link"
                aria-label="Previous page"
                onClick={() => go(page - 1)}
              >
                ‹
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
                ›
              </button>
            </li>
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
          </>
        )}
      </ul>
    </nav>
  );
}
