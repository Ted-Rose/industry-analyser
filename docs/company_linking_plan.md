# Company Linking Plan — canonical `Company` table for vacancies

> **Audience**: AI agents / developers implementing this.
> Read sections 1–4 once (shared spec), then implement the PR cards
> in section 6, following the guardrails in section 8.
>
> Same shape as the shipped property dedup: canonical entity table +
> nullable FK on existing rows + a linking/backfill command +
> review-assisted merging. Reference implementation:
> `classified_ads/property_matcher.py`,
> `classified_ads/management/commands/link_ads_to_properties.py`, and
> the `PropertyLinkActionsMixin` admin actions in
> `classified_ads/admin.py`.
>
> Updated 2026-10-02 to match the current codebase: stateful
> `ScrapeJobRunner` checkpointing, category-sweep pagination, batched
> `create_or_update_resources`, shipped property dedup, local
> migrations allowed, and the pending React frontend migration.

## 1. Objective

Give every `fetcher.Vacancy` a proper `company` FK instead of the
flat `company_name` string, so users can browse a list of companies
and see each company's vacancies. Company rows must carry the legal
**registration number** (`reg_code`, unique where present) and the
**portal employer identifier**, and must survive identity changes:
renames, re-registrations, acquisitions, and employers that operate
several portal accounts.

## 2. Data investigation (verified 2026-10-02)

### 2.1 What the vacancy detail page exposes

Test URL:
`https://www.cv.lv/lv/vacancy/1655039/gocardless/junior-data-analyst`
(794 KB SSR page, `__NEXT_DATA__` present). Relevant slice of
`props.pageProps.vacancy["1655039"]`:

```json
{
  "employerId": 66466,
  "employerName": "GoCardless",
  "employer": {
    "employerId": 66466,
    "regCode": "07495895",
    "about": "<div>GoCardless is a global bank payment company…</div>",
    "webpageUrl": "https://boards.greenhouse.io/gocardless",
    "videoUrl": "https://www.youtube.com/watch?v=…",
    "logoFileId": "1ccf9c82-…",
    "coverFileId": "126ad398-…",
    "logoFileName": null,
    "coverFileName": null,
    "gallery": ["1e2d435e-…", "…"]
  },
  "contacts": {
    "firstName": "Talent ",
    "lastName": "Team",
    "email": "talent@gocardless.com",
    "phone": ""
  },
  "highlights": {
    "address": "Marijas iela 2a",
    "location": {"townId": 543, "countyId": null, "countryId": 101}
  }
}
```

### 2.2 Field availability per source

| Field | Search payload (portal `api` AND `nextjs`) | Vacancy detail page (`_detail`) |
|---|---|---|
| `employerId` | yes — every result (re-verified against `/api/v1/vacancy-search-service/search?categories[]=…` today) | yes (top-level, plus inside `employer`) |
| `employerName` | yes — every result | yes |
| `logoId` | yes | via `employer.logoFileId` |
| `employer.regCode` | **no** | yes |
| `employer.about` (HTML) | no | yes |
| `employer.webpageUrl` / `videoUrl` | no | yes |
| `employer.logoFileId` / `coverFileId` / `gallery` | no | yes |
| `contacts` (name/email/phone) | no | yes |
| `highlights.address` + town/county/country ids | no | yes |
| `settings.applyingUrl` (external ATS link) | no | yes |

### 2.3 What does NOT exist publicly

- `GET /lv/employer/66466` → SSR page with `statusCode: 401` —
  employer profiles require login. **No public employer page.**
- `GET /api/v1/employer-service/employers/66466` → 404.
- `GET /lv/employers` → admin directory, `employersData` empty
  without auth.
- `searchResults.vacancyEmployerData` → only
  `{topEmployerEnabled, externalUrl}` UI flags. Useless.

**Conclusion**: the vacancy detail page's `employer` object is the
only public source of `regCode` and rich company data. The search
payload alone is enough to *link* vacancies to companies
(`employerId` + `employerName`); enrichment requires a detail fetch.

### 2.4 Identity semantics & edge cases

- `employerId` is cv.lv's account id — **stable**, survives renames.
  Namespaced to cv.lv; any future portal gets its own `source` value
  in the identity table.
- `regCode` is **self-reported** by the employer. GoCardless posts
  its *UK* company number (`07495895`), not a Latvian one. Expect:
  missing/empty values, foreign formats, whitespace, maybe typos.
  → It is a strong signal but cannot be the primary key.
- Renames keep `employerId` (e.g. "AirBaltic" → "airBaltic Corp").
- Acquisitions may change `regCode` under the same `employerId`,
  or migrate postings to the acquirer's `employerId`.
