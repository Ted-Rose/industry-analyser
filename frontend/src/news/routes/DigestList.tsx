import { useEffect, useRef, useSyncExternalStore } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  keepPreviousData,
  useQuery,
} from '@tanstack/react-query';
import { fetchDigests, type DigestListItemOut } from '../api';
import {
  getAudioSnapshot,
  itemJobs,
  jobsForItems,
  stopPlayback,
  subscribeAudio,
  warmClips,
} from '../audio';
import { errorDetail } from '../../shared/api/errors';
import { cx } from '../../shared/cx';
import { useBootstrap } from '../../shared/hooks/useBootstrap';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState from '../../shared/ui/ErrorState';
import { LoadingState } from '../../shared/ui/Skeleton';
import { pushToast } from '../../shared/toasts';
import AudioButton from '../components/AudioButton';
import DigestFilter, {
  type DigestPeriod,
} from '../components/DigestFilter';
import StorySlot from '../components/StorySlot';

/** /accounts/login/ hop for the anonymous "Log in to rank
 *  portals" header link — points straight at login (the old
 *  link's /news/preferences/ → 302 hop is pointless now). */
const LOGIN_NEXT =
  `/accounts/login/?next=${encodeURIComponent(
    '/news/preferences/',
  )}`;

/**
 * React port of news/digest_list.html — the digest index
 * with the ?date/?period GET filter (auto-applies like the
 * retired filter.js), the audio bar (▶ all / ■ Stop /
 * unavailable note), per-digest sections with inline story
 * expand and the two empty states.
 */
export default function DigestList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { is_authenticated: isAuthenticated } = useBootstrap();
  const audio = useSyncExternalStore(
    subscribeAudio,
    getAudioSnapshot,
  );

  const {
    data,
    isPending,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['news', 'digests', searchParams.toString()],
    queryFn: () =>
      fetchDigests({
        date: searchParams.get('date'),
        period: searchParams.get('period'),
      }),
    // A filter change keeps the previous digests on screen
    // while the new window loads.
    placeholderData: keepPreviousData,
  });

  // Echo the server-effective filter back into the URL — a
  // bare or malformed query still lands on the default window,
  // and the address bar should show the selected date and
  // period the filter displays. `replace` keeps normalization
  // out of the history stack; the isFetching gate stops the
  // previous response's echo from clobbering a just-applied
  // filter mid-refetch.
  useEffect(() => {
    if (!data || isFetching) return;
    const next = new URLSearchParams();
    if (data.anchor_date) next.set('date', data.anchor_date);
    next.set('period', data.period);
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [data, isFetching, searchParams, setSearchParams]);

  useEffect(() => {
    document.title = 'Ziņu kopsavilkumi';
  }, []);

  // Query failures surface inline (first load) and as a
  // toast (a failed background refetch while stale rows stay
  // visible). The ref dedupes StrictMode's double-effect.
  const reported = useRef<unknown>(null);
  useEffect(() => {
    if (!isError) {
      reported.current = null;
      return;
    }
    if (reported.current === error) return;
    reported.current = error;
    pushToast(
      `Failed to load digests — ${errorDetail(error)}`,
      'danger',
    );
  }, [isError, error]);

  // Pre-warm only the newest digest's clips — "generate on
  // visit" without blocking render (the old script's
  // [data-audio-newest] DOMContentLoaded fan-out).
  const digests = data?.digests ?? [];
  useEffect(() => {
    const newest = data?.digests[0];
    if (newest && newest.items.length) {
      warmClips(jobsForItems(newest.items));
    }
  }, [data]);

  const applyFilter = (date: string, period: DigestPeriod) => {
    const next = new URLSearchParams();
    if (date) next.set('date', date);
    next.set('period', period);
    setSearchParams(next);
  };

  const allJobs = jobsForItems(
    digests.flatMap((digest) => digest.items),
  );

  return (
    <PageContainer width="prose" className="news-prose">
      <PageHeader
        title={
          <Link to="/" className="text-fg hover:underline">
            Ziņu kopsavilkums
          </Link>
        }
      />
      {!isAuthenticated && (
        <nav className="back">
          <a className="muted" href={LOGIN_NEXT}>
            Log in to rank portals
          </a>
        </nav>
      )}
      {digests.length > 0 && (
        <div className="audio-bar">
          <AudioButton jobs={allJobs}>▶ Play all news</AudioButton>
          <button
            type="button"
            className="audio-stop"
            hidden={!audio.playing}
            onClick={stopPlayback}
          >
            ■ Stop
          </button>
          <span className="audio-note muted" hidden={!audio.down}>
            Audio unavailable
          </span>
        </div>
      )}
      {data?.max_date && (
        <DigestFilter
          date={
            data.anchor_date ??
            searchParams.get('date') ??
            ''
          }
          period={data.period as DigestPeriod}
          minDate={data.min_date ?? ''}
          maxDate={data.max_date}
          onApply={applyFilter}
        />
      )}
      {data?.range_start && (
        <p className="muted digest-range">
          {data.range_start === data.range_end
            ? data.range_end
            : `${data.range_start} – ${data.range_end}`}
        </p>
      )}
      {isError && !data ? (
        <ErrorState
          title="Failed to load digests"
          error={errorDetail(error)}
          onRetry={() => void refetch()}
        />
      ) : isPending ? (
        <LoadingState variant="cards" />
      ) : data && digests.length === 0 ? (
        <EmptyState
          title={
            data.max_date
              ? 'Šajā periodā nav neviena kopsavilkuma.'
              : 'Vēl nav neviena kopsavilkuma.'
          }
        />
      ) : (
        <div
          aria-busy={isFetching}
          className={cx(
            'transition-opacity ' +
              'motion-safe:duration-180 ease-ia',
            isFetching && 'opacity-60',
          )}
        >
          {digests.map((digest) => (
            <section key={digest.date} className="digest">
              <h2>
                <Link to={`/${digest.date}`}>{digest.date}</Link>{' '}
                {digest.items.length > 0 && (
                  <AudioButton
                    jobs={jobsForItems(digest.items)}
                  />
                )}
              </h2>
              <ol>
                {digest.items.length === 0 ? (
                  <li className="muted">Nav ierakstu.</li>
                ) : (
                  digest.items.map((item: DigestListItemOut) => (
                    <li key={item.story_id}>
                      <StorySlot
                        storyId={item.story_id}
                        headline={item.headline}
                        trailing={
                          <AudioButton jobs={itemJobs(item)} />
                        }
                      />
                    </li>
                  ))
                )}
              </ol>
            </section>
          ))}
        </div>
      )}
    </PageContainer>
  );
}
