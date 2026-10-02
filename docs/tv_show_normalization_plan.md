# TV Show Normalization + IMDb (OMDb) Re-integration Plan

## Executive Summary

**Problem**: `tv_programs` stores one `Program` row per *airing* with no
canonicalization — the same movie/episode is re-inserted every time it
airs. Measured on the local DB: **20,268 rows → 3,657 distinct titles**
(~5.5× duplication). Live tet.lv data (2026-10-01) confirms it: Filmzone
aired `Sirds robeža` 3× in one day; LTV1 airs the same telenovela episode
(`Mīlas viesulis 21. ... 4471. sērija`) twice daily.

**Solution**:

1. Split the model into a canonical **`Show`** table (unique per
   normalized `title_lv` + `description_lv`, plus season/episode for
   series) and keep **`Program`** as the *airing* row (`show` FK +
   channel + `start_time` + tet `data-id`).
2. Scraper resolves each airing to an existing `Show` via a dedup hash
   and only creates a `Show` for genuinely new content.
3. Re-integrate **OMDb** (the Open Movie Database — the "open source
   IMDb" API integrated in branch `feature/omdb-integration`, commit
   `0fe1775`, later dropped in `0eab1ec`) once per *new Show*, storing
   `imdb_id`, `imdb_url`, rating, `title_eng`, `description_eng`.
4. LV→EN title translation via the existing `ai_providers` JobClient
   (new `AIJobSpec`), so Latvian titles like `Atriebība` can match IMDb.
5. Single-user like/dislike (`ShowPreference`) — disliked shows hidden
   from `/tv/`; schema leaves room for a future `user` FK.

**Impact**: New tables (`tv_programs_show`, `tv_programs_show_preference`),
one migration adding `Program.show`/`Program.source_event_id`, a backfill
command, and terraform wiring for `OMDB_KEY` (Secret Manager secret
`industry-analyser-omdb-key` already created). All migrations are written
but **run by the user** (project rule).

---

## 1. Current state (verified)

### 1.1 Data model (`tv_programs/models.py`)

- `Program` rows are per-airing: `title_lv`, `description_lv`,
  `channel` FK, `start_time`, `duration_minutes`, `image_url`,
  `imdb_rating`, `pg_rating`, `url`, `title_eng`, `description_eng`,
  `imdb_id`, `tmdb_id`, `enrichment_source`, `content_type` +
  `classification_*` (heuristic classifier, `classification.py`).
- `unique_together` is **commented out** with a TODO — nothing stops
  duplicates.
- `Category` / `ProgramCategory` M2M exists but is unused by the scraper.

### 1.2 Scraper (`tv_programs/scraper.py`)

- Subclasses `BaseScraper`; `validate_result=True`,
  `enrich_search_results=True`. No HTTP detail fetch — `enrich_result`
  builds the resource dict purely from listing data + `classify()`.
- `remove_redundant_results` only dedups *same channel + same day +
  exact title* — a rerun next day inserts a new row. It also exact-matches
  `EXCLUDED_LOCAL_SHOWS` **before** stripping `(atkārtojums)`, so
  `"Kultūršoks (atkārtojums)"` bypasses the `"Kultūršoks"` exclusion
  (live-confirmed bug — the page only serves the suffixed variant).
- `scrape_tv_programs --dry-run` is parsed but **ignored** —
  `scraper.run()` always writes. Fix as part of this work.

### 1.3 Live tet.lv listing structure (fetched 2026-10-01)

`https://www.tet.lv/televizija/tv-programma?tv-type=interactive&view-type=list&date=YYYY-MM-DD&channel={slug}`

- 36 entries/day on `ltv1_hd`, ~14 on `filmzone_hd`. Each entry is a
  `<div class="show-line event-click" data-id="6789930397876">`
  immediately followed by its `.show-expander-content` block — `data-id`
  is a **per-airing event id** (pairing verified 1:1).
- Series encode season/episode in the title:
  `Mīlas viesulis 21. Vācijas seriāls. 4471. sērija`,
  `Alpu dakteris 13. Seriāls. 13. sērija`,
  `Solījums 4. Spānijas telenovele. 612. sērija`,
  `Garainis. 3. sezona (atkārtojums)`.
