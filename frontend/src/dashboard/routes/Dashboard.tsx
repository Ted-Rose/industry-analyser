import { useEffect, useRef } from 'react';
import {
  keepPreviousData,
  useQuery,
} from '@tanstack/react-query';
import { fetchDashboard } from '../api';
import type { DayRowOut, JobRowOut } from '../api';
import {
  formatDateTime,
  formatDay,
  formatDuration,
} from '../format';
import { errorDetail } from '../../shared/api/errors';
import { cx } from '../../shared/cx';
import useUrlFilters from '../../shared/hooks/useUrlFilters';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Badge, { StatusBadge } from '../../shared/ui/Badge';
import DataTable, {
  type Column,
} from '../../shared/ui/DataTable';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState from '../../shared/ui/ErrorState';
import Field from '../../shared/ui/Field';
import FilterBar from '../../shared/ui/FilterBar';
import Input from '../../shared/ui/Input';
import Progress from '../../shared/ui/Progress';
import { LoadingState } from '../../shared/ui/Skeleton';
import StatusIcon from '../../shared/ui/StatusIcon';
import { pushToast } from '../../shared/toasts';

/** Poll cadence while any job is RUNNING (plan §8.16). */
const RUNNING_POLL_MS = 5_000;

interface DateDraft {
  dateFrom: string;
  dateTo: string;
}

const MUTED = 'text-fg-subtle';

const JOB_COLUMNS: Column<JobRowOut>[] = [
  {
    id: 'job',
    header: 'Job',
    cell: (row) => (
      <span className="font-mono">{row.job.slug}</span>
    ),
  },
  {
    id: 'enabled',
    header: 'Enabled',
    cell: (row) => (
      <span className="inline-flex items-center gap-1.5">
        <StatusIcon value={row.job.is_enabled} />
        {!row.job.is_enabled && <Badge>Disabled</Badge>}
      </span>
    ),
  },
  {
    id: 'items',
    header: 'Items',
    align: 'right',
    cell: (row) => (
      <>
        {row.item_active}
        {row.item_total !== row.item_active && (
          <span className={MUTED}> / {row.item_total}</span>
        )}
      </>
    ),
  },
  {
    id: 'cycle',
    header: 'Cycle',
    hideBelow: 'md',
    cell: (row) =>
      row.cycle_key ?? <span className={MUTED}>&mdash;</span>,
  },
  {
    id: 'progress',
    header: 'Cycle progress',
    cell: (row) =>
      row.progress_pct != null ? (
        <div className="flex items-center gap-2">
          <Progress
            value={row.progress_pct}
            ariaLabel={`${row.job.slug} cycle progress`}
            className="w-24 shrink-0"
          />
          <span className="whitespace-nowrap tabular-nums">
            {row.cycle_done}/{row.item_active} (
            {row.progress_pct}%)
          </span>
        </div>
      ) : (
        <span className={MUTED}>&mdash;</span>
      ),
  },
  {
    id: 'failed',
    header: 'Failed',
    align: 'right',
    cell: (row) =>
      row.cycle_failed ? (
        row.cycle_failed
      ) : (
        <span className={MUTED}>0</span>
      ),
  },
  {
    id: 'status',
    header: 'Status',
    cell: (row) =>
      row.running ? (
        <StatusBadge status="RUNNING" />
      ) : row.last_run ? (
        <StatusBadge status={row.last_run.status} />
      ) : (
        <span className={MUTED}>never run</span>
      ),
  },
  {
    id: 'last_run',
    header: 'Last run',
    hideBelow: 'md',
    cell: (row) =>
      row.last_run ? (
        <>
          {formatDateTime(row.last_run.started_at)}{' '}
          <span className={MUTED}>
            {row.last_run.executed_by}
          </span>
        </>
      ) : (
        <span className={MUTED}>&mdash;</span>
      ),
  },
  {
    id: 'duration',
    header: 'Duration',
    align: 'right',
    hideBelow: 'md',
    cell: (row) =>
      row.last_run?.completed_at ? (
        formatDuration(row.last_run.duration_seconds)
      ) : (
        <span className={MUTED}>&mdash;</span>
      ),
  },
];

const DAY_COLUMNS: Column<DayRowOut>[] = [
  {
    id: 'day',
    header: 'Day (UTC)',
    cell: (row) => formatDay(row.day),
  },
  {
    id: 'job',
    header: 'Job',
    cell: (row) => (
      <span className="font-mono">{row.job_slug}</span>
    ),
  },
  {
    id: 'runs',
    header: 'Runs',
    align: 'right',
    cell: (row) => row.run_count,
  },
  {
    id: 'success',
    header: 'Success',
    align: 'right',
    cell: (row) => row.success_count,
  },
  {
    id: 'partial',
    header: 'Partial',
    align: 'right',
    cell: (row) => row.partial_count,
  },
  {
    id: 'failed',
    header: 'Failed',
    align: 'right',
    cell: (row) => row.failed_count,
  },
  {
    id: 'abandoned',
    header: 'Abandoned',
    align: 'right',
    cell: (row) => row.abandoned_count,
  },
  {
    id: 'avg_duration',
    header: 'Avg duration',
    align: 'right',
    cell: (row) =>
      row.avg_duration_seconds != null ? (
        formatDuration(row.avg_duration_seconds)
      ) : (
        <span className={MUTED}>&mdash;</span>
      ),
  },
];

