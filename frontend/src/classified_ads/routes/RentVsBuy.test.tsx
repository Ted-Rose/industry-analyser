import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import RentVsBuy from './RentVsBuy';
import { apiGet } from '../../shared/api/client';
import type {
  RentVsBuyRankedOut,
  RentVsBuyRankedRowOut,
} from '../api';

vi.mock('../../shared/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  getCsrfToken: () => undefined,
}));

const mockedApiGet = vi.mocked(apiGet);

function makeRow(
  overrides: Partial<RentVsBuyRankedRowOut> = {},
): RentVsBuyRankedRowOut {
  return {
    region: { id: 7, name: 'Ķengarags' },
    region_label: 'Rīga / Ķengarags',
    property_type: 'Panelai',
    is_residual: false,
    n_rent_ads: 30,
    n_sale_ads: 25,
    median_monthly_rent: 400,
    median_total_price: 60000,
    months_to_buyout: 150,
    years_to_buyout: 12.5,
    gross_yield_pct: 8,
    median_monthly_rent_per_sqm: 8,
    median_sale_price_per_sqm: 1200,
    price_to_rent_ratio_per_sqm: 150,
    median_size_rent: 50,
    median_size_sale: 52,
    size_comparable: true,
    n_paired_properties: 0,
    paired_months_to_buyout: null,
    ...overrides,
  };
}

function makeOut(
  overrides: Partial<RentVsBuyRankedOut> = {},
): RentVsBuyRankedOut {
  return {
    kind: 'apartment',
    days: 30,
    min_ads: 15,
    date_from: '2024-05-01',
    date_to: '2024-05-31',
    results: [makeRow()],
    residual: [],
    n_residual_cells: 0,
    ...overrides,
  };
}

function renderPage(entry = '/rent-vs-buy') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <QueryClientProvider client={queryClient}>
        <RentVsBuy />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

function calledUrls(): string[] {
  return mockedApiGet.mock.calls.map((call) => String(call[0]));
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiGet.mockResolvedValue(makeOut());
});

