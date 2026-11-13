import { useSearchParams } from 'react-router-dom';

/**
 * The `page` search param as a `[page, setPage]` pair — shared
 * by ui/Pagination so every app keeps the same contract: page 1
 * deletes the param (clean URLs), anything else writes it.
 */
export function usePageParam(): [number, (page: number) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = Number(searchParams.get('page') ?? '1');
  const page = Number.isInteger(raw) && raw >= 1 ? raw : 1;

  const setPage = (next: number) => {
    const params = new URLSearchParams(searchParams);
    if (next <= 1) {
      params.delete('page');
    } else {
      params.set('page', String(next));
    }
    setSearchParams(params);
  };

  return [page, setPage];
}

export default usePageParam;
