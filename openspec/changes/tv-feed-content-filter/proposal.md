# Proposal

## Why

`/tv/` shows every scraped tet.lv airing with no content-type
filter — `list_programs` (`tv_programs/api.py`) filters on
pg/imdb rating, match ratio, date window and channel only.
Against live prod data (7-day window, 769 airings): 186
`movie` (24%), 529 `not_movie` (69%), 54 `unknown` (7%).
Roughly 48% of the feed is news, interviews, concerts, talk
shows and church services — not the movies and TV shows the
page exists to surface.

A `duration_minutes >= 90` filter was considered and rejected
with data: it keeps only 206 airings while dropping 172 of
220 series-episode airings (78% — episodes are 30–60min
slots) and 43 of 186 movies (23%), and still admits 63
not_movie/unknown rows (sport, multi-episode blocks). The
structural signals that already exist — `content_type` and
`Show.series_title`/`series_episode` — separate the wanted
content far better: `movie OR has-series-meta` keeps 401/769
(every movie + every episode), verified against prod.

The `movie` class also leaks live sport/theater: "TIEŠRAIDE!
…basketbolā", "Pasaules kauss biatlonā" and "izrāde" airings
hit the ≥80min movie rule because `SERIES_MARKERS` (the
not-movie marker list) lacks live/sport/worship markers.

## What Changes

- `GET /api/tv/programs/` gains an `all_content` boolean
  param (default off). While off, the queryset keeps only
  `content_type='movie'` programs or airings whose Show has
  series metadata (`series_title` non-empty or
  `series_episode` set). `all_content=1` restores today's
  unfiltered feed. Programs whose Show `is_excluded` are
  hidden in both modes.
- `ProgramFiltersOut` echoes `all_content`.
- `classification.py`: extend the not-movie marker list with
  live/sport/worship markers observed leaking into `movie`
  (`tiešraide`, `pasaules kauss`, `čempionāt`, `olimpisk`,
  `biatlon`, `basketbol`, `volejbol`, `hokejs`, `futbol`,
  `izrāde`, `dievkalpojums`, `slow tv`).
- tv SPA: a checked-by-default "Only movies & shows"
  checkbox in the filter bar; unchecking serializes
  `all_content=1`. Summary/empty-state text reflects the
  effective mode.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `spa-api-contract`: `/api/tv/programs/` gains the
  `all_content` param and a default content filter — a
  behavior change to an existing endpoint the spec does not
  currently constrain (no spec delta file; the contract
  requirements it does state are unaffected).

## Impact

Both layers. Backend: `tv_programs/api.py` (query + schema),
`tv_programs/classification.py` (markers), `tv_programs`
tests, `frontend/openapi.json` + regenerated api-types.
Frontend: `frontend/src/tv/{api.ts,routes/ProgramList.tsx,
routes/ProgramList.test.tsx}` and the rebuilt committed
`frontend_dist/` output. No model changes, no migration.
Deployed classification changes apply to new scrapes only —
reclassifying existing rows (`reclassify_tv_programs`) is a
manual prod step for the maintainer, out of scope here.
