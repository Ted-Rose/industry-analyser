import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import StorySlot from './StorySlot';
import { apiGet } from '../../shared/api/client';
import type { StoryCardOut } from '../api';

vi.mock('../../shared/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  getCsrfToken: () => undefined,
}));

const mockedApiGet = vi.mocked(apiGet);

function makeCard(
  overrides: Partial<StoryCardOut> = {},
): StoryCardOut {
  return {
    story_id: 1,
    article: {
      id: 10,
      title: 'Stāsts A',
      lead: 'Pirmais apraksts.',
      link: 'https://a.lv/story',
      image_url: '',
      published_at: '2026-10-29T10:00:00+03:00',
      source_slug: 'a',
      source_name: 'A',
    },
    audio_url: null,
    other_articles: [{ source_slug: 'b', source_name: 'B' }],
    ...overrides,
  };
}

function renderSlot() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <StorySlot storyId={1} headline="Virsraksts" />
    </QueryClientProvider>,
  );
}

/** URLs apiGet was called with, most recent last. */
function calledUrls(): string[] {
  return mockedApiGet.mock.calls.map((call) => String(call[0]));
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiGet.mockResolvedValue(makeCard());
});

describe('StorySlot', () => {
  it('fetches the story card on first expand', async () => {
    renderSlot();
    const toggle = screen.getByRole('button', {
      name: 'Virsraksts',
    });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(mockedApiGet).not.toHaveBeenCalled();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await waitFor(() =>
      expect(calledUrls()).toEqual(['/api/news/stories/1/']),
    );
    expect(await screen.findByText('Stāsts A')).toBeInTheDocument();
    // audio_url null → the disabled Klausīties button.
    expect(
      screen.getByRole('button', { name: 'Klausīties' }),
    ).toBeDisabled();
  });

  it('collapses on re-click and serves the cache on re-expand',
    async () => {
      renderSlot();
      const toggle = screen.getByRole('button', {
        name: 'Virsraksts',
      });
      fireEvent.click(toggle);
      await screen.findByText('Stāsts A');

      fireEvent.click(toggle);
      expect(toggle).toHaveAttribute('aria-expanded', 'false');
      const slot = document.querySelector('.story-slot');
      expect(slot).toHaveAttribute('hidden');

      // Re-expand — the card is still mounted/cached, no
      // second fetch.
      fireEvent.click(toggle);
      expect(slot).not.toHaveAttribute('hidden');
      expect(screen.getByText('Stāsts A')).toBeInTheDocument();
      expect(mockedApiGet).toHaveBeenCalledTimes(1);
    });

  it('refetches with ?source= when an outlet chip is clicked',
    async () => {
      renderSlot();
      fireEvent.click(
        screen.getByRole('button', { name: 'Virsraksts' }),
      );
      await screen.findByText('Stāsts A');

      mockedApiGet.mockResolvedValue(
        makeCard({
          article: {
            ...makeCard().article,
            id: 11,
            title: 'Stāsts B',
            source_slug: 'b',
            source_name: 'B',
          },
          other_articles: [
            { source_slug: 'a', source_name: 'A' },
          ],
        }),
      );
      fireEvent.click(
        screen.getByRole('button', { name: 'B' }),
      );
      await waitFor(() =>
        expect(calledUrls()).toContain(
          '/api/news/stories/1/?source=b',
        ),
      );
      expect(
        await screen.findByText('Stāsts B'),
      ).toBeInTheDocument();
    });

  it('renders the failure alert when the fetch fails', async () => {
    mockedApiGet.mockRejectedValue(new Error('HTTP 500'));
    renderSlot();
    fireEvent.click(
      screen.getByRole('button', { name: 'Virsraksts' }),
    );
    expect(
      await screen.findByRole('alert'),
    ).toHaveTextContent('Neizdevās ielādēt stāstu.');
  });
});
