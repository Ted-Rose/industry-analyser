import { apiGet } from '../shared/api/client';
import type { components } from './api-types';

/** Type aliases over the generated OpenAPI schemas (api-types.ts). */
export type DashboardOut = components['schemas']['DashboardOut'];
export type JobRowOut = components['schemas']['JobRowOut'];
export type LastRunOut = components['schemas']['LastRunOut'];
export type DayRowOut = components['schemas']['DayRowOut'];
export type RunTotalsOut = components['schemas']['RunTotalsOut'];

const API = '/api/dashboard';

export interface DashboardParams {
  /** Page URLs keep the retired template's ?from=/&to= names so old
   *  bookmarks still filter; the API takes date_from/date_to. */
  dateFrom?: string | null;
  dateTo?: string | null;
}

/** date inputs arrive as YYYY-MM-DD; send only well-formed values. */
function setDate(
  qs: URLSearchParams,
  name: string,
  value?: string | null,
): void {
  if (value && /^\d{4}-\d{2}-\d{2}$/.test(value)) qs.set(name, value);
}

/** GET /api/dashboard/ — the whole page in one fat call (jobs
 *  table + day x job table + totals + the effective date window).
 *  Session-authed: a 401 body carries login_url and the shared
 *  client navigates there itself. */
export function fetchDashboard(
  params: DashboardParams = {},
): Promise<DashboardOut> {
  const qs = new URLSearchParams();
  setDate(qs, 'date_from', params.dateFrom);
  setDate(qs, 'date_to', params.dateTo);
  const suffix = qs.toString();
  return apiGet<DashboardOut>(
    `${API}/${suffix ? `?${suffix}` : ''}`,
  );
}
