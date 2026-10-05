import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchPrograms, type ProgramOut } from '../api';
import { useReactToProgram } from '../mutations';
import { displayRating, formatStartTime } from '../format';
import { errorDetail } from '../../shared/api/errors';

const PLACEHOLDER_IMAGE =
  'https://via.assets.so/img.jpg?w=400&h=300&bg=e5e7eb&f=png';

interface Draft {
  contentRating: string;
  notContentRating: string;
  ratingValue: string;
  ratio: string;
  startDate: string;
  endDate: string;
  channel: string;
  excludeChannel: string;
  showDisliked: boolean;
}

interface ProgramGroup {
  key: string;
  /** Airings sorted newest first — the card headline is [0]. */
  airings: ProgramOut[];
}

/** One card per program: airings sharing a Show (the canonical
 *  rerun dedup) collapse into a group keyed by show id; unlinked
 *  airings fall back to the normalized title. Group order follows
 *  first appearance in the feed. */
function groupPrograms(programs: ProgramOut[]): ProgramGroup[] {
  const byKey = new Map<string, ProgramOut[]>();
  for (const p of programs) {
    const key = p.show
      ? `show:${p.show.id}`
      : `title:${p.title_lv.trim().toLowerCase()}`;
    const list = byKey.get(key);
    if (list) list.push(p);
    else byKey.set(key, [p]);
  }
  return [...byKey].map(([key, airings]) => ({
    key,
    airings: airings.sort(
      (a, b) => Date.parse(b.start_time) - Date.parse(a.start_time),
    ),
  }));
}

/**
 * React port of tv_programs/program_list.html — the filtered program
 * feed. All filter state lives in the URL (useSearchParams) so
 * filtered feeds stay bookmarkable; like the GET form, inputs are
 * staged locally and applied to the URL on Filter.
 *
 * Draft seeding mirrors the template inputs: `request.GET.*` fields
 * render the raw param ('' when absent); `filters.*` fields render
 * the server-effective value (not_content_rating defaults to 'R',
 * dates to the last-7-days window) once the payload arrives.
 */
