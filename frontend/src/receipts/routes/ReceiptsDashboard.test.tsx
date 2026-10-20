import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import {
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query';
import ReceiptsDashboard from './ReceiptsDashboard';
import { fetchReceiptsDashboard } from '../api';
import type { ReceiptsDashboardOut } from '../api';

vi.mock('../api', () => ({
  fetchReceiptsDashboard: vi.fn(),
}));

const mockedFetch = vi.mocked(fetchReceiptsDashboard);

function makeDashboard(
  overrides: Partial<ReceiptsDashboardOut> = {},
): ReceiptsDashboardOut {
  return {
    owner_exists: true,
    summary: { total_spend: 5.98, receipt_count: 1 },
    item_count: 1,
    months: 12,
    date_from: '2025-02-15',
    date_to: '2026-02-15',
    last_month_from: '2026-01-01',
    last_month_to: '2026-01-31',
    monthly: [
      {
        month: '2026-02-01T00:00:00Z',
        receipt_count: 1,
        total: 5.98,
      },
    ],
    by_store: [
      {
        store_name: 'Rimi Akropolis',
        receipt_count: 1,
        total: 5.98,
      },
    ],
    categories: [
      {
        name: 'Uncategorized',
        item_count: 1,
        total: 5.98,
        monthly_avg: 0.5,
        top_items: [
          { raw_name: 'Piens', item_count: 1, total: 5.98 },
        ],
      },
    ],
    receipts: [
      {
        id: 1,
        purchased_at: '2026-02-15T14:32:00Z',
        store_name: 'Rimi Akropolis',
        document_number: '2-999888',
        total: 5.98,
        currency: 'EUR',
        parse_status_label: 'Parsed',
        item_count: 1,
        items: [
          {
            raw_name: 'Piens',
            is_fee: false,
            quantity: 1,
            unit: 'gab',
            unit_price: 5.98,
            discount: 0,
            total: 5.98,
          },
        ],
      },
    ],
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
        <ReceiptsDashboard />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockedFetch.mockReset();
  mockedFetch.mockResolvedValue(makeDashboard());
});

describe('ReceiptsDashboard', () => {
  it('renders summary cards, a category and a receipt row',
    async () => {
      const { container } = renderDashboard();
      // Summary cards ('5.98 €' also shows in the money columns).
      expect(
        (await screen.findAllByText('5.98 €')).length,
      ).toBeGreaterThan(0);
      const cards = container.querySelectorAll('.summary .card');
      expect(cards).toHaveLength(3);
      expect(cards[1]).toHaveTextContent('Receipts');
      // By-month row — 'F Y' like the template, not raw ISO.
      expect(screen.getByText('February 2026')).toBeInTheDocument();
      // Category row (name appears twice: category + all-receipts
      // store cells don't collide) and its top item.
      expect(screen.getByText('Uncategorized')).toBeInTheDocument();
      // All-receipts row.
      expect(screen.getByText('2-999888')).toBeInTheDocument();
      expect(screen.getByText('5.98 EUR')).toBeInTheDocument();
      expect(
        screen.getAllByText('Rimi Akropolis').length,
      ).toBeGreaterThan(0);
      // Per-receipt <details> item table.
      expect(screen.getAllByText('Piens')).toHaveLength(2);
    });

  it('passes ?date_from=&date_to= through to the API', async () => {
    renderDashboard('/?date_from=2026-01-01&date_to=2026-01-31');
    await waitFor(() =>
      expect(mockedFetch).toHaveBeenCalledWith({
        dateFrom: '2026-01-01',
        dateTo: '2026-01-31',
      }),
    );
  });

  it('"Last 12 months" clears the range params', async () => {
    renderDashboard('/?date_from=2026-01-01&date_to=2026-01-31');
    await screen.findByText('2-999888');
    mockedFetch.mockClear();
    fireEvent.click(
      screen.getByRole('link', { name: 'Last 12 months' }),
    );
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    expect(mockedFetch).toHaveBeenCalledWith({
      dateFrom: null,
      dateTo: null,
    });
  });

  it('"Last month" applies the server-provided preset', async () => {
    renderDashboard();
    await screen.findByText('2-999888');
    mockedFetch.mockClear();
    fireEvent.click(
      screen.getByRole('link', { name: 'Last month' }),
    );
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    expect(mockedFetch).toHaveBeenCalledWith({
      dateFrom: '2026-01-01',
      dateTo: '2026-01-31',
    });
  });

  it('shows the no-owner notice when owner_exists is false',
    async () => {
      mockedFetch.mockResolvedValue(
        makeDashboard({
          owner_exists: false,
          monthly: [],
          by_store: [],
          categories: [],
          receipts: [],
        }),
      );
      renderDashboard();
      expect(
        await screen.findByText(/user "admin" does not exist/),
      ).toBeInTheDocument();
      expect(screen.getAllByText('No data.')).toHaveLength(3);
    });
});