- The same legal company can run **two employer accounts** (one per
  brand/country) — same `regCode`, different `employerId`.
- `Vacancy` does **not** currently store `employerId` — existing
  rows can only be linked by refetching their detail pages, or for
  free once they are re-observed in a weekly sweep's search payload
  (see §7, "Backfill volume").
- Detail-page enrichment exists but only runs on `type: 'nextjs'`
  portals and only for new/renewed vacancies
  (`enrich_result` + `_needs_detail_fetch` gate on
  `detail_fetched_at`). `api`-portal rows get rich employer data
  only when a nextjs portal later enriches the same
  `vacancy_portal_id` — or via the backfill command (PR-4).
- `Vacancy.url` already stores the public detail page URL
  (`vacancy_base_url + vacancy_base_href + vacancy_portal_id`) — the
  backfill command needs no config lookups for the fetch target.

## 3. Proposed schema

### 3.1 `fetcher_company`

Canonical real-world company. Portal-agnostic — the same company
can later get identities on other portals.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | matches `Vacancy` |
| `name` | CharField(255) | latest observed display name |
| `reg_code` | CharField(64), null | normalized (strip, upper); **unique where non-empty** — see 4.1 |
| `reg_code_country` | CharField(2), null | best-effort ISO country of `reg_code`; null when unknown (GoCardless → `GB` cannot be auto-detected reliably — leave null, set manually or via future registry lookup) |
| `about` | TextField, null | `employer.about` — strip HTML on save (keep the raw object in `raw_employer`); the codebase stores no raw HTML today |
| `webpage_url` | URLField, null | |
| `video_url` | URLField, null | |
| `logo_file_id` | CharField(64), null | files-service UUID; render via `files_href` |
| `cover_file_id` | CharField(64), null | |
| `gallery` | JSONField, default list | file ids |
| `contact_name` / `contact_email` / `contact_phone` | CharFields, null | from `contacts`; business contact info the employer publishes on ads |
| `applying_url` | URLField, null | `settings.applyingUrl` — external ATS; also an identity hint |
| `address` | CharField(255), null | `highlights.address` — office address from the ad |
| `raw_employer` | JSONField, null | last-seen raw `employer` object — future-proof for fields we don't map yet |
| `first_seen` / `last_seen` | DateTimeField | scrape-observation window |
| `detail_fetched_at` | DateTimeField, null | mirrors `Vacancy.detail_fetched_at` |
| `needs_review` | BooleanField | set on reg-code conflicts / merge suggestions |
| `merged_into` | FK → self, null, PROTECT | soft-redirect for deduped companies; views/manager resolve it |

`Meta`: `db_table = 'fetcher_company'`.

Note the deliberate divergence from property dedup: emptied
`Property` rows are *deleted*; `Company` rows are portal-agnostic
canonical entities worth keeping browsable after a merge, hence
`merged_into` instead.

### 3.2 `fetcher_company_identity`

Portal-scoped identity — the stable join key. This is what makes
renames/merges survivable: vacancies never point at a mutable name,
they point at `employerId` which routes to the canonical company.

| Column | Type | Notes |
|---|---|---|
| `company` | FK → Company, CASCADE | |
| `source` | CharField(32) | `'cv.lv'` for every cv.lv portal — **not** the config `portal_id` and not `Vacancy.job_portal_id` (all cv.lv portals share one `employerId` namespace regardless of `type: api|nextjs`) |
| `employer_id` | IntegerField | portal-side `employerId` |
| `first_seen` / `last_seen` | DateTimeField | |

`Meta`: `db_table = 'fetcher_company_identity'`,
`unique_together = (('source', 'employer_id'),)`.

Merging two companies = repointing identity rows (+ vacancies)
to the survivor — `merged_into` keeps the dead row browsable.

### 3.3 `fetcher_company_alias`

Sighting-style history of observed names and reg codes — answers
"what was this company called before" and powers conflict
detection (same pattern as `*Sighting` in `classified_ads`).

| Column | Type | Notes |
|---|---|---|
| `company` | FK → Company, CASCADE | |
| `kind` | CharField(16) | `'name'` or `'reg_code'` |
| `value` | CharField(255) | |
| `first_seen` / `last_seen` | DateTimeField | |

`Meta`: `db_table = 'fetcher_company_alias'`,
`unique_together = (('company', 'kind', 'value'),)`.
On each observation: `get_or_create` + bump `last_seen` (batched —
see §5).

### 3.4 `Vacancy` changes

