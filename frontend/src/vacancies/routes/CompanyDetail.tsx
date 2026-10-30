import { useEffect } from 'react';
import {
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ExternalLink } from 'lucide-react';
import IdentityTag from '../components/IdentityTag';
import CompanyPreferenceButtons from '../components/CompanyPreferenceButtons';
import { fetchCompany } from '../api';
import { deadlineClass, formatDate, formatSalary } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { useBootstrap } from '../../shared/hooks/useBootstrap';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Badge from '../../shared/ui/Badge';
import Card from '../../shared/ui/Card';
import DataTable, {
  type Column,
} from '../../shared/ui/DataTable';
import DescriptionList from '../../shared/ui/DescriptionList';
import ErrorState from '../../shared/ui/ErrorState';
import Pagination from '../../shared/ui/Pagination';
import { LoadingState } from '../../shared/ui/Skeleton';
import type { CompanyVacancyOut } from '../api';

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

/**
 * React port of company_detail.html — the company card (identities,
 * about, contacts, aliases) plus its paginated vacancy table —
 * restyled on the shared component kit (plan §9.7). The pk comes
 * from the /companies/:pk route; a merged company resolves to its
 * canonical survivor server-side (the old view 301'd).
 */
export default function CompanyDetail() {
  const { pk } = useParams<{ pk: string }>();
  // Preference buttons are session-authed — render only for
  // logged-in users.
  const { user } = useBootstrap();
  const [searchParams] = useSearchParams();
  const page = searchParams.get('page');
  const navigate = useNavigate();

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['vacancies', 'company', pk, page],
    queryFn: () => fetchCompany(pk!, page),
    enabled: Boolean(pk),
  });

  // The API resolves a merged company to its canonical survivor —
  // re-point the address bar to the canonical pk like the old
  // view's 301 did (a real 301 can't work: apiFetch treats opaque
  // redirects as auth bounces).
  useEffect(() => {
    if (data && pk && data.id !== pk) {
      navigate(`/companies/${data.id}`, { replace: true });
    }
  }, [data, pk, navigate]);

  const now = new Date();

  const columns: Column<CompanyVacancyOut>[] = [
    {
      id: 'title',
      header: 'Title',
      mobile: 'title',
      cell: (vacancy) => (
        <a
          href={vacancy.url}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-fg hover:text-accent-text"
        >
          {vacancy.title || '(no title)'}
          <ExternalLink
            className="ml-0.5 inline size-3"
            aria-hidden="true"
          />
        </a>
      ),
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
    <PageContainer width="narrow">
      <PageHeader
        back={{ to: '/companies', label: 'All Companies' }}
        title={
          data ? (
            <>
              {data.name || '(unnamed)'}{' '}
              {data.needs_review && (
                <Badge tone="warning" className="align-middle">
                  needs review
                </Badge>
              )}
            </>
          ) : (
            'Company'
          )
        }
      />

      {isPending && <LoadingState variant="table" rows={3} />}
      {isError && !data && (
        <ErrorState
          title="Failed to load company"
          error={errorDetail(error)}
          onRetry={() => void refetch()}
        />
      )}

      {data && (
        <>
          {/* Company card */}
          <Card className="mb-4">
            <div className="flex items-start gap-4">
              {data.logo_url && (
                <img
                  src={data.logo_url}
                  alt={`${data.name} logo`}
                  className="max-h-16 max-w-50 object-contain"
                />
              )}
              <div className="min-w-0 grow">
                {user && (
                  <div className="mb-2">
                    <CompanyPreferenceButtons
                      companyId={data.id}
                      preference={data.preference}
                    />
                  </div>
                )}
                <div className="mb-2 flex flex-wrap gap-1">
                  {data.identities.map((identity) => (
                    <IdentityTag
                      key={
                        `${identity.source}:` +
                        `${identity.employer_id}`
                      }
                      identity={identity}
                    />
                  ))}
                </div>
                {data.about && (
                  <p className="mb-3 whitespace-pre-line text-sm text-fg-muted">
                    {data.about}
                  </p>
                )}
                <DescriptionList
                  items={[
                    ...(data.reg_code
                      ? [
                          {
                            term: 'Reg. code',
                            description: `${data.reg_code}${
                              data.reg_code_country
                                ? ` (${data.reg_code_country})`
                                : ''
                            }`,
                          },
                        ]
                      : []),
                    ...(data.webpage_url
                      ? [
                          {
                            term: 'Website',
                            description: (
                              <a
                                href={data.webpage_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="break-all text-accent-text hover:underline"
                              >
                                {data.webpage_url}
                                <ExternalLink
                                  className="ml-0.5 inline size-3"
                                  aria-hidden="true"
                                />
                              </a>
                            ),
                          },
                        ]
                      : []),
                    ...(data.address
                      ? [
                          {
                            term: 'Address',
                            description: data.address,
                          },
                        ]
                      : []),
                    ...(data.contact_name ||
                    data.contact_email ||
                    data.contact_phone
                      ? [
                          {
                            term: 'Contact',
                            description: (
                              <>
                                {data.contact_name || ''}{' '}
                                {data.contact_email && (
                                  <a
                                    href={`mailto:${data.contact_email}`}
                                    className="text-accent-text hover:underline"
                                  >
                                    {data.contact_email}
                                  </a>
                                )}{' '}
                                {data.contact_phone || ''}
                              </>
                            ),
                          },
                        ]
                      : []),
                    ...(data.applying_url
                      ? [
                          {
                            term: 'External ATS',
                            description: (
                              <a
                                href={data.applying_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="break-all text-accent-text hover:underline"
                              >
                                {data.applying_url}
                                <ExternalLink
                                  className="ml-0.5 inline size-3"
                                  aria-hidden="true"
                                />
                              </a>
                            ),
                          },
                        ]
                      : []),
                    ...(data.video_url
                      ? [
                          {
                            term: 'Video',
                            description: (
                              <a
                                href={data.video_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="break-all text-accent-text hover:underline"
                              >
                                {data.video_url}
                                <ExternalLink
                                  className="ml-0.5 inline size-3"
                                  aria-hidden="true"
                                />
                              </a>
                            ),
                          },
                        ]
                      : []),
                    {
                      term: 'Seen',
                      description:
                        `${formatDate(data.first_seen)} – ` +
                        formatDate(data.last_seen),
                    },
                  ]}
                />
              </div>
            </div>
          </Card>

          {/* Alias history */}
          {(data.name_aliases.length > 0 ||
            data.reg_aliases.length > 0) && (
            <Card className="mb-4">
              <h2 className="mb-3 text-lg font-medium text-fg">
                History
              </h2>
              {data.name_aliases.length > 0 && (
                <div className="mb-2">
                  <span className="text-sm font-medium text-fg-muted">
                    Names:
                  </span>{' '}
                  {data.name_aliases.map((alias) => (
                    <Badge
                      key={alias}
                      tone="accent"
                      className="mr-1"
                    >
                      {alias}
                    </Badge>
                  ))}
                </div>
              )}
              {data.reg_aliases.length > 0 && (
                <div>
                  <span className="text-sm font-medium text-fg-muted">
                    Reg. codes:
                  </span>{' '}
                  {data.reg_aliases.map((alias) => (
                    <Badge
                      key={alias}
                      tone="accent"
                      className="mr-1"
                    >
                      {alias}
                    </Badge>
                  ))}
                </div>
              )}
            </Card>
          )}

          {/* Vacancies */}
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-xl font-semibold text-fg">
              Vacancies
            </h2>
            <span className="text-sm text-fg-muted tabular-nums">
              {data.total_count > 0 &&
                `${data.total_count} ${
                  data.total_count === 1 ? 'vacancy' : 'vacancies'
                }`}
            </span>
          </div>
          <Card padding="none" className="overflow-hidden">
            <DataTable
              columns={columns}
              rows={data.vacancies}
              getRowKey={(vacancy) => vacancy.id}
              empty={
                <p className="px-4 py-6 text-sm text-fg-subtle">
                  No vacancies for this company.
                </p>
              }
              caption="Vacancies for this company"
              className="max-md:p-3"
            />
          </Card>

          <Pagination
            page={data.page}
            numPages={data.num_pages}
            className="mt-4"
          />
        </>
      )}
    </PageContainer>
  );
}
