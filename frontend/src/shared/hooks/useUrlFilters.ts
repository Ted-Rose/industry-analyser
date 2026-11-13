import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useSearchParams } from 'react-router-dom';

export interface UseUrlFiltersOptions<D> {
  /** Build the draft state from the current URL params. */
  fromParams: (params: URLSearchParams) => D;
  /** Serialize a draft to the params the URL should carry. */
  toParams: (draft: D) => URLSearchParams;
}

export interface UseUrlFiltersResult<D> {
  /** Staged (not-yet-applied) filter values for the form inputs. */
  draft: D;
  setDraft: React.Dispatch<React.SetStateAction<D>>;
  /** Write the draft to the URL — resets `page` to 1. */
  apply: () => void;
  /**
   * Apply a fresh draft (defaults to the empty-params draft)
   * and stage it — the Reset-button path.
   */
  reset: (next?: D) => void;
  /** The live search params (applied state). */
  searchParams: URLSearchParams;
}

/**
 * Draft → apply → setSearchParams — plan §6
 * `hooks/useUrlFilters`. Replaces the eight routes that each
 * re-implement staged filter state. Applying writes
 * `toParams(draft)` as the whole query string, which drops
 * `page` (back to 1) — a stale page number never survives a
 * filter change. Draft re-syncs when the URL changes behind
 * the form (back/forward, chips).
 */
export function useUrlFilters<D>({
  fromParams,
  toParams,
}: UseUrlFiltersOptions<D>): UseUrlFiltersResult<D> {
  const [searchParams, setSearchParams] = useSearchParams();
  const paramsKey = searchParams.toString();

  // Latest-ref pattern: callers pass fresh inline closures every
  // render without retriggering the resync effect.
  const callbacks = useRef({ fromParams, toParams });
  callbacks.current = { fromParams, toParams };

  const [draft, setDraft] = useState<D>(() =>
    fromParams(searchParams),
  );

  const lastSyncKey = useRef(paramsKey);
  useEffect(() => {
    if (lastSyncKey.current === paramsKey) return;
    lastSyncKey.current = paramsKey;
    setDraft(callbacks.current.fromParams(
      new URLSearchParams(paramsKey),
    ));
  }, [paramsKey]);

  const apply = useCallback(() => {
    const next = callbacks.current.toParams(draft);
    next.delete('page');
    setSearchParams(next);
  }, [draft, setSearchParams]);

  const reset = useCallback(
    (next?: D) => {
      const cleared =
        next ??
        callbacks.current.fromParams(new URLSearchParams());
      setDraft(cleared);
      const params = callbacks.current.toParams(cleared);
      params.delete('page');
      setSearchParams(params);
    },
    [setSearchParams],
  );

  return useMemo(
    () => ({ draft, setDraft, apply, reset, searchParams }),
    [draft, apply, reset, searchParams],
  );
}

export default useUrlFilters;
