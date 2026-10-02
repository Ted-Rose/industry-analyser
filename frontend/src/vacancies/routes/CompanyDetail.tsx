import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Pagination from '../components/Pagination';
import { fetchCompany } from '../api';
import { deadlineClass, formatDate, formatSalary } from '../format';
import { errorDetail } from '../../shared/api/errors';

/**
 * React port of company_detail.html — the company card (identities,
 * about, contacts, aliases) plus its paginated vacancy table. The
 * pk comes from the /companies/:pk route; a merged company resolves
 * to its canonical survivor server-side (the old view 301'd).
 */
export default function CompanyDetail() {
  const { pk } = useParams<{ pk: string }>();
  const [searchParams] = useSearchParams();
  const page = searchParams.get('page');

  const { data, isPending, isError, error } = useQuery({
    queryKey: ['vacancies', 'company', pk, page],
    queryFn: () => fetchCompany(pk!, page),
    enabled: Boolean(pk),
  });

  const now = new Date();

  return (
    <div className="container-fluid py-4 vacancies-page">
      <Link to="/companies" className="back-link">
        ← All Companies
      </Link>

      {isPending && <p className="text-muted">Loading…</p>}
      {isError && (
        <p className="text-danger">
          Failed to load company — {errorDetail(error)}
        </p>
      )}

      {data && (
        <>
          {/* Company card */}
          <div className="card filter-card mb-4">
            <div className="card-body">
              <div className="d-flex align-items-start">
                {data.logo_url && (
                  <img
                    src={data.logo_url}
                    alt={`${data.name} logo`}
                    className="company-logo me-4"
                  />
                )}
                <div className="flex-grow-1">
                  <h2 className="mb-1">
                    {data.name || '(unnamed)'}{' '}
                    {data.needs_review && (
                      <span className="badge bg-warning text-dark align-middle">
                        needs review
                      </span>
                    )}
                  </h2>
                  <div className="mb-2">
                    {data.identities.map((identity) => (
                      <span
                        key={`${identity.source}:${identity.employer_id}`}
                        className="source-tag"
                      >
                        {identity.source}:{identity.employer_id}
                      </span>
                    ))}
                  </div>
                  {data.about && (
                    <p className="about-text text-muted mb-3">
                      {data.about}
                    </p>
                  )}
                  <dl className="row mb-0">
                    {data.reg_code && (
                      <>
                        <dt className="col-sm-3 detail-label">
                          Reg. code
                        </dt>
                        <dd className="col-sm-9">
                          {data.reg_code}
                          {data.reg_code_country &&
                            ` (${data.reg_code_country})`}
                        </dd>
                      </>
                    )}
                    {data.webpage_url && (
                      <>
                        <dt className="col-sm-3 detail-label">
                          Website
                        </dt>
                        <dd className="col-sm-9">
                          <a
                            href={data.webpage_url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {data.webpage_url}
                          </a>
                        </dd>
                      </>
                    )}
                    {data.address && (
                      <>
                        <dt className="col-sm-3 detail-label">
                          Address
                        </dt>
                        <dd className="col-sm-9">{data.address}</dd>
                      </>
                    )}
                    {(data.contact_name ||
                      data.contact_email ||
                      data.contact_phone) && (
                      <>
                        <dt className="col-sm-3 detail-label">
                          Contact
                        </dt>
                        <dd className="col-sm-9">
                          {data.contact_name || ''}{' '}
                          {data.contact_email && (
                            <a href={`mailto:${data.contact_email}`}>
                              {data.contact_email}
                            </a>
                          )}{' '}
                          {data.contact_phone || ''}
                        </dd>
                      </>
                    )}
                    {data.applying_url && (
                      <>
                        <dt className="col-sm-3 detail-label">
                          External ATS
                        </dt>
                        <dd className="col-sm-9">
                          <a
                            href={data.applying_url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {data.applying_url}
                          </a>
                        </dd>
                      </>
                    )}
                    {data.video_url && (
                      <>
                        <dt className="col-sm-3 detail-label">Video</dt>
                        <dd className="col-sm-9">
                          <a
                            href={data.video_url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {data.video_url}
                          </a>
                        </dd>
                      </>
                    )}
                    <dt className="col-sm-3 detail-label">Seen</dt>
                    <dd className="col-sm-9">
                      {formatDate(data.first_seen)} –{' '}
                      {formatDate(data.last_seen)}
                    </dd>
                  </dl>
                </div>
              </div>
            </div>
          </div>

          {/* Alias history */}
          {(data.name_aliases.length > 0 ||
            data.reg_aliases.length > 0) && (
            <div className="card filter-card mb-4">
              <div className="card-body">
                <h5 className="mb-3">History</h5>
                {data.name_aliases.length > 0 && (
                  <div className="mb-2">
                    <span className="detail-label">Names:</span>{' '}
                    {data.name_aliases.map((alias) => (
                      <span key={alias} className="source-tag">
                        {alias}
                      </span>
                    ))}
                  </div>
                )}
                {data.reg_aliases.length > 0 && (
                  <div>
                    <span className="detail-label">Reg. codes:</span>{' '}
                    {data.reg_aliases.map((alias) => (
                      <span key={alias} className="source-tag">
                        {alias}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Vacancies */}
          <div className="d-flex justify-content-between align-items-center mb-2">
            <h4 className="mb-0">Vacancies</h4>
            <span className="results-summary">
              {data.total_count > 0 &&
                `${data.total_count} ${
                  data.total_count === 1 ? 'vacancy' : 'vacancies'
                }`}
            </span>
          </div>
          <div className="card filter-card">
            <div className="card-body p-0">
              <div className="table-responsive">
                <table className="table table-hover table-sm mb-0">
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Salary</th>
                      <th>Deadline</th>
                      <th>Last seen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.vacancies.length === 0 ? (
                      <tr>
                        <td
                          colSpan={4}
                          className="text-center text-muted py-5"
                        >
                          No vacancies for this company.
                        </td>
                      </tr>
                    ) : (
                      data.vacancies.map((vacancy) => (
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
                          <td className="salary-cell">
                            {formatSalary(
                              vacancy.salary_from,
                              vacancy.salary_to,
                            )}
                          </td>
                          <td>
                            {vacancy.application_deadline ? (
                              <span
                                className={deadlineClass(
                                  vacancy.application_deadline,
                                  now,
                                )}
                              >
                                {formatDate(
                                  vacancy.application_deadline,
                                )}
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

          <Pagination
            page={data.page}
            numPages={data.num_pages}
            hasPrevious={data.has_previous}
            hasNext={data.has_next}
          />
        </>
      )}
    </div>
  );
}
