# Vacancy Refetch — Usage Guide

Re-fetch cv.lv vacancy detail pages for a keyword-selected subset of
already-scraped vacancies. Unlike the incremental scrape (which only
fills empty fields and only ever *adds* keyword links), this performs
a true refresh per vacancy:

- vacancy fields updated from the live detail payload
  (title, salary, deadline, `detail_fetched_at`, `last_seen`)
- linked `Company` re-enriched (`about`, contacts, `reg_code`, …)
- keyword links **recomputed and replaced** — stale links removed
- `VacancyFile` OCR text reused or refreshed for image-based ads
- industry links replaced only when the payload resolves new ones

## Basic usage

```bash
python manage.py refetch_vacancies --keyword-id 12 --dry-run
```

Always start with `--dry-run`: it prints how many vacancies match and
the first ~10 rows — no HTTP requests, no writes. The local `.env`
points at the production database, so a real run writes prod data and
hits live cv.lv (~1 req/s, throttled) plus Gemini OCR.

## Options

### Selection (required — one of)

- `--keyword-id K` — refetch all vacancies linked to `Keyword` id K
- `--ids ID1 ID2 ...` — refetch specific `vacancy_portal_id`s
  (bypasses keyword selection; cannot be combined with `--keyword-id`
  or `--exclude-keywords`)

### Optional

- `--exclude-keywords A B C` — with `--keyword-id`: skip vacancies
  linked to ANY of these keyword ids
- `--limit N` — max vacancies to process (stalest `detail_fetched_at`
  first)
- `--batch-size N` — query batch size (default: 100)
- `--no-ocr` — skip fetching/AI-transcribing attached files; cached
  `VacancyFile` text is still reused for keyword matching
- `--dry-run` — preview only, no fetches or writes

## Examples

```bash
# All vacancies tagged "python" that are NOT tagged "senior"/"lead"
python manage.py refetch_vacancies \
    --keyword-id 12 --exclude-keywords 30 31

# Bounded run without AI calls (e.g. while Gemini quota is thin)
python manage.py refetch_vacancies --keyword-id 12 --no-ocr --limit 50

# Specific ads by portal id
python manage.py refetch_vacancies --ids 1655039 1655040
```

## What the summary line means

```
done: N vacancy(ies) processed: refreshed=..., no_detail=...,
    no_employer=..., fetch_failed=..., no_next_data=..., error=...
```

- `refreshed` — detail page fetched and row updated
- `no_detail` — `__NEXT_DATA__` has no `vacancy[id]` (expired/deleted ad)
- `no_next_data` — page fetched but `__NEXT_DATA__` unparseable
  (malformed HTML, WAF page)
- `no_employer` — detail parsed but no `employerId` (vacancy fields
  still refresh; company untouched)
- `fetch_failed` / `error` — HTTP or per-vacancy exception; a single
  bad row never aborts the run (each vacancy is its own transaction)

## Notes

- Overwrite semantics: `title`/`company_name` are filled only when the
  payload reports them; `salary_*`/`application_deadline` are
  overwritten only when the source key was present — an explicit
  `null` clears, a missing key keeps the stored value.
- OCR runs through the `fetcher.vacancy_image_ocr` AIJob (Gemini,
  quota-limited); `VacancyFile` is cached per `file_id`, so known
  files never re-request. Use `--no-ocr` to guarantee zero AI calls.
- Keyword ids come from the `fetcher_keyword` table
  (`Keyword.objects.values('id', 'name')`).

See `docs/vacancy_refetch_plan.md` for the design and
`docs/vacancy_refetch_context.md` for the architecture background.
