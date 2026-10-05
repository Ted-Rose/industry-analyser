import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ProgramList from './ProgramList';
import { apiGet } from '../../shared/api/client';
import type { ProgramOut, ProgramsOut } from '../api';

vi.mock('../../shared/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  getCsrfToken: () => undefined,
}));

const mockedApiGet = vi.mocked(apiGet);

function makeProgram(overrides: Partial<ProgramOut> = {}): ProgramOut {
  return {
    id: '11111111-1111-1111-1111-111111111111',
    title_lv: 'Dienas ziņas',
    title_eng: null,
    description_lv: 'Jaunākās ziņas',
    channel_name: 'ltv1_hd',
    start_time: '2026-10-02T15:15:00+03:00',
    image_url: null,
    url: 'https://tet.lv/programme/1',
    pg_rating: null,
    imdb_rating: '6.5',
    title_match_ratio: 0.42,
    show: null,
    user_reaction: null,
    ...overrides,
  };
}

function makePrograms(
  overrides: Partial<ProgramsOut> = {},
): ProgramsOut {
  return {
    programs: [makeProgram()],
    channels: ['ltv1_hd', 'tv3'],
    filters: {
      content_rating: null,
      not_content_rating: 'R',
      rating_value: null,
      ratio: null,
      start_date: '2026-09-25',
      end_date: '2026-10-02',
      channel_name: null,
      exclude_channel_name: null,
      show_disliked: false,
    },
    ...overrides,
  };
}

function renderList(entry = '/tv/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <QueryClientProvider client={queryClient}>
        <ProgramList />
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
  mockedApiGet.mockResolvedValue(makePrograms());
});

