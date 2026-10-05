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
  selection entirely. Combining it with `--keyword-id` /
  `--exclude-keywords` is a `CommandError` (they'd be silently
  ignored otherwise).
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

Then **normalize the detail object into search-result shape** and
run the normal build pipeline so keyword matching / OCR staging /
industry mapping are identical to a live scrape. The real
`pageProps.vacancy[id]` object nests what the search payload keeps
flat — verified against `/lv/vacancy/1655039`:

| `_build_vacancy` key | Detail source |
|---|---|
| `positionTitle` | `position` (or `highlights.position`) |
| `salaryFrom` / `salaryTo` | `highlights.salaryFrom` / `.salaryTo` |
| `expirationDate` | `settings.dateTo` (date-only → made aware) |
| `categories` | `settings.categories` — **enum names** (`'INFORMATION_TECHNOLOGY'`), not the numeric ids `industry_mapping` expects |
| `keywords` | `settings.keywords` `[{id, value}]` — lift `.value` |
| `positionContent` | absent — `details.standardDetails` text covers it via `_detail` |
| `employerId`/`employerName`/`employer`/`contacts`/`details` | work as-is |

```python
result = dict(detail)                    # employer* keys ride along
result['id'] = vacancy.vacancy_portal_id
result['positionTitle'] = detail.position or highlights.position
    or stored title
result['employerName'] = detail.employerName or stored company_name
result['salaryFrom'/'salaryTo'] = highlights.*
result['expirationDate'] = aware_iso(settings.dateTo)
result['categories'] = settings.categories      # enum names
result['keywords'] = [k['value'] for k in settings.keywords]
result['_detail'] = detail
fresh = scraper.initiate_resource(result)   # _build_vacancy
```

`_build_vacancy` produces an unsaved `Vacancy` with fresh scalars plus
`_pending_keywords`, `_pending_industries`, `_pending_employer_detail`,
`_pending_file` — all reused, none reimplemented. The command also
stamps `fresh._overwritable_fields` with which
`salary*`/`application_deadline` source keys the payload actually
carried (see conditional overwrite below).

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
2. **Scalars — conditional true refresh**: `title`, `company_name`
   overwritten when the fresh value is non-None. `salary_from`,
   `salary_to`, `application_deadline` are overwritten **only when
   the payload carried the source key** (`_overwritable_fields`) —
   an explicit `null` clears the stored value, but a missing key
   means "the portal didn't report it this time" and the stored
   value survives. `first_seen` is never overwritten: it records
   when *we* first saw the ad, not the portal's publish date.
   `last_seen` and `detail_fetched_at` always set on success.
3. **Keywords — replace, not merge**: delete existing
   `VacancyContainsKeyword` rows and bulk-create the fresh
   `_pending_keywords` set (portal-declared keywords ride in via
   `settings.keywords`, so they survive the replacement). Skipped
   when the set is unchanged.
   **Industries — replace only when fresh ones resolved**: detail
   `settings.categories` are enum names `industry_mapping` can't
   resolve, so a detail fetch normally produces no
   `_pending_industries` — deleting then would wipe every
   `VacancyIndustries` link. The swap only runs when the
   normalized payload yielded at least one industry; otherwise
   the stored set is kept.
4. **OCR**: `fileDetails.fileId` rides `_build_vacancy` →
   `_ocr_vacancy_file` (cache-first, per-file failures non-fatal).
   `--no-ocr` sets `scraper._ocr_unavailable = True`, which keeps
   cached `VacancyFile` text for matching but never fetches/AI-calls.
   `_pending_file` rows persist via `get_or_create(file_id=…)`.

## Outcomes / counters

Per-vacancy partition: `refreshed` | `no_employer` | `fetch_failed`
| `no_next_data` (malformed page — no `__NEXT_DATA__` blob at all)
| `no_detail` (expired ad — `vacancy[id]` absent from an
otherwise-valid `__NEXT_DATA__`) | `error`. Stats: `files_seen`,
`files_saved`,
`keywords_changed`, `industries_changed`, `companies`. Each vacancy is
wrapped in try/except so one bad row can't kill the run; summary line
is INFO-logged via `logging.getLogger('fetcher')` and printed.

## Flags

`--keyword-id`, `--exclude-keywords`, `--ids`, `--limit`
(must be >= 1 — `CommandError` otherwise),
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
The `refetch_detail()` fixture mirrors the real
`pageProps.vacancy[id]` shape (nested `highlights`/`settings`, no
flat `positionTitle`/`salaryFrom`/`expirationDate`). Cover:
keyword-id selection, exclude filtering, `--ids` override and its
rejection of keyword-selection args, unknown keyword id
`CommandError`, `--limit` cap + validation, dry-run zero
fetches/writes, full refetch updating vacancy + company + keyword
replacement, conditional-overwrite regression (stored
salary/industries survive a payload lacking them; explicit nulls
clear), expired ad (`no_detail`) vs malformed page
(`no_next_data`), `no_employer`, `--no-ocr` skipping the file
fetch, OCR text feeding keyword matching + `VacancyFile`
persistence.