export default function ProgramList() {
  const [searchParams, setSearchParams] = useSearchParams();

  const { data, isPending, isError, error } = useQuery({
    queryKey: ['tv', 'programs', searchParams.toString()],
    queryFn: () =>
      fetchPrograms({
        contentRating: searchParams.get('content_rating'),
        // `has` not `get`: absent → server default 'R'; explicit
        // empty (?not_content_rating=) → exclusion disabled.
        notContentRating: searchParams.has('not_content_rating')
          ? searchParams.get('not_content_rating')
          : null,
        ratingValue: searchParams.get('rating_value'),
        ratio: searchParams.get('ratio'),
        startDate: searchParams.get('start_date'),
        endDate: searchParams.get('end_date'),
        channel: searchParams.get('channel'),
        excludeChannel: searchParams.get('exclude_channel'),
        showDisliked: searchParams.get('show_disliked'),
      }),
  });

  const paramsKey = searchParams.toString();
  const [draft, setDraft] = useState<Draft>({
    contentRating: searchParams.get('content_rating') ?? '',
    notContentRating: searchParams.get('not_content_rating') ?? 'R',
    ratingValue: searchParams.get('rating_value') ?? '',
    ratio: searchParams.get('ratio') ?? '',
    startDate: searchParams.get('start_date') ?? '',
    endDate: searchParams.get('end_date') ?? '',
    channel: searchParams.get('channel') ?? '',
    excludeChannel: searchParams.get('exclude_channel') ?? '',
    showDisliked: searchParams.get('show_disliked') === '1',
  });

  // Re-sync the staged inputs when the URL changes (back/forward,
  // Filter submit). On a same-params data update — the initial
  // resolve or a refetch (e.g. the reaction mutation's invalidate)
  // — only fill still-empty fields with the server-echoed defaults
  // (filters.not_content_rating 'R', the 7-day window) so staged
  // edits are never discarded.
  const lastSyncKey = useRef<string | null>(null);
  useEffect(() => {
    const p = new URLSearchParams(paramsKey);
    const paramsChanged = lastSyncKey.current !== paramsKey;
    lastSyncKey.current = paramsKey;
    setDraft((d) => {
      if (paramsChanged) {
        return {
          contentRating: p.get('content_rating') ?? '',
          notContentRating: p.has('not_content_rating')
            ? (p.get('not_content_rating') ?? '')
            : 'R',
          ratingValue: p.get('rating_value') ?? '',
          ratio: p.get('ratio') ?? '',
          startDate: p.get('start_date') ?? '',
          endDate: p.get('end_date') ?? '',
          channel: p.get('channel') ?? '',
          excludeChannel: p.get('exclude_channel') ?? '',
          showDisliked: p.get('show_disliked') === '1',
        };
      }
      if (!data) return d;
      return {
        ...d,
        notContentRating:
          d.notContentRating ||
          data.filters.not_content_rating ||
          'R',
        startDate: d.startDate || data.filters.start_date,
        endDate: d.endDate || data.filters.end_date,
      };
    });
  }, [paramsKey, data]);

  const applyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    const next = new URLSearchParams();
    if (draft.contentRating) {
      next.set('content_rating', draft.contentRating);
    }
    // Always send — even '' — so clearing the input disables the
    // server-side 'R' default (param absent would re-apply it).
    next.set('not_content_rating', draft.notContentRating);
    if (draft.ratingValue) next.set('rating_value', draft.ratingValue);
    if (draft.ratio) next.set('ratio', draft.ratio);
    if (draft.startDate) next.set('start_date', draft.startDate);
    if (draft.endDate) next.set('end_date', draft.endDate);
    if (draft.channel) next.set('channel', draft.channel);
    if (draft.excludeChannel) {
      next.set('exclude_channel', draft.excludeChannel);
    }
    if (draft.showDisliked) next.set('show_disliked', '1');
    setSearchParams(next);
  };

  const reactMutation = useReactToProgram();
  const groups = useMemo(
    () => groupPrograms(data?.programs ?? []),
    [data],
  );

  return (
    <div className="feed-container">
      {/* Filtering Form */}
      <form className="filter-form" onSubmit={applyFilters}>
        <div className="form-group">
          <label htmlFor="content_rating">Content Rating:</label>
          <input
            type="text"
            name="content_rating"
            id="content_rating"
            value={draft.contentRating}
            onChange={(e) =>
              setDraft((d) => ({ ...d, contentRating: e.target.value }))
            }
          />
        </div>

        <div className="form-group">
          <label htmlFor="not_content_rating">Exclude Rating:</label>
          <input
            type="text"
            name="not_content_rating"
            id="not_content_rating"
            value={draft.notContentRating}
            placeholder="e.g., R"
            onChange={(e) =>
              setDraft((d) => ({
                ...d,
                notContentRating: e.target.value,
              }))
            }
          />
        </div>

        <div className="form-group">
          <label htmlFor="rating_value">Minimum Rating:</label>
          <input
            type="number"
            step="0.1"
            name="rating_value"
            id="rating_value"
            value={draft.ratingValue}
            onChange={(e) =>
              setDraft((d) => ({ ...d, ratingValue: e.target.value }))
            }
          />
        </div>

        <div className="form-group">
          <label htmlFor="start_date">Start Date:</label>
          <input
            type="date"
            name="start_date"
            id="start_date"
            value={draft.startDate}
            onChange={(e) =>
              setDraft((d) => ({ ...d, startDate: e.target.value }))
            }
          />
        </div>

        <div className="form-group">
          <label htmlFor="end_date">End Date:</label>
          <input
            type="date"
            name="end_date"
            id="end_date"
            value={draft.endDate}
            onChange={(e) =>
              setDraft((d) => ({ ...d, endDate: e.target.value }))
            }
          />
        </div>

        <div className="form-group">
          <label htmlFor="ratio">Min. Match Ratio:</label>
          <input
            type="number"
            step="0.1"
            name="ratio"
            id="ratio"
            value={draft.ratio}
            onChange={(e) =>
              setDraft((d) => ({ ...d, ratio: e.target.value }))
            }
          />
        </div>

        <div className="form-group">
          <label htmlFor="channel">Channel:</label>
          <input
            type="text"
            name="channel"
            id="channel"
            list="channel-names"
            value={draft.channel}
            onChange={(e) =>
              setDraft((d) => ({ ...d, channel: e.target.value }))
            }
          />
        </div>

        <div className="form-group">
          <label htmlFor="not_channel">Exclude Channel:</label>
          <input
            type="text"
            name="exclude_channel"
            id="not_channel"
            list="channel-names"
            value={draft.excludeChannel}
            onChange={(e) =>
              setDraft((d) => ({ ...d, excludeChannel: e.target.value }))
            }
          />
        </div>

        <div className="form-group">
          <label htmlFor="show_disliked">Show disliked:</label>
          <input
            type="checkbox"
            name="show_disliked"
            id="show_disliked"
            value="1"
            checked={draft.showDisliked}
            onChange={(e) =>
              setDraft((d) => ({ ...d, showDisliked: e.target.checked }))
            }
          />
        </div>

        <button type="submit">Filter</button>
      </form>

      {/* Channel names — the template context carried `channels` for
          autocomplete that never shipped; the API still returns it. */}
      <datalist id="channel-names">
        {data?.channels.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>

      {isError && (
        <div className="feed-card feed-content">
          Failed to load programs — {errorDetail(error)}
        </div>
      )}
      {reactMutation.isError && (
        <div className="feed-card feed-content">
          Reaction failed — {errorDetail(reactMutation.error)}
        </div>
      )}

      {/* Feed Content */}
      {groups.length === 0 && !isPending ? (
        <div>No programs available</div>
      ) : (
        groups.map((group) => (
          <ProgramCard
            key={group.key}
            airings={group.airings}
            pendingProgramId={
              reactMutation.isPending
                ? (reactMutation.variables?.programId ?? null)
                : null
            }
            onReact={(reaction) => {
              reactMutation.mutate({
                programId: group.airings[0].id,
                reaction,
              });
            }}
          />
        ))
      )}
      {isPending && <div>Loading…</div>}
    </div>
  );
}

