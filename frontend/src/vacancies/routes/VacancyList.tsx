import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Pagination from '../components/Pagination';
import SavedFiltersBar from '../components/SavedFiltersBar';
import { fetchVacancies, type CompanyFilter } from '../api';
import { deadlineClass, formatDate, formatSalary } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { useBootstrap } from '../../shared/hooks/useBootstrap';

interface Draft {
  includeKeywords: string[];
  excludeKeywords: string[];
  includeIndustries: string[];
  showActiveOnly: boolean;
  companyFilter: CompanyFilter;
}

const COMPANY_FILTERS = new Set<CompanyFilter>([
  'all',
  'liked',
  'not_disliked',
  'disliked',
]);

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

/**
 * React port of vacancies.html — the filtered vacancy list.
 * All filter state lives in the URL (useSearchParams) so filtered
 * pages stay bookmarkable; like the template form, checkbox changes
 * are staged locally and applied to the URL on Search — which also
 * resets ?page= back to the first page.
 */
export default function VacancyList() {
  // Saved filters are session-authed — render the bar (and fire its
  // query) only for logged-in users, or an anonymous visitor's 401
  // would bounce the whole page to /admin/login/.
  const { user } = useBootstrap();
  const [searchParams, setSearchParams] = useSearchParams();
  const params = {
    includeKeywords: searchParams.getAll('include_keywords'),
    excludeKeywords: searchParams.getAll('exclude_keywords'),
    includeIndustries: searchParams.getAll('include_industries'),
    showActiveOnly: searchParams.get('show_active_only') === '1',
    companyFilter: toCompanyFilter(
      searchParams.get('company_filter'),
    ),
    page: searchParams.get('page'),
  };

  const { data, isPending, isError, error } = useQuery({
    queryKey: ['vacancies', 'list', searchParams.toString()],
    queryFn: () => fetchVacancies(params),
  });

  // Staged filter state — mirrors the GET form: nothing applies
  // until Search is pressed. Re-synced when the URL changes (back/
  // forward navigation, pagination links keep the same filters).
  const paramsKey = searchParams.toString();
  const [draft, setDraft] = useState<Draft>({
    includeKeywords: params.includeKeywords,
    excludeKeywords: params.excludeKeywords,
    includeIndustries: params.includeIndustries,
    showActiveOnly: params.showActiveOnly,
    companyFilter: params.companyFilter,
  });
  useEffect(() => {
    const p = new URLSearchParams(paramsKey);
    setDraft({
      includeKeywords: p.getAll('include_keywords'),
      excludeKeywords: p.getAll('exclude_keywords'),
      includeIndustries: p.getAll('include_industries'),
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
    if (draft.showActiveOnly) next.set('show_active_only', '1');
    if (draft.companyFilter !== 'all') {
      next.set('company_filter', draft.companyFilter);
    }
    // Filters changed — land back on page 1.
    setSearchParams(next);
  };

  const now = new Date();
  const vacancies = data?.vacancies ?? [];

  return (
    <div className="container-fluid py-4 vacancies-page">
      <a href="/" className="back-link">
        ← Back to Home
      </a>
      <div className="d-flex justify-content-between align-items-center mb-4">
        <h2 className="mb-0">Vacancies</h2>
        <div className="d-flex gap-2">
          <Link
            to="/companies"
            className="btn btn-sm btn-outline-secondary"
          >
            Companies
          </Link>
          <Link
            to="/vacancies/keywords"
            className="btn btn-sm btn-outline-secondary"
          >
            + Add Keyword
          </Link>
        </div>
      </div>

      {/* Filters */}
      <div className="card filter-card mb-4">
        <div className="card-body">
          {user && (
            <SavedFiltersBar
              applied={{
                includeKeywords: params.includeKeywords,
                excludeKeywords: params.excludeKeywords,
                includeIndustries: params.includeIndustries,
                showActiveOnly: params.showActiveOnly,
                companyFilter: params.companyFilter,
              }}
            />
          )}
          <form onSubmit={applyFilters}>
            {data && data.industries.length > 0 && (
              <div className="mb-3">
                <label className="filter-label d-block mb-2">
                  Industries
                </label>
                <div className="d-flex flex-wrap">
                  {data.industries.map((industry, i) => (
                    <div className="form-check me-4 mb-1" key={industry}>
                      <input
                        className="form-check-input"
                        type="checkbox"
                        id={`ind_${i}`}
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
                      <label
                        className="form-check-label"
                        htmlFor={`ind_${i}`}
                      >
                        {industry}
                      </label>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="row align-items-end">
              <div className="col-md-5 mb-2">
                <label className="filter-label d-block mb-1">
                  Include keywords
                </label>
                <div className="checkbox-scroll-list">
                  {isPending ? (
                    <span className="text-muted">Loading…</span>
                  ) : data && data.keywords.length > 0 ? (
                    data.keywords.map((keyword) => (
                      <label key={keyword}>
                        <input
                          type="checkbox"
                          checked={draft.includeKeywords.includes(
                            keyword,
                          )}
                          onChange={(e) =>
                            setDraft((d) => ({
                              ...d,
                              includeKeywords: toggleValue(
                                d.includeKeywords,
                                keyword,
                                e.target.checked,
                              ),
                            }))
                          }
                        />{' '}
                        {keyword}
                      </label>
                    ))
                  ) : (
                    <span className="text-muted">No keywords yet.</span>
                  )}
                </div>
              </div>
              <div className="col-md-5 mb-2">
                <label className="filter-label d-block mb-1">
                  Exclude keywords
                </label>
                <div className="checkbox-scroll-list">
                  {data?.keywords.map((keyword) => (
                    <label key={keyword}>
                      <input
                        type="checkbox"
                        checked={draft.excludeKeywords.includes(keyword)}
                        onChange={(e) =>
                          setDraft((d) => ({
                            ...d,
                            excludeKeywords: toggleValue(
                              d.excludeKeywords,
                              keyword,
                              e.target.checked,
                            ),
                          }))
                        }
                      />{' '}
                      {keyword}
                    </label>
                  ))}
                </div>
              </div>
              <div className="col-md-2 mb-2 d-flex flex-column justify-content-end">
                {user && (
                  <div className="mb-3">
                    <label
                      className="filter-label d-block mb-1"
                      htmlFor="company_filter"
                    >
                      Companies
                    </label>
                    <select
                      id="company_filter"
                      className="form-select form-select-sm"
                      value={draft.companyFilter}
                      onChange={(e) =>
                        setDraft((d) => ({
                          ...d,
                          companyFilter: e.target
                            .value as CompanyFilter,
                        }))
                      }
                    >
                      <option value="all">All companies</option>
                      <option value="liked">Liked only</option>
                      <option value="not_disliked">
                        Hide disliked
                      </option>
                      <option value="disliked">Disliked only</option>
                    </select>
                  </div>
                )}
                <div className="form-check mb-3">
                  <input
                    className="form-check-input"
                    type="checkbox"
                    id="show_active_only"
                    checked={draft.showActiveOnly}
                    onChange={(e) =>
                      setDraft((d) => ({
                        ...d,
                        showActiveOnly: e.target.checked,
                      }))
                    }
                  />
                  <label
                    className="form-check-label filter-label"
                    htmlFor="show_active_only"
                  >
                    Active only
                  </label>
                </div>
                <button type="submit" className="btn btn-primary btn-sm">
                  Search
                </button>
              </div>
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
              ? `Failed to load vacancies — ${errorDetail(error)}`
              : !data || data.total_count === 0
                ? 'No vacancies found'
                : data.num_pages > 1
                  ? `Showing ${data.start_index}–${data.end_index} of ${data.total_count} vacancies`
                  : `${data.total_count} ${
                      data.total_count === 1 ? 'vacancy' : 'vacancies'
                    } found`}
        </span>
      </div>

      {/* Table */}
      <div className="card filter-card">
        <div className="card-body p-0">
          <div className="table-responsive">
            <table className="table table-hover table-sm mb-0">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Company</th>
                  <th>Salary</th>
                  <th>Keywords</th>
                  <th>Industries</th>
                  <th>Deadline</th>
                  <th>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {vacancies.length === 0 && !isPending ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="text-center text-muted py-5"
                    >
                      No vacancies found. Try adjusting your filters.
                    </td>
                  </tr>
                ) : (
                  vacancies.map((vacancy) => (
                    <tr key={vacancy.id}>
                      <td className="vacancy-title">
                        <a
                          href={vacancy.url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {vacancy.title || '(no title)'}
                        </a>
                      </td>
                      <td>
                        {vacancy.company_id ? (
                          <Link to={`/companies/${vacancy.company_id}`}>
                            {vacancy.company_name || '—'}
                          </Link>
                        ) : (
                          vacancy.company_name || '—'
                        )}
                        {vacancy.company_preference === 'like' && (
                          <span className="badge bg-success ms-1">
                            liked
                          </span>
                        )}
                        {vacancy.company_preference === 'dislike' && (
                          <span className="badge bg-danger ms-1">
                            disliked
                          </span>
                        )}
                      </td>
                      <td className="salary-cell">
                        {formatSalary(
                          vacancy.salary_from,
                          vacancy.salary_to,
                        )}
                      </td>
                      <td>
                        {vacancy.keywords.map((kw) => (
                          <span
                            key={kw}
                            className="keyword-match-badge"
                          >
                            {kw}
                          </span>
                        ))}
                      </td>
                      <td>
                        {vacancy.industries.map((industry) => (
                          <span key={industry} className="industry-tag">
                            {industry}
                          </span>
                        ))}
                      </td>
                      <td>
                        {vacancy.application_deadline ? (
                          <span
                            className={deadlineClass(
                              vacancy.application_deadline,
                              now,
                            )}
                          >
                            {formatDate(vacancy.application_deadline)}
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="text-muted">
                        {formatDate(vacancy.last_seen)}
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