- `(atkārtojums)` = rerun marker appended to the title.
- Movie descriptions are full LV synopses and identical across repeats —
  good dedup material. LTV shows often have no/short description
  (`ar subtitriem`).
- Posters: `https://www.tet.lv/cache/mdsposters/{uuid}.webp` — stable
  per content, belongs on `Show`.

### 1.4 IMDb integration history

| Commit | Branch | What |
|---|---|---|
| `0fe1775` + `ba6788b` + `7c211ad` | `feature/omdb-integration` (never merged) | Full OMDb client: `t=` exact → `s=` search → `i=` fetch, 1000/day counter, 100 ms throttle, `SequenceMatcher` match ratios, `imdb.com/title/{id}` URLs. `OMDB_MIGRATION_PLAN.md` documents field mapping. |
| `b0d1363`..`d4f44a5` | master | IMDb HTML scraping + JSON-LD extraction (`imdb.com/find`). Dead — IMDb blocks/alters markup. |
| `0eab1ec` | master | Dropped all external enrichment → heuristics only. Fields `imdb_id`, `title_eng`, `url`, `imdb_rating`, `pg_rating`, `enrichment_source` remain on `Program`, mostly null. |

- Old code called `translate_lv_to_eng()` (`tv_programs/utils.py`) which
  is a **stub returning the input** — OMDb was effectively queried with
  Latvian titles. Real translation was never implemented.
- Old `settings.OMDB_KEY` came from `private_settings.json`; current
  settings use `django-environ` — re-add as `env('OMDB_KEY', default='')`
  (`.env.example` already documents `OMDB_KEY`).
- Cloud Run job `scrape-tv-programs` (`terraform/main.tf` ~L226) envs do
  **not** include `OMDB_KEY` — terraform change needed for prod.

### 1.5 API availability checks (2026-10-01)

- `https://www.omdbapi.com/?apikey=invalid&t=matrix` →
  `{"Response":"False","Error":"Invalid API key!"}` — API alive, needs
  the key. Free tier: 1,000 req/day (old code already capped at 1000).
