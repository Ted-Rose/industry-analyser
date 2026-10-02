import { apiGet, apiPost } from '../shared/api/client';
import type { components } from './api-types';

/** Type aliases over the generated OpenAPI schemas (api-types.ts). */
export type AdOut = components['schemas']['AdOut'];
export type AdsTableOut = components['schemas']['AdsTableOut'];
export type RegionNodeOut = components['schemas']['RegionNodeOut'];
export type RegionRefOut = components['schemas']['RegionRefOut'];
export type RegionConfigOut = components['schemas']['RegionConfigOut'];
export type RegionConfigIn = components['schemas']['RegionConfigIn'];
export type RegionConfigSavedOut =
  components['schemas']['RegionConfigSavedOut'];
export type RegionStatsOut = components['schemas']['RegionStatsOut'];
export type RegionStatsRowOut =
  components['schemas']['RegionStatsRowOut'];
export type RegionStatsChildrenOut =
  components['schemas']['RegionStatsChildrenOut'];
export type RegionAdsOut = components['schemas']['RegionAdsOut'];
export type DailySightingsOut =
  components['schemas']['DailySightingsOut'];
export type DailySightingsRowOut =
  components['schemas']['DailySightingsRowOut'];
export type SightingsRegionOut =
  components['schemas']['SightingsRegionOut'];
export type PropertyRowOut = components['schemas']['PropertyRowOut'];
export type PropertyListOut = components['schemas']['PropertyListOut'];
export type PropertyDetailOut =
  components['schemas']['PropertyDetailOut'];
export type LinkedAdOut = components['schemas']['LinkedAdOut'];

export type Kind = 'apartment' | 'house';
export type Deal = 'rent' | 'sale';

const API = '/api/classified-ads';

/** Pass numeric fields through only when they parse — the template
 *  inputs were free-form and the views ignored garbage (or 500'd), so
 *  a stray ?price_min=abc shouldn't 422 the whole page. */
function setNumber(
  qs: URLSearchParams,
  name: string,
  value?: string | null,
): void {
  if (value != null && value !== '' && !Number.isNaN(Number(value))) {
    qs.set(name, value);
  }
}

/** Non-numeric pages are dropped client-side — the template's
 *  paginator tolerated them, but the API contract is int (a stray
 *  ?page=abc shouldn't 422 the whole page). */
function appendPage(qs: URLSearchParams, page?: string | null): void {
  if (page && /^\d+$/.test(page)) qs.set('page', page);
}

/** date inputs arrive as YYYY-MM-DD; send only well-formed values. */
function setDate(
  qs: URLSearchParams,
  name: string,
  value?: string | null,
): void {
  if (value && /^\d{4}-\d{2}-\d{2}$/.test(value)) qs.set(name, value);
}

export interface AdsTableParams {
  district?: string | null;
  rooms?: string | null;
  priceMin?: string | null;
  priceMax?: string | null;
  page?: string | null;
}

/** GET /api/classified-ads/ads/?kind=&deal=&district=&rooms=
 *  &price_min=&price_max=&page= — one table page plus the district /
 *  rooms filter option lists (single fat endpoint). */
export function fetchAdsTable(
  kind: Kind,
  deal: Deal,
  params: AdsTableParams,
): Promise<AdsTableOut> {
  const qs = new URLSearchParams();
  qs.set('kind', kind);
  qs.set('deal', deal);
  if (params.district) qs.set('district', params.district);
  setNumber(qs, 'rooms', params.rooms);
  setNumber(qs, 'price_min', params.priceMin);
  setNumber(qs, 'price_max', params.priceMax);
  appendPage(qs, params.page);
  return apiGet<AdsTableOut>(`${API}/ads/?${qs}`);
}

/** GET /api/classified-ads/regions/config/?kind= — the region tree +
 *  enabled counts for the config page. */
export function fetchRegionConfig(kind: Kind): Promise<RegionConfigOut> {
  return apiGet<RegionConfigOut>(
    `${API}/regions/config/?kind=${kind}`,
  );
}

/** POST /api/classified-ads/regions/config/ — session-auth mutation
 *  replacing the retired anonymous POST forms (401 → login bounce via
 *  the shared client's login_url handling). */
