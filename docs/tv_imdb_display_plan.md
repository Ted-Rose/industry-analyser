# TV page: display IMDb link, IMDb rating and OMDb parental rating

## Status audit (2026-10-05)

### Already implemented

- **Data**: `Show.imdb_id`, `imdb_url`, `imdb_rating` (Decimal),
  `pg_rating` (OMDb `Rated` field — MPAA/TV certification like
  `R`, `PG-13`, `TV-MA`), `enrichment_source` (`omdb`/`cinemeta`).
  Populated by `tv_programs/enrichment.py`:
  OMDb `t=`/`s=`/`i=` -> LV->EN title translation via
  `tv_programs.title_translation` AIJobSpec -> Cinemeta fallback.
- **API**: `GET /api/tv/programs/` returns `show.imdb_rating`,
  `show.imdb_url`, `show.pg_rating` (+ `program.imdb_rating`,
  `program.pg_rating` scraped fallbacks) — `tv_programs/api.py`.
- **Frontend**: `frontend/src/tv/routes/ProgramList.tsx` already
  renders `Rating:`, `PG Rating:` and an `IMDb` link button
  (lines ~372-424), plus `title_eng` and `title_match_ratio`.

### Root cause of missing data (fixed 2026-10-05)

Prod shows were 131/145 `enrichment_status='not_found'` because the
`translate` role had **no active assignment** — the seeded model
`gemini-2.5-flash-lite` was disabled, so `JobClient.generate()` raised
`AIJobNotConfiguredError`, `title_eng` stayed null and Latvian titles
missed OMDb. Diagnosed via job logs:

    WARNING Title translation failed for '...': AI job
    'tv_programs.title_translation' has no active assignment for role
    'translate'

**Fix applied**: the assignment was repointed to the enabled
`gemini-3.5-flash-lite` (AIJobModel row id=10, prod). Verified —
7/8 previously `not_found` shows enriched in a test run
(`Spartaks: Ašura nams` -> `tt29921437` 6.5 TV-MA, etc.).
Remaining `not_found` rows re-enriched via
`python manage.py enrich_tv_shows --status not_found`.

Caveat: `.env` `DATABASE_URL` points directly at the prod Aiven
Postgres — "local" management commands write prod data.

## Display plan (frontend/src/tv)

Card metadata row in `ProgramList.tsx`, current markup:

    Rating: {displayRating(show?.imdb_rating, program.imdb_rating)}
    | Channel: ... | Start Time: ... | PG Rating: {show?.pg_rating || program.pg_rating}
    | Match Ratio: {matchRatio.toFixed(2)} | [IMDb button]

### Changes

1. **IMDb link + rating combined**: render the rating as the IMDb
   link text, e.g. `IMDb 7.6` / `IMDb` when rating unknown.
   Keep `target="_blank" rel="noopener noreferrer"`.
   `imdbHref = show?.imdb_url || program.url` — keep.
2. **OMDb parental rating (`pg_rating`)**: show as a small chip/badge
   (`PG-13`, `TV-MA`); when absent render `—` or omit the segment —
   pick whichever matches existing empty-state style in `tv.css`.
3. **Empty states**: don't print `Rating:` / `PG Rating:` labels with
   blank values; render `—` (or hide the span) when neither
   show-level nor program-level value exists.
4. **Match Ratio**: debug-grade field; keep hidden behind the value
   or drop from the card (developer info, noise for users).
   Decide: keep as-is vs move to title tooltip — user's call.
5. Keep `displayRating()` fallback semantics
   (`frontend/src/tv/format.ts`: show rating, else program rating,
   treat `0`/empty as missing).

### Tests

`frontend/src/tv/routes/ProgramList.test.tsx` already covers:
IMDb link href, `imdb_rating` display, `pg_rating`. Extend for:
- rating-as-link (`IMDb 7.6`),
- `—`/hidden placeholder when fields are null,
- `pg_rating` chip rendering.

### Verification

- `npm test` / vitest in `frontend/` for the updated test file.
- Manual: `/tv/` cards for enriched shows
  (e.g. `Džons Viks 4` -> IMDb 7.6, PG `R`) vs `not_found` shows
  (clean empty state, no dangling separators).

## Ops follow-ups

- `enrichment.py` now logs one INFO line per show
  (`status= source= title_eng= imdb_id= rating= pg=`) — deploy with the
  next push; check `scrape-tv-programs` job logs after deploy.
- Watch `ai_request` rows / AIProvider usage page for translation
  spend (~1 request per new show).
