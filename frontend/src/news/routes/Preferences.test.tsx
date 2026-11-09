import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';
import Preferences from './Preferences';
import { apiGet, apiPost } from '../../shared/api/client';
import type { DigestTaskStatusOut, PreferencesOut } from '../api';

vi.mock('../../shared/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  getCsrfToken: () => undefined,
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPost = vi.mocked(apiPost);

function makePrefs(
  overrides: Partial<PreferencesOut> = {},
): PreferencesOut {
  return {
    rows: [
      { slug: 'a', name: 'A', checked: false, rank: null },
      { slug: 'b', name: 'B', checked: true, rank: 1 },
      { slug: 'c', name: 'C', checked: false, rank: null },
    ],
    ...overrides,
  };
}

function makeStatus(
  overrides: Partial<DigestTaskStatusOut> = {},
): DigestTaskStatusOut {
  return {
    oauth_configured: true,
    google_connected: true,
    subscribed: false,
    last_task: null,
    ...overrides,
  };
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="loc">{location.search}</div>;
}

function currentSearch(): string {
  return screen.getByTestId('loc').textContent ?? '';
}

function renderPrefs(entry = '/preferences') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <QueryClientProvider client={queryClient}>
        <Preferences />
        <LocationProbe />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPost.mockReset();
  mockedApiGet.mockImplementation((url: string) =>
    Promise.resolve(
      url === '/api/news/digest-task/'
        ? makeStatus()
        : makePrefs(),
    ),
  );
  mockedApiPost.mockResolvedValue({
    success: true,
    saved: 2,
    message: 'Preferences saved.',
  });
});

describe('Preferences', () => {
  it('prefills checked and rank from the payload', async () => {
    renderPrefs();
    const checkboxB = await screen.findByRole('checkbox', {
      name: 'B',
    });
    expect(checkboxB).toBeChecked();
    expect(
      screen.getByRole('checkbox', { name: 'A' }),
    ).not.toBeChecked();
    const rankB = screen.getByRole('spinbutton', {
      name: 'B rangs',
    });
    expect(rankB).toHaveValue(1);
  });

  it('posts only checked rows with their rank values',
    async () => {
      renderPrefs();
      await screen.findByRole('checkbox', { name: 'B' });

      fireEvent.click(
        screen.getByRole('checkbox', { name: 'A' }),
      );
      fireEvent.change(
        screen.getByRole('spinbutton', { name: 'A rangs' }),
        { target: { value: '2' } },
      );
      fireEvent.click(
        screen.getByRole('button', { name: 'Saglabāt' }),
      );

      await waitFor(() =>
        expect(mockedApiPost).toHaveBeenCalledWith(
          '/api/news/preferences/',
          {
            rows: [
              { slug: 'a', rank: 2 },
              { slug: 'b', rank: 1 },
            ],
          },
        ),
      );
      // 'c' stayed unchecked — not submitted.
      const body = mockedApiPost.mock.calls[0][1] as {
        rows: { slug: string }[];
      };
      expect(body.rows.map((row) => row.slug)).toEqual(['a', 'b']);
    });

  it('sends rank null for a checked-but-unranked row',
    async () => {
      renderPrefs();
      await screen.findByRole('checkbox', { name: 'B' });

      fireEvent.click(
        screen.getByRole('checkbox', { name: 'C' }),
      );
      fireEvent.click(
        screen.getByRole('button', { name: 'Saglabāt' }),
      );

      await waitFor(() =>
        expect(mockedApiPost).toHaveBeenCalledWith(
          '/api/news/preferences/',
          {
            rows: [
              { slug: 'b', rank: 1 },
              { slug: 'c', rank: null },
            ],
          },
        ),
      );
    });
});

describe('DigestTaskCard', () => {
  it('stays hidden when oauth_configured is false', async () => {
    mockedApiGet.mockImplementation((url: string) =>
      Promise.resolve(
        url === '/api/news/digest-task/'
          ? makeStatus({ oauth_configured: false })
          : makePrefs(),
      ),
    );
    renderPrefs();
    await screen.findByRole('checkbox', { name: 'B' });
    expect(
      screen.queryByText('Google Tasks digest'),
    ).not.toBeInTheDocument();
  });

  it('links Connect Google back with ?subscribe=1', async () => {
    mockedApiGet.mockImplementation((url: string) =>
      Promise.resolve(
        url === '/api/news/digest-task/'
          ? makeStatus({ google_connected: false })
          : makePrefs(),
      ),
    );
    renderPrefs();
    const connect = await screen.findByRole('link', {
      name: 'Pievienot Google',
    });
    expect(connect).toHaveAttribute(
      'href',
      '/google/login/?next=/news/preferences/?subscribe=1',
    );
  });

  it('auto-subscribes once on ?subscribe=1 then strips it',
    async () => {
      renderPrefs('/preferences?subscribe=1');
      await waitFor(() =>
        expect(mockedApiPost).toHaveBeenCalledWith(
          '/api/news/digest-task/subscribe/',
        ),
      );
      const subscribeCalls = mockedApiPost.mock.calls.filter(
        ([url]) => url === '/api/news/digest-task/subscribe/',
      );
      expect(subscribeCalls).toHaveLength(1);
      await waitFor(() =>
        expect(currentSearch()).not.toContain('subscribe=1'),
      );
    });

  it('shows the subscribed state with a failed last task',
    async () => {
      mockedApiGet.mockImplementation((url: string) =>
        Promise.resolve(
          url === '/api/news/digest-task/'
            ? makeStatus({
                subscribed: true,
                last_task: {
                  digest_date: '2026-11-09',
                  status: 'failed',
                  error: 're-authorize at /google/login',
                  updated_at: '2026-11-09T08:00:00Z',
                },
              })
            : makePrefs(),
        ),
      );
      renderPrefs();
      await screen.findByRole('button', { name: 'Atsakties' });
      expect(
        screen.getByText(/re-authorize at \/google\/login/),
      ).toBeInTheDocument();
      expect(
        screen.getByRole('link', {
          name: 'Pievieno Google vēlreiz',
        }),
      ).toHaveAttribute('href', '/google/login');
    });
});
