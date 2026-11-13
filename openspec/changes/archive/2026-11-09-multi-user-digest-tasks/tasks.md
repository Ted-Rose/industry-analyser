# Tasks

## 1. Models, migration and admin

- [x] 1.1 backend: In `news/models.py` add
  `NewsDigestSubscription` (`user` OneToOne to
  `AUTH_USER_MODEL` CASCADE, `is_enabled` default True,
  `created_at`/`updated_at`,
  `db_table='news_digest_subscription'`) and reshape
  `NewsDigestTask`: `digest` OneToOne → `ForeignKey(
  related_name='google_tasks')`, new non-null `user` FK
  (CASCADE), `unique_together(('digest', 'user'),)`,
  `db_table` unchanged. Verify: `python manage.py check`
  passes.
- [x] 1.2 backend: Run `python manage.py makemigrations
  news` (safe — touches no DB), then edit the migration so
  `user` lands non-null: add field with `null=True`, a
  `RunPython` that assigns existing rows to the sole
  `GoogleOAuthCredentials` user when exactly one row
  exists, else the first superuser by pk, else deletes the
  orphaned audit rows, then `AlterField` to `null=False`.
  NEVER run `migrate`/`sqlmigrate`. Verify: the migration
  file contains all three ops and imports no env var.
- [x] 1.3 backend: In `news/admin.py` register
  `NewsDigestSubscription` (`list_display=('user',
  'is_enabled', 'updated_at')`, `list_editable` is_enabled)
  and add `'user'` to `NewsDigestTaskAdmin`'s
  `list_display`/`readonly_fields`. Verify:
  `python manage.py check` passes.

## 2. Per-user fan-out in news/tasks.py

- [x] 2.1 backend: Rewrite `create_digest_task`/`_run` for
  fan-out: iterate
  `NewsDigestSubscription.objects.filter(is_enabled=True)
  .select_related('user')`; per subscriber skip on an
  existing `created` `(digest, user)` row, else
  `update_or_create` to `pending`, resolve
  `get_user_credentials(user, GOOGLE_TASKS_SCOPES)` (None →
  `failed` row whose error names
  `{BASE_URL}/google/login`), build the service, resolve
  their task list, insert, mark `created`. Wrap each
  subscriber's attempt in try/except → `failed` row +
  logged exception; keep the outer never-raises guarantee.
  Task notes keep using `ordered_story_articles(story,
  <that user>)`. Verify:
  `DATABASE_URL=sqlite:///db.sqlite3 python manage.py test
  news` passes after task 2.3.
- [x] 2.2 backend: Drop the `GOOGLE_TASKS_USERNAME` half of
  `_feature_enabled()` (gate is `GOOGLE_OAUTH_CLIENT_JSON`
  alone), remove the setting + its comment from
  `industry_analyser/settings.py` (~lines 127-132, keep
  `GOOGLE_TASKS_LIST_TITLE`/`GOOGLE_TASKS_LINK_BASE_URL`)
  and remove the `.env.example` line. Verify:
  `python manage.py check` passes and `grep -rn
  GOOGLE_TASKS_USERNAME industry_analyser/ news/` returns
  nothing.
- [x] 2.3 backend: Rewrite `DigestGoogleTaskTests` in
  `news/tests.py`: drop the `GOOGLE_TASKS_USERNAME`
  override, create subscriptions in setUp, and cover —
  task created per subscriber with per-user link rows;
  notes use the subscriber's own outlet ranking; a
  no-creds subscriber gets `failed` while a connected one
  gets `created` in the same build; an insert exception
  for user A leaves user B `created`; rebuild dedups per
  user but inserts for a newly subscribed user on `--date`
  rerun; `failed` retried on next build; no-subscriber and
  unconfigured-install no-ops. Verify:
  `DATABASE_URL=sqlite:///db.sqlite3 python manage.py test
  news` passes.

## 3. API ops

