import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Pagination from '../components/Pagination';
import { fetchCompanies } from '../api';
import { formatDate } from '../format';
import { errorDetail } from '../../shared/api/errors';

/**
 * React port of companies.html — the canonical-company browser with
 * a name/reg-code search box. `q` and `page` live in the URL so
 * filtered pages are bookmarkable; the input is staged and applied
 * on Search (the template's GET form), clearing `page`.
 */
export default function Companies() {
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
            className="d-flex align-items-center"
          >
            <input
              type="text"
              name="q"
              value={draftQ}
              onChange={(e) => setDraftQ(e.target.value)}
              className="form-control form-control-sm me-2"
              placeholder="Name or reg. code"
              style={{ minWidth: '280px' }}
            />
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

      {/* Table */}
      <div className="card filter-card">
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
                </tr>
              </thead>
              <tbody>
                {companies.length === 0 && !isPending ? (
                  <tr>
                    <td
                      colSpan={7}
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
                      </td>
                      <td>{company.reg_code || '—'}</td>
                      <td>
                        {company.identities.map((identity) => (
                          <span
                            key={`${identity.source}:${identity.employer_id}`}
                            className="source-tag"
                          >
                            {identity.source}:{identity.employer_id}
                          </span>
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
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
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
