import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import AdsTable from './AdsTable';
import { apiGet } from '../../shared/api/client';
import type { AdOut, AdsTableOut } from '../api';

vi.mock('../../shared/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  getCsrfToken: () => undefined,
}));

const mockedApiGet = vi.mocked(apiGet);

function makeAd(overrides: Partial<AdOut> = {}): AdOut {
  return {
    id: 1,
    ad_id: 'abc123',
    link: 'https://ss.com/msg/abc123',
    district: 'Centrs',
    street_name: 'Čaka iela',
    street_no: '133',
    rooms: 2,
    size: 50,
    post_date: '2024-05-01',
    days_active: 7,
    deal: 'Rent',
    project: null,
    floor: 3,
    max_floor: 5,
    floors: null,
    land_area_sqm: null,
    price_per_sqm: 6,
    total_price: 300,
    monthly_price: 300,
    monthly_price_per_sqm: 6,
    ...overrides,
  };
}

function makeTable(overrides: Partial<AdsTableOut> = {}): AdsTableOut {
  return {
    ads: [makeAd()],
    page: 1,
    num_pages: 1,
    total_count: 1,
    has_next: false,
    has_previous: false,
    districts: ['Centrs', 'Āgenskalns'],
    room_choices: [1, 2, 3],
    filters: {
      district: '',
      rooms: null,
      price_min: null,
      price_max: null,
    },
    ...overrides,
  };
}

function renderTable(entry = '/apartments/rent') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <QueryClientProvider client={queryClient}>
        <AdsTable kind="apartment" deal="rent" />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

/** URLs apiGet was called with, most recent last. */
function calledUrls(): string[] {
  return mockedApiGet.mock.calls.map((call) => String(call[0]));
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiGet.mockResolvedValue(makeTable());
});

describe('AdsTable', () => {
  it('passes URL filter params through to the API', async () => {
    renderTable(
      '/apartments/rent?district=Centrs&rooms=2&price_min=5' +
        '&price_max=10&page=2',
    );
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    const url = calledUrls()[0];
    expect(url).toContain('/api/classified-ads/ads/');
    expect(url).toContain('kind=apartment');
    expect(url).toContain('deal=rent');
    expect(url).toContain('district=Centrs');
    expect(url).toContain('rooms=2');
    expect(url).toContain('price_min=5');
    expect(url).toContain('price_max=10');
    expect(url).toContain('page=2');
  });

  it('drops non-numeric filters instead of 422ing', async () => {
    renderTable('/apartments/rent?price_min=abc&page=x');
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    const url = calledUrls()[0];
    expect(url).not.toContain('price_min');
    expect(url).not.toContain('page=');
  });

  it('renders rent rows with monthly prices', async () => {
    renderTable();
    await screen.findByText('Čaka iela 133');
    expect(screen.getByText('Apartments for Rent')).toBeInTheDocument();
    expect(screen.getByText('1 result')).toBeInTheDocument();
    expect(screen.getByText('6.00')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View' })).toHaveAttribute(
      'href',
      'https://ss.com/msg/abc123',
    );
  });

  it('stages filter edits until Filter is pressed', async () => {
    renderTable();
    await screen.findByText('Čaka iela 133');
    expect(mockedApiGet).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText('District'), {
      target: { value: 'Āgenskalns' },
    });
    expect(mockedApiGet).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Filter' }));
    await waitFor(() =>
      expect(mockedApiGet).toHaveBeenCalledTimes(2),
    );
    expect(calledUrls()[1]).toContain('district=%C4%80genskalns');
    // Filtering lands back on page 1 — no page param.
    expect(calledUrls()[1]).not.toContain('page=');
  });

  it('renders the empty state and an error state', async () => {
    mockedApiGet.mockResolvedValue(makeTable({ ads: [], total_count: 0 }));
    const { unmount } = renderTable();
    await screen.findByText('No ads match your filters.');

    unmount();
    mockedApiGet.mockRejectedValue(new Error('boom'));
    renderTable();
    await screen.findByText(/Failed to load ads/);
  });
});