function ProgramCard({
  airings,
  pendingProgramId,
  onReact,
}: {
  airings: ProgramOut[];
  pendingProgramId: string | null;
  onReact: (reaction: 'like' | 'dislike') => void;
}) {
  const [expanded, setExpanded] = useState(false);
  // Newest airing fronts the card (airings arrive sorted desc).
  const program = airings[0];
  const channels = [...new Set(airings.map((a) => a.channel_name))];
  const show = program.show;
  const imageSrc =
    program.image_url || show?.image_url || PLACEHOLDER_IMAGE;
  // `||` not `??`: the template used |default: (falsy), so an empty
  // string on the linked Show must still fall back.
  const imageAlt =
    show?.title_eng || program.title_eng || program.title_lv;
  const imdbHref = show?.imdb_url || program.url;
  const rating = displayRating(show?.imdb_rating, program.imdb_rating);
  const pgRating = show?.pg_rating || program.pg_rating;
  const busy = pendingProgramId === program.id;

  return (
    <div className="feed-card">
      <img src={imageSrc} alt={imageAlt} />
      <div className="feed-content">
        <div className="feed-title">
          {show ? show.title_lv : program.title_lv}
          {show?.title_eng && (
            <span className="feed-title-eng"> {show.title_eng}</span>
          )}
        </div>
        <div className="feed-description">{program.description_lv}</div>
        <div className="feed-metadata">
          {(imdbHref || rating) && (
            <>
              {imdbHref ? (
                <a
                  href={imdbHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-secondary btn-sm"
                >
                  IMDb{rating ? ` ${rating}` : ''}
                </a>
              ) : (
                <span>Rating: {rating}</span>
              )}{' '}
              |{' '}
            </>
          )}
          <span>Channel: {channels.join(', ')}</span> |{' '}
          <span>
            Start Time: {formatStartTime(program.start_time)}
            {airings.length > 1 && (
              <button
                type="button"
                className="airings-toggle"
                aria-expanded={expanded}
                aria-label="All showtimes"
                onClick={() => setExpanded((v) => !v)}
              >
                {expanded ? '▾' : '▸'} {airings.length}
              </button>
            )}
          </span>
          {pgRating && (
            <>
              {' '}
              | <span className="pg-badge">{pgRating}</span>
            </>
          )}
        </div>
        {expanded && (
          <ul className="airings-list">
            {airings.map((a) => (
              <li key={a.id}>
                {formatStartTime(a.start_time)}
                {channels.length > 1 ? ` — ${a.channel_name}` : ''}
              </li>
            ))}
          </ul>
        )}
        {/* Reactions work on every card — the API lazily resolves a
            Show for airings that don't have one yet. */}
        <div className="feed-actions">
          <button
            type="button"
            className={`reaction-btn${
              program.user_reaction === 'like' ? ' liked' : ''
            }`}
            disabled={busy}
            onClick={() => onReact('like')}
          >
            Like
          </button>
          <button
            type="button"
            className={`reaction-btn${
              program.user_reaction === 'dislike' ? ' disliked' : ''
            }`}
            disabled={busy}
            onClick={() => onReact('dislike')}
          >
            Dislike
          </button>
        </div>
      </div>
    </div>
  );
}