describe('RentVsBuy', () => {
  it('defaults to apartments with no extra params', async () => {
    renderPage();
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    const url = calledUrls()[0];
    expect(url).toContain(
      '/api/classified-ads/regions/rent-vs-buy/ranked/',
    );
    expect(url).toContain('kind=apartment');
    expect(url).not.toContain('include_residual');
    // 30 is the API default — it doesn't ride the query.
    expect(url).not.toContain('days=');
  });

  it('passes kind/days/min_ads/residual params through', async () => {
    renderPage('/rent-vs-buy?kind=house&days=90&min_ads=5&residual=1');
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    const url = calledUrls()[0];
    expect(url).toContain('kind=house');
    expect(url).toContain('days=90');
    expect(url).toContain('min_ads=5');
    expect(url).toContain('include_residual=true');
  });

  it('renders ranked rows with the buyout metric', async () => {
    renderPage();
    await screen.findByText('Rīga / Ķengarags');
    expect(screen.getByText('Panelai')).toBeInTheDocument();
    expect(screen.getByText('150.0')).toBeInTheDocument();
    expect(screen.getByText('12.5')).toBeInTheDocument();
  });

  it('flags rows whose sizes are not comparable', async () => {
    mockedApiGet.mockResolvedValue(
      makeOut({
        results: [makeRow({ size_comparable: false })],
      }),
    );
    renderPage();
    const cell = await screen.findByText('Rīga / Ķengarags');
    expect(cell.closest('tr')).toHaveClass('text-muted');
  });

  it('renders residual rows only when returned', async () => {
    mockedApiGet.mockResolvedValue(
      makeOut({
        residual: [
          makeRow({
            region_label: 'Rīga',
            is_residual: true,
            region: { id: 1, name: 'Rīga' },
          }),
        ],
      }),
    );
    renderPage('/rent-vs-buy?residual=1');
    await screen.findByText(/Residual regions/);
    expect(screen.getByText('Rīga')).toBeInTheDocument();
  });

  it('shows the caveat note under the table', async () => {
    renderPage();
    await screen.findByText('Rīga / Ķengarags');
    expect(screen.getByText(/Caveats:/)).toBeInTheDocument();
    expect(screen.getByText(/room-share/)).toBeInTheDocument();
    expect(
      screen.getByText(/net yield is typically/),
    ).toBeInTheDocument();
  });

  it('renders the yield column after Years', async () => {
    renderPage();
    await screen.findByText('Rīga / Ķengarags');
    expect(screen.getByText('Yield %')).toBeInTheDocument();
    // 1200 / 150 months = 8.0%.
    expect(screen.getByText('8.0')).toBeInTheDocument();
  });

  it('is null-safe on the yield column', async () => {
    mockedApiGet.mockResolvedValue(
      makeOut({
        results: [makeRow({ gross_yield_pct: null })],
      }),
    );
    renderPage();
    const cell = await screen.findByText('Rīga / Ķengarags');
    expect(cell.closest('tr')).toHaveTextContent('—');
  });

  it('renders the group segmented control', async () => {
    renderPage();
    expect(
      screen.getByRole('link', { name: 'By type' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'By region' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'By rooms' }),
    ).toBeInTheDocument();
  });

  it('sends group_by from the group URL param', async () => {
    renderPage('/rent-vs-buy?group=region');
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    expect(calledUrls()[0]).toContain('group_by=region');
  });

  it('sends no group_by by default', async () => {
    renderPage();
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    expect(calledUrls()[0]).not.toContain('group_by');
  });

  it('labels the group column per mode', async () => {
    renderPage('/rent-vs-buy?group=rooms');
    await screen.findByText('Rīga / Ķengarags');
    expect(screen.getByText('Rooms')).toBeInTheDocument();
  });

  it('flags paired medians under five pairs with †', async () => {
    mockedApiGet.mockResolvedValue(
      makeOut({
        results: [
          makeRow({
            n_paired_properties: 3,
            paired_months_to_buyout: 90,
          }),
        ],
      }),
    );
    renderPage();
    const cell = await screen.findByText('Rīga / Ķengarags');
    expect(cell.closest('tr')).toHaveTextContent('90.0 †');
  });

  it('does not flag paired medians at five or more pairs', async () => {
    mockedApiGet.mockResolvedValue(
      makeOut({
        results: [
          makeRow({
            n_paired_properties: 5,
            paired_months_to_buyout: 90,
          }),
        ],
      }),
    );
    renderPage();
    const cell = await screen.findByText('Rīga / Ķengarags');
    expect(cell.closest('tr')).toHaveTextContent('90.0');
    expect(cell.closest('tr')).not.toHaveTextContent('†');
  });

  it('hints at hidden residual cells from n_residual_cells', async () => {
    mockedApiGet.mockResolvedValue(
      makeOut({ n_residual_cells: 4, residual: [] }),
    );
    renderPage();
    await screen.findByText(
      /4 more cells pass the gate in residual regions/,
    );
  });

  it('hides the residual hint when residual rows are shown', async () => {
    mockedApiGet.mockResolvedValue(
      makeOut({
        n_residual_cells: 1,
        residual: [
          makeRow({
            region_label: 'Rīga',
            is_residual: true,
            region: { id: 1, name: 'Rīga' },
          }),
        ],
      }),
    );
    renderPage('/rent-vs-buy?residual=1');
    await screen.findByText(/Residual regions/);
    expect(
      screen.queryByText(/more cells pass the gate/),
    ).toBeNull();
  });

  it('defaults the days input to 90 for houses', async () => {
    renderPage('/rent-vs-buy?kind=house');
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    expect(screen.getByLabelText('Window (days)')).toHaveValue(90);
    // The kind-aware default is sent too — the displayed filter
    // must match the actual data window.
    expect(calledUrls()[0]).toContain('days=90');
  });
});
