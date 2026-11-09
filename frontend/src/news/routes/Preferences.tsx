import { FormEvent, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  fetchDigestTaskStatus,
  fetchPreferences,
  type PreferenceRowIn,
} from '../api';
import {
  useSavePreferences,
  useSubscribeDigestTask,
  useUnsubscribeDigestTask,
} from '../mutations';
import { errorDetail } from '../../shared/api/errors';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Button from '../../shared/ui/Button';
import Card, { CardHeader } from '../../shared/ui/Card';
import Checkbox from '../../shared/ui/Checkbox';
import ErrorState from '../../shared/ui/ErrorState';
import { LoadingState } from '../../shared/ui/Skeleton';
import { pushToast } from '../../shared/toasts';

interface DraftRow {
  checked: boolean;
  /** Number input's raw value — '' is checked-but-unranked. */
  rank: string;
}

/**
 * The Google Tasks digest card — one state per the status
 * payload: hidden when OAuth is unconfigured, a Connect link
 * (which returns here carrying ?subscribe=1), a Subscribe
 * button, or the subscribed state with the last task's
 * status/error plus Unsubscribe.
 */
function DigestTaskCard() {
  const { data } = useQuery({
    queryKey: ['news', 'digest-task'],
    queryFn: fetchDigestTaskStatus,
  });
  const subscribe = useSubscribeDigestTask();
  const unsubscribe = useUnsubscribeDigestTask();
  const [searchParams, setSearchParams] = useSearchParams();
  const wantSubscribe = searchParams.get('subscribe') === '1';
  const subscribeFired = useRef(false);

  // The OAuth round-trip lands back here with ?subscribe=1 —
  // fire subscribe once the status payload shows a connected,
  // unsubscribed user, then strip the param so a refresh can't
  // silently re-subscribe someone who just opted out.
  useEffect(() => {
    if (!wantSubscribe || !data) return;
    const canSubscribe = data.google_connected && !data.subscribed;
    if (canSubscribe && !subscribeFired.current) {
      subscribeFired.current = true;
      subscribe.mutate(undefined, {
        onError: (mutationError) =>
          pushToast(
            `Subscribe failed — ${errorDetail(mutationError)}`,
            'danger',
          ),
      });
    }
    const stillWaiting =
      canSubscribe && !subscribe.isSuccess && !subscribe.isError;
    if (!stillWaiting) {
      const next = new URLSearchParams(searchParams);
      next.delete('subscribe');
      setSearchParams(next, { replace: true });
    }
  }, [wantSubscribe, data, subscribe, searchParams, setSearchParams]);

  if (!data || !data.oauth_configured) return null;

  const last = data.last_task;
  return (
    <Card className="mt-4">
      <CardHeader
        title="Google Tasks digest"
        description={
          'Katrā jaunā ziņu kopsavilkumā tavā Google Tasks ' +
          'sarakstā tiks izveidots uzdevums ar saiti uz to.'
        }
      />
      {!data.google_connected ? (
        <Button
          as="a"
          href={
            '/google/login/' +
            '?next=/news/preferences/?subscribe=1'
          }
          className="mt-2"
        >
          Pievienot Google
        </Button>
      ) : !data.subscribed ? (
        <Button
          onClick={() => subscribe.mutate()}
          loading={subscribe.isPending}
          className="mt-2"
        >
          Piesakties
        </Button>
      ) : (
        <div className="mt-2">
          <p className="text-sm text-fg">
            Piesakts — uzdevums tiks izveidots nākamajā
            kopsavilkuma izveidē.
          </p>
          {last && (
            <p className="mt-1 text-sm text-fg-muted">
              {`Pēdējais uzdevums (${last.digest_date}): `}
              <strong>{last.status}</strong>
              {last.status === 'failed' && (
                <>
                  {` — ${last.error} `}
                  <a href="/google/login">
                    Pievieno Google vēlreiz
                  </a>
                </>
              )}
            </p>
          )}
          <Button
            variant="secondary"
            onClick={() => unsubscribe.mutate()}
            loading={unsubscribe.isPending}
            className="mt-2"
          >
            Atsakties
          </Button>
        </div>
      )}
    </Card>
  );
}

