# Spec Delta

## MODIFIED Requirements

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