export function saveRegionConfig(
  input: RegionConfigIn,
): Promise<RegionConfigSavedOut> {
  return apiPost<RegionConfigSavedOut>(
    `${API}/regions/config/`,
    input,
  );
}

export interface RegionStatsParams {
  dateFrom?: string | null;
  dateTo?: string | null;
  dealType?: string | null;
  regions?: string[];
}

function appendStatsQuery(
  qs: URLSearchParams,
  params: Omit<RegionStatsParams, 'regions'>,
): void {
  setDate(qs, 'date_from', params.dateFrom);
  setDate(qs, 'date_to', params.dateTo);
  if (params.dealType) qs.set('deal_type', params.dealType);
}

/** GET /api/classified-ads/regions/stats/ — parent-region stats; the
 *  `regions` param repeats per checked region (mirrors the retired
 *  checkbox form's name="regions"). */
export function fetchRegionStats(
  kind: Kind,
  params: RegionStatsParams,
): Promise<RegionStatsOut> {
  const qs = new URLSearchParams();
  qs.set('kind', kind);
  appendStatsQuery(qs, params);
  (params.regions ?? []).forEach((id) => {
    if (/^\d+$/.test(id)) qs.append('regions', id);
  });
  return apiGet<RegionStatsOut>(
    `${API}/regions/stats/?${qs}`,
  );
}

/** GET /api/classified-ads/regions/<id>/children/ — sub-region stats
 *  for one parent region. */
export function fetchRegionStatsChildren(
  kind: Kind,
  regionId: string,
  params: Omit<RegionStatsParams, 'regions'>,
): Promise<RegionStatsChildrenOut> {
  const qs = new URLSearchParams();
  qs.set('kind', kind);
  appendStatsQuery(qs, params);
  return apiGet<RegionStatsChildrenOut>(
    `${API}/regions/${regionId}/children/?${qs}`,
  );
}

export interface RegionAdsParams {
  dateFrom?: string | null;
  dateTo?: string | null;
  dealType?: string | null;
  page?: string | null;
}

/** GET /api/classified-ads/regions/<id>/ads/ — ads first-seen in the
 *  window inside the region subtree (empty unless deal_type is set). */
export function fetchRegionAds(
  kind: Kind,
  regionId: string,
  params: RegionAdsParams,
): Promise<RegionAdsOut> {
  const qs = new URLSearchParams();
  qs.set('kind', kind);
  appendStatsQuery(qs, params);
  appendPage(qs, params.page);
  return apiGet<RegionAdsOut>(
    `${API}/regions/${regionId}/ads/?${qs}`,
  );
}

export interface SightingsParams {
  dateFrom?: string | null;
  dateTo?: string | null;
  order?: string | null;
  region?: string | null;
}

/** GET /api/classified-ads/sightings/ — daily sighting counts per ad
 *  table, optionally restricted to a region subtree. */
export function fetchDailySightings(
  params: SightingsParams,
): Promise<DailySightingsOut> {
  const qs = new URLSearchParams();
  setDate(qs, 'date_from', params.dateFrom);
  setDate(qs, 'date_to', params.dateTo);
  if (params.order === 'asc' || params.order === 'desc') {
    qs.set('order', params.order);
  }
  setNumber(qs, 'region', params.region);
  const suffix = qs.toString();
  return apiGet<DailySightingsOut>(
    `${API}/sightings/${suffix ? `?${suffix}` : ''}`,
  );
}

export interface PropertyListParams {
  district?: string | null;
  street?: string | null;
  page?: string | null;
}

/** GET /api/classified-ads/properties/?kind=&district=&street=&page= */
export function fetchProperties(
  kind: Kind,
  params: PropertyListParams,
): Promise<PropertyListOut> {
  const qs = new URLSearchParams();
  qs.set('kind', kind);
  if (params.district) qs.set('district', params.district);
  if (params.street) qs.set('street', params.street);
  appendPage(qs, params.page);
  return apiGet<PropertyListOut>(`${API}/properties/?${qs}`);
}

/** GET /api/classified-ads/properties/<kind>/<pk>/ */
export function fetchProperty(
  kind: Kind,
  pk: string,
): Promise<PropertyDetailOut> {
  return apiGet<PropertyDetailOut>(
    `${API}/properties/${kind}/${pk}/`,
  );
}
