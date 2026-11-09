import { apiGet, apiPost } from '../shared/api/client';
import type { components } from './api-types';

/** Type aliases over the generated OpenAPI schemas (api-types.ts). */
export type DigestListOut = components['schemas']['DigestListOut'];
export type DigestOut = components['schemas']['DigestOut'];
export type DigestListItemOut =
  components['schemas']['DigestListItemOut'];
export type DigestDetailOut =
  components['schemas']['DigestDetailOut'];
export type DigestDetailItemOut =
  components['schemas']['DigestDetailItemOut'];
export type StoryCardOut = components['schemas']['StoryCardOut'];
export type StoryArticleOut =
  components['schemas']['StoryArticleOut'];
export type PreferencesOut =
  components['schemas']['PreferencesOut'];
export type PreferenceRowOut =
  components['schemas']['PreferenceRowOut'];
export type PreferencesSavedOut =
  components['schemas']['PreferencesSavedOut'];
export type DigestTaskStatusOut =
  components['schemas']['DigestTaskStatusOut'];

/** One submitted preferences row — presence = the include
 *  checkbox; `rank: null` is checked-but-unranked (sinks last
 *  server-side). */
export interface PreferenceRowIn {
  slug: string;
  rank: number | null;
}

/** GET /api/news/digests/ — digests plus the effective
 *  filter state. Params pass through raw: the op parses
 *  `date` itself and degrades malformed values to the
 *  default window (never a 422 on garbage like the old
 *  template page). */
export function fetchDigests(params: {
  date?: string | null;
  period?: string | null;
}): Promise<DigestListOut> {
  const qs = new URLSearchParams();
  if (params.date) qs.set('date', params.date);
  if (params.period) qs.set('period', params.period);
  const suffix = qs.toString();
  return apiGet<DigestListOut>(
    `/api/news/digests/${suffix ? `?${suffix}` : ''}`,
  );
}

/** GET /api/news/digests/<date>/ — one digest day. */
export function fetchDigest(date: string): Promise<DigestDetailOut> {
  return apiGet<DigestDetailOut>(`/api/news/digests/${date}/`);
}

/** GET /api/news/stories/<id>/ — the inline-reader story card;
 *  `?source=<slug>` switches the picked outlet (stale slugs
 *  fall back server-side). */
export function fetchStoryCard(
  storyId: number,
  source?: string | null,
): Promise<StoryCardOut> {
  const qs = new URLSearchParams();
  if (source) qs.set('source', source);
  const suffix = qs.toString();
  return apiGet<StoryCardOut>(
    `/api/news/stories/${storyId}/${suffix ? `?${suffix}` : ''}`,
  );
}

/** GET /api/news/preferences/ — session-auth; the 401
 *  login_url handshake bounces anonymous readers to
 *  /accounts/login/?next=/news/preferences/. */
export function fetchPreferences(): Promise<PreferencesOut> {
  return apiGet<PreferencesOut>('/api/news/preferences/');
}

/** POST /api/news/preferences/ — replaces the user's outlet
 *  ranking wholesale (checked rows only, ranks renumbered
 *  1..N server-side). */
export function savePreferences(
  rows: PreferenceRowIn[],
): Promise<PreferencesSavedOut> {
  return apiPost<PreferencesSavedOut>(
    '/api/news/preferences/',
    { rows },
  );
}

/** GET /api/news/digest-task/ — session-auth; the digest-task
 *  card's subscription/Google-connection state plus the
 *  caller's newest link row. */
export function fetchDigestTaskStatus(): Promise<DigestTaskStatusOut> {
  return apiGet<DigestTaskStatusOut>('/api/news/digest-task/');
}

/** POST /api/news/digest-task/subscribe/ — idempotent opt-in;
 *  answers the same status payload (200 even without a Google
 *  grant). */
export function subscribeDigestTask(): Promise<DigestTaskStatusOut> {
  return apiPost<DigestTaskStatusOut>(
    '/api/news/digest-task/subscribe/',
  );
}

/** POST /api/news/digest-task/unsubscribe/ — idempotent
 *  opt-out; keeps the row (is_enabled=false) server-side. */
export function unsubscribeDigestTask(): Promise<DigestTaskStatusOut> {
  return apiPost<DigestTaskStatusOut>(
    '/api/news/digest-task/unsubscribe/',
  );
}
