import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import VacancyList from './VacancyList';
import { apiGet } from '../../shared/api/client';
import type { VacanciesOut, VacancyOut } from '../api';

vi.mock('../../shared/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  getCsrfToken: () => undefined,
}));

const mockedApiGet = vi.mocked(apiGet);

function makeVacancy(overrides: Partial<VacancyOut> = {}): VacancyOut {
  return {
    id: '11111111-1111-1111-1111-111111111111',
    title: 'Python developer',
    url: 'https://www.cv.lv/lv/vacancy/1',
    company_id: '22222222-2222-2222-2222-222222222222',
    company_name: 'Acme SIA',
    salary_from: 1000,
    salary_to: 2000,
    application_deadline: '2030-07-01T10:00:00+03:00',
    last_seen: '2025-06-15T10:00:00+03:00',
    days_open: 10,
    keywords: ['python'],
    industries: ['it'],
    ...overrides,
  };
}

function makeVacancies(
  overrides: Partial<VacanciesOut> = {},
): VacanciesOut {
  return {
    vacancies: [makeVacancy()],
    page: 1,
    num_pages: 1,
    total_count: 1,
    start_index: 1,
    end_index: 1,
    has_next: false,
    has_previous: false,
    keywords: ['python', 'django'],
    industries: ['it'],
    ...overrides,
  };
}

function renderList(entry = '/vacancies') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <QueryClientProvider client={queryClient}>
        <VacancyList />
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
  mockedApiGet.mockResolvedValue(makeVacancies());
});

describe('VacancyList', () => {
  it('passes URL filter params through to the API', async () => {
    renderList(
      '/vacancies?include_keywords=python&show_active_only=1&page=2',
    );
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    const url = calledUrls()[0];
    expect(url).toContain('include_keywords=python');
    expect(url).toContain('show_active_only=1');
    expect(url).toContain('page=2');
  });

  it('checks the filters named in the URL', async () => {
    renderList('/vacancies?include_keywords=python');
    await screen.findByText('Python developer');
    // Both the include and the exclude list render 'python'; the
    // include one comes first in DOM order.
    const [includeBox, excludeBox] =
      screen.getAllByLabelText('python');
    expect(includeBox).toBeChecked();
    expect(excludeBox).not.toBeChecked();
    expect(screen.getByLabelText('Active only')).not.toBeChecked();
  });

  it('stages checkbox changes until Search is pressed', async () => {
    renderList('/vacancies');
    await screen.findByText('Python developer');
    expect(mockedApiGet).toHaveBeenCalledTimes(1);

    // Toggling a checkbox alone must not refetch — the template form
    // applied everything on submit.
    const [includeDjango] = screen.getAllByLabelText('django');
    fireEvent.click(includeDjango);
    expect(mockedApiGet).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() =>
      expect(mockedApiGet).toHaveBeenCalledTimes(2),
    );
    expect(calledUrls()[1]).toContain('include_keywords=django');
  });

  it('resets ?page when filters are reapplied', async () => {
    renderList('/vacancies?page=3');
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    expect(calledUrls()[0]).toContain('page=3');

    fireEvent.click(screen.getByLabelText('Active only'));
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() =>
      expect(mockedApiGet).toHaveBeenCalledTimes(2),
    );
    const url = calledUrls()[1];
    expect(url).toContain('show_active_only=1');
    expect(url).not.toContain('page=');
  });

  it('drops a non-numeric page param instead of sending it', async () => {
    renderList('/vacancies?page=abc');
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    expect(calledUrls()[0]).not.toContain('page=');
  });

  it('links a vacancy to its company detail route', async () => {
    renderList('/vacancies');
    const link = await screen.findByRole('link', {
      name: 'Acme SIA',
    });
    expect(link).toHaveAttribute(
      'href',
      '/companies/22222222-2222-2222-2222-222222222222',
    );
  });
});
