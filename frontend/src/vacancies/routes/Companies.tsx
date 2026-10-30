import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  keepPreviousData,
  useQuery,
} from '@tanstack/react-query';
import { ExternalLink } from 'lucide-react';
import IdentityTag from '../components/IdentityTag';
import CompanyPreferenceButtons from '../components/CompanyPreferenceButtons';
import { fetchCompanies } from '../api';
import { formatDate } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { cx } from '../../shared/cx';
import { useBootstrap } from '../../shared/hooks/useBootstrap';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import { pushToast } from '../../shared/toasts';
import Badge from '../../shared/ui/Badge';
import Card from '../../shared/ui/Card';
import DataTable, {
  type Column,
} from '../../shared/ui/DataTable';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState from '../../shared/ui/ErrorState';
import Field from '../../shared/ui/Field';
import FilterBar from '../../shared/ui/FilterBar';
import Input from '../../shared/ui/Input';
import Pagination from '../../shared/ui/Pagination';
import type { CompanyOut } from '../api';

/**
 * React port of companies.html — the canonical-company browser with
 * a name/reg-code search box — restyled on the shared component
 * kit (plan §9.7). `q` and `page` live in the URL so filtered pages
 * are bookmarkable; the input is staged and applied on Search (the
 * template's GET form), clearing `page`.
 *
 * The table renders on ≥md viewports; below that DataTable swaps
 * to the stacked card layout — seven columns don't fit a phone.
 */
