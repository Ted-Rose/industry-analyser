import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
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
      renderDashboard();
      // Summary cards ('5.98 €' also shows in the money columns).
      expect(
        (await screen.findAllByText('5.98 €')).length,
      ).toBeGreaterThan(0);
      const summary = screen.getByTestId('summary');
      // The three StatCards of the old .summary row.
      expect(
        summary.firstElementChild?.children,
      ).toHaveLength(3);
      expect(
        within(summary).getByText('Total spend'),
      ).toBeInTheDocument();
      expect(
        within(summary).getByText('Receipts'),
      ).toBeInTheDocument();
      // By-month row — 'F Y' like the template, not raw ISO.
      // (Every cell renders twice: desktop table + mobile card.)
      expect(
        screen.getAllByText('February 2026').length,
      ).toBeGreaterThan(0);
      // Category row and all-receipts row.
      expect(
        screen.getAllByText('Uncategorized').length,
      ).toBeGreaterThan(0);
      expect(
        screen.getAllByText('2-999888').length,
      ).toBeGreaterThan(0);
      expect(
        screen.getAllByText('5.98 EUR').length,
      ).toBeGreaterThan(0);
      expect(
        screen.getAllByText('Rimi Akropolis').length,
      ).toBeGreaterThan(0);
      // Expandable rows: the category's top-items table and the
      // receipt's item table hide behind the chevron toggles —
      // aria-expanded flips and the content lands in the
      // colSpan row (and inside the mobile card).
      const toggles = screen.getAllByRole('button', {
        name: 'Expand row',
      });
      expect(toggles.length).toBeGreaterThanOrEqual(2);
      for (const toggle of toggles) {
        expect(toggle).toHaveAttribute(
          'aria-expanded',
          'false',
        );
        fireEvent.click(toggle);
        expect(toggle).toHaveAttribute(
          'aria-expanded',
          'true',
        );
      }
      // 'Piens' in both expanded bodies, each rendered twice
      // (desktop colSpan row + mobile in-card expansion).
      expect(screen.getAllByText('Piens')).toHaveLength(4);
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
    await screen.findAllByText('2-999888');
    mockedFetch.mockClear();
    fireEvent.click(
      screen.getByRole('button', { name: 'Last 12 months' }),
    );
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    expect(mockedFetch).toHaveBeenCalledWith({
      dateFrom: null,
      dateTo: null,
    });
  });

  it('"Last month" applies the server-provided preset', async () => {
    renderDashboard();
    await screen.findAllByText('2-999888');
    mockedFetch.mockClear();
    fireEvent.click(
      screen.getByRole('button', { name: 'Last month' }),
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
