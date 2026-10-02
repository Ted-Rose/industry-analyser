import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchDashboard } from '../api';
import { formatDateTime, formatDay, formatDuration } from '../format';
import { errorDetail } from '../../shared/api/errors';

/**
 * React port of scrape_jobs/dashboard.html — the jobs table
 * (per-job progress over each job's latest cycle) plus the
 * day x job run table. The date window lives in the URL as
 * ?from=/&to= (the retired template's param names, so old
 * bookmarks still filter); the API takes them as
 * date_from/date_to — and those names are accepted too, since a
 * 401's login_url `next` round-trips the API-param spelling.
 */
export default function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = {
    dateFrom:
      searchParams.get('from') ?? searchParams.get('date_from'),
    dateTo: searchParams.get('to') ?? searchParams.get('date_to'),
  };

  const { data, isPending, isError, error } = useQuery({
    queryKey: ['dashboard', searchParams.toString()],
    queryFn: () => fetchDashboard(params),
  });

  const paramsKey = searchParams.toString();
  const [draft, setDraft] = useState({
    dateFrom: params.dateFrom ?? '',
    dateTo: params.dateTo ?? '',
  });
  useEffect(() => {
    const p = new URLSearchParams(paramsKey);
    setDraft({
      dateFrom: p.get('from') ?? p.get('date_from') ?? '',
      dateTo: p.get('to') ?? p.get('date_to') ?? '',
    });
  }, [paramsKey]);

  const applyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    const next = new URLSearchParams();
    if (draft.dateFrom) next.set('from', draft.dateFrom);
    if (draft.dateTo) next.set('to', draft.dateTo);
    setSearchParams(next);
  };

  const jobs = data?.jobs ?? [];
  const rows = data?.rows ?? [];
  const totals = data?.totals;

  return (
    <div className="dash-panel">
      <div className="top-nav">
        {/* Cross-app links leave the SPA (plain <a>) — each is a
            Django-routed SPA mount of its own. The retired Accounts
            stub link is gone; /accounts/ now 301s here. */}
        <a href="/vacancies/">Vacancies</a>
        <a href="/tv/">TV Programs</a>
        <a href="/classified-ads/">Classified Ads</a>
        <a href="/admin/">Admin</a>
      </div>

      <h1>Scrape Jobs</h1>
      <p className="subtitle">
        Per-job progress over each job&apos;s latest cycle, plus daily
        run statistics.
      </p>

      {isError && (
        <div className="alert alert-danger" role="alert">
          Failed to load the dashboard — {errorDetail(error)}
        </div>
      )}

      <h2>Jobs</h2>
      <table>
        <thead>
          <tr>
            <th>Job</th>
            <th>Enabled</th>
            <th className="num">Items</th>
            <th>Cycle</th>
            <th>Cycle progress</th>
            <th className="num">Failed</th>
            <th>Status</th>
            <th>Last run</th>
            <th className="num">Duration</th>
          </tr>
        </thead>
        <tbody>
          {jobs.length === 0 && !isPending ? (
            <tr>
              <td colSpan={9} className="muted">
                No jobs recorded yet.
              </td>
            </tr>
          ) : (
            jobs.map((row) => (
              <tr key={row.job.slug}>
                <td className="job-slug">{row.job.slug}</td>
                <td>
                  {row.job.is_enabled ? (
                    'yes'
                  ) : (
                    <span className="muted">no</span>
                  )}
                </td>
                <td className="num">
                  {row.item_active}
                  {row.item_total !== row.item_active && (
                    <span className="muted"> / {row.item_total}</span>
                  )}
                </td>
                <td>
                  {row.cycle_key ?? (
                    <span className="muted">&mdash;</span>
                  )}
                </td>
                <td>
                  {row.progress_pct != null ? (
                    <>
                      <span className="progress-bar">
                        <span
                          style={{ width: `${row.progress_pct}%` }}
                        />
                      </span>
                      {row.cycle_done}/{row.item_active} (
                      {row.progress_pct}%)
                    </>
                  ) : (
                    <span className="muted">&mdash;</span>
                  )}
                </td>
                <td className="num">
                  {row.cycle_failed ? (
                    row.cycle_failed
                  ) : (
                    <span className="muted">0</span>
                  )}
                </td>
                <td>
                  {row.running ? (
                    <span className="st st-RUNNING">RUNNING</span>
                  ) : row.last_run ? (
                    <span className={`st st-${row.last_run.status}`}>
                      {row.last_run.status}
                    </span>
                  ) : (
                    <span className="muted">never run</span>
                  )}
                </td>
                <td>
                  {row.last_run ? (
                    <>
                      {formatDateTime(row.last_run.started_at)}{' '}
                      <span className="muted">
                        {row.last_run.executed_by}
                      </span>
                    </>
                  ) : (
                    <span className="muted">&mdash;</span>
                  )}
                </td>
                <td className="num">
                  {row.last_run?.completed_at ? (
                    formatDuration(row.last_run.duration_seconds)
                  ) : (
                    <span className="muted">&mdash;</span>
                  )}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <h2>Daily runs</h2>
      <form className="filter-form" onSubmit={applyFilters}>
        <label htmlFor="id_from">From</label>{' '}
        <input
          type="date"
          id="id_from"
          name="from"
          value={draft.dateFrom}
          onChange={(e) =>
            setDraft((d) => ({ ...d, dateFrom: e.target.value }))
          }
        />{' '}
        <label htmlFor="id_to">To</label>{' '}
        <input
          type="date"
          id="id_to"
          name="to"
          value={draft.dateTo}
          onChange={(e) =>
            setDraft((d) => ({ ...d, dateTo: e.target.value }))
          }
        />{' '}
        <button type="submit">Filter</button>
      </form>
      {totals && (
        <p className="subtitle" style={{ marginBottom: 12 }}>
          {totals.run_count} runs ({totals.success_count} success,{' '}
          {totals.partial_count} partial, {totals.failed_count}{' '}
          failed, {totals.abandoned_count} abandoned)
        </p>
      )}
      <table>
        <thead>
          <tr>
            <th>Day (UTC)</th>
            <th>Job</th>
            <th className="num">Runs</th>
            <th className="num">Success</th>
            <th className="num">Partial</th>
            <th className="num">Failed</th>
            <th className="num">Abandoned</th>
            <th className="num">Avg duration</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && !isPending ? (
            <tr>
              <td colSpan={8} className="muted">
                No runs in this range.
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={`${row.day}-${row.job_slug}`}>
                <td>{formatDay(row.day)}</td>
                <td className="job-slug">{row.job_slug}</td>
                <td className="num">{row.run_count}</td>
                <td className="num">{row.success_count}</td>
                <td className="num">{row.partial_count}</td>
                <td className="num">{row.failed_count}</td>
                <td className="num">{row.abandoned_count}</td>
                <td className="num">
                  {row.avg_duration_seconds != null ? (
                    formatDuration(row.avg_duration_seconds)
                  ) : (
                    <span className="muted">&mdash;</span>
                  )}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
