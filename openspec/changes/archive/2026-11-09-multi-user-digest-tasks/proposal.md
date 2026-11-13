# Proposal

## Why

`build_digest()` creates one Google task per daily news digest,
but only for the single Django user named by
`GOOGLE_TASKS_USERNAME` (`news/tasks.py`). Self-service
registered users already exist (accounts SPA) and the Google
OAuth flow already attaches credentials to any logged-in user —
yet there is no way for anyone but the maintainer to receive
the digest task in their own Google Tasks list.

## What Changes

- New `NewsDigestSubscription` model in `news` — per-user
  opt-in (`user` OneToOne, `is_enabled`, timestamps) —
  admin-registered; migration file included.
- `NewsDigestTask` becomes per-(digest, user): `digest`
  `OneToOneField` → `ForeignKey` (`related_name='google_tasks'`),
  new non-null `user` FK, `unique_together(digest, user)`;
  data migration backfills existing audit rows.
- `create_digest_task` fans out over enabled subscriptions:
  per-user credentials → per-user task list resolution →
  insert → per-user link row. One user's failure is recorded
  on their link row only and never affects other subscribers.
- **BREAKING**: the `GOOGLE_TASKS_USERNAME` setting is removed
  (`settings.py` + `.env.example`); the feature gate is just
  `GOOGLE_OAUTH_CLIENT_JSON`. The maintainer keeps receiving
  tasks by subscribing like any other user.
- New session-auth ops on the news router:
  `GET /api/news/digest-task/` (state + last task status) and
  `POST /api/news/digest-task/subscribe|unsubscribe/`.
- A "Google Tasks digest" card on `/news/preferences/`:
  Connect Google → OAuth round-trip → auto-subscribe via a
  `?subscribe=1` return param; subscribed state shows the
  last task status plus an Unsubscribe button.
- `SPA_SUBPATHS` gains `('news', 'digest-task')` →
  `/news/preferences/` so the 401 login handshake lands on
  the owning page.

## Capabilities

### New Capabilities

(none — the subscription is the same digest-task capability)

### Modified Capabilities

- `news-digest-google-task`: task creation fans out to every
  subscribed user instead of one configured user; link rows
  are per-(digest, user); a subscription model plus status /
  subscribe / unsubscribe API ops are added; the
  `GOOGLE_TASKS_USERNAME` half of the feature toggle is
  removed.
- `user-auth`: the registered-user access tier gains the
  session-auth `GET /api/news/digest-task/` and
  `POST /api/news/digest-task/subscribe|unsubscribe/` ops.

## Impact

- **Layers**: backend (news app models/tasks/api/admin,
  `industry_analyser/settings.py` + `api.py` `SPA_SUBPATHS`,
  `.env.example`) and frontend (`frontend/src/news/` — new
  card on Preferences, `api.ts`/`mutations.ts`, regenerated
  `openapi.json` + `api-types.ts`, rebuilt `frontend_dist/`).
- **Data**: one migration on `news` — new
  `news_digest_subscription` table; `news_digest_task` schema
  change (FK + user column + `unique_together`) with a data
  backfill for existing audit rows.
- **APIs**: three new ops under `/api/news/`; OpenAPI schema
  and generated TS types must be regenerated (CI drift
  check).
- **Config**: `GOOGLE_TASKS_USERNAME` env var becomes a no-op
  and is removed from settings/`.env.example`; existing prod
  `.env` values are harmless leftovers.
- **Tests**: `news/tests.py` `DigestGoogleTaskTests` rewritten
  for fan-out; new API-op tests.
