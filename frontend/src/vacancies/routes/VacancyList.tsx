import {
  ReactNode,
  useEffect,
  useRef,
  useState,
} from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  keepPreviousData,
  useQuery,
} from '@tanstack/react-query';
import { ExternalLink } from 'lucide-react';
import SavedFiltersBar from '../components/SavedFiltersBar';
import {
  fetchVacancies,
  type CompanyFilter,
  type VacancyOut,
} from '../api';
import { deadlineClass, formatDate, formatSalary } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { cx } from '../../shared/cx';
import { useBootstrap } from '../../shared/hooks/useBootstrap';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import { pushToast } from '../../shared/toasts';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import Card from '../../shared/ui/Card';
import Checkbox from '../../shared/ui/Checkbox';
import CheckboxList from '../../shared/ui/CheckboxList';
import DataTable, {
  type Column,
} from '../../shared/ui/DataTable';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState from '../../shared/ui/ErrorState';
import Field from '../../shared/ui/Field';
import FilterBar from '../../shared/ui/FilterBar';
import FilterChips, {
  type FilterChip,
} from '../../shared/ui/FilterChips';
import Pagination from '../../shared/ui/Pagination';
import Select from '../../shared/ui/Select';

interface Draft {
  includeKeywords: string[];
  excludeKeywords: string[];
  includeIndustries: string[];
  includeProfessions: string[];
  excludeProfessions: string[];
  showActiveOnly: boolean;
  companyFilter: CompanyFilter;
}

const COMPANY_FILTERS = new Set<CompanyFilter>([
  'all',
  'liked',
  'not_disliked',
  'disliked',
]);

/** Option order + labels of the ?company_filter= select. */
const COMPANY_FILTER_OPTIONS: [CompanyFilter, string][] = [
  ['all', 'All companies'],
  ['liked', 'Liked only'],
  ['not_disliked', 'Hide disliked'],
  ['disliked', 'Disliked only'],
];

const COMPANY_FILTER_LABELS = Object.fromEntries(
  COMPANY_FILTER_OPTIONS,
) as Record<CompanyFilter, string>;

/** A stray ?company_filter= value falls back to 'all' — the API
 *  would 422 on anything outside the enum. */
function toCompanyFilter(raw: string | null): CompanyFilter {
  return COMPANY_FILTERS.has(raw as CompanyFilter)
    ? (raw as CompanyFilter)
    : 'all';
}

function toggleValue(list: string[], value: string, on: boolean) {
  return on ? [...list, value] : list.filter((v) => v !== value);
}

/** One labelled CheckboxList cell in a FilterBar field — the
 *  visible caption pairs with the fieldset's sr-only legend. */
function FilterList({
  label,
  options,
  value,
  onChange,
  searchPlaceholder,
}: {
  label: string;
  options: string[];
  value: string[];
  onChange: (next: string[]) => void;
  searchPlaceholder: string;
}) {
  return (
    <Field label={label}>
      <CheckboxList
        options={options.map((o) => ({ value: o, label: o }))}
        value={value}
        onChange={onChange}
        searchable
        searchPlaceholder={searchPlaceholder}
        legend={label}
      />
    </Field>
  );
}

/** The shared external-link treatment — text plus the ExternalLink
 *  glyph, opened in a new tab (plan §9.7's one pattern). */
function ExternalAnchor({
  href,
  className,
  children,
}: {
  href: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={className}
    >
      {children}
      <ExternalLink
        className="ml-0.5 inline size-3"
        aria-hidden="true"
      />
    </a>
  );
}

/** Deadline cells — deadline-past red, deadline-active green,
 *  mirroring `{% if vacancy.application_deadline < now %}`. */
function DeadlineBadge({
  deadline,
  now,
}: {
  deadline?: string | null;
  now: Date;
}) {
  if (!deadline) return <>—</>;
  const cls = deadlineClass(deadline, now);
  if (cls === '') return <>{formatDate(deadline)}</>;
  return (
    <Badge tone={cls === 'deadline-past' ? 'danger' : 'success'}>
      {formatDate(deadline)}
    </Badge>
  );
}

