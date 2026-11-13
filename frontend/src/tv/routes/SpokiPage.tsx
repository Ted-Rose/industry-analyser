import { useQuery } from '@tanstack/react-query';
import { fetchSpokiPage } from '../api';
import { errorDetail } from '../../shared/api/errors';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Card from '../../shared/ui/Card';
import ErrorState from '../../shared/ui/ErrorState';
import Prose from '../../shared/ui/Prose';
import { LoadingState } from '../../shared/ui/Skeleton';

/**
 * React port of the old spoki_page view — fetches the hardcoded
 * spoki.lv article through GET /api/tv/spoki-page/ and renders the
 * HTML fragment (same |safe trust posture as the template) inside
 * the kit's Prose typography wrapper (plan §9.6).
 */
export default function SpokiPage() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['tv', 'spoki-page'],
    queryFn: fetchSpokiPage,
  });

  return (
    <PageContainer width="narrow">
      <PageHeader
        title={data?.title ?? 'Spoki'}
        back={{ to: '/', label: 'Back to the program feed' }}
      />
      <Card>
        {isPending && <LoadingState variant="cards" rows={1} />}
        {isError && (
          <ErrorState
            title="Failed to load"
            error={errorDetail(error)}
            onRetry={() => void refetch()}
          />
        )}
        {data && (
          /* The API returns the article's HTML fragment, like the
             template's {{ content|safe }} — rendered as markup. */
          <Prose html={data.content} />
        )}
      </Card>
    </PageContainer>
  );
}