describe('ProgramList', () => {
  it('passes URL filter params through to the API', async () => {
    renderList(
      '/tv/?content_rating=PG-13&start_date=2026-01-01' +
        '&end_date=2026-01-10&channel=ltv1_hd&show_disliked=1',
    );
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    const url = calledUrls()[0];
    expect(url).toContain('content_rating=PG-13');
    expect(url).toContain('start_date=2026-01-01');
    expect(url).toContain('end_date=2026-01-10');
    expect(url).toContain('channel=ltv1_hd');
    expect(url).toContain('show_disliked=1');
  });

  it('sends an explicit empty not_content_rating (disables the ' +
    "server's 'R' default)", async () => {
    renderList('/tv/?not_content_rating=');
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    expect(calledUrls()[0]).toContain('not_content_rating=');
  });

  it('omits not_content_rating when the param is absent ' +
    '(server applies the R default)', async () => {
    renderList('/tv/');
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    expect(calledUrls()[0]).not.toContain('not_content_rating');
  });

  it('shows the server-effective filter defaults in the inputs',
    async () => {
      renderList('/tv/');
      await screen.findByText('Dienas ziņas');
      // filters.* echo — like the template rendering filters.*
      // into the form on first paint.
      await waitFor(() =>
        expect(screen.getByLabelText('Exclude Rating:'))
          .toHaveValue('R'),
      );
      expect(screen.getByLabelText('Start Date:')).toHaveValue(
        '2026-09-25',
      );
      expect(screen.getByLabelText('End Date:')).toHaveValue(
        '2026-10-02',
      );
    });

  it('stages filter edits until Filter is pressed', async () => {
    renderList('/tv/');
    await screen.findByText('Dienas ziņas');
    expect(mockedApiGet).toHaveBeenCalledTimes(1);

    // Editing an input alone must not refetch — the template form
    // applied everything on submit.
    fireEvent.change(screen.getByLabelText('Channel:'), {
      target: { value: 'tv3' },
    });
    expect(mockedApiGet).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Filter' }));
    await waitFor(() =>
      expect(mockedApiGet).toHaveBeenCalledTimes(2),
    );
    expect(calledUrls()[1]).toContain('channel=tv3');
    // The staged 'R' exclusion submits explicitly — clearing the
    // input would submit '' instead of re-applying the default.
    expect(calledUrls()[1]).toContain('not_content_rating=R');
  });

  it('drops non-numeric rating inputs instead of 422ing', async () => {
    renderList('/tv/?rating_value=abc');
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled());
    expect(calledUrls()[0]).not.toContain('rating_value');
  });

  it('renders the card with show fallbacks and reactions', async () => {
    mockedApiGet.mockResolvedValue(
      makePrograms({
        programs: [
          makeProgram({
            show: {
              id: '22222222-2222-2222-2222-222222222222',
              title_lv: 'Filma',
              title_eng: 'The Movie',
              imdb_rating: '8.1',
              imdb_url: 'https://imdb.com/title/tt1',
              pg_rating: 'PG-13',
              image_url: null,
              title_match_ratio: 0.9,
            },
            user_reaction: 'like',
          }),
        ],
      }),
    );
    renderList('/tv/');
    await screen.findByText('Filma');
    expect(screen.getByText('The Movie')).toBeInTheDocument();
    expect(screen.getByText(/Rating: 8\.1/)).toBeInTheDocument();
    expect(screen.getByText(/Match Ratio: 0\.90/)).toBeInTheDocument();
    const like = screen.getByRole('button', { name: 'Like' });
    expect(like).toHaveClass('liked');
    expect(
      screen.getByRole('button', { name: 'Dislike' }),
    ).not.toHaveClass('disliked');
    expect(
      screen.getByRole('link', { name: 'IMDb' }),
    ).toHaveAttribute('href', 'https://imdb.com/title/tt1');
  });

  it('hides reaction buttons for programs without a Show', async () => {
    renderList('/tv/');
    await screen.findByText('Dienas ziņas');
    expect(
      screen.queryByRole('button', { name: 'Like' }),
    ).not.toBeInTheDocument();
  });

  it('aggregates repeat airings of a show into one expandable ' +
    'card, newest first', async () => {
    const show = {
      id: '22222222-2222-2222-2222-222222222222',
      title_lv: '13. karotājs',
      title_eng: null,
      imdb_rating: null,
      imdb_url: null,
      pg_rating: null,
      image_url: null,
      title_match_ratio: 0.9,
    };
    mockedApiGet.mockResolvedValue(
      makePrograms({
        programs: [
          makeProgram({
            id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            show,
            start_time: '2026-09-30T18:00:00+03:00',
            channel_name: 'ltv1_hd',
          }),
          makeProgram({
            id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
            show,
            start_time: '2026-10-02T18:00:00+03:00',
            channel_name: 'tv3',
          }),
        ],
      }),
    );
    const { container } = renderList('/tv/');
    await screen.findByText('13. karotājs');
    expect(container.querySelectorAll('.feed-card')).toHaveLength(1);
    // Collapsed: only the newest slot headlines the card.
    expect(
      screen.getByText(/Start Time: Oct\. 2, 2026, 3:00 p\.m\./),
    ).toBeInTheDocument();
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);

    fireEvent.click(
      screen.getByRole('button', { name: 'All showtimes' }),
    );
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('Oct. 2, 2026, 3:00 p.m.');
    expect(items[0]).toHaveTextContent('tv3');
    expect(items[1]).toHaveTextContent('Sept. 30, 2026, 3:00 p.m.');
    expect(items[1]).toHaveTextContent('ltv1_hd');

    fireEvent.click(
      screen.getByRole('button', { name: 'All showtimes' }),
    );
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);
  });

  it('groups unlinked airings by title and keeps distinct titles ' +
    'on separate cards', async () => {
    mockedApiGet.mockResolvedValue(
      makePrograms({
        programs: [
          makeProgram({
            id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            start_time: '2026-10-01T15:15:00+03:00',
          }),
          makeProgram({
            id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
            start_time: '2026-10-02T15:15:00+03:00',
          }),
          makeProgram({
            id: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
            title_lv: 'Vakara ziņas',
          }),
        ],
      }),
    );
    const { container } = renderList('/tv/');
    await screen.findByText('Dienas ziņas');
    expect(container.querySelectorAll('.feed-card')).toHaveLength(2);

    fireEvent.click(
      screen.getByRole('button', { name: 'All showtimes' }),
    );
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    // Single-channel group — no channel suffix on the times.
    expect(items[0]).not.toHaveTextContent('ltv1_hd');
    expect(items[0]).toHaveTextContent('Oct. 2, 2026, 12:15 p.m.');
  });
});