/** Company name cell — link to the detail route when the API
 *  resolved a canonical company, plus the preference badge. */
function CompanyName({ vacancy }: { vacancy: VacancyOut }) {
  return (
    <>
      {vacancy.company_id ? (
        <Link
          to={`/companies/${vacancy.company_id}`}
          className="text-fg hover:text-accent-text"
        >
          {vacancy.company_name || '—'}
        </Link>
      ) : (
        vacancy.company_name || '—'
      )}
      {vacancy.company_preference === 'like' && (
        <Badge tone="success" className="ml-1">
          liked
        </Badge>
      )}
      {vacancy.company_preference === 'dislike' && (
        <Badge tone="danger" className="ml-1">
          disliked
        </Badge>
      )}
    </>
  );
}

/**
 * React port of vacancies.html — the filtered vacancy list —
 * restyled on the shared component kit (plan §9.7). All filter
 * state lives in the URL (useSearchParams) so filtered pages stay
 * bookmarkable; like the template form, checkbox changes are
 * staged locally and applied to the URL on Search — which also
 * resets ?page= back to the first page.
 *
 * The table renders on ≥md viewports; below that DataTable swaps
 * to the stacked card layout — seven columns don't fit a phone.
 * The filter bar collapses behind a "Filters (n)" toggle on
 * mobile (the old card was open everywhere by default).
 */
