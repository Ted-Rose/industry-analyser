# Proposal

## Why

`/tv/` already filters by rating, match ratio, date window and
channel — but not by program length. `Program.duration_minutes`
is populated by the scraper for essentially every airing (prod:
24,287 rows, 86 NULL) — the data is already there, no scraping
changes are needed. A minimum-length filter lets the user
restrict the feed to movie-length slots (the classification
layer already treats ≥80min as a movie signal).

## What Changes

- `GET /api/tv/programs/` gains a `min_duration` numeric param
  (minutes, `Optional[float]` truncated server-side). Absent →
  the server applies a default of `80`; `?min_duration=<n>`
  overrides; `?min_duration=0` disables the filter (a numeric
  param can't carry the "explicit empty disables" convention
  `not_content_rating` uses — a bare `?min_duration=` would 422
  — so 0 is the documented off value). Fractional/non-finite
  values truncate/disable rather than 422. Programs with
  NULL `duration_minutes` (86 prod rows) are excluded whenever
  the filter is active — their length is unknown.
- `ProgramFiltersOut` echoes the effective `min_duration`
  (null when disabled via 0).
- `ProgramOut` gains `duration_minutes` so the card can show
  the airing's length — makes the filter self-verifying in the
  UI.
- tv SPA: a "Min. Length (min):" number input seeded to the
  server-effective value (80 by default); clearing it and
  submitting serializes `min_duration=0`. Summary line gains
  `· ≥N min` while the filter is active.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `spa-api-contract`: `/api/tv/programs/` gains the
  `min_duration` param and a default-on length filter — a
  behavior change to an existing endpoint the spec does not
  constrain per-param (no spec delta file; the contract
  requirements it does state are unaffected).

## Impact

Both layers. Backend: `tv_programs/api.py` (query + schemas),
`tv_programs` tests, `frontend/openapi.json` + regenerated
api-types. Frontend: `frontend/src/tv/{api.ts,
routes/ProgramList.tsx, routes/ProgramList.test.tsx}` and the
rebuilt committed `frontend_dist/` output. No model changes,
no migration — `duration_minutes` is already populated.
