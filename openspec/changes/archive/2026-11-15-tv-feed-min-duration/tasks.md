# Tasks

## 1. Backend filter

- [x] 1.1 backend: In `tv_programs/api.py` `list_programs`,
  add `min_duration: Optional[float] = Query(None)`. Absent →
  effective 80; `>0` ANDs `duration_minutes__gte` into the
  query; `0`/negative disables. Echo the effective value on
  `ProgramFiltersOut.min_duration` (null when disabled). Add
  `duration_minutes` to `ProgramOut`. Verify:
  `python manage.py check`.
- [x] 1.2 backend: Regenerate the API contract:
  `python manage.py export_openapi_schema --output
  frontend/openapi.json` then `cd frontend &&
  npm run gen:types`. Verify: `git status` shows the
  regenerated files.

## 2. Backend tests

- [x] 2.1 backend: Add tests in `tv_programs/tests.py`: a
  default request hides programs under 80min and
  NULL-duration rows; `?min_duration=45` filters at 45;
  `?min_duration=0` returns short programs;
  `filters.min_duration` echoes 80 by default and null when
  disabled; `duration_minutes` is present in the program
  payload. Verify:
  `DATABASE_URL=sqlite:///db.sqlite3 python manage.py test
  tv_programs`.

## 3. Frontend

- [x] 3.1 frontend: `frontend/src/tv/api.ts` — add
  `minDuration?: string | null` to `ProgramParams`;
  serialize via `setNumber` as `min_duration`.
- [x] 3.2 frontend: `frontend/src/tv/routes/ProgramList.tsx`
  — "Min. Length (min):" number input; draft seeded from the
  URL then filled with `filters.min_duration` on resolve;
  submit skips the param while the draft equals the echoed
  default and serializes `min_duration=0` when cleared.
  Summary gains `· ≥N min`; EmptyState mentions the 80-min
  default; card meta gains `· N min`.
- [x] 3.3 frontend: Update `ProgramList.test.tsx` — default
  render doesn't send `min_duration`; a changed value is
  submitted; a cleared input submits `min_duration=0`; the
  card renders the duration; filters fixture gains
  `min_duration`. Verify: `cd frontend && npm run typecheck
  && npm test`.
- [x] 3.4 frontend: Rebuild and recommit `frontend_dist/`
  (`npm run build` — tracked build output, see AGENTS.md).

## 4. Docs

- [x] 4.1 both: If AGENTS.md or openspec specs describe the
  program feed filters, update the param list one line.