- **Cinemeta** (Stremio's open-source metadata addon) works **key-free**:
  `v3-cinemeta.strem.io/catalog/{movie|series}/top/search={q}.json` →
  IMDb ids + posters; `.../meta/{type}/{imdb_id}.json` → `imdbRating`,
  `genres`, `releaseInfo`. Verified with `tt0133093`. Good zero-key
  fallback.

---

## 2. Design decisions

### 2.1 Naming: `Show` (canonical) + `Program` (airing)

Keep the existing `tv_programs_program` table as the *airing* table —
all 20k existing rows are airings, so renaming nothing minimizes
migration churn and every existing query stays valid after adding the
FK. New canonical table is `Show` (`tv_programs_show`).

*Alternative considered*: `Program` = canonical + new `ProgramAiring` —
semantically nicer but requires renaming a populated table and touching
every reference; rejected.

### 2.2 `Show` uniqueness

Dedup key = `sha256(title_norm | desc_norm | season | episode)`:

- `title_norm`: casefold, collapse whitespace, strip `(atkārtojums)`
  (case-insensitive) and trailing dots.
- `desc_norm`: casefold, collapse whitespace, strip `&\w+;` entities
  (same cleanup as `enrich_result` today).
- `season`, `episode`: parsed ints or empty — so `Solījums 4 ... 611.
  sērija` and `... 612. sērija` are different Shows, while a rerun of
  611 (possibly with a slightly different synopsis) still matches when
  the description is empty/equal. Series episodes of the same show share
  `series_title` (base name) — needed later for series-level dislike.

Exact-hash matching is deliberately the only matcher in v1. If tet.lv
varies a description slightly between airings, we get a second `Show` —
acceptable, mergeable in admin later; fuzzy `SequenceMatcher` matching
is listed as a follow-up, not v1.

### 2.3 `Program` (airing) uniqueness

`unique_together = (show, channel, start_time)`; plus
`source_event_id` (tet `data-id`) `unique=True, null=True`. A rerun at
a different time is a different airing of the same Show — exactly the
"repeated references" the user wants.

### 2.4 Exclusion moves to Show level

- Check exclusions against the **normalized** title (fixes the
  `(atkārtojums)` bypass).
- Add `Show.is_excluded` flag so curated exclusions survive admin edits
  and excluded shows are skipped before any enrichment.

### 2.5 Classification stays on `Show`

`content_type`/`classification_*` describe content, not an airing.
Computed once at `Show` creation (uses first-seen duration; acceptable
since duration varies little). Airing keeps only `duration_minutes`.

### 2.6 OMDb as primary, Cinemeta as fallback

- OMDb gives `Rated` (→ `pg_rating`), `imdbRating`, `Plot`
  (→ `description_eng`), `Poster`, `Type`, `Year` — a superset of what
  we stored before. Requires `OMDB_KEY` (already in `.env.example` and
  presumably the user's `.env` / Secret Manager).
- Cinemeta needs no key and yields `imdb_id` + poster + `imdbRating`
  (no PG rating). Use it as fallback when OMDb key missing or query
  misses, so IMDb links still get generated.
- Both are plain HTTP — route through `self.make_request()`
  (throttle + retry) per project scraper rules.

### 2.7 Translation via `ai_providers` JobClient

New `tv_programs/ai_jobs.py`:

```python
TITLE_TRANSLATION = AIJobSpec(
    slug='tv_programs.title_translation',
    description='Translate LV TV show titles to English for IMDb lookup',
    roles=('translate',),
    default_assignments={
        'translate': [('gemini', 'gemini-2.5-flash-lite')],
    },
)
```

- Prompt file `tv_programs/prompts/title_translate.txt` (system_v1
  layout; input = raw title; output = JSON `{"title_en": "..."}` —
  same pattern as `fetcher.vacancy_ocr`).
- Enrichment order per **new** Show (bounded — only new shows cost):
  1. OMDb `t=` with normalized LV title (free; LV aka titles sometimes
     hit),
  2. OMDb `s=` search, pick best candidate via `SequenceMatcher`,
  3. translate via JobClient → retry `t=`/`s=`,
  4. Cinemeta search → meta fetch,
  5. mark `enrichment_status='not_found'`.
- AI spend is capped by `AIJob.max_requests_per_run` (admin-editable,
  seeded e.g. 50/day) — honors the cost-control rule.
- Only run translation once per Show; store result in `title_eng`
  regardless of OMDb outcome.

### 2.8 Like/dislike — single user now, user FK later

`ShowPreference`: `show` FK, `reaction` ∈ `{like, dislike}`, `created_at`.
`user = FK(AUTH_USER_MODEL, null=True, blank=True)` from day one —
`null` = the single anonymous user; `unique_together(show, user)` works
for both. No auth module now; the `/tv/` list excludes shows with a
`dislike` reaction (for series shows, also excludes every Show sharing
the disliked `series_title`).

---

## 3. Data model changes (`tv_programs/models.py`)

```python
class Show(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4,
                          editable=False)
    title_lv = models.CharField(max_length=500)           # normalized
    series_title = models.CharField(max_length=500, blank=True)
    series_season = models.IntegerField(null=True, blank=True)
    series_episode = models.IntegerField(null=True, blank=True)
    description_lv = models.TextField(blank=True, null=True)
    dedup_key = models.CharField(max_length=64, unique=True, db_index=True)
    title_eng = models.CharField(max_length=500, blank=True, null=True)
    description_eng = models.TextField(blank=True, null=True)
    year = models.CharField(max_length=10, blank=True, null=True)
    imdb_id = models.CharField(max_length=20, blank=True, null=True,
                               db_index=True)
    imdb_url = models.URLField(max_length=200, blank=True, null=True)
    imdb_rating = models.DecimalField(max_digits=3, decimal_places=1,
                                      null=True, blank=True)
    pg_rating = models.CharField(max_length=50, blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    categories = models.ManyToManyField(Category, blank=True)
    content_type = models.CharField(choices=Program.ContentType.choices,
                                    default='unknown', db_index=True)
    classification_confidence = models.FloatField(default=0.0)
    classification_reasoning = models.CharField(max_length=255,
                                                blank=True, null=True)
    enrichment_status = models.CharField(        # pending | enriched |
        max_length=20, default='pending', db_index=True)  # not_found |
                                                        # failed
    enrichment_source = models.CharField(max_length=20,   # omdb |
                                         blank=True, null=True)  # cinemeta
    enriched_at = models.DateTimeField(null=True, blank=True)
    title_match_ratio = models.FloatField(default=0)
    is_excluded = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tv_programs_show'


class ShowPreference(models.Model):
    class Reaction(models.TextChoices):
        LIKE = 'like', 'Like'
        DISLIKE = 'dislike', 'Dislike'

    show = models.ForeignKey(Show, on_delete=models.CASCADE,
                             related_name='preferences')
    reaction = models.CharField(max_length=10, choices=Reaction.choices)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                             blank=True, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tv_programs_show_preference'
        unique_together = (('show', 'user'),)
```

`Program` gains:

```python
    show = models.ForeignKey(Show, on_delete=models.PROTECT,
                           related_name='airings', null=True)
    source_event_id = models.CharField(max_length=30, unique=True,
                                       null=True, blank=True)
    # Meta: unique_together = (('show', 'channel', 'start_time'),)
```

`Program` keeps its existing `title_lv`, `description_lv`, `image_url`
etc. as the as-scraped snapshot (cheap denormalization; backfill reads
them; template can fall back when `show` is null). `imdb_rating` becomes
`DecimalField` on `Show` — fixes `imdb_rating__gte` string comparison.

---

## 4. Scraper changes (`tv_programs/scraper.py` + new `dedup.py`)

### 4.1 New module `tv_programs/dedup.py`

```python
def normalize_title(title: str) -> str          # strip (atkārtojums), ws
def parse_series_info(title: str) -> dict       # series_title/season/episode
def normalize_description(desc: str) -> str
def compute_dedup_key(title, desc, season, episode) -> str  # sha256 hex
def get_or_create_show(parsed: dict) -> tuple[Show, bool]
```

`parse_series_info` regexes (verified against live data):

- episode: `r'(\d+)\.\s*sērija'`
- season: `r'(\d+)\.\s*sezona'` or a bare `(\d+)` immediately after the
  base title before the genre word (`Alpu dakteris 13. Seriāls...`,
  `Solījums 4. Spānijas telenovele...`, `Mīlas viesulis 21. Vācijas
  seriāls...`)
- `series_title` = base text before the genre/episode fragments.

### 4.2 `parse_results`

Additionally capture `data-id` from the `.show-line` sibling preceding
each `.show-expander-content`, and `series_*` via `parse_series_info`.
Return dicts gain `source_event_id`, `season`, `episode`,
`series_title`, normalized `title_lv`.

### 4.3 `remove_redundant_results`

Rewrite: drop entries whose normalized title is in
`EXCLUDED_LOCAL_SHOWS`; batch-load existing `Show` rows by dedup key and
existing airings by `(source_event_id)` + `(show, channel, start_time)`.
Keep airings that are genuinely new; attach the resolved `show` to each
result so `enrich_result` doesn't re-query. **Airings of known shows are
kept** (not dropped) — that's the whole point: they become new rows
referencing the same Show.

### 4.4 `enrich_result` / `initiate_resource`

- `enrich_result`: resolve `Show` (get_or_create on dedup key); if
  *created* → run enrichment chain (§5) unless `is_excluded`. Attach
  `show` to the resource dict.
- `initiate_resource`: build `Program` airing row (`show`, `channel`,
  `start_time`, `duration_minutes`, `source_event_id`, scraped
  title/desc snapshot).
- `create_or_update_resources`: `bulk_create(...,
  ignore_conflicts=True)` on airings — reruns/overlapping ranges are
  idempotent.

### 4.5 Command

`scrape_tv_programs`: honor `--dry-run` (skip `create_or_update`),
add `--days-past/--days-future` passthrough to `config`, and
`--no-enrich` to disable OMDb/AI calls for pure scraping tests.

---

## 5. OMDb + translation (`tv_programs/enrichment.py`)

```python
class OMDbClient:
    def __init__(self, request_fn, api_key, daily_limit=1000,
                     min_interval=0.1): ...
    def search_title(self, title, year=None, kind=None) -> dict|None
        # t= exact → s= search → best SequenceMatcher candidate → i= fetch
    def get_by_id(self, imdb_id) -> dict|None


def enrich_show(show, omdb: OMDbClient|None, ai_client,
                cinemeta_ok=True) -> Show
```

- Port `_omdb_request`/`get_omdb_data`/`process_item` from
  `feature/omdb-integration` (`git show 7c211ad:tv_programs/scraper.py`),
  cleaned up: `https://` (old code used `http://`), key guard
  (skip chain entirely when `OMDB_KEY` empty), counters/log lines kept.
- `request_fn` = `self.make_request` inside the scraper; the enrich
  command constructs a `TVProgramScraper()` instance without calling
  `run()` to reuse its throttled HTTP (or a small shared throttled
  urllib3 wrapper — decide at implementation).
- Field mapping (from `OMDB_MIGRATION_PLAN.md` / `process_item`):
  `Title→title_eng`, `Plot→description_eng`, `imdbRating→imdb_rating`,
  `Rated→pg_rating`, `Year→year`, `Poster→image_url` (only when tet
  poster missing), `imdbID→imdb_id` + `imdb.com/title/{id}` → `imdb_url`,
  `Type` cross-check against `content_type`, `enrichment_source='omdb'`,
  `title_match_ratio` kept for debuggability.
- Store `enrichment_status` always — `not_found` rows are queryable for
  later retries (e.g. `--retry-failed` after N days or when a better
  translator lands).
- Translation client: `get_job_client(TITLE_TRANSLATION)`; on
  `AIRequestCapReached`/`AIAllModelsFailedError` log + continue without
  translation (show still gets OMDb-LV + Cinemeta attempts).
- `translate_lv_to_eng` in `utils.py` is deleted or made to delegate —
  don't leave a second fake path.

New command `enrich_tv_shows` (plain `BaseCommand`, modeled on
`backfill_page_analysis_ai_models`): `--status pending|not_found|failed`,
`--limit`, `--batch-size`, `--dry-run`. Backfills Show enrichment without
rescraping.

---

## 6. Views & template

- `program_list`: `Program.objects.select_related('show','channel')`;
  filters move to `show__` fields (`pg_rating`, `imdb_rating__gte` now a
  real numeric compare); exclude `show__preferences__reaction='dislike'`
  (and same `series_title`) unless `?show_disliked=1`.
- New POST endpoint `react/<uuid:show_id>/<reaction>/` (toggle:
  same reaction again = delete). CSRF + POST-only; no login required
  (single user) but keep the view ready for `request.user`.
- `program_list.html`: per-card buttons Like/Dislike, IMDb link from
  `program.show.imdb_url` labelled "IMDb", show `title_eng` beside
  `title_lv`, display `imdb_rating`/`pg_rating` from `show`, indicate
  liked cards.
- `admin.py`: register `Show` (search title, filter
  `enrichment_status`/`content_type`/`is_excluded`), `Program`,
  `ShowPreference`, `Channel`, `Category`. Admin `merge` action on Show
  is a nice-to-have later.

---

## 7. Backfill (`backfill_program_shows` command)

Maps the ~20k existing `Program` rows:

1. Iterate `Program.objects.filter(show__isnull=True)` in batches.
2. Compute dedup key from each row's `title_lv`/`description_lv`
   (series fields via `parse_series_info`).
3. `get_or_create` Show (enrichment_status='pending'), set FK.
4. `--dry-run` prints expected Show count first (~3.6k from 20k locally).

Idempotent; afterwards `Program.show` can go `null=False` in a follow-up
migration (keep nullable in v1 so partial backfills don't break).

---

## 8. Infra & config

- `settings.py`: `OMDB_KEY = env('OMDB_KEY', default='')` —
  `.env.example` already lists it.
- **Secret already created** (2026-10-01, gcloud):
  `industry-analyser-omdb-key` in project `gen-lang-client-0833674612`,
  following the `industry-analyser-fetcher-*` convention (secrets are
  created outside Terraform with gcloud — see comment in `main.tf`).
- Terraform wiring (`terraform/main.tf`): mount it as a runtime env on
  the `scrape-tv-programs` job via `secret_key_ref`
  (`secret = "industry-analyser-omdb-key"`, `version = "latest"` → env
  `OMDB_KEY`) and add a
  `google_secret_manager_secret_iam_member.omdb_key_accessor` binding
  granting `roles/secretmanager.secretAccessor` on that secret to
  `google_service_account.job_runtime` — the same pattern as
  `fetcher_keywords_accessor`/`fetcher_portals_accessor`. No
  `TF_VAR_`/GitHub secret needed since the value stays in Secret
  Manager. `GEMINI_API_KEY` is already present on the job (for the
  translation JobClient).
- `python manage.py seed_ai_config` picks up the new
  `tv_programs.title_translation` spec on next run/deploy (idempotent).
- Reminder: **never** run `makemigrations`/`migrate` as the agent — the
  user generates and runs them.

---

## 9. Implementation phases (PR-sized)

| PR | Scope | Depends on |
|---|---|---|
| 1 | `Show` model + `dedup.py` + `Program.show`/`source_event_id` + unit tests for normalize/series-parse/dedup key | — |
| 2 | Scraper rewrite: `data-id` capture, Show matching, airing upserts, exclusion-on-normalized-title fix, `--dry-run` fix | 1 |
| 3 | `backfill_program_shows` command + admin registration | 1 |
| 4 | `OMDbClient` + `enrich_show` + `enrich_tv_shows` command + settings/terraform `OMDB_KEY` | 1–3 |
| 5 | `tv_programs/ai_jobs.py` + prompt file + translation in enrich chain | 4 |
| 6 | `ShowPreference` + react endpoint + template buttons + dislike filtering + IMDb link rendering | 1 (UI); 4–5 make links non-null |
| 7 | Cinemeta fallback inside `enrich_show` (can merge into PR-4 if small) | 4 |

PRs 1–3 are pure normalization and can ship/verify independently;
enrichment and reactions layer on afterwards.

---

## 10. Verification

- `python manage.py check`; `python manage.py test tv_programs`
  (extend `tests.py`: series-parse cases for all live patterns, dedup
  key stability, rerun-of-same-episode dedups to one Show, exclusion
  catches `(atkārtojums)` variants, OMDb client mocked — reuse
  `tests/test_omdb_integration.py` from `feature/omdb-integration` as a
  starting point).
- Fixture: refresh `tests/fixtures/tet_sample.html` with a 2026-10
  page containing `data-id` attributes.
- Manual scrape: `scrape_tv_programs --dry-run --days-past 0
  --days-future 1` then a real limited run; confirm a rerun creates 0
  new airings and 0 new Shows.
- Backfill dry-run on local DB → ~3.6k Shows from 20,268 Programs.
- Enrich a few pending shows with `enrich_tv_shows --limit 5` —
  confirm `imdb_url` renders in `/tv/`.
- UI: like/dislike a show → it disappears/reappears on the feed.

## 11. Risks & open questions

- **OMDb key**: `industry-analyser-omdb-key` exists in GCP Secret
  Manager; still needs adding to local `.env` for dev runs
  (`OMDB_KEY=...`). If the key proves invalid/quota-blocked, PR-7
  (Cinemeta) becomes the primary path — same code shape, fewer fields
  (no `Rated`).
- **Description drift**: if tet.lv rewords synopses between reruns,
  duplicate Shows appear. Mitigation later: fuzzy merge admin action or
  a `title+series` secondary key pass.
- **data-id stability**: assumed stable per broadcast event; if it
  regenerates, `(show, channel, start_time)` unique still protects us.
- **Translation cost**: bounded by `AIJob.max_requests_per_run`; only
  new unmatched shows consume requests.
- **Films vs series naming edge cases**: Latvian titles occasionally
  differ wildly from originals (`Lodes pa gaisu!` = *Free Fire*) —
  translation quality is the bottleneck for match rate; match-ratio
  fields let us audit.
