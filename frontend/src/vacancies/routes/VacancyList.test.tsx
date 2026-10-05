import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import VacancyList from './VacancyList';
import {
  apiDelete,
  apiGet,
  apiPost,
} from '../../shared/api/client';
import type {
  SavedFilterOut,
  VacanciesOut,
  VacancyOut,
} from '../api';

vi.mock('../../shared/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  getCsrfToken: () => undefined,
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPost = vi.mocked(apiPost);
const mockedApiDelete = vi.mocked(apiDelete);

function makeVacancy(overrides: Partial<VacancyOut> = {}): VacancyOut {
  return {
    id: '11111111-1111-1111-1111-111111111111',
    title: 'Python developer',
    url: 'https://www.cv.lv/lv/vacancy/1',
    company_id: '22222222-2222-2222-2222-222222222222',
    company_name: 'Acme SIA',
    company_preference: null,
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

function makeSavedFilter(
  overrides: Partial<SavedFilterOut> = {},
): SavedFilterOut {
  return {
    id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    name: 'Python IT',
    include_keywords: ['python'],
    exclude_keywords: ['senior'],
    include_industries: ['it'],
    show_active_only: true,
    company_filter: 'all',
    ...overrides,
  };
}

/** The shell's #spa-bootstrap json_script — must exist before
 *  render; useBootstrap() reads it once at mount. */
function setBootstrap(payload: unknown) {
  let el = document.getElementById('spa-bootstrap');
  if (!el) {
    el = document.createElement('script');
    el.id = 'spa-bootstrap';
    el.setAttribute('type', 'application/json');
    document.body.appendChild(el);
  }
  el.textContent = JSON.stringify(payload);
}

/** apiGet router: the filters list for the authed URL, the vacancy
 *  payload for everything else. */
function mockAuthedGet(filters: SavedFilterOut[]) {
  mockedApiGet.mockImplementation((url) =>
    Promise.resolve(
      String(url).startsWith('/api/vacancies/filters/')
        ? filters
        : makeVacancies(),
    ),
  );
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
  mockedApiPost.mockReset();
  mockedApiDelete.mockReset();
  // No stale bootstrap between tests — anonymous is the default.
  document.getElementById('spa-bootstrap')?.remove();
});

afterEach(() => {
  vi.restoreAllMocks();
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

  it('renders a badge next to liked/disliked company names', async () => {
    mockedApiGet.mockResolvedValue(
      makeVacancies({
        vacancies: [
          makeVacancy({ company_preference: 'like' }),
          makeVacancy({
            id: '33333333-3333-3333-3333-333333333333',
            title: 'Java developer',
            company_name: 'Bad Corp',
            company_preference: 'dislike',
          }),
        ],
      }),
    );
    renderList('/vacancies');
    expect(await screen.findByText('liked')).toBeInTheDocument();
    expect(screen.getByText('disliked')).toBeInTheDocument();
  });
});

describe('VacancyList company filter', () => {
  it('hides the Companies selector for anonymous users', async () => {
    renderList('/vacancies?company_filter=liked');
    await screen.findByText('Python developer');
    expect(
      screen.queryByLabelText('Companies'),
    ).not.toBeInTheDocument();
    // The param still goes to the API — the server ignores it for
    // anonymous requests (treated as 'all').
    expect(calledUrls()[0]).toContain('company_filter=liked');
  });

  it('stages the selector and applies it on Search', async () => {
    setBootstrap({ user: 'alice' });
    mockAuthedGet([]);
    renderList('/vacancies');
    await screen.findByText('Python developer');

    const select = screen.getByLabelText('Companies');
    fireEvent.change(select, { target: { value: 'liked' } });
    // Staged — no refetch until Search.
    expect(
      calledUrls().some((u) => u.includes('company_filter')),
    ).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() =>
      expect(
        calledUrls().some((u) =>
          u.includes('company_filter=liked'),
        ),
      ).toBe(true),
    );
  });

  it('drops the param when the selector goes back to all', async () => {
    setBootstrap({ user: 'alice' });
    mockAuthedGet([]);
    renderList('/vacancies?company_filter=disliked');
    await screen.findByText('Python developer');
    const listCalls = () =>
      calledUrls().filter((u) => !u.includes('/filters/'));
    expect(listCalls()[0]).toContain('company_filter=disliked');

    fireEvent.change(screen.getByLabelText('Companies'), {
      target: { value: 'all' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() =>
      expect(listCalls().length).toBeGreaterThan(1),
    );
    expect(listCalls()[1]).not.toContain('company_filter');
  });

  it('falls back to all on an invalid param value', async () => {
    setBootstrap({ user: 'alice' });
    mockAuthedGet([]);
    renderList('/vacancies?company_filter=bogus');
    await screen.findByText('Python developer');
    expect(calledUrls()[0]).not.toContain('company_filter');
    expect(screen.getByLabelText('Companies')).toHaveValue('all');
  });
});

describe('VacancyList saved filters', () => {
  it('hides the bar (and never calls the authed API) when the bootstrap user is null', async () => {
    setBootstrap({ user: null });
    renderList('/vacancies');
    await screen.findByText('Python developer');
    expect(
      screen.queryByLabelText('Saved filters'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Save current' }),
    ).not.toBeInTheDocument();
    // The only GET fired is the public vacancy list — an authed
    // /filters/ call would 401 and bounce the page to login.
    for (const url of calledUrls()) {
      expect(url).not.toContain('/api/vacancies/filters/');
    }
  });

  it('writes the preset params into the URL on select', async () => {
    setBootstrap({ user: 'alice' });
    mockAuthedGet([makeSavedFilter()]);
    renderList('/vacancies?page=2');
    await screen.findByText('Python developer');
    await waitFor(() =>
      expect(calledUrls()).toContain('/api/vacancies/filters/'),
    );

    fireEvent.change(screen.getByLabelText('Saved filters'), {
      target: { value: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' },
    });

    await waitFor(() =>
      expect(
        calledUrls().some((u) =>
          u.includes('include_keywords=python'),
        ),
      ).toBe(true),
    );
    const applied = calledUrls().find((u) =>
      u.includes('include_keywords=python'),
    )!;
    expect(applied).toContain('exclude_keywords=senior');
    expect(applied).toContain('include_industries=it');
    expect(applied).toContain('show_active_only=1');
    // Selecting a preset lands on page 1 — the stale ?page=2 goes.
    expect(applied).not.toContain('page=');

    // The staged checkboxes re-sync from the rewritten URL (once
    // the refetch lands — the list shows "Loading…" meanwhile).
    await waitFor(() =>
      expect(screen.getAllByLabelText('python')[0]).toBeChecked(),
    );
    const [, excludePython] = screen.getAllByLabelText('python');
    expect(excludePython).not.toBeChecked();
    const [includeDjango] = screen.getAllByLabelText('django');
    expect(includeDjango).not.toBeChecked();
    expect(screen.getByLabelText('it')).toBeChecked();
    expect(screen.getByLabelText('Active only')).toBeChecked();
    // …and the select itself shows the matching preset.
    expect(screen.getByLabelText('Saved filters')).toHaveValue(
      'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    );
  });

  it('deletes the selected preset', async () => {
    setBootstrap({ user: 'alice' });
    mockAuthedGet([makeSavedFilter()]);
    mockedApiDelete.mockResolvedValue(undefined);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    // Entry params match the preset — derived selection shows it,
    // so the per-preset buttons render.
    renderList(
      '/vacancies?include_keywords=python' +
        '&exclude_keywords=senior&include_industries=it' +
        '&show_active_only=1',
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'Delete' }),
    );
    await waitFor(() =>
      expect(mockedApiDelete).toHaveBeenCalledWith(
        '/api/vacancies/filters/' +
          'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/',
      ),
    );
    // Invalidation refetches the preset list.
    await waitFor(() =>
      expect(
        calledUrls().filter((u) => u === '/api/vacancies/filters/'),
      ).toHaveLength(2),
    );
  });

  it('saves the applied URL params, not the staged draft', async () => {
    setBootstrap({ user: 'alice' });
    mockAuthedGet([]);
    mockedApiPost.mockResolvedValue(
      makeSavedFilter({
        id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
        name: 'My filter',
      }),
    );
    vi.spyOn(window, 'prompt').mockReturnValue('My filter');
    renderList(
      '/vacancies?include_keywords=python&show_active_only=1&page=3',
    );
    await screen.findByText('Python developer');

    // Stage an extra keyword without pressing Search — it must NOT
    // be part of the saved preset.
    const [includeDjango] = screen.getAllByLabelText('django');
    fireEvent.click(includeDjango);

    fireEvent.click(
      screen.getByRole('button', { name: 'Save current' }),
    );

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled());
    expect(mockedApiPost).toHaveBeenCalledWith(
      '/api/vacancies/filters/',
      {
        name: 'My filter',
        include_keywords: ['python'],
        exclude_keywords: [],
        include_industries: [],
        show_active_only: true,
        company_filter: 'all',
      },
    );
  });

  it('writes a preset company_filter into the URL on select', async () => {
    setBootstrap({ user: 'alice' });
    mockAuthedGet([makeSavedFilter({ company_filter: 'liked' })]);
    renderList('/vacancies');
    await screen.findByText('Python developer');
    await waitFor(() =>
      expect(calledUrls()).toContain('/api/vacancies/filters/'),
    );

    fireEvent.change(screen.getByLabelText('Saved filters'), {
      target: { value: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' },
    });

    await waitFor(() =>
      expect(
        calledUrls().some((u) =>
          u.includes('company_filter=liked'),
        ),
      ).toBe(true),
    );
    expect(screen.getByLabelText('Companies')).toHaveValue('liked');
  });
});
