import { apiGet } from '../shared/api/client';
import type { components } from './api-types';

/** Type aliases over the generated OpenAPI schemas (api-types.ts). */
export type ReceiptsDashboardOut =
  components['schemas']['ReceiptsDashboardOut'];
export type ReceiptRowOut = components['schemas']['ReceiptRowOut'];
export type ReceiptItemOut = components['schemas']['ReceiptItemOut'];
export type CategoryOut = components['schemas']['CategoryOut'];
export type TopItemOut = components['schemas']['TopItemOut'];
export type MonthlyRowOut = components['schemas']['MonthlyRowOut'];
export type StoreRowOut = components['schemas']['StoreRowOut'];
export type SummaryOut = components['schemas']['SummaryOut'];

const API = '/api/receipts';

export interface ReceiptsDashboardParams {
  /** Page URLs keep the retired template's ?date_from=/&date_to=
   *  names, so old bookmarks keep filtering. */
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

/** GET /api/receipts/ — the whole page in one fat call (summary
 *  cards + by-month/by-store/by-category tables + the all-receipts
 *  table). Session-authed: the op keeps django_auth and the page
 *  mount is login-required — a 401's login_url sends the browser
 *  to /admin/login/?next=/receipts/. */
export function fetchReceiptsDashboard(
  params: ReceiptsDashboardParams = {},
): Promise<ReceiptsDashboardOut> {
  const qs = new URLSearchParams();
  setDate(qs, 'date_from', params.dateFrom);
  setDate(qs, 'date_to', params.dateTo);
  const suffix = qs.toString();
  return apiGet<ReceiptsDashboardOut>(
    `${API}/${suffix ? `?${suffix}` : ''}`,
  );
}
