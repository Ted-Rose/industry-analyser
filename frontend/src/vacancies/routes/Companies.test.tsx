import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Companies from './Companies';
import { apiGet, apiPut } from '../../shared/api/client';
import type { CompaniesOut, CompanyOut } from '../api';

vi.mock('../../shared/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  getCsrfToken: () => undefined,
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPut = vi.mocked(apiPut);

function makeCompany(overrides: Partial<CompanyOut> = {}): CompanyOut {
  return {
    id: '22222222-2222-2222-2222-222222222222',
    name: 'Acme SIA',
    reg_code: '40103000000',
    about: 'We build payment infrastructure.',
    webpage_url: 'https://www.acme.example',
    needs_review: false,
    preference: null,
    vacancy_count: 5,
    open_count: 2,
    last_seen: '2025-06-15T10:00:00+03:00',
    identities: [
      {
        source: 'cv.lv',
        employer_id: 66466,
        portal_url: 'https://www.cv.lv/lv/search?employerId=66466',
      },
    ],
    ...overrides,
  };
}

function makeCompanies(
  overrides: Partial<CompaniesOut> = {},
): CompaniesOut {
  return {
    companies: [makeCompany()],
    page: 1,
    num_pages: 1,
    total_count: 1,
    start_index: 1,
    end_index: 1,
    has_next: false,
    has_previous: false,
    query: '',
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

function renderList(entry = '/companies') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <QueryClientProvider client={queryClient}>
        <Companies />
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
  mockedApiGet.mockResolvedValue(makeCompanies());
  mockedApiPut.mockReset();
  // No stale bootstrap between tests — anonymous is the default.
  document.getElementById('spa-bootstrap')?.remove();
});

describe('Companies', () => {
  it('passes q and page through to the API', async () => {
    renderList('/companies?q=acme&page=2');
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    const url = calledUrls()[0];
    expect(url).toContain('q=acme');
    expect(url).toContain('page=2');
  });

  it('applies the staged search on submit', async () => {
    renderList('/companies');
    await screen.findAllByText('Acme SIA');

    fireEvent.change(screen.getByPlaceholderText('Name or reg. code'), {
      target: { value: 'acme' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() =>
      expect(mockedApiGet).toHaveBeenCalledTimes(2),
    );
    expect(calledUrls()[1]).toContain('q=acme');
  });

  it('links the identity tag to the portal url', async () => {
    renderList('/companies');
    const links = await screen.findAllByRole('link', {
      name: 'cv.lv:66466',
    });
    // Both the desktop table and the mobile card render the tag.
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      expect(link).toHaveAttribute(
        'href',
        'https://www.cv.lv/lv/search?employerId=66466',
      );
      expect(link).toHaveAttribute('target', '_blank');
    }
  });

  it('renders a plain tag when the identity has no portal url', async () => {
    mockedApiGet.mockResolvedValue(
      makeCompanies({
        companies: [
          makeCompany({
            identities: [
              {
                source: 'example.com',
                employer_id: 1,
                portal_url: null,
              },
            ],
          }),
        ],
      }),
    );
    renderList('/companies');
    await screen.findAllByText('example.com:1');
    expect(
      screen.queryByRole('link', { name: 'example.com:1' }),
    ).not.toBeInTheDocument();
  });

  it('shows the company description and website link', async () => {
    renderList('/companies');
    await screen.findAllByText('We build payment infrastructure.');
    const siteLink = await screen.findByRole('link', {
      name: 'site ↗',
    });
    expect(siteLink).toHaveAttribute(
      'href',
      'https://www.acme.example',
    );
  });

  it('renders the mobile card layout alongside the table', async () => {
    const { container } = renderList('/companies');
    await screen.findAllByText('Acme SIA');
    expect(
      container.querySelector('.d-md-none'),
    ).toBeInTheDocument();
    expect(
      container.querySelector('.d-none.d-md-block table'),
    ).toBeInTheDocument();
  });

  it('hides the preference buttons for anonymous users', async () => {
    renderList('/companies');
    await screen.findAllByText('Acme SIA');
    expect(
      screen.queryByRole('button', { name: 'Like' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Dislike' }),
    ).not.toBeInTheDocument();
  });

  it('PUTs a like when a logged-in user clicks Like', async () => {
    setBootstrap({ user: 'alice' });
    renderList('/companies');
    // Both the desktop table and the mobile card render a pair.
    const likeButtons = await screen.findAllByRole('button', {
      name: 'Like',
    });
    expect(likeButtons.length).toBeGreaterThan(0);

    fireEvent.click(likeButtons[0]);
    await waitFor(() =>
      expect(mockedApiPut).toHaveBeenCalledWith(
        '/api/vacancies/companies/' +
          '22222222-2222-2222-2222-222222222222/preference/',
        { preference: 'like' },
      ),
    );
  });

  it('clears the preference when the active button is clicked', async () => {
    setBootstrap({ user: 'alice' });
    mockedApiGet.mockResolvedValue(
      makeCompanies({
        companies: [makeCompany({ preference: 'like' })],
      }),
    );
    renderList('/companies');
    const likeButtons = await screen.findAllByRole('button', {
      name: 'Like',
    });
    fireEvent.click(likeButtons[0]);
    await waitFor(() =>
      expect(mockedApiPut).toHaveBeenCalledWith(
        expect.any(String),
        { preference: null },
      ),
    );
  });

  it('shows an inline error when the preference PUT fails', async () => {
    setBootstrap({ user: 'alice' });
    mockedApiPut.mockRejectedValue(new Error('fetch failed'));
    renderList('/companies');
    const likeButtons = await screen.findAllByRole('button', {
      name: 'Like',
    });
    fireEvent.click(likeButtons[0]);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Network error');
  });

  it('links the company name to its detail route', async () => {
    renderList('/companies');
    const links = await screen.findAllByRole('link', {
      name: 'Acme SIA',
    });
    for (const link of links) {
      expect(link).toHaveAttribute(
        'href',
        '/companies/22222222-2222-2222-2222-222222222222',
      );
    }
  });
});