export default function VacancyList() {
  // Saved filters are per-user — render the bar (and fire its
  // query) only for logged-in users; anonymous visitors have no
  // presets to show (the public GET would just return []).
  const { user } = useBootstrap();
  const [searchParams, setSearchParams] = useSearchParams();
  const params = {
    includeKeywords: searchParams.getAll('include_keywords'),
    excludeKeywords: searchParams.getAll('exclude_keywords'),
    includeIndustries: searchParams.getAll('include_industries'),
    includeProfessions: searchParams.getAll(
      'include_professions',
    ),
    excludeProfessions: searchParams.getAll(
      'exclude_professions',
    ),
    showActiveOnly: searchParams.get('show_active_only') === '1',
    companyFilter: toCompanyFilter(
      searchParams.get('company_filter'),
    ),
    page: searchParams.get('page'),
  };

  const {
    data,
    isPending,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['vacancies', 'list', searchParams.toString()],
    queryFn: () => fetchVacancies(params),
    // A filter change keeps the previous page on screen while the
    // new one loads — the opacity dim below is the only "loading"
    // signal a refetch needs.
    placeholderData: keepPreviousData,
  });

  // Query failures surface both inline (ErrorState on first load)
  // and as a toast — a failed background refetch must still be
  // visible while stale rows stay on screen. The ref dedupes
  // StrictMode's double-effect and repeat failures of one error.
  const reported = useRef<unknown>(null);
  useEffect(() => {
    if (!isError) {
      reported.current = null;
      return;
    }
    if (reported.current === error) return;
    reported.current = error;
    pushToast(
      `Failed to load vacancies — ${errorDetail(error)}`,
      'danger',
    );
  }, [isError, error]);

  // Staged filter state — mirrors the GET form: nothing applies
  // until Search is pressed. Re-synced when the URL changes (back/
  // forward navigation, pagination links keep the same filters).
  const paramsKey = searchParams.toString();
  const [draft, setDraft] = useState<Draft>({
    includeKeywords: params.includeKeywords,
    excludeKeywords: params.excludeKeywords,
    includeIndustries: params.includeIndustries,
    includeProfessions: params.includeProfessions,
    excludeProfessions: params.excludeProfessions,
    showActiveOnly: params.showActiveOnly,
    companyFilter: params.companyFilter,
  });
  useEffect(() => {
    const p = new URLSearchParams(paramsKey);
    setDraft({
      includeKeywords: p.getAll('include_keywords'),
      excludeKeywords: p.getAll('exclude_keywords'),
      includeIndustries: p.getAll('include_industries'),
      includeProfessions: p.getAll('include_professions'),
      excludeProfessions: p.getAll('exclude_professions'),
      showActiveOnly: p.get('show_active_only') === '1',
      companyFilter: toCompanyFilter(p.get('company_filter')),
    });
  }, [paramsKey]);

  const applyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    const next = new URLSearchParams();
    draft.includeKeywords.forEach((k) =>
      next.append('include_keywords', k),
    );
    draft.excludeKeywords.forEach((k) =>
      next.append('exclude_keywords', k),
    );
    draft.includeIndustries.forEach((i) =>
      next.append('include_industries', i),
    );
    draft.includeProfessions.forEach((p) =>
      next.append('include_professions', p),
    );
    draft.excludeProfessions.forEach((p) =>
      next.append('exclude_professions', p),
    );
    if (draft.showActiveOnly) next.set('show_active_only', '1');
    if (draft.companyFilter !== 'all') {
      next.set('company_filter', draft.companyFilter);
    }
    // Filters changed — land back on page 1.
    setSearchParams(next);
  };

  const clearAllFilters = () => setSearchParams({});

  /** Remove one applied URL param — a single value for the
   *  multi-value keys, the whole key otherwise — and land back
   *  on page 1 like a Search press. */
  const removeParam = (key: string, value?: string) => {
    const next = new URLSearchParams(searchParams);
    next.delete('page');
    if (value === undefined) {
      next.delete(key);
    } else {
      const kept = next.getAll(key).filter((v) => v !== value);
      next.delete(key);
      kept.forEach((v) => next.append(key, v));
    }
    setSearchParams(next);
  };

  // One chip per applied param value — removing a chip drops just
  // that value (plan §7 filter order / chips).
  const chips: FilterChip[] = [
    ...params.includeKeywords.map((k) => ({
      label: `Keyword: ${k}`,
      onRemove: () => removeParam('include_keywords', k),
    })),
    ...params.excludeKeywords.map((k) => ({
      label: `Exclude keyword: ${k}`,
      onRemove: () => removeParam('exclude_keywords', k),
    })),
    ...params.includeIndustries.map((i) => ({
      label: `Industry: ${i}`,
      onRemove: () => removeParam('include_industries', i),
    })),
    ...params.includeProfessions.map((p) => ({
      label: `Profession: ${p}`,
      onRemove: () => removeParam('include_professions', p),
    })),
    ...params.excludeProfessions.map((p) => ({
      label: `Exclude profession: ${p}`,
      onRemove: () => removeParam('exclude_professions', p),
    })),
    ...(params.showActiveOnly
      ? [
          {
            label: 'Active only',
            onRemove: () => removeParam('show_active_only'),
          },
        ]
      : []),
    ...(params.companyFilter !== 'all'
      ? [
          {
            label:
              'Companies: ' +
              COMPANY_FILTER_LABELS[params.companyFilter],
            onRemove: () => removeParam('company_filter'),
          },
        ]
      : []),
  ];

  const now = new Date();
  const vacancies = data?.vacancies ?? [];

  const columns: Column<VacancyOut>[] = [
    {
      id: 'title',
      header: 'Title',
      cell: (vacancy) => (
        <ExternalAnchor
          href={vacancy.url}
          className="font-medium text-fg hover:text-accent-text"
        >
          {vacancy.title || '(no title)'}
        </ExternalAnchor>
      ),
    },
    {
      id: 'company',
      header: 'Company',
      cell: (vacancy) => <CompanyName vacancy={vacancy} />,
    },
    {
      id: 'salary',
      header: 'Salary',
      cell: (vacancy) => (
        <span className="whitespace-nowrap">
          {formatSalary(vacancy.salary_from, vacancy.salary_to)}
        </span>
      ),
    },
    {
      id: 'keywords',
      header: 'Keywords',
      cell: (vacancy) => (
        <span className="flex flex-wrap gap-1">
          {vacancy.keywords.map((kw) => (
            <Badge key={kw} tone="warning">
              {kw}
            </Badge>
          ))}
        </span>
      ),
    },
    {
      id: 'industries',
      header: 'Industries',
      cell: (vacancy) => (
        <span className="flex flex-wrap gap-1">
          {vacancy.industries.map((industry) => (
            <Badge key={industry} tone="accent">
              {industry}
            </Badge>
          ))}
        </span>
      ),
    },
    {
      id: 'professions',
      header: 'Professions',
      cell: (vacancy) => (
        <span
          className="flex flex-wrap gap-1"
          data-testid="profession-tags"
        >
          {vacancy.professions.map((profession) => (
            <Badge key={profession} tone="accent">
              {profession}
            </Badge>
          ))}
        </span>
      ),
    },
    {
      id: 'deadline',
      header: 'Deadline',
      cell: (vacancy) => (
        <DeadlineBadge
          deadline={vacancy.application_deadline}
          now={now}
        />
      ),
    },
    {
      id: 'last_seen',
      header: 'Last seen',
      cell: (vacancy) => (
        <span className="text-fg-subtle">
          {formatDate(vacancy.last_seen)}
        </span>
      ),
    },
  ];

  return (
    <PageContainer width="page">
      <PageHeader title="Vacancies" />

      {/* Saved filters stay outside the FilterBar's <form> — the
          name/confirm dialogs mount their own form, and nested
          forms are invalid (a bubbled submit would apply the
          draft early). */}
      {user && (
        <SavedFiltersBar
          applied={{
            includeKeywords: params.includeKeywords,
            excludeKeywords: params.excludeKeywords,
            includeIndustries: params.includeIndustries,
            includeProfessions: params.includeProfessions,
            excludeProfessions: params.excludeProfessions,
            showActiveOnly: params.showActiveOnly,
            companyFilter: params.companyFilter,
          }}
          staged={draft}
          className="mb-4"
        />
      )}

      <FilterBar
        onSubmit={applyFilters}
        onReset={clearAllFilters}
        activeCount={chips.length}
        collapsible="mobile"
        submitLabel="Search"
        className="mb-4"
      >
        {data && data.industries.length > 0 && (
          <Field
            label="Industries"
            className="sm:col-span-2 lg:col-span-4"
          >
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {data.industries.map((industry) => (
                <Checkbox
                  key={industry}
                  label={industry}
                  checked={draft.includeIndustries.includes(
                    industry,
                  )}
                  onChange={(e) =>
                    setDraft((d) => ({
                      ...d,
                      includeIndustries: toggleValue(
                        d.includeIndustries,
                        industry,
                        e.target.checked,
                      ),
                    }))
                  }
                />
              ))}
            </div>
          </Field>
        )}

        {data && data.professions.length > 0 && (
          <div
            className={
              'grid gap-4 sm:col-span-2 sm:grid-cols-2 ' +
              'lg:col-span-4'
            }
          >
            <FilterList
              label="Professions"
              options={data.professions}
              value={draft.includeProfessions}
              onChange={(next) =>
                setDraft((d) => ({
                  ...d,
                  includeProfessions: next,
                }))
              }
              searchPlaceholder="Search professions…"
            />
            <FilterList
              label="Exclude professions"
              options={data.professions}
              value={draft.excludeProfessions}
              onChange={(next) =>
                setDraft((d) => ({
                  ...d,
                  excludeProfessions: next,
                }))
              }
              searchPlaceholder="Search professions…"
            />
          </div>
        )}

        {data && (
          <div
            className={
              'grid gap-4 sm:col-span-2 sm:grid-cols-2 ' +
              'lg:col-span-4'
            }
          >
            <FilterList
              label="Include keywords"
              options={data.keywords}
              value={draft.includeKeywords}
              onChange={(next) =>
                setDraft((d) => ({ ...d, includeKeywords: next }))
              }
              searchPlaceholder="Search keywords…"
            />
            <FilterList
              label="Exclude keywords"
              options={data.keywords}
              value={draft.excludeKeywords}
              onChange={(next) =>
                setDraft((d) => ({ ...d, excludeKeywords: next }))
              }
              searchPlaceholder="Search keywords…"
            />
          </div>
        )}

        {user && (
          <Field label="Companies" htmlFor="company_filter">
            <Select
              id="company_filter"
              value={draft.companyFilter}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  companyFilter: e.target.value as CompanyFilter,
                }))
              }
            >
              {COMPANY_FILTER_OPTIONS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
        )}

        {/* items-end drops the checkbox level with the row's
            inputs (it carries no Field label row of its own). */}
        <div className="flex items-end">
          <Checkbox
            id="show_active_only"
            label="Active only"
            checked={draft.showActiveOnly}
            onChange={(e) =>
              setDraft((d) => ({
                ...d,
                showActiveOnly: e.target.checked,
              }))
            }
          />
        </div>
      </FilterBar>

      <FilterChips
        chips={chips}
        onClearAll={clearAllFilters}
        className="mb-4"
      />

      {isError && !data ? (
        <ErrorState
          title="Failed to load vacancies"
          error={errorDetail(error)}
          onRetry={() => void refetch()}
        />
      ) : (
        <div
          aria-busy={isFetching}
          className={cx(
            'transition-opacity motion-safe:duration-180 ease-ia',
            isFetching && 'opacity-60',
          )}
        >
          {data && data.total_count > 0 && (
            <p className="mb-2 text-sm text-fg-muted tabular-nums">
              {data.num_pages > 1
                ? `Showing ${data.start_index}–` +
                  `${data.end_index} of ` +
                  `${data.total_count} vacancies`
                : `${data.total_count} ${
                    data.total_count === 1
                      ? 'vacancy'
                      : 'vacancies'
                  } found`}
            </p>
          )}
          <Card padding="none" className="overflow-hidden">
            <DataTable
              columns={columns}
              rows={vacancies}
              getRowKey={(vacancy) => vacancy.id}
              loading={isPending}
              empty={
                <EmptyState
                  title="No vacancies found."
                  description="Try adjusting your filters."
                  action={
                    chips.length > 0 ? (
                      <Button
                        variant="secondary"
                        onClick={clearAllFilters}
                      >
                        Clear filters
                      </Button>
                    ) : undefined
                  }
                />
              }
              caption="Vacancies"
              mobile="cards"
              renderMobileCard={(vacancy) => (
                <VacancyCard vacancy={vacancy} now={now} />
              )}
              className="max-md:p-3"
            />
          </Card>
          {data && (
            <Pagination
              page={data.page}
              numPages={data.num_pages}
              className="mt-4"
            />
          )}
        </div>
      )}
    </PageContainer>
  );
}

/** Stacked vacancy card for <md viewports — only the fields that
 *  matter at a glance: wrapping title and company, salary and
 *  deadline. Keywords/industries/last-seen stay desktop-only. */
function VacancyCard({
  vacancy,
  now,
}: {
  vacancy: VacancyOut;
  now: Date;
}) {
  return (
    <div data-testid="vacancy-card">
      <div className="font-medium text-fg">
        <ExternalAnchor
          href={vacancy.url}
          className="hover:text-accent-text"
        >
          {vacancy.title || '(no title)'}
        </ExternalAnchor>
      </div>
      <div className="mt-1 text-sm text-fg">
        <CompanyName vacancy={vacancy} />
      </div>
      <div className="mt-2 space-y-0.5 text-xs text-fg-subtle">
        <div>
          {formatSalary(vacancy.salary_from, vacancy.salary_to)}
        </div>
        <div>
          Deadline:{' '}
          <DeadlineBadge
            deadline={vacancy.application_deadline}
            now={now}
          />
        </div>
      </div>
    </div>
  );
}