/**
 * React port of scrape_jobs/dashboard.html — the jobs table
 * (per-job progress over each job's latest cycle) plus the
 * day x job run table, restyled on the shared component kit
 * (plan §9.4). The date window lives in the URL as
 * ?from=/&to= (the retired template's param names, so old
 * bookmarks still filter); the API takes them as
 * date_from/date_to — and those names are accepted too, since a
 * 401's login_url `next` round-trips the API-param spelling.
 */
export default function Dashboard() {
  const { draft, setDraft, apply, reset, searchParams } =
    useUrlFilters<DateDraft>({
      fromParams: (p) => ({
        dateFrom: p.get('from') ?? p.get('date_from') ?? '',
        dateTo: p.get('to') ?? p.get('date_to') ?? '',
      }),
      toParams: (d) => {
        const next = new URLSearchParams();
        if (d.dateFrom) next.set('from', d.dateFrom);
        if (d.dateTo) next.set('to', d.dateTo);
        return next;
      },
    });

  const params = {
    dateFrom:
      searchParams.get('from') ?? searchParams.get('date_from'),
    dateTo: searchParams.get('to') ?? searchParams.get('date_to'),
  };

  const {
    data,
    isPending,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['dashboard', searchParams.toString()],
    queryFn: () => fetchDashboard(params),
    // A filter change keeps the previous window's rows on
    // screen while the new one loads — the opacity dim below
    // is the only "loading" signal a refetch needs.
    placeholderData: keepPreviousData,
    // §8.16 — poll while any job is mid-run so the RUNNING
    // badge and cycle progress stay live.
    refetchInterval: (query) =>
      query.state.data?.jobs.some((job) => job.running)
        ? RUNNING_POLL_MS
        : false,
  });

  // Query failures surface both inline (ErrorState) and as a
  // toast — a failed background refetch must still be visible
  // while old rows stay on screen. The ref dedupes StrictMode's
  // double-effect and repeat failures of the same error.
  const reported = useRef<unknown>(null);
  useEffect(() => {
    if (!isError) {
      reported.current = null;
      return;
    }
    if (reported.current === error) return;
    reported.current = error;
    pushToast(
      `Failed to load the dashboard — ${errorDetail(error)}`,
      'danger',
    );
  }, [isError, error]);

  const jobs = data?.jobs ?? [];
  const rows = data?.rows ?? [];
  const totals = data?.totals;

  return (
    <PageContainer width="page">
      <PageHeader
        title="Scrape Jobs"
        description={
          "Per-job progress over each job's latest cycle, " +
          'plus daily run statistics.'
        }
      />
      {isError && !data ? (
        <ErrorState
          title="Failed to load the dashboard"
          error={errorDetail(error)}
          onRetry={() => void refetch()}
        />
      ) : (
        <div
          aria-busy={isFetching}
          className={cx(
            'space-y-6 transition-opacity ' +
              'motion-safe:duration-180 ease-ia',
            isFetching && 'opacity-60',
          )}
        >
          <section>
            <h2 className="mb-3 text-xl font-semibold text-fg">
              Jobs
            </h2>
            {isPending ? (
              <LoadingState variant="table" />
            ) : (
              <DataTable
                columns={JOB_COLUMNS}
                rows={jobs}
                getRowKey={(row) => row.job.slug}
                mobile="scroll"
                stickyFirstColumn
                caption={
                  'Scrape jobs — progress over each ' +
                  "job's latest cycle"
                }
                empty={
                  <EmptyState title="No jobs recorded yet." />
                }
                className="rounded-lg bg-surface shadow-xs"
              />
            )}
          </section>
          <section>
            <h2 className="mb-3 text-xl font-semibold text-fg">
              Daily runs
            </h2>
            <FilterBar
              onSubmit={apply}
              onReset={reset}
              className="mb-4"
            >
              <Field label="From" htmlFor="id_from">
                <Input
                  type="date"
                  id="id_from"
                  name="from"
                  value={draft.dateFrom}
                  onChange={(event) =>
                    setDraft((d) => ({
                      ...d,
                      dateFrom: event.target.value,
                    }))
                  }
                />
              </Field>
              <Field label="To" htmlFor="id_to">
                <Input
                  type="date"
                  id="id_to"
                  name="to"
                  value={draft.dateTo}
                  onChange={(event) =>
                    setDraft((d) => ({
                      ...d,
                      dateTo: event.target.value,
                    }))
                  }
                />
              </Field>
            </FilterBar>
            {totals && (
              <p
                className={
                  'mb-4 text-sm text-fg-muted tabular-nums'
                }
              >
                {totals.run_count} runs ({totals.success_count}{' '}
                success, {totals.partial_count} partial,{' '}
                {totals.failed_count > 0 ? (
                  <Badge tone="danger">
                    {totals.failed_count}
                  </Badge>
                ) : (
                  totals.failed_count
                )}{' '}
                failed, {totals.abandoned_count} abandoned)
              </p>
            )}
            {isPending ? (
              <LoadingState variant="table" rows={3} />
            ) : (
              <DataTable
                columns={DAY_COLUMNS}
                rows={rows}
                getRowKey={(row) =>
                  `${row.day}-${row.job_slug}`
                }
                mobile="scroll"
                stickyFirstColumn
                caption="Daily runs by job"
                empty={
                  <EmptyState title="No runs in this range." />
                }
                className="rounded-lg bg-surface shadow-xs"
              />
            )}
          </section>
        </div>
      )}
    </PageContainer>
  );
}
