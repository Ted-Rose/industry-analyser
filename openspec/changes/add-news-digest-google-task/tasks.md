# Tasks

## 1. Dependencies and settings

- [ ] 1.1 backend: Add `google-api-python-client`,
      `google-auth-oauthlib` and an explicit `google-auth` pin to
      `requirements.txt` (google-auth is imported directly but
      currently only transitive); `pip install -r
      requirements.txt` in the venv succeeds.
- [ ] 1.2 backend: In `industry_analyser/settings.py` add
      `GOOGLE_OAUTH_CLIENT_JSON` materialization to a
      `GOOGLE_APP_SECRETS_PATH` file (port of
      `django_apps/settings.py` ~167-170/221-232),
      `GOOGLE_TASKS_LIST_TITLE` (default `'News'`),
      `GOOGLE_TASKS_USERNAME` (default `''`), `'google_api'` in
      `INSTALLED_APPS`, and a `'google_api'` entry in `LOGGING`
      following the per-app logger pattern; `python manage.py
      check` passes.
- [ ] 1.3 backend: Mount `path('google/',
      include('google_api.urls'))` in
      `industry_analyser/urls.py` before the terminal SPA
      catch-all drains; `reverse`/`/google/login` route resolves
      (`manage.py check` + a URL resolve assertion in shell).

## 2. `google_api` platform app

- [ ] 2.1 backend: Scaffold `google_api/` (`apps.py`,
      `models.py`, `utils.py`, `views.py`, `urls.py`, `admin.py`,
      `migrations/`); port `GoogleOAuthCredentials` verbatim from
      `django-apps/google_api/models.py` plus
      `db_table='google_oauth_credentials'`; `makemigrations
      google_api` produces a migration (do not apply to prod).
- [ ] 2.2 backend: Port `utils.py`: module-level
      `OAUTHLIB_RELAX_TOKEN_SCOPE`/`OAUTHLIB_INSECURE_TRANSPORT`
      env hacks, `get_user_credentials` **verbatim including the
      naive-UTC↔aware expiry conversions**, trimmed `google_auth`
      (DB path + reauth dict only, `access_type='offline'`,
      `include_granted_scopes='true'`, `prompt='consent'`,
      `redirect_uri={BASE_URL}/google/callback`), and
      `build_google_service`; unit-test
      `get_user_credentials` happy path, expired-refresh and
      `RefreshError → None` with `unittest.mock` in
      `google_api/tests.py`.
- [ ] 2.3 backend: Port views — `login_view` (session-stashed
      `state`/`next`, scope `auth/tasks`, 503 when
      `GOOGLE_APP_SECRETS_PATH` is unconfigured) and `callback`
      (`@login_required`, `flow.fetch_token`, `update_or_create`
      on `request.user`, denied/invalid grant → redirect to
      `/google/login`); `@login_required` on both. Test the
      anonymous-redirect and unconfigured-503 paths.
- [ ] 2.4 backend: `google_api/admin.py` — list display
      user/expiry/scopes only, all fields read-only, tokens never
      rendered; verify no token text reaches the admin page in a
      `TestCase` asserting field exclusions.

## 3. `news` app feature

- [ ] 3.1 backend: Add `NewsDigestTask` to `news/models.py`
      (`OneToOneField(NewsDigest)`, `task_id`, `task_list_id`,
      `status` choices pending/created/failed, `error`,
      timestamps, `db_table='news_digest_task'`), register it in
      `news/admin.py` read-only; `makemigrations news` produces
      the migration.
- [ ] 3.2 backend: New `news/tasks.py` —
      `create_digest_task(digest)`: early-return when feature
      settings are unset or a `created` link row exists; resolve
      `GOOGLE_TASKS_USERNAME` → `get_user_credentials` →
      `build('tasks','v1')`; resolve/create the
      `GOOGLE_TASKS_LIST_TITLE` list via
      `tasklists().list/insert`; `tasks().insert` with `title`
      `News digest {date}` and `notes` =
      `{BASE_URL}/news/{date}/` + ranked headlines (no `due`);
      `update_or_create` the link row. Wrap the whole body so it
      can never raise; failures log via `logging.getLogger('news')`
      and mark the link row `failed` (missing creds → warning
      naming `{BASE_URL}/google/login`).
- [ ] 3.3 backend: Call `create_digest_task(digest)` in
      `news/digest.py` after the `transaction.atomic()` block
      inside `if not dry_run:`; verify `--dry-run` performs no
      Google call.
- [ ] 3.4 backend: Tests in `news/tests.py` (`DigestTests`-style
      class): mock `googleapiclient.discovery.build` — assert
      insert body (title/notes, **no `due`**), `News` list
      auto-creation when absent, dedup on rebuild, `dry_run`
      no-op, missing-creds → `failed` row + digest intact,
      feature-disabled → no link row.
      `DATABASE_URL=sqlite:///db.sqlite3 python manage.py test
      news google_api` passes.

## 4. Docs and rollout prep

- [ ] 4.1 backend: Update `.env.example` (new vars, commented,
      no values) and `AGENTS.md`/app docs (`google_api` in the
      layout, env vars, `/google/login` reauth path); keep every
      line ≤79 chars (`awk 'length > 79 {print
      FILENAME":"NR}' <files>` clean).
- [ ] 4.2 backend: Verify locally end-to-end after GCP setup:
      add `GOOGLE_OAUTH_CLIENT_JSON` + `GOOGLE_TASKS_USERNAME` to
      `.env`, set `BASE_URL=http://127.0.0.1:8274` if needed, run
      dev server, visit `/google/login` → consent → callback →
      credentials row in admin; run `build_news_digest` → task
      appears in the `News` list in Google Tasks, link row is
      `created`.
- [ ] 4.3 backend: `DATABASE_URL=sqlite:///db.sqlite3 python
      manage.py migrate` locally; hand the maintainer the prod
      `migrate` command (prod apply is manual).

## Workflow follow-up

- GCP Console (manual, maintainer): enable Google Tasks API on
  `django-apps-7345`; add prod and `http://127.0.0.1:8274`
  `/google/callback` redirect URIs to the OAuth client.
- Apply prod migrations manually with prod `DATABASE_URL`.
- Add env keys to the `env-file` Secret Manager payload only if
  the web flow should also run on the deployed site.
- Archive the change after review requirements are satisfied.
