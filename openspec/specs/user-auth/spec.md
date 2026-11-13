# user-auth Specification

## Purpose
Public user registration and session authentication: how
accounts are created, how users log in and out, how the current
user is reported, and how access splits between staff,
registered users, and anonymous visitors.

## Requirements

### Requirement: Public registration endpoint

`POST /api/accounts/register/` SHALL accept `{username,
password, password_confirm, email?}` anonymously (`auth=None`),
enforce CSRF, and on success create a non-staff user, establish
a session (auto-login) and answer 201 with `{user: {id,
username, email, is_staff}}`. Validation failures SHALL be 400
`{error, detail, code}`; a lost uniqueness race SHALL surface
as 400, never 500.

#### Scenario: Successful registration auto-logs-in

- **WHEN** an anonymous caller POSTs a valid username, matching
  passwords and no email
- **THEN** the user row exists with `is_staff=False`, the
  response is 201 `{user: {...}}`, and the session cookie now
  authenticates subsequent requests

#### Scenario: Duplicate username in a different case

- **WHEN** `alice` exists and a caller registers `ALICE`
- **THEN** the response is 400 with `code: 'username_taken'`

#### Scenario: Password rejected by validators

- **WHEN** the password fails `AUTH_PASSWORD_VALIDATORS` (too
  short, too common, numeric-only, or too similar to the
  username/email)
- **THEN** the response is 400 with `code: 'weak_password'` and
  no user row is created

#### Scenario: Missing CSRF token

- **WHEN** a register POST arrives without a valid CSRF token
- **THEN** the request is rejected before the endpoint runs

### Requirement: Username and email rules

Usernames SHALL match `^\S+$` (no whitespace) and be unique
case-insensitively, so the case-insensitive login lookup stays
deterministic. Email SHALL be optional, but unique
case-insensitively when provided.

#### Scenario: Username with whitespace

- **WHEN** a register body carries `username: 'al ice'`
- **THEN** the response is 400 with `code: 'invalid_username'`

#### Scenario: Email reused by another account

- **WHEN** a register body carries an email already on another
  user row
- **THEN** the response is 400 with `code: 'email_taken'`

#### Scenario: Blank email stored as empty

- **WHEN** a register body omits `email` or sends `''`
- **THEN** the user is created with an empty email and a second
  blank-email registration succeeds

### Requirement: Session login endpoint

`POST /api/accounts/login/` SHALL accept `{username, password}`
anonymously (`auth=None`), enforce CSRF, and authenticate
case-insensitively — a user registered as `Alice` logs in as
`alice`, with an exact-case row preferred if several differ
only by case. Success SHALL create a session and return 200
`{user: {id, username, email, is_staff}}`. Unknown usernames,
wrong passwords and inactive accounts SHALL all return the same
uniform failure — never a `login_url` body.

#### Scenario: Case-insensitive login

- **WHEN** `Alice` registered and a caller logs in as `alice`
  with the right password
- **THEN** the response is 200 `{user: {...}}` and the session
  authenticates subsequent requests

#### Scenario: Uniform credential failure

- **WHEN** the username does not exist, the password is wrong,
  or the account is inactive
- **THEN** the response is 401 `{error: 'unauthenticated',
  detail: '...', code: 'invalid_credentials'}` — identical in
  every case — and no `login_url` is emitted

### Requirement: Session logout endpoint

`POST /api/accounts/logout/` SHALL require an authenticated
session (default `django_auth`, CSRF enforced), end it, and
return 200 `{success: true}`.

#### Scenario: Authenticated logout

- **WHEN** a logged-in user POSTs to logout
- **THEN** the response is 200 and subsequent authenticated
  calls see an anonymous session

#### Scenario: Anonymous logout

- **WHEN** an anonymous caller POSTs to logout
- **THEN** the response is the standard 401 `login_url`
  handshake

### Requirement: Current-user endpoint

`GET /api/accounts/me/` SHALL be public (`auth=None`) and always
answer 200: `{user: {id, username, email, is_staff},
is_authenticated: true}` for a logged-in caller, `{user: null,
is_authenticated: false}` for an anonymous one — never a 401,
so callers can check auth state without triggering the client's
login redirect.

#### Scenario: Anonymous caller

- **WHEN** an anonymous caller GETs `/api/accounts/me/`
- **THEN** the response is 200 `{user: null,
  is_authenticated: false}`

#### Scenario: Authenticated caller

- **WHEN** a logged-in caller GETs `/api/accounts/me/`
- **THEN** the response is 200 with the user's id, username,
  email and `is_staff` flag

### Requirement: Staff-only access tier

`/dashboard/` + `GET /api/dashboard/`, `/receipts/` +
`GET /api/receipts/`, `POST /api/vacancies/keywords/` and
`POST /api/classified-ads/regions/config/` SHALL require staff:
anonymous callers get the 401 `login_url` handshake and
authenticated non-staff callers get 403
`{error: 'forbidden'}`.

#### Scenario: Registered user hits a staff-only API

- **WHEN** an authenticated non-staff user GETs
  `/api/dashboard/` or POSTs a staff-only mutation
- **THEN** the response is 403 `{error: 'forbidden'}`

#### Scenario: Anonymous caller hits a staff-only API

- **WHEN** an anonymous caller GETs `/api/receipts/`
- **THEN** the response is the 401 `login_url` handshake

#### Scenario: Staff-only SPA page