/**
 * React port of news/preferences.html — rank favorite
 * outlets: checked sources ordered by their submitted rank
 * become NewsSourcePreference rank 1..N (checked-but-unranked
 * sinks last server-side). Anonymous readers never reach the
 * form — the GET's 401 login_url handshake bounces to
 * /accounts/login/?next=/news/preferences/ (equivalent to
 * the old @login_required 302).
 */
export default function Preferences() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['news', 'preferences'],
    queryFn: fetchPreferences,
  });
  const mutation = useSavePreferences();
  const [draft, setDraft] = useState<Record<string, DraftRow>>({});

  useEffect(() => {
    document.title = 'Portālu izvēle';
  }, []);

  // Seed the staged form from the payload — checked + rank
  // echo the user's saved rows (rank '' = the old empty
  // input).
  useEffect(() => {
    if (!data) return;
    setDraft(
      Object.fromEntries(
        data.rows.map((row) => [
          row.slug,
          {
            checked: row.checked,
            rank: row.rank == null ? '' : String(row.rank),
          },
        ]),
      ),
    );
  }, [data]);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!data) return;
    const rows: PreferenceRowIn[] = data.rows
      .filter((row) => draft[row.slug]?.checked)
      .map((row) => {
        const raw = draft[row.slug]?.rank ?? '';
        return {
          slug: row.slug,
          rank: raw === '' ? null : Number(raw),
        };
      });
    mutation.mutate(rows, {
      onSuccess: (result) =>
        pushToast(result.message, 'success'),
      onError: (mutationError) =>
        pushToast(
          `Save failed — ${errorDetail(mutationError)}`,
          'danger',
        ),
    });
  };

  return (
    <PageContainer width="prose" className="news-prose">
      <PageHeader
        title="Portālu izvēle"
        description={
          'Atzīmē mīļākos ziņu portālus un piešķir tiem ' +
          'rangu — mazāks skaitlis nozīmē augstāku ' +
          'prioritāti. Kad vairāki portāli raksta par to ' +
          'pašu notikumu, atverot virsrakstu tiks rādīts ' +
          'tava augstāk novērtētā portāla raksts.'
        }
      />
      {isError ? (
        <ErrorState
          title="Failed to load preferences"
          error={errorDetail(error)}
          onRetry={() => void refetch()}
        />
      ) : isPending || !data ? (
        <LoadingState variant="cards" />
      ) : (
        <form onSubmit={onSubmit}>
          <table className="prefs">
            <tbody>
              {data.rows.map((row) => {
                const entry = draft[row.slug] ?? {
                  checked: row.checked,
                  rank: row.rank == null ? '' : String(row.rank),
                };
                return (
                  <tr key={row.slug}>
                    <td>
                      <Checkbox
                        id={`src-${row.slug}`}
                        name={`include-${row.slug}`}
                        label={row.name}
                        checked={entry.checked}
                        onChange={(event) =>
                          setDraft((d) => ({
                            ...d,
                            [row.slug]: {
                              ...entry,
                              checked: event.target.checked,
                            },
                          }))
                        }
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        min={1}
                        max={99}
                        size={3}
                        name={`rank-${row.slug}`}
                        value={entry.rank}
                        aria-label={`${row.name} rangs`}
                        onChange={(event) =>
                          setDraft((d) => ({
                            ...d,
                            [row.slug]: {
                              ...entry,
                              rank: event.target.value,
                            },
                          }))
                        }
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Button
            type="submit"
            loading={mutation.isPending}
            className="mt-2"
          >
            Saglabāt
          </Button>
        </form>
      )}
      <DigestTaskCard />
    </PageContainer>
  );
}