- `company = FK(Company, null=True, on_delete=SET_NULL,
  related_name='vacancies')`.
- Keep `company_name` — it becomes the point-in-time snapshot of
  what the ad displayed (still useful for ads whose company row is
  merged away, and for portals without employer ids).
- Do **not** add `employer_id` to `Vacancy` — redundant with
  `company → identities`.

## 4. Identity & change handling (decisions)

### 4.1 `reg_code` uniqueness

`UniqueConstraint(fields=['reg_code'],
condition=~Q(reg_code='') & Q(reg_code__isnull=False))` — partial
unique index (supported by Postgres and SQLite). Normalize before
save: `strip().upper()`, drop internal whitespace.

Scraper-side, a collision is a **signal, not a crash**:

- Same `regCode` observed under a **new** `employerId` → strong
  same-entity evidence (or a typo). Do NOT auto-merge: create the
  identity → point it at a new Company with `reg_code=None`
  (constraint can't fire) + `needs_review=True`, and record the
  observed code in `fetcher_company_alias` anyway. Admin merges
  after a human look (merging is a repoint, cheap to do, annoying
  to undo).
- `regCode` **changes** on an existing identity's company → write
  old value to alias, update `reg_code`, set `needs_review=True`
  (possible acquisition — exactly the case the user cares about).
- Name changes likewise → new `'name'` alias row, update `name`.
  `needs_review` NOT set — renames are routine.

### 4.2 Resolution flow (scrape time)

```
result.employerId + result.employerName
        │
        ▼
resolve (source='cv.lv', employer_id=N) → CompanyIdentity
        │                                    │
        ├─ exists → company = identity.company
        │
        └─ new → Company(name=employerName) → identity → company
        │
        ▼  (only when _detail present)
employer.regCode/about/webpageUrl/… → upsert Company fields
                                      + alias observations
                                      + conflict logic (4.1)
vacancy.company = company
```

`employerId` linking runs for **every** result on **all** portals
(it's in both search payloads — free), including sighting-only rows
where nothing else changed. Rich fields only when the nextjs
enrichment fetched `_detail`.

### 4.3 Expired/deleted vacancies in backfill

Detail pages for expired ads may 404 or lose `pageProps.vacancy`.
Leave `company` null and count failures; a vacancy that never yields
a detail page stays linked-by-name only (`company_name` snapshot is
already there). Re-running the command targets only null-FK rows —
self-resuming, no extra state needed. Optionally a
`--max-attempts` guard column later if retry storms appear.

## 5. Scraper & codebase touchpoints (current code)

`fetcher/scraper.py`, `VacancyScrapper`:

- `_build_vacancy(result, vacancy_portal_id)` already stashes
  `_pending_industries`, `_pending_keywords`, `_pending_file` on the
  unsaved `Vacancy`. Add the same for employer data:
  - `vacancy._pending_employer = (employer_id, employer_name)` from
    the search payload (both portal types).
  - When `result['_detail']` is present also stash
    `vacancy._pending_employer_detail` = the `employer`, `contacts`,
    `settings.applyingUrl`, `highlights.address` slices (the detail
    dict currently isn't retained — `_build_vacancy` only consumes
    `details.standardDetails`/`fileDetails`).
- `create_or_update_resources` partitions the batch into
  `new_vacancies` / `changed_vacancies` / `sighted_pks`, transfers
  `_pending_*` onto `existing` rows, then does `bulk_create` + one
  `last_seen` UPDATE + `bulk_update` + M2M `bulk_create
  (ignore_conflicts=True)` + `VacancyFile.get_or_create`. Integrate
  a `_persist_companies()` pass into that flow:
  - Transfer `_pending_employer`/`_pending_employer_detail` to
    `existing` rows alongside the existing `_pending_file` transfer.
  - Collect the unique `(employer_id)` set across the whole batch,
    fetch existing `CompanyIdentity` rows in one query, bulk-create
    the missing identities + their `Company` rows (batched —
    per-row `get_or_create` would be N queries per page).
  - Set `vacancy.company` on **new** rows *before* `bulk_create` so
    the INSERT carries the FK (PKs are populated post-insert — the
    M2M pass already relies on that).
  - For existing rows add `'company'` to the `bulk_update` field
    list; for sighting-only rows (`sighted_pks`) that lack a
    company, run a grouped `UPDATE … SET company_id=…` per distinct
    company.
  - Alias `'name'` observations:
    `CompanyAlias.objects.bulk_create(ignore_conflicts=True)` then a
    `last_seen` UPDATE for pre-existing rows.
  - Detail enrichment (`_pending_employer_detail`) applies §4.1
    conflict logic — only on nextjs portals and only for rows that
    fetched a fresh detail page this run.
  - The `dry_run` early-return happens before any writes — the
    company pass must sit after it (and log what it *would* link).
- `enrich_result` extracts the detail dict inline as
  `data['props']['pageProps']['vacancy'][str(id)]` via
  `_extract_next_data(html)`. Extract that lookup into a small pure
  function — e.g. `extract_vacancy_detail(next_data, vacancy_id) ->
  dict | None` in a new `fetcher/company_linking.py` (mirroring
  `classified_ads/property_matcher.py`) — so the backfill command
  reuses it without instantiating the scrape flow. The same module
  should host `normalize_reg_code`, identity resolution and the
  §4.1 upsert/conflict logic shared by scraper and command.
- API-portal vacancies get `company` from the identity link alone;
  rich fields arrive when a nextjs portal enriches the same
  `vacancy_portal_id` — or via the backfill command. No change to
  the `enrich_search_results` flag for `api` portals.
- `Vacancy.company_name` continues to be written exactly as today.
- No `ScrapeJobRunner` changes: the persist pass lives inside
  `create_or_update_resources`, so item checkpointing, heartbeats
  and `--dry-run` semantics are untouched. The runner only
  checkpoints search items anyway.

## 6. PR cards

### PR-1 — Models + migration

- `Company`, `CompanyIdentity`, `CompanyAlias` per §3;
  `Vacancy.company` FK.
- Conditional unique constraint on `reg_code`; `unique_together`
  on both new tables; explicit `db_table` names.
- Model `save()` normalizes `reg_code` (strip/upper/collapse).
- Run `python manage.py makemigrations fetcher` **and** `migrate`
  locally — the dev DB is the gitignored `db.sqlite3`, local
  migrations are fully allowed; CI applies them to prod on master
  push (`.github/workflows/run-migrations.yml`).

### PR-2 — Scrape-time linking

- `_pending_employer` capture in `_build_vacancy` +
  `_persist_companies()` in `create_or_update_resources` (batched
  identity resolve, company create, alias `'name'` observations,
  FK assignment incl. sighting-only rows). Works on all portals,
  dry-run safe.
- Unit tests: identity reuse across runs, rename → alias row,
  two employerIds same name → two companies, batch with 100
  vacancies from one employer → 1 identity + 1 company.

### PR-3 — Detail enrichment → company fields

- `fetcher/company_linking.py`: `extract_vacancy_detail()`,
  `normalize_reg_code()`, employer-detail upsert + §4.1 conflict
  logic incl. `needs_review` semantics.
- Wire `enrich_result`/`_build_vacancy` to stash
  `_pending_employer_detail`; apply the upsert in
  `_persist_companies()`.
- Tests: regCode set / change / collision / missing.

### PR-4 — Backfill command

- `python manage.py link_vacancies_to_companies [--ids …]
  [--limit N] [--batch-size N] [--dry-run] [--employers-only]`.
- **Do NOT subclass `BaseRefetchCommand`** — it is coupled to
  classified-ads conventions (`--ids` filters `ad_id__in`, prints
  `record.link`, uses `model.all_objects`, drives
  `scraper.refetch_single()` which requires a `.link` attribute).
  `Vacancy` has `url`/`vacancy_portal_id` and no `all_objects`
  manager. Write a bespoke `BaseCommand` modeled on
  `tv_programs/.../enrich_tv_shows.py` and
  `link_ads_to_properties.py`: `qs.iterator(chunk_size=…)`,
  `--dry-run` prints counts only.
- Instantiate `VacancyScrapper` purely for its throttled
  `make_request` + `_extract_next_data` — never call `run()` (same
  trick as `enrich_tv_shows`). Discover the portal id dynamically:
  scan `load_portals_config()` for `type == 'nextjs'` — do not
  hardcode `2` (prod `FETCHER_PORTALS_JSON` may differ; also the
  local config's legacy portal `3` has no `type` and must not be
  picked).
- Default queryset: `Vacancy.objects.filter(company__isnull=True)
  .order_by('-last_seen')` — freshest ads first, their detail pages
  are most likely alive. `--ids` takes `vacancy_portal_id`s.
- Per vacancy: `make_request(vacancy.url)` → `_extract_next_data` →
  `extract_vacancy_detail(data, vacancy.vacancy_portal_id)` → the
  same PR-3 upsert path (share the helper, don't duplicate). Dead
  detail pages: log at INFO, leave FK null, move on — self-resuming
  via the null-FK predicate.
- `--employers-only` mode: refresh `reg_code`/`about` for companies
  whose `detail_fetched_at` is stale, using any one of their live
  vacancies — N companies ≤ N vacancies to fetch.

### PR-5 — UI + admin

- **UI choice** (decide at implementation time):
  `docs/react_frontend_migration/` plans to convert `/vacancies/`
  into a React SPA entry (`/vacancies/` + `/api/vacancies/`), but
  the migration hasn't started — there is no `frontend/` workspace
  yet. Either:
  - build `/companies/` list + `/companies/<id>/` detail as ordinary
    Django template views now (they'll be ported with the vacancies
    stage — keep view queries thin so they port to ninja ops), or
  - fold company pages into the vacancies React stage and ship
    admin-only in this PR.
  Default: Django templates now — keeps this plan self-contained.
- `/companies/` list: name, reg_code, identity sources, vacancy
  count (total + currently-open, annotated), `needs_review` flag.
  `/companies/<id>/` detail: company card (about text, logo via
  `files_href` URL, webpage link, alias history) + paginated
  vacancies.
- `vacancies.html` — wrap `company_name` (currently rendered plain
  at the Company column, ~line 217) in a link to the company page
  when `vacancy.company` is set.
- `fetcher` has no `urls.py` — views are wired in
  `industry_analyser/urls.py` (`path('vacancies/', …)`); add
  `path('companies/', …)` / `path('companies/<uuid:pk>/', …)`
  there for consistency.
- `fetcher/admin.py` is a stub today (no models registered at all).
  Add `CompanyAdmin` — `list_display` name/reg_code/counts/
  needs_review, `search_fields` name+reg_code+alias values,
  `list_filter` needs_review; `CompanyIdentityInline`; admin action
  **Merge into…** that repoints identities + vacancies, sets
  `merged_into`, clears `needs_review` (mirror the action style of
  `PropertyLinkActionsMixin` in `classified_ads/admin.py`).
  Register `CompanyAlias` read-only-ish. Registering `Vacancy`
  itself is out of scope unless trivially useful.

## 7. Risks / open questions

- **regCode quality**: self-reported → normalization (strip spaces,
  uppercase) is mandatory; expect foreign numbers (the test
  employer's is UK). `reg_code_country` stays null until a real
  lookup source exists — a future `sync` against the Latvian
  Enterprise Register open data (data.gov.lv) could validate/fill
  names + country; out of scope here.
- **Auto-merge**: rejected (§4.1) — regCode typos are cheap to make
  and a bad merge pollutes FK history. `needs_review` + admin
  action keeps it human-gated, same philosophy as the property
  review queue (`candidate_property` + confirm/reject actions).
- **`contacts` personal data**: it's employer-published business
  contact info; storing it is fine but it's the least valuable
  field — can be dropped from PR-3 if unwanted.
- **Backfill volume**: after PR-2, every vacancy still live gets
  linked for free on the next weekly sweep (employerId is in the
  search payload) — the command is needed only for (a) rows that
  expire before they are re-observed and (b) `reg_code`/`about`
  enrichment, which is one throttled detail fetch per vacancy.
  Run in `--limit` batches; resumable via the null-FK predicate.
- **Future portals**: the likeit.lv HTML path was removed; the
  local config's portal `3` is legacy cv.lv HTML without a `type`
  and can't produce parsed results. The identity table's `source`
  column is what makes a genuinely new portal safe later — nothing
  else needs to change.
- **`Vacancy.url` correctness**: backfill assumes `url` points at
  the public detail page — true for rows built by both current
  portals (`vacancy_base_url + vacancy_base_href + id`). Rows from
  removed legacy portals may have dead URLs; they just count as
  failures.

## 8. Guardrails

- Local migrations are allowed and expected — dev DB is the
  gitignored `db.sqlite3`; run `makemigrations`/`migrate` freely,
  commit the generated files. Never point `migrate` at the prod
  `DATABASE_URL` — CI (`run-migrations.yml`) applies them.
- Max line length **79 chars** (`.flake8`);
  `logging.getLogger('fetcher')`, not `__name__`.
- Detail fetches must go through `BaseScraper.make_request`
  (shared `urllib3.PoolManager`, retries, per-domain throttle) —
  no raw `requests`/`urllib3` in new code.
- The scraper runs under `ScrapeJobRunner` checkpointing — keep all
  company writes inside `create_or_update_resources` so item
  checkpointing and `--dry-run` semantics stay untouched.
- Verify: `python manage.py check`, `python manage.py test fetcher`.
- Testing scraper paths: `--dry-run` + small `--limit`; detail
  fetches hit the live site — never run a full scrape just to
  verify a code change.