export default function Companies() {
  // Preference buttons are session-authed — render them (and the
  // Preference column) only for logged-in users.
  const { user } = useBootstrap();
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get('q') ?? '';
  const page = searchParams.get('page');

  const {
    data,
    isPending,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['vacancies', 'companies', query, page],
    queryFn: () => fetchCompanies({ q: query, page }),
    // A search keeps the previous page on screen while the new one
    // loads — the opacity dim below is the only "loading" signal a
    // refetch needs.
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
      `Failed to load companies — ${errorDetail(error)}`,
      'danger',
    );
  }, [isError, error]);

  // Staged search input — synced when the URL changes (Clear,
  // pagination, back/forward).
  const [draftQ, setDraftQ] = useState(query);
  useEffect(() => setDraftQ(query), [query]);

  const applySearch = (e: React.FormEvent) => {
    e.preventDefault();
    const next = new URLSearchParams(searchParams);
    next.delete('page');
    if (draftQ.trim()) next.set('q', draftQ.trim());
    else next.delete('q');
    setSearchParams(next);
  };

  const clearSearch = () => {
    const next = new URLSearchParams(searchParams);
    next.delete('q');
    next.delete('page');
    setSearchParams(next);
    setDraftQ('');
  };

  const companies = data?.companies ?? [];

  const columns: Column<CompanyOut>[] = [
    {
      id: 'name',
      header: 'Name',
      cell: (company) => (
        <>
          <Link
            to={`/companies/${company.id}`}
            className="font-medium text-fg hover:text-accent-text"
          >
            {company.name || '(unnamed)'}
          </Link>
          {company.webpage_url && (
            <a
              href={company.webpage_url}
              target="_blank"
              rel="noopener noreferrer"
              title={company.webpage_url}
              className={
                'ml-2 inline-flex items-center gap-0.5 ' +
                'whitespace-nowrap text-xs text-accent-text ' +
                'hover:underline'
              }
            >
              site
              <ExternalLink
                className="size-3"
                aria-hidden="true"
              />
            </a>
          )}
          {company.about && (
            <div className="mt-0.5 line-clamp-3 whitespace-pre-line text-xs font-normal text-fg-subtle">
              {company.about}
            </div>
          )}
        </>
      ),
    },
    {
      id: 'reg_code',
      header: 'Reg. code',
      cell: (company) => company.reg_code || '—',
    },
    {
      id: 'sources',
      header: 'Sources',
      cell: (company) => (
        <span className="flex flex-wrap gap-1">
          {company.identities.map((identity) => (
            <IdentityTag
              key={`${identity.source}:${identity.employer_id}`}
              identity={identity}
            />
          ))}
        </span>
      ),
    },
    {
      id: 'vacancies',
      header: 'Vacancies',
      align: 'right',
      cell: (company) => company.vacancy_count,
    },
    {
      id: 'open',
      header: 'Open',
      align: 'right',
      cell: (company) => company.open_count,
    },
    {
      id: 'review',
      header: 'Review',
      cell: (company) =>
        company.needs_review && (
          <Badge tone="warning">review</Badge>
        ),
    },
    {
      id: 'last_seen',
      header: 'Last seen',
      cell: (company) => (
        <span className="text-fg-subtle">
          {formatDate(company.last_seen)}
        </span>
      ),
    },
    ...(user
      ? [
          {
            id: 'preference',
            header: 'Preference',
            cell: (company: CompanyOut) => (
              <CompanyPreferenceButtons
                companyId={company.id}
                preference={company.preference}
              />
            ),
          },
        ]
      : []),
  ];

  return (
    <PageContainer width="page">
      <PageHeader title="Companies" />

      <FilterBar
        onSubmit={applySearch}
        onReset={query ? clearSearch : undefined}
        submitLabel="Search"
        resetLabel="Clear"
        className="mb-4"
      >
        <Field className="sm:col-span-2 lg:col-span-2">
          <Input
            type="text"
            name="q"
            aria-label="Name or reg. code"
            value={draftQ}
            onChange={(e) => setDraftQ(e.target.value)}
            placeholder="Name or reg. code"
          />
        </Field>
      </FilterBar>

      {isError && !data ? (
        <ErrorState
          title="Failed to load companies"
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
                  `${data.total_count} companies`
                : `${data.total_count} ${
                    data.total_count === 1
                      ? 'company'
                      : 'companies'
                  }`}
            </p>
          )}
          <Card padding="none" className="overflow-hidden">
            <DataTable
              columns={columns}
              rows={companies}
              getRowKey={(company) => company.id}
              loading={isPending}
              empty={<EmptyState title="No companies found." />}
              caption="Companies"
              mobile="cards"
              renderMobileCard={(company) => (
                <CompanyCard
                  company={company}
                  showPreference={Boolean(user)}
                />
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

/** Stacked company card for <md viewports — same fields as the
 *  desktop table's row, reflowed vertically. */
function CompanyCard({
  company,
  showPreference,
}: {
  company: CompanyOut;
  showPreference: boolean;
}) {
  return (
    <div data-testid="company-card">
      <div className="flex items-start justify-between gap-2">
        <span className="font-medium text-fg">
          <Link
            to={`/companies/${company.id}`}
            className="hover:text-accent-text"
          >
            {company.name || '(unnamed)'}
          </Link>
        </span>
        {company.needs_review && (
          <Badge tone="warning" className="shrink-0">
            review
          </Badge>
        )}
      </div>
      {company.about && (
        <p className="mt-1 line-clamp-3 whitespace-pre-line text-xs text-fg-subtle">
          {company.about}
        </p>
      )}
      <div className="mt-2 flex flex-wrap gap-1">
        {company.identities.map((identity) => (
          <IdentityTag
            key={`${identity.source}:${identity.employer_id}`}
            identity={identity}
          />
        ))}
        {company.webpage_url && (
          <Badge
            tone="accent"
            href={company.webpage_url}
            target="_blank"
            rel="noopener"
          >
            website
            <ExternalLink className="size-3" aria-hidden="true" />
          </Badge>
        )}
      </div>
      <div className="mt-2 space-y-0.5 text-xs text-fg-subtle">
        {company.reg_code && <div>Reg. code {company.reg_code}</div>}
        <div>
          {company.vacancy_count}{' '}
          {company.vacancy_count === 1 ? 'vacancy' : 'vacancies'} ·{' '}
          {company.open_count} open
        </div>
        <div>Last seen {formatDate(company.last_seen)}</div>
      </div>
      {showPreference && (
        <div className="mt-2">
          <CompanyPreferenceButtons
            companyId={company.id}
            preference={company.preference}
          />
        </div>
      )}
    </div>
  );
}
