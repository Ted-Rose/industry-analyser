# Tasks

## 1. Backend filter

- [x] 1.1 backend: In `tv_programs/api.py` `list_programs`,
  add `all_content: bool = False` query param. While false,
  AND `(content_type='movie' OR show__series_title>''
  OR show__series_episode IS NOT NULL)` into the query. In
  both modes AND `(show IS NULL OR show__is_excluded=False)`.
  Echo `all_content` on `ProgramFiltersOut`. Verify:
  `python manage.py check`.
- [x] 1.2 backend: In `tv_programs/classification.py` extend
  `SERIES_MARKERS` with: `tiešraide`, `pasaules kauss`,
  `čempionāt`, `olimpisk`, `biatlon`, `basketbol`,
  `volejbol`, `hokejs`, `futbol`, `izrāde`,
  `dievkalpojums`, `slow tv`. Verify: unit-test a
  "TIEŠRAIDE! …basketbolā…" 155min title now classifies
  `not_movie`.
- [x] 1.3 backend: Regenerate the API contract:
  `python manage.py export_openapi_schema --output
  frontend/openapi.json` then `cd frontend &&
  npm run gen:types`. Verify: `git status` shows both
  regenerated files.

## 2. Backend tests

- [x] 2.1 backend: Add tests in the tv_programs test suite:
  default request returns movie + series-meta programs and
  hides not_movie/unknown without series meta;
  `?all_content=1` returns them; a program whose Show
  `is_excluded` is hidden in both modes; `filters.
  all_content` echoes correctly. Verify:
  `DATABASE_URL=sqlite:///db.sqlite3 python manage.py test
  tv_programs`.

## 3. Frontend

- [x] 3.1 frontend: `frontend/src/tv/api.ts` — add
  `allContent?: string | null` to `ProgramParams`;
  serialize `all_content=1` when `'1'`.
- [x] 3.2 frontend: `frontend/src/tv/routes/ProgramList.tsx`
  — "Only movies & shows:" checkbox next to "Show
  disliked:", checked unless `?all_content=1`; unchecking
  serializes `all_content=1`, checking omits the param.
  Summary line gains `· all content` when bypassed;
  EmptyState copy notes the default content filter. Seed
  draft from URL in both draft-init and the resync effect,
  mirroring `showDisliked`.
- [x] 3.3 frontend: Update `ProgramList.test.tsx` — default
  render doesn't send `all_content`; unchecking the box
  submits `all_content=1`; summary text reflects bypass.
  Verify: `cd frontend && npm run typecheck && npm test`.
- [x] 3.4 frontend: Rebuild and recommit `frontend_dist/`
  (tracked build output — see openspec apply guidance /
  AGENTS.md).

## 4. Docs

- [x] 4.1 both: If AGENTS.md or openspec specs describe the
  program feed filters, update the param list one line.
  (No file enumerates the feed params — nothing to update.)