- [x] 3.1 backend: In `news/api.py` add
  `DigestTaskStatusOut` (`oauth_configured: bool`,
  `google_connected: bool`, `subscribed: bool`,
  `last_task: {digest_date, status, error, updated_at} |
  null`) plus three ops on the news router — `GET
  /digest-task/` and `POST /digest-task/subscribe|unsubscribe/`
  (default `django_auth`, so writes keep CSRF).
  `google_connected` is the cheap check —
  `GoogleOAuthCredentials` row exists and
  `has_all_scopes(GOOGLE_TASKS_SCOPES)` — never
  `get_user_credentials` (a GET must not refresh tokens).
  Subscribe/unsubscribe are idempotent `is_enabled` flips
  returning the same status payload; subscribe without a
  grant answers 200, not 4xx. Verify: `python manage.py
  check` passes and the ops appear in
  `python manage.py export_openapi_schema` output.
- [x] 3.2 backend: In `industry_analyser/api.py` add
  `('news', 'digest-task'): '/news/preferences/'` to
  `SPA_SUBPATHS`. Verify: an anonymous GET to
  `/api/news/digest-task/` returns 401 whose `login_url`
  `next` is `/news/preferences/` (assert in test 3.3).
- [x] 3.3 backend: Add API tests (extend `news/tests.py`):
  anonymous GET/POST → 401 `login_url` with
  `next=/news/preferences/`; authed GET on a fresh user →
  `oauth_configured`/`google_connected`/`subscribed` false,
  `last_task` null; subscribe without creds → 200
  `subscribed: true, google_connected: false`; unsubscribe
  idempotent; `last_task` echoes the newest link row. Run
  them under sqlite. Verify:
  `DATABASE_URL=sqlite:///db.sqlite3 python manage.py test
  news` passes.
- [x] 3.4 both: Regenerate the API surface:
  `python manage.py export_openapi_schema --output
  frontend/openapi.json` then `cd frontend && npm run
  gen:types`. Verify: `git diff` shows the three new ops in
  `openapi.json` and the new schemas in
  `src/news/api-types.ts`.

## 4. Preferences-page card (frontend)

- [x] 4.1 frontend: In `frontend/src/news/api.ts` add
  `fetchDigestTaskStatus()`, `subscribeDigestTask()`,
  `unsubscribeDigestTask()` typed off the generated
  `api-types.ts`; in `mutations.ts` add
  `useSubscribeDigestTask`/`useUnsubscribeDigestTask`
  invalidating the `['news']` root. Verify: `cd frontend &&
  npm run typecheck` passes.
- [x] 4.2 frontend: Add the Google Tasks digest card on
  `frontend/src/news/routes/Preferences.tsx` (below the
  form, reusing `Button`/`pushToast` from
  `frontend/src/shared/`): hidden when
  `oauth_configured` is false; `!google_connected` →
  Connect button navigating to
  `/google/login/?next=/news/preferences/?subscribe=1`;
  connected-unsubscribed → Subscribe; subscribed → state +
  `last_task` status/error (re-connect hint on `failed`) +
  Unsubscribe. Read `?subscribe=1` via `useSearchParams`
  and fire subscribe once when `google_connected &&
  !subscribed`, then strip the param with `replace: true`.
  Verify: `cd frontend && npm run typecheck` passes.
- [x] 4.3 frontend: Extend `Preferences.test.tsx` (or a
  sibling test): card hidden when `oauth_configured`
  false; Connect button href carries `?subscribe=1`;
  `?subscribe=1` + connected fires the subscribe mutation
  once and strips the param; subscribed state shows
  `last_task` error + Unsubscribe. Verify: `cd frontend &&
  npm test` passes.
- [x] 4.4 frontend: Rebuild the committed bundle so
  `frontend_dist/` reflects the new card (the repo tracks
  build output). Verify: `git status` shows updated files
  under `frontend_dist/`.

## 5. Final verification

- [x] 5.1 both: Full scoped sweep — `python manage.py
  check`;
  `DATABASE_URL=sqlite:///db.sqlite3 python manage.py test
  news`; `cd frontend && npm run typecheck && npm test`.
  Verify: all pass with no skipped regressions in
  `DigestGoogleTaskTests`.

## Workflow follow-up

- Maintainer applies the `news` migration to prod manually
  (`python manage.py migrate` with the prod `DATABASE_URL`)
  — never run it against prod from an agent session.
- Maintainer drops `GOOGLE_TASKS_USERNAME` from prod env at
  leisure and self-subscribes via `/news/preferences/`.
- Archive the change after the project's review
  requirements are satisfied.
