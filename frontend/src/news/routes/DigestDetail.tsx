import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  useInfiniteQuery,
  useQuery,
} from '@tanstack/react-query';
import {
  fetchDigest,
  fetchDigestExtra,
  type DigestDetailItemOut,
  type DigestExtraItemOut,
} from '../api';
import { ApiError, errorDetail } from '../../shared/api/errors';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Button from '../../shared/ui/Button';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState from '../../shared/ui/ErrorState';
import { LoadingState } from '../../shared/ui/Skeleton';

/** One ranked digest row — identical markup for stored
 *  DigestDetailItemOut rows and the appended 'Load more'
 *  DigestExtraItemOut rows (ranks continue across both). */
function renderItem(
  item: DigestDetailItemOut | DigestExtraItemOut,
) {
  return (
    <article key={item.rank} className="item">
      <h3>
        {item.rank}. {item.headline}
      </h3>
      <p className="muted">
        {item.rationale}
        {item.topic_name && ` · ${item.topic_name}`}
      </p>
      <ul className="articles">
        {item.articles.map((article) => (
          <li key={article.link}>
            <a href={article.link}>{article.title}</a>{' '}
            <span className="muted">
              ({article.source_name})
            </span>
          </li>
        ))}
      </ul>
    </article>
  );
}

/**
 * React port of news/digest_detail.html — one digest day:
 * `rank. headline`, the `rationale · topic` muted line and
 * the confirmed-members-only article list (candidate links
 * never arrive — the API filters them). Garbage or missing
 * dates 404 at the API and render the not-found state. When
 * the day holds eligible stories past the stored top-N
 * (`has_more`), a 'Load more' button appends them 20 at a
 * time via /api/news/digests/<date>/extra/.
 */
export default function DigestDetail() {
  const { date } = useParams<{ date: string }>();
  // Extras stream only after the first 'Load more' click —
  // the infinite query stays disabled until then so its
  // initial page never prefetches. Deriving the flag from
  // startedDate === date (not an effect reset) keeps a
  // same-route date change from briefly enabling the query
  // during the commit before the reset effect runs.
  const [startedDate, setStartedDate] = useState<string | null>(
    null,
  );
  const moreStarted = startedDate === date;

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['news', 'digest', date],
    queryFn: () => fetchDigest(date as string),
    enabled: Boolean(date),
    retry: (failureCount, queryError) =>
      !(queryError instanceof ApiError && queryError.status === 404) &&
      failureCount < 3,
  });

  const extra = useInfiniteQuery({
    queryKey: ['news', 'digest', date, 'extra'],
    queryFn: ({ pageParam }) =>
      fetchDigestExtra(date as string, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last) =>
      last.has_next
        ? last.offset + last.items.length
        : undefined,
    enabled: Boolean(date) && moreStarted,
  });

  useEffect(() => {
    if (date) {
      document.title = `Kopsavilkums ${date}`;
    }
  }, [date]);

  const notFound =
    error instanceof ApiError && error.status === 404;

  const extraItems =
    extra.data?.pages.flatMap((page) => page.items) ?? [];
  // The server's has_more gates the first click; once pages
  // stream in, the last page's has_next takes over. While a
  // failed FIRST page shows its ErrorState+Retry, hide the
  // button — its onClick is a no-op then (moreStarted already
  // true and fetchNextPage has nothing to resume).
  const moreAvailable =
    (extra.data ? Boolean(extra.hasNextPage)
      : (data?.has_more ?? false)) &&
    !(extra.isError && !extra.data);

  return (
    <PageContainer width="prose" className="news-prose">
      <nav className="back">
        <Link to="/">&larr; Visi kopsavilkumi</Link>
      </nav>
      <PageHeader title={data?.date ?? date} />
      {isError ? (
        notFound ? (
          <EmptyState title="Kopsavilkums nav atrasts." />
        ) : (
          <ErrorState
            title="Failed to load the digest"
            error={errorDetail(error)}
            onRetry={() => void refetch()}
          />
        )
      ) : isPending || !data ? (
        <LoadingState variant="cards" />
      ) : (
        <>
          {/* A digest row can hold 0 stored items yet still
              have eligible extras (stories re-clustered after
              the build) — the extras UI lives outside the
              empty-list branch so has_more stays reachable. */}
          {data.items.length === 0 ? (
            <p className="muted">
              Šajā kopsavilkumā nav ierakstu.
            </p>
          ) : (
            data.items.map(renderItem)
          )}
          {extraItems.map(renderItem)}
          {extra.isError && (
            <ErrorState
              title="Failed to load more news"
              error={errorDetail(extra.error)}
              onRetry={() =>
                void (extra.data
                  ? extra.fetchNextPage()
                  : extra.refetch())
              }
            />
          )}
          {moreAvailable && (
            <Button
              variant="secondary"
              className="mt-4"
              loading={
                extra.isFetchingNextPage ||
                (moreStarted && !extra.data && extra.isFetching)
              }
              onClick={() =>
                extra.data
                  ? void extra.fetchNextPage()
                  : setStartedDate(date as string)
              }
            >
              Ielādēt vēl 20 ziņas
            </Button>
          )}
        </>
      )}
    </PageContainer>
  );
}
