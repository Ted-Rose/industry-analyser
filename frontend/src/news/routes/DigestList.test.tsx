import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';
import DigestList from './DigestList';
import { apiGet } from '../../shared/api/client';
import { resetAudioForTests } from '../audio';
import type { DigestListOut } from '../api';

vi.mock('../../shared/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  getCsrfToken: () => undefined,
}));

const mockedApiGet = vi.mocked(apiGet);

const ANCHOR = '2026-11-04';

function makeList(overrides: Partial<DigestListOut> = {}): DigestListOut {
  return {
    digests: [{ date: ANCHOR, items: [] }],
    period: 'week',
    anchor_date: ANCHOR,
    range_start: '2026-10-29',
    range_end: ANCHOR,
    min_date: '2026-10-01',
    max_date: ANCHOR,
    ...overrides,
  };
}

/** Server-side degradation: malformed/missing values fall back
 *  to the week window ending on the newest digest — same rule
 *  as news.api.list_digests. */
function serverEcho(url: string): DigestListOut {
  const params = new URL(url, 'http://test').searchParams;
  const rawDate = params.get('date');
  const date = rawDate && /^\d{4}-\d{2}-\d{2}$/.test(rawDate)
    ? rawDate
    : ANCHOR;
  const rawPeriod = params.get('period');
  const period =
    rawPeriod === 'day' || rawPeriod === 'week' || rawPeriod === 'all'
      ? rawPeriod
      : 'week';
  const weekStart = new Date(
    Date.parse(`${date}T00:00:00Z`) - 6 * 86400000,
  )
    .toISOString()
    .slice(0, 10);
  const rangeStart =
    period === 'all'
      ? '2026-10-01'
      : period === 'day'
        ? date
        : weekStart;
  return makeList({
    anchor_date: date,
    period,
    range_start: rangeStart,
    range_end: period === 'all' ? ANCHOR : date,
  });
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="loc">{location.search}</div>;
}

function renderAt(entry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <QueryClientProvider client={queryClient}>
        <DigestList />
        <LocationProbe />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

function currentSearch(): string {
  return screen.getByTestId('loc').textContent ?? '';
}

beforeEach(() => {
  resetAudioForTests();
  mockedApiGet.mockReset();
  mockedApiGet.mockImplementation((url: string) =>
    Promise.resolve(serverEcho(url)),
  );
});

describe('DigestList URL filters', () => {
  it('writes the effective date and period to a bare URL',
    async () => {
      renderAt('/');
      await waitFor(() =>
        expect(currentSearch()).toBe(
          `?date=${ANCHOR}&period=week`,
        ),
      );
    });

  it('normalizes malformed params to the server-echoed values',
    async () => {
      renderAt('/?date=garbage&period=bogus');
      await waitFor(() =>
        expect(currentSearch()).toBe(
          `?date=${ANCHOR}&period=week`,
        ),
      );
    });

  it('leaves a valid filter URL untouched (no extra fetch)',
    async () => {
      renderAt('/?date=2026-10-20&period=day');
      await screen.findByText(ANCHOR);
      expect(currentSearch()).toBe('?date=2026-10-20&period=day');
      // A normalization rewrite would change the query key and
      // trigger a second fetch — one call means none happened.
      expect(mockedApiGet).toHaveBeenCalledTimes(1);
    });

  it('puts a picked date into the URL', async () => {
    renderAt('/');
    await waitFor(() =>
      expect(currentSearch()).toContain('period=week'),
    );
    fireEvent.change(screen.getByLabelText('Datums'), {
      target: { value: '2026-10-15' },
    });
    await waitFor(() =>
      expect(currentSearch()).toBe('?date=2026-10-15&period=week'),
    );
  });

  it('puts a picked period into the URL', async () => {
    renderAt('/');
    await waitFor(() =>
      expect(currentSearch()).toContain('period=week'),
    );
    fireEvent.click(screen.getByRole('radio', { name: 'Visi' }));
    await waitFor(() =>
      expect(currentSearch()).toBe(`?date=${ANCHOR}&period=all`),
    );
  });
});
