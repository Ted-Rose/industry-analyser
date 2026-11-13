import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import DigestDetail from './DigestDetail';
import { apiGet } from '../../shared/api/client';
import type {
  DigestDetailOut,
  DigestExtraOut,
} from '../api';

vi.mock('../../shared/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  getCsrfToken: () => undefined,
}));

const mockedApiGet = vi.mocked(apiGet);

const DATE = '2026-11-04';

function makeItem(rank: number, headline: string) {
  return {
    rank,
    headline,
    rationale: '1 outlet: a',
    topic_name: null,
    articles: [
      {
        title: `${headline} raksts`,
        link: `https://a.lv/${rank}`,
        source_name: 'A',
      },
    ],
  };
}

function makeDetail(
  overrides: Partial<DigestDetailOut> = {},
): DigestDetailOut {
  return {
    date: DATE,
    has_more: true,
    items: [makeItem(1, 'Ziņa viens'), makeItem(2, 'Ziņa divi')],
    ...overrides,
  };
}

/** Server echo for /extra/?offset=N — one page of `size`
 *  extra rows whose ranks continue after the stored items,
 *  then the well runs dry unless `hasNext` says otherwise. */
function extraPage(
  url: string,
  size = 2,
  hasNext = false,
): DigestExtraOut {
  const offset = Number(
    new URL(url, 'http://test').searchParams.get('offset'),
  );
  const items = Array.from({ length: size }, (_, i) =>
    makeItem(3 + offset + i, `Papildu ${offset + i}`),
  );
  return { items, offset, has_next: hasNext };
}

function renderAt(entry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <QueryClientProvider client={queryClient}>
        <Routes>
          <Route path="/:date" element={<DigestDetail />} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiGet.mockImplementation((url: string) =>
    Promise.resolve(
      url.includes('/extra/') ? extraPage(url) : makeDetail(),
    ),
  );
});

describe('DigestDetail', () => {
  it('renders the stored items without extra fetches', async () => {
    renderAt(`/${DATE}`);
    expect(
      await screen.findByText('1. Ziņa viens'),
    ).toBeInTheDocument();
    expect(mockedApiGet).toHaveBeenCalledTimes(1);
    expect(mockedApiGet.mock.calls[0][0]).toBe(
      `/api/news/digests/${DATE}/`,
    );
  });

  it('appends extra stories on Load more and hides the button when exhausted', async () => {
    renderAt(`/${DATE}`);
    const button = await screen.findByRole('button', {
      name: 'Ielādēt vēl 20 ziņas',
    });
    fireEvent.click(button);
    // Ranks continue after the stored top-N.
    expect(
      await screen.findByText('3. Papildu 0'),
    ).toBeInTheDocument();
    // has_next false → the button unmounts.
    await waitFor(() =>
      expect(
        screen.queryByRole('button', {
          name: 'Ielādēt vēl 20 ziņas',
        }),
      ).not.toBeInTheDocument(),
    );
    const requested = mockedApiGet.mock.calls.map(
      (call) => call[0],
    );
    expect(requested).toContain(
      `/api/news/digests/${DATE}/extra/?offset=0`,
    );
  });

  it('pages through extras with fetchNextPage offsets', async () => {
    mockedApiGet.mockImplementation((url: string) =>
      Promise.resolve(
        url.includes('/extra/')
          ? extraPage(url, 1, url.includes('offset=0'))
          : makeDetail(),
      ),
    );
    renderAt(`/${DATE}`);
    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Ielādēt vēl 20 ziņas',
      }),
    );
    await screen.findByText('3. Papildu 0');
    // has_next true → second click fetches offset=1.
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Ielādēt vēl 20 ziņas',
      }),
    );
    await screen.findByText('4. Papildu 1');
    const requested = mockedApiGet.mock.calls.map(
      (call) => call[0],
    );
    expect(requested).toContain(
      `/api/news/digests/${DATE}/extra/?offset=1`,
    );
    await waitFor(() =>
      expect(
        screen.queryByRole('button', {
          name: 'Ielādēt vēl 20 ziņas',
        }),
      ).not.toBeInTheDocument(),
    );
  });

  it('shows Load more on an empty digest with extras', async () => {
    mockedApiGet.mockImplementation((url: string) =>
      Promise.resolve(
        url.includes('/extra/')
          ? extraPage(url)
          : makeDetail({ items: [], has_more: true }),
      ),
    );
    renderAt(`/${DATE}`);
    await screen.findByText('Šajā kopsavilkumā nav ierakstu.');
    const button = screen.getByRole('button', {
      name: 'Ielādēt vēl 20 ziņas',
    });
    fireEvent.click(button);
    expect(
      await screen.findByText('3. Papildu 0'),
    ).toBeInTheDocument();
  });

  it('hides Load more while the first extra page errors', async () => {
    mockedApiGet.mockImplementation((url: string) =>
      url.includes('/extra/')
        ? Promise.reject(new Error('boom'))
        : Promise.resolve(makeDetail()),
    );
    renderAt(`/${DATE}`);
    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Ielādēt vēl 20 ziņas',
      }),
    );
    await screen.findByText('Failed to load more news');
    expect(
      screen.queryByRole('button', {
        name: 'Ielādēt vēl 20 ziņas',
      }),
    ).not.toBeInTheDocument();
  });

  it('hides Load more when the server reports no extras', async () => {
    mockedApiGet.mockImplementation(() =>
      Promise.resolve(makeDetail({ has_more: false })),
    );
    renderAt(`/${DATE}`);
    await screen.findByText('1. Ziņa viens');
    expect(
      screen.queryByRole('button', {
        name: 'Ielādēt vēl 20 ziņas',
      }),
    ).not.toBeInTheDocument();
  });
});
