# Design

## Filter semantics

Default-on filter with a numeric opt-out — the same
"absent → server default applies" convention as
`not_content_rating` (default 'R') in `list_programs`:

```python
if min_duration is None:
    min_duration = 80
# An explicit ?min_duration=0 (or negative) disables the
# filter — a >=0 predicate would just hide NULL rows.
if min_duration > 0:
    query &= Q(duration_minutes__gte=min_duration)
```

- `0` is the disable value because the param is numeric —
  the "explicit empty disables" trick `not_content_rating`
  uses would fail schema validation (422). A ≥0 predicate is
  semantically a no-op anyway, so `min_duration=0` reads
  naturally as "no minimum".
- NULL `duration_minutes` rows drop out under any active
  `__gte` predicate — correct: length unknown means it can't
  be claimed ≥N. Only 86 prod rows.
- `filters.min_duration` echoes the effective value — the
  post-default integer, or null when disabled — matching how
  `filters.not_content_rating` echoes 'R'. The SPA seeds the
  input from it on first resolve (like it does for the
  not_content_rating and date defaults).
- The filter composes with `all_content`: it constrains
  length, not content kind, so it applies in both modes.
- Consequence worth noting: with the default-on
  movies-and-series filter, series airings under 80min are
  hidden too — the user accepted this (episodes are mostly
  20–45min slots; the filter's purpose is movie-length
  picks).

## Data already exists

`duration_minutes` is computed per airing from the tet.lv
schedule's start/end times in `TvScraper.parse_results`
(`scraper.py`), stored on `create_or_update_resources`, and
backfilled historically — verified on prod: 24,287 rows, 86
NULL. No scraping or migration work.

## Frontend contract

- `ProgramParams.minDuration` — serialized via `setNumber`
  like `ratingValue`; absent → server applies 80.
- Draft seeding mirrors `notContentRating`'s 'R': the input
  seeds to the known server default ('80') whenever the URL
  param is absent, so '' only ever means a deliberate clear.
  On submit the param is skipped only while the draft equals
  the echoed default (avoids inflating "Filters (n)"); a real
  change is sent, and a cleared input serializes
  `min_duration=0` (the documented disable).
- The card's meta row gains `· N min` after Start Time —
  makes the active filter visually verifiable.
- The summary line gains `· ≥N min` while the filter is
  active; EmptyState copy mentions the 80-min default.

## Out of scope

- Max-duration filtering — not requested; the param shape
  leaves room to add `max_duration` later.
- Surfacing duration inside the rerun expander's per-airing
  list — headline airing's length is enough.
