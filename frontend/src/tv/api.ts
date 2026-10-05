import { apiGet, apiPost } from '../shared/api/client';
import type { components } from './api-types';

/** Type aliases over the generated OpenAPI schemas (api-types.ts). */
export type ProgramsOut = components['schemas']['ProgramsOut'];
export type ProgramOut = components['schemas']['ProgramOut'];
export type ProgramFiltersOut =
  components['schemas']['ProgramFiltersOut'];
export type SpokiPageOut = components['schemas']['SpokiPageOut'];
export type ReactionOut = components['schemas']['ReactionOut'];

/** Filter state of the program feed, parsed from the URL. Mirrors
 *  the GET params of the retired program_list view/form. */
export interface ProgramParams {
  contentRating?: string | null;
  notContentRating?: string | null;
  ratingValue?: string | null;
  ratio?: string | null;
  startDate?: string | null;
  endDate?: string | null;
  channel?: string | null;
  excludeChannel?: string | null;
  showDisliked?: string | null;
}

/** Pass numeric fields through only when they parse — the template
 *  inputs were free-form and the view ignored garbage, so a stray
 *  ?rating_value=abc shouldn't 422 the whole feed. */
function setNumber(
  qs: URLSearchParams,
  name: string,
  value?: string | null,
): void {
  if (value != null && value !== '' && !Number.isNaN(Number(value))) {
    qs.set(name, value);
  }
}

/** GET /api/tv/programs/ — one fat payload: filtered programs, the
 *  channel option list and the effective filter state. */
export function fetchPrograms(
  params: ProgramParams,
): Promise<ProgramsOut> {
  const qs = new URLSearchParams();
  if (params.contentRating) {
    qs.set('content_rating', params.contentRating);
  }
  // An explicit empty string disables the default 'R' exclusion —
  // the param must be sent (unset → server default 'R'), matching
  // the old form which always submitted the field.
  if (params.notContentRating != null) {
    qs.set('not_content_rating', params.notContentRating);
  }
  setNumber(qs, 'rating_value', params.ratingValue);
  setNumber(qs, 'ratio', params.ratio);
  if (params.startDate) qs.set('start_date', params.startDate);
  if (params.endDate) qs.set('end_date', params.endDate);
  if (params.channel) qs.set('channel', params.channel);
  if (params.excludeChannel) {
    qs.set('exclude_channel', params.excludeChannel);
  }
  if (params.showDisliked === '1') qs.set('show_disliked', '1');
  const suffix = qs.toString();
  return apiGet<ProgramsOut>(
    `/api/tv/programs/${suffix ? `?${suffix}` : ''}`,
  );
}

/** GET /api/tv/spoki-page/ — live-fetched article title + HTML. */
export function fetchSpokiPage(): Promise<SpokiPageOut> {
  return apiGet<SpokiPageOut>('/api/tv/spoki-page/');
}

/** POST /api/tv/programs/<id>/react/<reaction>/ — session-auth
 *  toggle. Program-level so unlinked airings (no Show yet) are
 *  reactable too — the API lazily resolves the canonical Show. */
export function reactToProgram(
  programId: string,
  reaction: 'like' | 'dislike',
): Promise<ReactionOut> {
  return apiPost<ReactionOut>(
    `/api/tv/programs/${programId}/react/${reaction}/`,
  );
}
