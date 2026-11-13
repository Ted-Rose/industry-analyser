# Spec Delta

## ADDED Requirements

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
