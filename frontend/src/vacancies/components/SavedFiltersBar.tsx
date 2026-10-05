import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  fetchSavedFilters,
  type CompanyFilter,
  type SavedFilterOut,
} from '../api';
import {
  useCreateSavedFilter,
  useDeleteSavedFilter,
  useUpdateSavedFilter,
} from '../mutations';
import { errorDetail } from '../../shared/api/errors';
import { useBootstrap } from '../../shared/hooks/useBootstrap';

/** The URL-applied filter state — what "Save current" persists. */
interface AppliedFilters {
  includeKeywords: string[];
  excludeKeywords: string[];
  includeIndustries: string[];
  showActiveOnly: boolean;
  companyFilter: CompanyFilter;
}

interface SavedFiltersBarProps {
  applied: AppliedFilters;
}

/** Mirrors SavedFilterIn.name's max_length on the API. */
const NAME_MAX_LENGTH = 100;

function toSearchParams(filter: {
  include_keywords: string[];
  exclude_keywords: string[];
  include_industries: string[];
  show_active_only: boolean;
  company_filter: CompanyFilter;
}): URLSearchParams {
  const next = new URLSearchParams();
  filter.include_keywords.forEach((k) =>
    next.append('include_keywords', k),
  );
  filter.exclude_keywords.forEach((k) =>
    next.append('exclude_keywords', k),
  );
  filter.include_industries.forEach((i) =>
    next.append('include_industries', i),
  );
  if (filter.show_active_only) next.set('show_active_only', '1');
  if (filter.company_filter !== 'all') {
    next.set('company_filter', filter.company_filter);
  }
  // Deliberately no `page` — applying a preset lands on page 1.
  return next;
}

/** Order-insensitive list equality — the URL params and the stored
 *  preset carry the same names but not necessarily in the same
 *  order after checkbox edits. */
function sameNames(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((v) => b.includes(v));
}

/** Trimmed prompt value, or null when the entry is unusable —
 *  surfaces the >100-char case inline so the API's 422 path is
 *  unreachable from the UI. */
function promptName(
  message: string,
  initial: string | undefined,
  setError: (msg: string) => void,
): string | null {
  const raw = window.prompt(message, initial);
  if (raw === null) return null;
  const name = raw.trim();
  if (!name) return null;
  if (name.length > NAME_MAX_LENGTH) {
    setError(
      `Filter names are limited to ${NAME_MAX_LENGTH} characters.`,
    );
    return null;
  }
  return name;
}

/**
 * Per-user saved vacancy-filter presets, shown only to logged-in
 * users. Choosing a preset rewrites the URL params (the URL stays
 * the source of truth — the staged checkbox draft re-syncs from it).
 * The selected option is derived: whichever preset's params match
 * the applied URL, so editing filters or navigating falls back to
 * the placeholder. "Save current" snapshots the *applied* URL
 * params, not the staged draft. The `enabled` gate matters: an
 * authed request from an anonymous visitor would 401 and the client
 * would bounce the whole page to /admin/login/.
 */
export default function SavedFiltersBar({
  applied,
}: SavedFiltersBarProps) {
  const { user } = useBootstrap();
  const [, setSearchParams] = useSearchParams();
  const { data: filters } = useQuery({
    queryKey: ['vacancies', 'saved-filters'],
    queryFn: fetchSavedFilters,
    enabled: !!user,
  });
  const createFilter = useCreateSavedFilter();
  const updateFilter = useUpdateSavedFilter();
  const deleteFilter = useDeleteSavedFilter();
  const [error, setError] = useState('');

  const selected = (filters ?? []).find(
    (f) =>
      sameNames(f.include_keywords, applied.includeKeywords) &&
      sameNames(f.exclude_keywords, applied.excludeKeywords) &&
      sameNames(f.include_industries, applied.includeIndustries) &&
      f.show_active_only === applied.showActiveOnly &&
      f.company_filter === applied.companyFilter,
  );
  const mutationError = (err: unknown) => setError(errorDetail(err));

  const appliedPayload = () => ({
    include_keywords: applied.includeKeywords,
    exclude_keywords: applied.excludeKeywords,
    include_industries: applied.includeIndustries,
    show_active_only: applied.showActiveOnly,
    company_filter: applied.companyFilter,
  });

  const onSelect = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const filter = (filters ?? []).find(
      (f) => f.id === e.target.value,
    );
    if (filter) setSearchParams(toSearchParams(filter));
  };

  const saveCurrent = () => {
    setError('');
    const name = promptName(
      'Name for this saved filter:',
      undefined,
      setError,
    );
    if (name === null) return;
    // Saved params are exactly the applied ones — once the list
    // refetch lands (and the optimistic cache entry before it), the
    // derived selection above resolves to the new preset on its own.
    createFilter.mutate(
      { name, ...appliedPayload() },
      { onError: mutationError },
    );
  };

  const overwriteSelected = () => {
    if (!selected) return;
    if (
      !window.confirm(
        `Overwrite "${selected.name}" with the current filters?`,
      )
    )
      return;
    setError('');
    updateFilter.mutate(
      {
        id: selected.id,
        input: { name: selected.name, ...appliedPayload() },
      },
      { onError: mutationError },
    );
  };

  const renameSelected = () => {
    if (!selected) return;
    setError('');
    const name = promptName('New name:', selected.name, setError);
    if (name === null || name === selected.name) return;
    updateFilter.mutate(
      {
        id: selected.id,
        input: {
          name,
          include_keywords: selected.include_keywords,
          exclude_keywords: selected.exclude_keywords,
          include_industries: selected.include_industries,
          show_active_only: selected.show_active_only,
          company_filter: selected.company_filter,
        },
      },
      { onError: mutationError },
    );
  };

  const deleteSelected = () => {
    if (!selected) return;
    if (!window.confirm(`Delete saved filter "${selected.name}"?`))
      return;
    setError('');
    deleteFilter.mutate(selected.id, { onError: mutationError });
  };

  const busy =
    createFilter.isPending ||
    updateFilter.isPending ||
    deleteFilter.isPending;

  return (
    <div className="mb-3">
      <div className="d-flex flex-wrap align-items-center gap-2">
        <label
          className="filter-label mb-0"
          htmlFor="saved-filter-select"
        >
          Saved filters
        </label>
        <select
          id="saved-filter-select"
          className="form-select form-select-sm w-auto"
          value={selected?.id ?? ''}
          onChange={onSelect}
        >
          <option value="">Saved filters…</option>
          {(filters ?? []).map((f: SavedFilterOut) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn btn-sm btn-outline-primary"
          onClick={saveCurrent}
          disabled={busy}
        >
          Save current
        </button>
        {selected && (
          <>
            <button
              type="button"
              className="btn btn-sm btn-outline-secondary"
              onClick={overwriteSelected}
              disabled={busy}
            >
              Overwrite
            </button>
            <button
              type="button"
              className="btn btn-sm btn-outline-secondary"
              onClick={renameSelected}
              disabled={busy}
            >
              Rename
            </button>
            <button
              type="button"
              className="btn btn-sm btn-outline-danger"
              onClick={deleteSelected}
              disabled={busy}
            >
              Delete
            </button>
          </>
        )}
      </div>
      {error && (
        <div className="alert alert-danger py-2 mt-2 mb-0" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
