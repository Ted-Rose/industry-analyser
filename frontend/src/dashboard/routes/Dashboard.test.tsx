import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Dashboard from './Dashboard';
import { apiGet } from '../../shared/api/client';
import type { DashboardOut } from '../api';

vi.mock('../../shared/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  getCsrfToken: () => undefined,
}));

const mockedApiGet = vi.mocked(apiGet);

function makeDashboard(
  overrides: Partial<DashboardOut> = {},
): DashboardOut {
  return {
    jobs: [
      {
        job: {
          slug: 'fetcher.vacancies',
          description: '',
          is_enabled: true,
        },
        cycle_key: '2026-W02',
        item_total: 4,
        item_active: 4,
        cycle_done: 2,
        cycle_failed: 0,
        progress_pct: 50,
        running: false,
        last_run: {
          id: 7,
          status: 'SUCCESS',
          executed_by: 'local',
          started_at: '2026-01-05T10:00:00Z',
          completed_at: '2026-01-05T10:05:23Z',
          duration_seconds: 323,
        },
      },
    ],
    rows: [
      {
        day: '2026-01-05',
        job_slug: 'fetcher.vacancies',
        run_count: 2,
        success_count: 1,
        partial_count: 1,
        failed_count: 0,
        abandoned_count: 0,
        avg_duration_seconds: 323,
      },
    ],
    totals: {
      run_count: 2,
      success_count: 1,
      partial_count: 1,
      failed_count: 0,
      abandoned_count: 0,
      avg_duration_seconds: 323,
    },
    date_from: '2025-12-07',
    date_to: '2026-01-05',
    ...overrides,
  };
}

function renderDashboard(entry = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <QueryClientProvider client={queryClient}>
        <Dashboard />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('Dashboard', () => {
  it('renders the jobs and day x job tables', async () => {
    mockedApiGet.mockResolvedValue(makeDashboard());
    renderDashboard();
    expect(await screen.findByText('SUCCESS')).toBeInTheDocument();
    // The slug renders in both the jobs and daily-runs tables.
    expect(
      screen.getAllByText('fetcher.vacancies'),
    ).toHaveLength(2);
    // Progress bar + done/active text.
    expect(screen.getByText(/2\/4/)).toBeInTheDocument();
    // Daily table row — rendered via DATE_FORMAT like {{ row.day }}
    // did, not raw ISO.
    expect(screen.getByText('Jan. 5, 2026')).toBeInTheDocument();
    // Totals subtitle.
    expect(
      screen.getByText(/2 runs \(1 success, 1 partial/),
    ).toBeInTheDocument();
  });

  it('passes the template-era ?from/&to= params to the API', async () => {
    mockedApiGet.mockResolvedValue(makeDashboard({ rows: [] }));
    renderDashboard('/?from=2026-01-01&to=2026-01-10');
    await waitFor(() => {
      expect(mockedApiGet).toHaveBeenCalledWith(
        '/api/dashboard/?date_from=2026-01-01&date_to=2026-01-10',
      );
    });
  });

  it('shows the empty states when nothing is recorded', async () => {
    mockedApiGet.mockResolvedValue(
      makeDashboard({ jobs: [], rows: [] }),
    );
    renderDashboard();
    expect(
      await screen.findByText('No jobs recorded yet.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('No runs in this range.'),
    ).toBeInTheDocument();
  });
});
