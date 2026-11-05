import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Preferences from './Preferences';
import { apiGet, apiPost } from '../../shared/api/client';
import type { PreferencesOut } from '../api';

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

function renderPrefs() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <Preferences />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPost.mockReset();
  mockedApiGet.mockResolvedValue(makePrefs());
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
