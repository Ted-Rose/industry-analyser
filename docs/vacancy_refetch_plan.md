# Plan: `refetch_vacancies` management command

Context: `docs/vacancy_refetch_context.md`. Re-fetches cv.lv vacancy
**detail pages** for a user-selected subset of already-scraped
`Vacancy` rows and refreshes them end-to-end — vacancy fields, linked
`Company`, keyword/industry links, and OCR'd file text.

## Why not `BaseRefetchCommand`

`core_scraper.BaseRefetchCommand` is shaped for classified_ads models
(`ad_id`/`link`, `--filter`, `--fields`). `Vacancy` has
`vacancy_portal_id`/`url` and needs M2M-aware refresh semantics, so a
Vacancy-specific command modeled on
`fetcher/management/commands/link_vacancies_to_companies.py` is the
right fit (same scraper-without-`run()` trick, same per-row outcome
counters).

## Selection

- `--keyword-id K` — required unless `--ids` is given. Selects
  `Vacancy.objects.filter(keywords__id=K)` (M2M through
  `VacancyContainsKeyword`).
- `--exclude-keywords A B C` — drops vacancies linked to *any* of the
  given keyword ids via the explicit subquery (avoids the same-relation
  alias pitfall of chained `.exclude(keywords__in=...)`):

  ```python
  qs.filter(keywords__id=K).exclude(
      pk__in=Vacancy.objects.filter(keywords__id__in=excluded)
  )
  ```

- `--ids` — explicit `vacancy_portal_id` list; bypasses keyword
  selection entirely.
- All supplied keyword ids are validated against `Keyword` —
  unknown ids raise `CommandError` before any fetch.
- Ordering: `detail_fetched_at` ascending (nulls first) so the
  stalest rows are refreshed first.

## Per-vacancy refresh (reuse path)

```python
scraper = VacancyScrapper(portal_id=nextjs_portal_id())
resp = scraper.make_request(vacancy.url)            # throttled
detail = company_linking.extract_vacancy_detail(
    scraper._extract_next_data(resp.data),
    vacancy.vacancy_portal_id)
```

`nextjs_portal_id` is imported from
`fetcher.management.commands.link_vacancies_to_companies` (no
duplication, no changes to that command).

Then **synthesize a search-result dict** and run the normal build
pipeline so keyword matching / OCR staging / industry mapping are
identical to a live scrape:

```python
result = dict(detail)                    # detail carries
                                         # positionTitle, salary…
result['id'] = vacancy.vacancy_portal_id
result.setdefault fallback: positionTitle/employerName from the
    stored row when the detail object lacks them
result['_detail'] = detail
fresh = scraper.initiate_resource(result)   # _build_vacancy
```

`_build_vacancy` produces an unsaved `Vacancy` with fresh scalars plus
`_pending_keywords`, `_pending_industries`, `_pending_employer_detail`,
`_pending_file` — all reused, none reimplemented.

### Why not `create_or_update_resources`

It only fills **empty** `title`/`company_name` and bulk-inserts keyword
links with `ignore_conflicts` — it never overwrites stale scalar
fields nor removes links whose text no longer matches. The command
therefore persists manually inside one `transaction.atomic()` per
vacancy:

1. **Company**: `fresh._pending_employer_detail` →
   `resolve_company(employer_id, employer_name)` →
   `apply_employer_detail(company, slice)` (writes about/contacts/
   reg_code with the §4.1 conflict rules + `clip_field`), then
   `vacancy.company = company`. Missing `employer_id` → outcome
   `no_employer` (vacancy still refreshed, company untouched).
2. **Scalars — true refresh**: `title`, `company_name`, `first_seen`
   overwritten when the fresh value is non-None; `salary_from`,
   `salary_to`, `application_deadline` overwritten unconditionally
   (a removed salary/deadline must clear). `last_seen` and
   `detail_fetched_at` always set on success.
3. **Keywords/industries — replace, not merge**: delete existing
   `VacancyContainsKeyword`/`VacancyIndustries` rows and bulk-create
   the fresh `_pending_*` sets (deduped by id). Skipped when the set
   is unchanged.
4. **OCR**: `fileDetails.fileId` rides `_build_vacancy` →
   `_ocr_vacancy_file` (cache-first, per-file failures non-fatal).
   `--no-ocr` sets `scraper._ocr_unavailable = True`, which keeps
   cached `VacancyFile` text for matching but never fetches/AI-calls.
   `_pending_file` rows persist via `get_or_create(file_id=…)`.

## Outcomes / counters

Per-vacancy partition: `refreshed` | `no_employer` | `fetch_failed`
| `no_detail` (expired ad — `vacancy[id]` absent from
`__NEXT_DATA__`) | `error`. Stats: `files_seen`, `files_saved`,
`keywords_changed`, `industries_changed`, `companies`. Each vacancy is
wrapped in try/except so one bad row can't kill the run; summary line
is INFO-logged via `logging.getLogger('fetcher')` and printed.

## Flags

`--keyword-id`, `--exclude-keywords`, `--ids`, `--limit`,
`--batch-size` (default 100, feeds `qs.iterator(chunk_size=…)`),
`--no-ocr`, `--dry-run` (prints count + first ~10 vacancies; no
fetches, no writes).

## Gotchas honored

- `_needs_detail_fetch` gating is bypassed — every selected row is
  fetched unconditionally (that's the point of the command).
- All portal strings pass through `clip_field` inside
  `_build_vacancy`/`apply_employer_detail` (StringDataRightTruncation
  protection).
- Throttling: only `scraper.make_request` (~1 s/domain + retries) —
  never raw urllib/requests.
- No new dependencies, no migrations, 79-char lines.

## Tests (`fetcher/tests.py`)

Mock boundary: `VacancyScrapper.make_request` (class-level
`mock.patch.object`, per-URL `side_effect` returning
`SimpleNamespace(data=…, headers=…)` fakes) +
`load_portals_config` patched like `LinkVacanciesToCompaniesTests`.
Cover: keyword-id selection, exclude filtering, `--ids` override,
unknown keyword id `CommandError`, dry-run zero fetches/writes, full
refetch updating vacancy + company + keyword replacement, expired ad
(`no_detail`), `--no-ocr` skipping the file fetch, OCR text feeding
keyword matching + `VacancyFile` persistence.
