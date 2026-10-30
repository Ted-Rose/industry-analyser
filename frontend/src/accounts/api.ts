import { apiGet, apiPost } from '../shared/api/client';
import type { components } from './api-types';

/** Type aliases over the generated OpenAPI schemas (api-types.ts). */
export type UserOut = components['schemas']['UserOut'];
export type MeOut = components['schemas']['MeOut'];
export type AuthOut = components['schemas']['AuthOut'];
export type RegisterIn = components['schemas']['RegisterIn'];
export type LoginIn = components['schemas']['LoginIn'];
export type SuccessOut = components['schemas']['SuccessOut'];

const API = '/api/accounts';

/** GET /api/accounts/me/ — always 200; the auth-state probe.
 *  Never 401s, so calling it can't bounce the page to login. */
export function fetchMe(): Promise<MeOut> {
  return apiGet<MeOut>(`${API}/me/`);
}

/** POST /api/accounts/register/ — anonymous; success creates the
 *  session (auto-login). */
export function register(input: RegisterIn): Promise<AuthOut> {
  return apiPost<AuthOut>(`${API}/register/`, input);
}

/** POST /api/accounts/login/ — anonymous; username resolves
 *  case-insensitively. */
export function login(input: LoginIn): Promise<AuthOut> {
  return apiPost<AuthOut>(`${API}/login/`, input);
}

/** POST /api/accounts/logout/ — session-authed (django_auth). */
export function logout(): Promise<SuccessOut> {
  return apiPost<SuccessOut>(`${API}/logout/`);
}