- **WHEN** an anonymous or non-staff user navigates to
  `/dashboard/` or `/receipts/`
- **THEN** they are redirected to the admin login, not the
  public login page

### Requirement: Registered-user access tier

Per-user surfaces SHALL remain reachable by any authenticated
user regardless of staff status: `PUT
/api/vacancies/companies/<pk>/preference/`, the
`/api/vacancies/filters/` CRUD, the TV reaction POSTs, the
`/api/news/preferences/` GET/POST ops and the
`/api/news/digest-task/` GET plus subscribe/unsubscribe POST
ops (the `/news/preferences/` SPA page itself is a public
`react_app_public` mount — only its API calls are gated).
Public reads stay `auth=None` for everyone including
anonymous.

#### Scenario: Registered user uses a per-user feature

- **WHEN** an authenticated non-staff user PUTs a company
  preference or POSTs a TV reaction
- **THEN** the op runs normally against their user row

#### Scenario: Registered user manages a digest subscription

- **WHEN** an authenticated non-staff user GETs
  `/api/news/digest-task/` or POSTs to its subscribe op
- **THEN** the op runs normally against their user row — no
  staff check

#### Scenario: Anonymous caller still cannot write

- **WHEN** an anonymous caller PUTs a company preference or
  POSTs to `/api/news/digest-task/subscribe/`
- **THEN** the response is the 401 `login_url` handshake

#### Scenario: Public read stays public

- **WHEN** an anonymous caller GETs `/api/vacancies/` or
  `/api/vacancies/filters/`
- **THEN** the response is 200 — no login is required for
  reads

### Requirement: Google sign-in

`GET /google/signin/` SHALL be a public endpoint starting a
Google OAuth sign-in flow: it accepts `?next=` (same-origin
paths only — anything else falls back to `/`) and `?tasks=1`,
stashes state, PKCE verifier, scopes, flow mode and redirect
target in the session, and redirects to Google's consent
screen. An unconfigured OAuth client SHALL answer 503. A
completed sign-in SHALL leave a session for the resolved user
and redirect to `next`.

#### Scenario: Anonymous visitor signs in with Google

- **WHEN** an anonymous visitor hits `/google/signin/`,
  consents on Google and returns to `/google/callback`
- **THEN** a Django session exists for the resolved user and
  the callback redirects to the stashed `next` path

#### Scenario: Sign-in endpoint when OAuth is unconfigured

- **WHEN** `GOOGLE_OAUTH_CLIENT_JSON` is unset and a visitor
  GETs `/google/signin/`
- **THEN** the response is a 503 explaining Google OAuth is
  not configured, not a 500

#### Scenario: Sign-in while already logged in

- **WHEN** a logged-in user completes the sign-in flow with a
  Google identity that resolves to a different user
- **THEN** the session belongs to the resolved user — the
  Google identity, not the prior session, decides who is
  signed in

#### Scenario: Denied consent returns to the login page

- **WHEN** Google redirects back with an access-denied error
  or the token exchange fails in sign-in mode
- **THEN** the user is redirected to `/accounts/login/`
  carrying the sanitized `next`, and no session or
  credentials row is created

### Requirement: Google account resolution

Sign-in SHALL resolve the Django user from the userinfo
`sub`, `email` and `email_verified` claims: (1) the user
whose credentials row stores `google_sub == sub`; (2) else,
with a verified `email`, the `email__iexact` match, linking
the grant to that account; (3) else a new non-staff user
with an unusable password and a unique `^\S+$` username
derived from the email local-part or `google-<sub>`. An
unverified/missing email SHALL never link or populate an
existing account.

#### Scenario: Returning Google user resolves by sub

- **WHEN** a credentials row with the presented `google_sub`
  exists
- **THEN** that row's user is signed in regardless of what
  email Google returns this time

#### Scenario: Verified email links an existing account

- **WHEN** a password-registered user's email matches the
  Google-verified `email` case-insensitively and no
  credentials row holds the `sub`
- **THEN** the existing user is signed in and their
  credentials row records the tokens and `google_sub`

#### Scenario: New Google user gets a unique derived username

- **WHEN** no credentials row and no verified-email match
  exists for the Google identity
- **THEN** a non-staff user with an unusable password is
  created — with a `-N`-suffixed username when the derived
  name is already taken — and signed in

#### Scenario: Unverified email never links

- **WHEN** userinfo returns `email_verified: false` for an
  email that matches an existing user
- **THEN** that user is NOT signed in; a new user with empty
  email and a `sub`-derived username is created instead

### Requirement: Sign-in UI on the accounts SPA

The `/accounts/login/` and `/accounts/register/` pages SHALL
render a "Sign in with Google" link to
`/google/signin/?next=<sanitized>` (a full-page navigation,
not XHR) plus an unchecked-by-default checkbox appending
`tasks=1` to request Google Tasks access in the same consent.
The section SHALL be hidden when the bootstrap's
`google_oauth_configured` is falsy; the credential forms are
unchanged.

#### Scenario: Checkbox opts into the tasks scope

- **WHEN** a visitor ticks the tasks checkbox and clicks
  "Sign in with Google"
- **THEN** the link navigates to
  `/google/signin/?next=…&tasks=1` so the consent screen
  requests the `auth/tasks` scope

#### Scenario: Section hidden when OAuth is unconfigured

- **WHEN** the bootstrap payload has
  `google_oauth_configured: false`
- **THEN** neither the button nor the checkbox renders
