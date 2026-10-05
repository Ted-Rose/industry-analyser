import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Pagination from '../components/Pagination';
import IdentityTag from '../components/IdentityTag';
import CompanyPreferenceButtons from '../components/CompanyPreferenceButtons';
import { fetchCompanies } from '../api';
import { formatDate } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { useBootstrap } from '../../shared/hooks/useBootstrap';
import type { CompanyOut } from '../api';

/**
 * React port of companies.html — the canonical-company browser with
 * a name/reg-code search box. `q` and `page` live in the URL so
 * filtered pages are bookmarkable; the input is staged and applied
 * on Search (the template's GET form), clearing `page`.
 *
 * Renders as a table on ≥md viewports and a stacked card list below
 * that — seven columns don't fit a phone.
 */
export default function Companies() {
  // Preference buttons are session-authed — render them (and the
  // Preference column) only for logged-in users.
  const { user } = useBootstrap();
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get('q') ?? '';
  const page = searchParams.get('page');

  const { data, isPending, isError, error } = useQuery({
    queryKey: ['vacancies', 'companies', query, page],
    queryFn: () => fetchCompanies({ q: query, page }),
  });

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
  const empty = companies.length === 0 && !isPending;

  return (
    <div className="container-fluid py-4 vacancies-page">
      <a href="/" className="back-link">
        ← Back to Home
      </a>
      <div className="d-flex justify-content-between align-items-center mb-4">
        <h2 className="mb-0">Companies</h2>
        <Link
          to="/vacancies"
          className="btn btn-sm btn-outline-secondary"
        >
          Vacancies
        </Link>
      </div>

      {/* Search */}
      <div className="card filter-card mb-4">
        <div className="card-body">
          <form
            onSubmit={applySearch}
            className="d-flex flex-column flex-sm-row align-items-stretch align-items-sm-center"
          >
            <input
              type="text"
              name="q"
              value={draftQ}
              onChange={(e) => setDraftQ(e.target.value)}
              className="form-control form-control-sm me-sm-2 mb-2 mb-sm-0 company-search-input"
              placeholder="Name or reg. code"
            />
            <div className="d-flex align-items-center">
              <button type="submit" className="btn btn-primary btn-sm">
                Search
              </button>
              {query && (
                <button
                  type="button"
                  className="btn btn-link btn-sm"
                  onClick={clearSearch}
                >
                  Clear
                </button>
              )}
            </div>
          </form>
        </div>
      </div>

      {/* Results summary */}
      <div className="d-flex justify-content-between align-items-center mb-2">
        <span className="results-summary">
          {isPending
            ? 'Loading…'
            : isError
              ? `Failed to load companies — ${errorDetail(error)}`
              : !data || data.total_count === 0
                ? 'No companies found'
                : data.num_pages > 1
                  ? `Showing ${data.start_index}–${data.end_index} of ${data.total_count} companies`
                  : `${data.total_count} ${
                      data.total_count === 1 ? 'company' : 'companies'
                    }`}
        </span>
      </div>

      {/* Table — desktop */}
      <div className="card filter-card d-none d-md-block">
        <div className="card-body p-0">
          <div className="table-responsive">
            <table className="table table-hover table-sm mb-0">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Reg. code</th>
                  <th>Sources</th>
                  <th>Vacancies</th>
                  <th>Open</th>
                  <th>Review</th>
                  <th>Last seen</th>
                  {user && <th>Preference</th>}
                </tr>
              </thead>
              <tbody>
                {empty ? (
                  <tr>
                    <td
                      colSpan={user ? 8 : 7}
                      className="text-center text-muted py-5"
                    >
                      No companies found.
                    </td>
                  </tr>
                ) : (
                  companies.map((company) => (
                    <tr key={company.id}>
                      <td className="company-name">
                        <Link to={`/companies/${company.id}`}>
                          {company.name || '(unnamed)'}
                        </Link>
                        {company.webpage_url && (
                          <a
                            href={company.webpage_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="company-site-link ms-2"
                            title={company.webpage_url}
                          >
                            site ↗
                          </a>
                        )}
                        {company.about && (
                          <div className="company-about">
                            {company.about}
                          </div>
                        )}
                      </td>
                      <td>{company.reg_code || '—'}</td>
                      <td>
                        {company.identities.map((identity) => (
                          <IdentityTag
                            key={`${identity.source}:${identity.employer_id}`}
                            identity={identity}
                          />
                        ))}
                      </td>
                      <td>{company.vacancy_count}</td>
                      <td>{company.open_count}</td>
                      <td>
                        {company.needs_review && (
                          <span className="badge bg-warning text-dark">
                            review
                          </span>
                        )}
                      </td>
                      <td className="text-muted">
                        {formatDate(company.last_seen)}
                      </td>
                      {user && (
                        <td>
                          <CompanyPreferenceButtons
                            companyId={company.id}
                            preference={company.preference}
                          />
                        </td>
                      )}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Cards — mobile */}
      <div className="d-md-none">
        {empty ? (
          <div className="card filter-card">
            <div className="card-body text-center text-muted py-5">
              No companies found.
            </div>
          </div>
        ) : (
          companies.map((company) => (
            <CompanyCard
              key={company.id}
              company={company}
              showPreference={Boolean(user)}
            />
          ))
        )}
      </div>

      {data && (
        <Pagination
          page={data.page}
          numPages={data.num_pages}
          hasPrevious={data.has_previous}
          hasNext={data.has_next}
        />
      )}
    </div>
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
    <div className="card filter-card mb-3">
      <div className="card-body">
        <div className="d-flex justify-content-between align-items-start gap-2">
          <span className="company-name">
            <Link to={`/companies/${company.id}`}>
              {company.name || '(unnamed)'}
            </Link>
          </span>
          {company.needs_review && (
            <span className="badge bg-warning text-dark flex-shrink-0">
              review
            </span>
          )}
        </div>
        {company.about && (
          <p className="company-about mt-1 mb-2">{company.about}</p>
        )}
        <div className="mb-2">
          {company.identities.map((identity) => (
            <IdentityTag
              key={`${identity.source}:${identity.employer_id}`}
              identity={identity}
            />
          ))}
          {company.webpage_url && (
            <a
              href={company.webpage_url}
              target="_blank"
              rel="noopener noreferrer"
              className="source-tag"
            >
              website ↗
            </a>
          )}
        </div>
        <div className="company-card-meta">
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
    </div>
  );
}
