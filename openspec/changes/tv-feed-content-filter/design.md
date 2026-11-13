# Design

## Filter semantics

Default-on filter, opt-out param — mirroring the
`not_content_rating` default-'R' convention already in
`list_programs`: the server applies the content filter when
`all_content` is absent, an explicit `?all_content=1`
disables it, and `filters.all_content` echoes the effective
state so the SPA can render it.

```python
if not all_content:
    query &= (
        Q(content_type=Program.ContentType.MOVIE)
        | Q(show__series_title__gt='')
        | Q(show__series_episode__isnull=False)
    )
query &= Q(show__isnull=True) | Q(show__is_excluded=False)
```

- `content_type` is read from `Program`, not `Show` — the
  scraper stamps `show.content_type if show else
  c.content_type` on the Program row (`scraper.py`), so the
  program field already carries the canonical value and is
  what `reclassify_tv_programs` refreshes.
- Series membership is judged on Show structure, not title
  text — `dedup.parse_series_info` extracts
  `series_title`/`series_episode` at scrape; verified on
  prod that every real series airing carries it.
- `is_excluded` applies in both modes: it is the explicit
  "never surface" flag (dedup sets it from
  `EXCLUDED_LOCAL_SHOWS`, admin can toggle it). An "all
  content" opt-out should show the full schedule, not
  resurrect admin-excluded rows.

## Why not duration

`duration_minutes >= 90` measures slot length, not content
kind. Prod: 78% of series airings and 23% of movies fall
under 90min, while sport broadcasts and multi-episode
blocks pass it. It can still be added later as a user-side
optional filter; it is wrong as the default mechanism.

## Classifier markers

Additions go to `SERIES_MARKERS` (the effective not-movie
list — it fires before the duration rules, so it also
fixes the "non-movie channel + ≥80min" leaks). Deliberately
excluded: `spēle` (too broad — appears in film plots),
bare `sports`/`ziņas` variants already covered.
`Slow TV:` airings are ambient programming, not movies.

## Frontend contract

- `ProgramParams.allContent` — `'1'` serializes the param,
  anything else omits it (absent = filtered).
- Checkbox "Only movies & shows:" checked by default;
  unchecking sets `all_content=1` on submit. This keeps the
  URL the source of truth like every other filter and
  keeps the checkbox readable as the feature it controls
  (a "Show all content" unchecked box would hide the
  default behind a double negative).
- The summary line notes when the filter is bypassed
  (`· all content`), matching how the 'R' exclusion is
  echoed today; EmptyState text mentions the default
  content filter.

## Out of scope

- `reclassify_tv_programs` does not sync
  `Show.content_type` — pre-existing drift, doesn't affect
  this filter (it reads `Program.content_type`).
- Running reclassification on prod — maintainer step.
- Category-based filtering — `tv_programs_category` is
  empty; nothing populates it.
