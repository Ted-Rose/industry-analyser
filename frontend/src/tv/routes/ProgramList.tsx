import {
  Fragment,
  ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  keepPreviousData,
  useQuery,
} from '@tanstack/react-query';
import {
  ChevronDown,
  ChevronRight,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react';
import { fetchPrograms, type ProgramOut } from '../api';
import { useReactToProgram } from '../mutations';
import { displayRating, formatStartTime } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { cx } from '../../shared/cx';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import Card from '../../shared/ui/Card';
import Checkbox from '../../shared/ui/Checkbox';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState from '../../shared/ui/ErrorState';
import Field from '../../shared/ui/Field';
import FilterBar from '../../shared/ui/FilterBar';
import IconButton from '../../shared/ui/IconButton';
import Input from '../../shared/ui/Input';
import { LoadingState } from '../../shared/ui/Skeleton';
import { pushToast } from '../../shared/toasts';

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
 * feed — restyled on the shared component kit (plan §9.6). All
 * filter state lives in the URL (useSearchParams) so filtered feeds
 * stay bookmarkable; like the GET form, inputs are staged locally
 * and applied to the URL on Filter.
 *
 * Draft seeding mirrors the template inputs: `request.GET.*` fields
 * render the raw param ('' when absent); `filters.*` fields render
 * the server-effective value (not_content_rating defaults to 'R',
 * dates to the last-7-days window) once the payload arrives.
 */
export default function ProgramList() {
  const [searchParams, setSearchParams] = useSearchParams();

  const {
    data,
    isPending,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery({
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
    // A filter change keeps the previous feed on screen while the
    // new one loads — the opacity dim below is the only "loading"
    // signal a refetch needs.
    placeholderData: keepPreviousData,
  });

  // Query failures surface both inline (ErrorState on first load)
  // and as a toast — a failed background refetch must still be
  // visible while stale rows stay on screen. The ref dedupes
  // StrictMode's double-effect and repeat failures of one error.
  const reported = useRef<unknown>(null);
  useEffect(() => {
    if (!isError) {
      reported.current = null;
      return;
    }
    if (reported.current === error) return;
    reported.current = error;
    pushToast(
      `Failed to load programs — ${errorDetail(error)}`,
      'danger',
    );
  }, [isError, error]);

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

  // Only user-set URL params count as active filters — the server's
  // effective defaults (the 'R' exclusion, the 7-day window) are
  // applied silently and surface in the summary line instead
  // (plan §8.4).
  const activeCount = [...new Set(searchParams.keys())].length;

  return (
    <PageContainer width="narrow">
      <PageHeader
        title="TV programs"
        description={
          'Filtered program feed — repeat airings of a show ' +
          'group into one card.'
        }
      />
      <FilterBar
        onSubmit={applyFilters}
        collapsible="mobile"
        activeCount={activeCount}
        submitLabel="Filter"
        className="mb-6"
      >
        <Field label="Content Rating:" htmlFor="content_rating">
          <Input
            type="text"
            name="content_rating"
            id="content_rating"
            value={draft.contentRating}
            onChange={(e) =>
              setDraft((d) => ({ ...d, contentRating: e.target.value }))
            }
          />
        </Field>

        <Field label="Exclude Rating:" htmlFor="not_content_rating">
          <Input
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
        </Field>

        <Field label="Minimum Rating:" htmlFor="rating_value">
          <Input
            type="number"
            step="0.1"
            name="rating_value"
            id="rating_value"
            value={draft.ratingValue}
            onChange={(e) =>
              setDraft((d) => ({ ...d, ratingValue: e.target.value }))
            }
          />
        </Field>

        <Field label="Start Date:" htmlFor="start_date">
          <Input
            type="date"
            name="start_date"
            id="start_date"
            value={draft.startDate}
            onChange={(e) =>
              setDraft((d) => ({ ...d, startDate: e.target.value }))
            }
          />
        </Field>

        <Field label="End Date:" htmlFor="end_date">
          <Input
            type="date"
            name="end_date"
            id="end_date"
            value={draft.endDate}
            onChange={(e) =>
              setDraft((d) => ({ ...d, endDate: e.target.value }))
            }
          />
        </Field>

        <Field label="Min. Match Ratio:" htmlFor="ratio">
          <Input
            type="number"
            step="0.1"
            name="ratio"
            id="ratio"
            value={draft.ratio}
            onChange={(e) =>
              setDraft((d) => ({ ...d, ratio: e.target.value }))
            }
          />
        </Field>

        <Field label="Channel:" htmlFor="channel">
          <Input
            type="text"
            name="channel"
            id="channel"
            list="channel-names"
            value={draft.channel}
            onChange={(e) =>
              setDraft((d) => ({ ...d, channel: e.target.value }))
            }
          />
        </Field>

        <Field label="Exclude Channel:" htmlFor="not_channel">
          <Input
            type="text"
            name="exclude_channel"
            id="not_channel"
            list="channel-names"
            value={draft.excludeChannel}
            onChange={(e) =>
              setDraft((d) => ({ ...d, excludeChannel: e.target.value }))
            }
          />
        </Field>

        {/* items-end drops the checkbox level with the row's inputs
            (it carries no Field label row of its own). */}
        <div className="flex items-end">
          <Checkbox
            name="show_disliked"
            id="show_disliked"
            value="1"
            label="Show disliked:"
            checked={draft.showDisliked}
            onChange={(e) =>
              setDraft((d) => ({ ...d, showDisliked: e.target.checked }))
            }
          />
        </div>
      </FilterBar>

      {/* Channel names — the template context carried `channels` for
          autocomplete that never shipped; the API still returns it. */}
      <datalist id="channel-names">
        {data?.channels.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>

      {/* The effective server defaults live here, not in the
          "Filters (n)" count (plan §8.4). */}
      {data && (
        <p className="mb-4 text-sm text-fg-muted tabular-nums">
          Showing {groups.length} programs ·{' '}
          {data.filters.start_date}–{data.filters.end_date}
          {data.filters.not_content_rating &&
            ` · rating "${data.filters.not_content_rating}" excluded`}
        </p>
      )}

      {isError && !data ? (
        <ErrorState
          title="Failed to load programs"
          error={errorDetail(error)}
          onRetry={() => void refetch()}
        />
      ) : isPending ? (
        <LoadingState variant="cards" />
      ) : groups.length === 0 ? (
        <EmptyState
          title="No programs available"
          description={
            activeCount > 0
              ? 'Nothing matches the active filters.'
              : 'No programs in the default window — the last 7 ' +
                'days, R-rated content excluded.'
          }
          action={
            activeCount > 0 ? (
              <Button
                variant="secondary"
                onClick={() => setSearchParams({})}
              >
                Clear filters
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div
          aria-busy={isFetching}
          className={cx(
            'space-y-4 transition-opacity ' +
              'motion-safe:duration-180 ease-ia',
            isFetching && 'opacity-60',
          )}
        >
          {groups.map((group) => (
            <ProgramCard
              key={group.key}
              airings={group.airings}
              pendingProgramId={
                reactMutation.isPending
                  ? (reactMutation.variables?.programId ?? null)
                  : null
              }
              onReact={(reaction) => {
                reactMutation.mutate(
                  {
                    programId: group.airings[0].id,
                    reaction,
                  },
                  {
                    onError: (mutationError) =>
                      pushToast(
                        'Reaction failed — ' +
                          errorDetail(mutationError),
                        'danger',
                      ),
                  },
                );
              }}
            />
          ))}
        </div>
      )}
    </PageContainer>
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
  // `||` not `??`: the template used |default: (falsy), so an empty
  // string on the linked Show must still fall back.
  const imageSrc = program.image_url || show?.image_url;
  const imageAlt =
    show?.title_eng || program.title_eng || program.title_lv;
  const imdbHref = show?.imdb_url || program.url;
  const rating = displayRating(show?.imdb_rating, program.imdb_rating);
  const pgRating = show?.pg_rating || program.pg_rating;
  const busy = pendingProgramId === program.id;

  // `·`-separated meta row — plan §9.6: IMDb link or bare rating,
  // channels, start time (+ the rerun toggle) and the PG badge.
  const meta: ReactNode[] = [];
  if (imdbHref) {
    meta.push(
      <Button
        as="a"
        variant="secondary"
        size="sm"
        href={imdbHref}
        target="_blank"
        rel="noopener noreferrer"
      >
        IMDb{rating ? ` ${rating}` : ''}
      </Button>,
    );
  } else if (rating) {
    meta.push(<span>Rating: {rating}</span>);
  }
  meta.push(<span>Channel: {channels.join(', ')}</span>);
  meta.push(
    <span className="inline-flex items-center gap-1">
      Start Time: {formatStartTime(program.start_time)}
      {airings.length > 1 && (
        <>
          <IconButton
            size="sm"
            icon={expanded ? <ChevronDown /> : <ChevronRight />}
            label="All showtimes"
            aria-expanded={expanded}
            onClick={() => setExpanded((v) => !v)}
          />
          <Badge variant="outline">{airings.length}</Badge>
        </>
      )}
    </span>,
  );
  if (pgRating) {
    meta.push(<Badge variant="outline">{pgRating}</Badge>);
  }

  return (
    // Feed-card recipe (§7): image left ≥sm, stacked <sm; the
    // remote via.assets.so placeholder is replaced by a local
    // bg-surface-2 block (§8.17).
    <Card
      data-testid="program-card"
      className="flex flex-col gap-4 sm:flex-row"
    >
      {imageSrc ? (
        <img
          src={imageSrc}
          alt={imageAlt}
          loading="lazy"
          className="size-24 shrink-0 rounded-md object-cover"
        />
      ) : (
        <div
          aria-hidden="true"
          className="size-24 shrink-0 rounded-md bg-surface-2"
        />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <h2 className="text-lg font-medium text-fg">
            {show ? show.title_lv : program.title_lv}
            {show?.title_eng && (
              <span
                className={
                  'ml-1 text-sm font-normal text-fg-subtle'
                }
              >
                {show.title_eng}
              </span>
            )}
          </h2>
          {/* Reactions work on every card — the API lazily resolves
              a Show for airings that don't have one yet. Re-clicking
              the same reaction toggles it off server-side. */}
          <div className="flex shrink-0 items-center gap-1">
            <IconButton
              icon={<ThumbsUp />}
              label="Like"
              pressed={program.user_reaction === 'like'}
              disabled={busy}
              onClick={() => onReact('like')}
            />
            <IconButton
              icon={<ThumbsDown />}
              label="Dislike"
              pressed={program.user_reaction === 'dislike'}
              disabled={busy}
              onClick={() => onReact('dislike')}
            />
          </div>
        </div>
        <p className="mt-1 text-sm text-fg-muted">
          {program.description_lv}
        </p>
        <div
          data-testid="program-meta"
          className={
            'mt-2 flex flex-wrap items-center gap-x-1.5 gap-y-1 ' +
            'text-xs text-fg-subtle'
          }
        >
          {meta.map((item, index) => (
            <Fragment key={index}>
              {index > 0 && <span aria-hidden="true">·</span>}
              {item}
            </Fragment>
          ))}
        </div>
        {expanded && (
          <ul className="mt-2 space-y-0.5 text-xs text-fg-subtle">
            {airings.map((a) => (
              <li key={a.id}>
                {formatStartTime(a.start_time)}
                {channels.length > 1 ? ` — ${a.channel_name}` : ''}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
