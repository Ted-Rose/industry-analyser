# Spec Delta

## Purpose

Public user registration and session authentication: how
accounts are created, how users log in and out, how the current
user is reported, and how access splits between staff,
registered users, and anonymous visitors.

## ADDED Requirements

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
`/api/vacancies/filters/` CRUD, the TV reaction POSTs and the
`news:preferences` page. Public reads stay `auth=None` for
everyone including anonymous.

#### Scenario: Registered user uses a per-user feature

- **WHEN** an authenticated non-staff user PUTs a company
  preference or POSTs a TV reaction
- **THEN** the op runs normally against their user row

#### Scenario: Anonymous caller still cannot write

- **WHEN** an anonymous caller PUTs a company preference
- **THEN** the response is the 401 `login_url` handshake

#### Scenario: Public read stays public

- **WHEN** an anonymous caller GETs `/api/vacancies/` or
  `/api/vacancies/filters/`
- **THEN** the response is 200 — no login is required for
  reads
