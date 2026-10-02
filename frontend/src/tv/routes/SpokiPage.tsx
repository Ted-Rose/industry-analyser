import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchSpokiPage } from '../api';
import { errorDetail } from '../../shared/api/errors';

/**
 * React port of the old spoki_page view — fetches the hardcoded
 * spoki.lv article through GET /api/tv/spoki-page/ and renders the
 * HTML fragment (same |safe trust posture as the template).
 */
export default function SpokiPage() {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['tv', 'spoki-page'],
    queryFn: fetchSpokiPage,
  });

  return (
    <div className="feed-container">
      <div className="spoki-article">
        {isPending && <p>Loading…</p>}
        {isError && <p>Failed to load — {errorDetail(error)}</p>}
        {data && (
          <>
            <h1>{data.title}</h1>
            {/* The API returns the article's HTML fragment, like the
                template's {{ content|safe }} — rendered as markup. */}
            <div dangerouslySetInnerHTML={{ __html: data.content }} />
          </>
        )}
      </div>
      <p>
        <Link to="/">← Back to the program feed</Link>
      </p>
    </div>
  );
}
