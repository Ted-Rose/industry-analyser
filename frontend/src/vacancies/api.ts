import { apiGet, apiPost } from '../shared/api/client';
import type { components } from './api-types';

/** Type aliases over the generated OpenAPI schemas (api-types.ts). */
export type VacanciesOut = components['schemas']['VacanciesOut'];
export type VacancyOut = components['schemas']['VacancyOut'];
export type CompaniesOut = components['schemas']['CompaniesOut'];
export type CompanyOut = components['schemas']['CompanyOut'];
export type CompanyDetailOut =
  components['schemas']['CompanyDetailOut'];
export type CompanyVacancyOut =
  components['schemas']['CompanyVacancyOut'];
export type CompanyIdentityOut =
  components['schemas']['CompanyIdentityOut'];
export type KeywordIn = components['schemas']['KeywordIn'];
export type KeywordSavedOut =
  components['schemas']['KeywordSavedOut'];

/** Filter/page state of the vacancy list, parsed from the URL. */
export interface VacancyParams {
  includeKeywords: string[];
  excludeKeywords: string[];
  includeIndustries: string[];
  showActiveOnly: boolean;
  page?: string | null;
}

/** Non-numeric pages are dropped client-side — the template's
 *  paginator tolerated them, but the API contract is int (a stray
 *  ?page=abc shouldn't 422 the whole page). */
function appendPage(qs: URLSearchParams, page?: string | null): void {
  if (page && /^\d+$/.test(page)) qs.set('page', page);
}

/** GET /api/vacancies/ — one page plus the keyword/industry filter
 *  option lists (single fat endpoint per the rewrite plan). */
export function fetchVacancies(
  params: VacancyParams,
): Promise<VacanciesOut> {
  const qs = new URLSearchParams();
  params.includeKeywords.forEach((k) =>
    qs.append('include_keywords', k),
  );
  params.excludeKeywords.forEach((k) =>
    qs.append('exclude_keywords', k),
  );
  params.includeIndustries.forEach((i) =>
    qs.append('include_industries', i),
  );
  if (params.showActiveOnly) qs.set('show_active_only', '1');
  appendPage(qs, params.page);
  const suffix = qs.toString();
  return apiGet<VacanciesOut>(
    `/api/vacancies/${suffix ? `?${suffix}` : ''}`,
  );
}

export interface CompaniesParams {
  q?: string | null;
  page?: string | null;
}

/** GET /api/vacancies/companies/?q=&page= */
export function fetchCompanies(
  params: CompaniesParams = {},
): Promise<CompaniesOut> {
  const qs = new URLSearchParams();
  if (params.q) qs.set('q', params.q);
  appendPage(qs, params.page);
  const suffix = qs.toString();
  return apiGet<CompaniesOut>(
    `/api/vacancies/companies/${suffix ? `?${suffix}` : ''}`,
  );
}

/** GET /api/vacancies/companies/<pk>/?page= */
export function fetchCompany(
  pk: string,
  page?: string | null,
): Promise<CompanyDetailOut> {
  const qs = new URLSearchParams();
  appendPage(qs, page);
  const suffix = qs.toString();
  return apiGet<CompanyDetailOut>(
    `/api/vacancies/companies/${pk}/${suffix ? `?${suffix}` : ''}`,
  );
}

/** POST /api/vacancies/keywords/ — session-auth mutation. */
export function addKeyword(input: KeywordIn): Promise<KeywordSavedOut> {
  return apiPost<KeywordSavedOut>('/api/vacancies/keywords/', input);
}
