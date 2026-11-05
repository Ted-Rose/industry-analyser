import { useEffect } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchDigest } from '../api';
import { ApiError, errorDetail } from '../../shared/api/errors';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState from '../../shared/ui/ErrorState';
import { LoadingState } from '../../shared/ui/Skeleton';

/**
 * React port of news/digest_detail.html — one digest day:
 * `rank. headline`, the `rationale · topic` muted line and
 * the confirmed-members-only article list (candidate links
 * never arrive — the API filters them). Garbage or missing
 * dates 404 at the API and render the not-found state.
 */
export default function DigestDetail() {
  const { date } = useParams<{ date: string }>();

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['news', 'digest', date],
    queryFn: () => fetchDigest(date as string),
    enabled: Boolean(date),
    retry: (failureCount, queryError) =>
      !(queryError instanceof ApiError && queryError.status === 404) &&
      failureCount < 3,
  });

  useEffect(() => {
    if (date) {
      document.title = `Kopsavilkums ${date}`;
    }
  }, [date]);

  const notFound =
    error instanceof ApiError && error.status === 404;

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
      ) : data.items.length === 0 ? (
        <p className="muted">Šajā kopsavilkumā nav ierakstu.</p>
      ) : (
        data.items.map((item) => (
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
        ))
      )}
    </PageContainer>
  );
}
