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
import { pushToast } from '../../shared/toasts';
import Button from '../../shared/ui/Button';
import { useConfirm, usePrompt } from '../../shared/ui/Dialog';
import Select from '../../shared/ui/Select';

/** The URL-applied filter state — what "Save current" persists. */
interface AppliedFilters {
  includeKeywords: string[];
  excludeKeywords: string[];
  includeIndustries: string[];
  includeProfessions: string[];
  excludeProfessions: string[];
  showActiveOnly: boolean;
  companyFilter: CompanyFilter;
}

interface SavedFiltersBarProps {
  applied: AppliedFilters;
  /** The staged (uncommitted) checkbox draft — what the save
   *  buttons persist and apply to the URL. */
  staged: AppliedFilters;
  className?: string;
}

/** Mirrors SavedFilterIn.name's max_length on the API. */
const NAME_MAX_LENGTH = 100;

function toSearchParams(filter: {
  include_keywords: string[];
  exclude_keywords: string[];
  include_industries: string[];
  include_professions: string[];
  exclude_professions: string[];
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
  filter.include_professions.forEach((p) =>
    next.append('include_professions', p),
  );
  filter.exclude_professions.forEach((p) =>
    next.append('exclude_professions', p),
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

/**
 * Per-user saved vacancy-filter presets, shown only to logged-in
 * users. Choosing a preset rewrites the URL params (the URL stays
 * the source of truth — the staged checkbox draft re-syncs from it).
 * The selected option is derived: whichever preset's params match
 * the applied URL, so editing filters or navigating falls back to
 * the placeholder. "Save current" and "Overwrite" snapshot the
 * *staged* checkbox draft — and apply it to the URL like a Search
 * press, so the saved preset is what the user sees checked and
 * what actually filters the list. The `enabled` gate matters:
 * presets are per-user, so there's no bar to show an anonymous
 * visitor (its GET would just come back empty).
 */
export default function SavedFiltersBar({
  applied,
  staged,
  className,
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
  const { prompt, promptElement } = usePrompt();
  const { confirm, confirmElement } = useConfirm();

  const selected = (filters ?? []).find(
    (f) =>
      sameNames(f.include_keywords, applied.includeKeywords) &&
      sameNames(f.exclude_keywords, applied.excludeKeywords) &&
      sameNames(f.include_industries, applied.includeIndustries) &&
      sameNames(
        f.include_professions,
        applied.includeProfessions,
      ) &&
      sameNames(
        f.exclude_professions,
        applied.excludeProfessions,
      ) &&
      f.show_active_only === applied.showActiveOnly &&
      f.company_filter === applied.companyFilter,
  );
  const mutationError = (err: unknown) =>
    pushToast(errorDetail(err), 'danger');

  const payloadOf = (f: AppliedFilters) => ({
    include_keywords: f.includeKeywords,
    exclude_keywords: f.excludeKeywords,
    include_industries: f.includeIndustries,
    include_professions: f.includeProfessions,
    exclude_professions: f.excludeProfessions,
    show_active_only: f.showActiveOnly,
    company_filter: f.companyFilter,
  });

  /** Write the staged draft to the URL when it differs from the
   *  applied params — a save doubles as a Search press so the list
   *  shows what was just persisted. Skipped when nothing is
   *  staged, so saving while paging doesn't reset ?page=. */
  const applyStaged = () => {
    const next = toSearchParams(payloadOf(staged));
    if (
      next.toString() !==
      toSearchParams(payloadOf(applied)).toString()
    ) {
      setSearchParams(next);
    }
  };

  const onSelect = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const filter = (filters ?? []).find(
      (f) => f.id === e.target.value,
    );
    if (filter) setSearchParams(toSearchParams(filter));
  };

  /** Trimmed dialog value, or null when the entry is unusable —
   *  surfaces the >100-char case as a toast so the API's 422 path
   *  is unreachable from the UI. */
  const askName = async (
    title: string,
    initial?: string,
  ): Promise<string | null> => {
    const raw = await prompt({
      title,
      label: 'Name',
      defaultValue: initial,
    });
    if (raw === null) return null;
    const name = raw.trim();
    if (!name) return null;
    if (name.length > NAME_MAX_LENGTH) {
      pushToast(
        `Filter names are limited to ${NAME_MAX_LENGTH} ` +
          'characters.',
        'danger',
      );
      return null;
    }
    return name;
  };

  const saveCurrent = async () => {
    const name = await askName('Name for this saved filter:');
    if (name === null) return;
    const input = { name, ...payloadOf(staged) };
    applyStaged();
    // Once the list refetch lands (and the optimistic cache entry
    // before it), the derived selection above resolves to the new
    // preset on its own.
    createFilter.mutate(input, { onError: mutationError });
  };

  const overwriteSelected = async () => {
    if (!selected) return;
    const ok = await confirm({
      title: 'Overwrite saved filter?',
      body: `Overwrite "${selected.name}" with the current filters?`,
      confirmLabel: 'Overwrite',
    });
    if (!ok) return;
    applyStaged();
    updateFilter.mutate(
      {
        id: selected.id,
        input: { name: selected.name, ...payloadOf(staged) },
      },
      { onError: mutationError },
    );
  };

  const renameSelected = async () => {
    if (!selected) return;
    const name = await askName('New name:', selected.name);
    if (name === null || name === selected.name) return;
    updateFilter.mutate(
      {
        id: selected.id,
        input: {
          name,
          include_keywords: selected.include_keywords,
          exclude_keywords: selected.exclude_keywords,
          include_industries: selected.include_industries,
          include_professions: selected.include_professions,
          exclude_professions: selected.exclude_professions,
          show_active_only: selected.show_active_only,
          company_filter: selected.company_filter,
        },
      },
      { onError: mutationError },
    );
  };

  const deleteSelected = async () => {
    if (!selected) return;
    const ok = await confirm({
      title: 'Delete saved filter?',
      body: `Delete saved filter "${selected.name}"?`,
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    deleteFilter.mutate(selected.id, { onError: mutationError });
  };

  const busy =
    createFilter.isPending ||
    updateFilter.isPending ||
    deleteFilter.isPending;

  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-2">
        <label
          className="text-sm font-medium text-fg"
          htmlFor="saved-filter-select"
        >
          Saved filters
        </label>
        <div className="w-full sm:w-64">
          <Select
            id="saved-filter-select"
            value={selected?.id ?? ''}
            onChange={onSelect}
          >
            <option value="">Saved filters…</option>
            {(filters ?? []).map((f: SavedFilterOut) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </Select>
        </div>
        <Button size="sm" onClick={saveCurrent} disabled={busy}>
          Save current
        </Button>
        {selected && (
          <>
            <Button
              size="sm"
              variant="secondary"
              onClick={overwriteSelected}
              disabled={busy}
            >
              Overwrite
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={renameSelected}
              disabled={busy}
            >
              Rename
            </Button>
            <Button
              size="sm"
              variant="danger"
              onClick={deleteSelected}
              disabled={busy}
            >
              Delete
            </Button>
          </>
        )}
      </div>
      {promptElement}
      {confirmElement}
    </div>
  );
}
