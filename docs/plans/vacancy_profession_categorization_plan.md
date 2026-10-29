# Vacancy Profession Categorization Plan

Rule-based profession tagging for `fetcher` vacancies, verified
against the production database (read-only ORM analysis,
2026-10-29).

## tl;dr

- **Feasible without AI.** Ordered regex rules on `Vacancy.title`
  (LV inflected stems + EN) classify ~96% of all rows; the residual
  ~1.3-4% is long-tail/creative titles ("Pievienojies mūsu
  komandai") that even AI would guess at.
- **Scope decided: IT-focused taxonomy** (~20 categories +
  `other`). The corpus is only ~15-20% IT despite the
  `INFORMATION_TECHNOLOGY` scrape filter — non-IT rows collapse
  into `other` rather than getting their own categories.
- **Design: clone the `Industry` idiom** — a name-keyed
  `Profession` table + `VacancyProfession` through-table,
  populated at scrape time inside `_build_vacancy` and
  bulk-inserted with `ignore_conflicts=True` next to the existing
  M2M writes. Backfill via a standalone management command — no
  HTTP needed, stored titles suffice.
- **Ordering is load-bearing**: 91% of rows match ≥2 patterns.
  Rules are an ordered list with explicit precedence
  (driver-before-manager etc.), not a set.

## 1. Data findings (prod, read-only)

Dataset: 49,350 `Vacancy` rows; 47,969 with a title (1,381 legacy
rows have `title=NULL`, `state=''`). `state` is unmaintained —
`CREATED` 11,683 / `'UPDATED'` 36,286 (stringified-tuple legacy
artifact) — so "active" means `last_seen`/`application_deadline`,
not `state`. `first_seen` spans 2024-08-27 → 2026-10-27.

Existing dimensions don't help: `Industry` holds raw cv.lv
category ids (only `"it"` is readable, 9,002 links); `Keyword`
(109 rows) is a tech/management hint bag, not a taxonomy.

### Proposed IT-focused taxonomy (measured title-only counts)

| # | Category (`Profession.name`) | Example rules | n |
|---|---|---|---:|
| 1 | `frontend-developer` | `front-?end`, react/angular/vue + dev/izstrādātājs | 222 |
| 2 | `backend-developer` | `back-?end` | 261 |
| 3 | `fullstack-developer` | `full-?stack` | 386 |
| 4 | `mobile-developer` | ios/android/mobile + dev, swift/kotlin/flutter | 133 |
| 5 | `software-developer` (generic) | `programmētājs`, `izstrādātājs`, developer, software engineer | 1,301 |
| 6 | `qa-engineer` | `qa`, `testētājs`, test automation | 478 |
| 7 | `data-engineer` | data engineer, `datu inženieris`, dwh, etl | 168 |
| 8 | `data-scientist` | data scien, machine learning, ai engineer, llm | 131 |
| 9 | `data-analyst` | data analyst, `datu analītiķis`, bi analyst | 276 |
| 10 | `devops-engineer` | devops, sre, platform/cloud engineer | 299 |
| 11 | `sysadmin` | `sistēmu/datorsistēmu/datortīklu administrators`, system/network admin | 295 |
| 12 | `it-security` | `it/informācijas drošības`, security engineer, cybersecurity | 189 |
| 13 | `it-architect` | solution/software/technical/data architect, `risinājumu/sistēmu/tehnoloģiju arhitekts` | ~115 |
| 14 | `it-consultant` | sap, erp, crm, salesforce, `it konsultants` | 296 |
| 15 | `it-support` | `it atbalsta`, it support, service desk, `lietotāju atbalsta` | 378 |
| 16 | `ux-designer` | ui/ux, ux/product designer | 119 |
| 17 | `product-manager` | product owner/manager, `produktu vadītājs` | 445 |
| 18 | `project-manager` | `projektu/a vadītājs`, project manager/coordinator | 2,573 |
| 19 | `tech-lead` | tech/team/engineering lead, `izstrādes vadītājs` | 304 |
| 20 | `it-manager` | `it vadītājs`, it nodaļas vadītājs, cio | 131 |
| 21 | `business-analyst` | `sistēmanalītiķis`, `biznesa analītiķis`, business analyst | ~500 |
| 22 | `executive` | ceo/cto/cfo, chief, founder, `īpašnieks`, `valdes loceklis`, `direktors` | 581 |
| 23 | `manager` (generic) | `vadītājs`, manager, `pārzinis`, head of, supervisor | 2,592 |
| 24 | `intern` | `prakse`, `praktikants`, intern, `stažieris` | 176 |
| 25 | `other` | catch-all for everything unmatched | ~37,000 |

IT-tagged total ≈ 9,000-10,000 vacancies (~20%); `manager`,
`project-manager`, `executive`, `intern` overlap into non-IT rows,
which is fine — they're still meaningful filters.

### Precedence rules (must be ordered)

- **Driver before manager**: `auto/kravas/iekrāvēja vadītājs`,
  `šoferis` (328 rows) → `other` (driver is out of IT scope), then
  bare `vadītājs` (7,864) → `manager`.
- **Sysadmin before office-admin**: `sistēmu/datorsistēmu
  administrators` → `sysadmin`; bare `administrators` → `other`.
- **IT architect before building architect**: `risinājumu/
  sistēmu/tehnoloģiju/data arhitekts` → `it-architect`; bare
  `arhitekts` (124) → `other`.
- **Infosec before security-guard**: `it/informācijas drošības`
  → `it-security`; `apsargs`, `drošības inspektors` → `other`.
- **Specific before generic**: `projektu vadītājs` →
  `project-manager` even when compounded (`pārdošanas projektu
  vadītājs`); `biznesa/sistēmanalītiķis` → `business-analyst`
  before generic `analītiķis`/`speciālists` → `other`.

### Normalization before matching

Strip gender/seniority noise so patterns stay short: `/-a`,
`/-e`, `(m/f/d)`, `(vīr./siev.)`, and seniority words (`vecākais`,
`jaunākais`, `senior`, `junior`, `lead`). Seniority is a possible
future second axis — out of scope here.

## 2. Model changes (`fetcher/models.py`)

Clone the `Industry`/`VacancyIndustries` pair:

```python
class Profession(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True)


class VacancyProfession(models.Model):
    vacancy = models.ForeignKey('Vacancy', on_delete=models.CASCADE)
    profession = models.ForeignKey('Profession', on_delete=models.CASCADE)

    class Meta:
        unique_together = (('vacancy', 'profession'),)
        db_table = 'fetcher_vacancy_professions'
```

Plus `professions = models.ManyToManyField('Profession',
through='VacancyProfession')` on `Vacancy`.

M2M (not a CharField/FK) keeps the app's taxonomy idiom —
name-keyed rows, through-tables, name-based filter params — and
leaves room for future multi-tagging (e.g. fullstack →
frontend+backend). V1 classifier emits at most one category per
vacancy (`other` when nothing matches), so every titled vacancy
gets exactly one row; `NULL`-title legacy rows get none.

One migration; **applied to prod manually by the maintainer**
(project rule — ship the file, run locally with
`DATABASE_URL=sqlite:///db.sqlite3`).

## 3. Classifier (`fetcher/professions.py`, new)

Mirror `tv_programs/classification.py`: a pure, testable module —
no ORM, no I/O.

```python
PROFESSION_RULES: list[tuple[str, tuple[str, ...]]]
# ordered: first match wins

def normalize_title(title: str) -> str: ...
def classify(title: str, content: str = '') -> str:  # 'other' default
```

`content` (the `_extract_searchable_content` blob) is accepted
but unused in v1 — reserved as a tiebreaker for compounds later.
Rules table encodes the precedence in §1 verbatim; each entry is
`(profession_name, patterns)` compiled case-insensitively with
`\b` boundaries on the normalized title.

## 4. Scrape-pipeline integration (`fetcher/scraper.py`)

- `__init__` (~line 74): `self._profession_cache = {}` +
  `_profession_named(name)` helper cloning `_industry_named`
  (455-462).
- `_build_vacancy` (485-604): after the `_pending_keywords` block
  (~597), `vacancy._pending_professions =
  [self._profession_named(classify(title))]` using the already-
  computed `searchable_content`.
- `create_or_update_resources` (606-760): transfer
  `_pending_professions` onto existing rows (~662) and add a third
  through-row bulk INSERT (`VacancyProfession`,
  `ignore_conflicts=True`) in the 722-740 block.
- `refetch_vacancies` rides free: `_build_vacancy` produces
  `_pending_professions` and `_replace_links`/`_apply_fresh`
  (429-479) swaps through-row sets — extend to cover the new
  relation so detail-page refetches re-tag.

## 5. Backfill command

`fetcher/management/commands/classify_vacancy_professions.py` —
plain `BaseCommand` à la `reclassify_tv_programs.py` (NOT
`BaseRefetchCommand`, which hard-codes `ad_id`/`link`):

- `--dry-run` (report per-category counts, no writes),
  `--batch-size` (default 500), `--limit`, `--ids`,
  `--reclassify` (re-tag rows that already have a profession).
- Upserts `Profession` rows from `PROFESSION_RULES` keys
  (idempotent — admin edits/additions afterwards are never
  clobbered), iterates titled `Vacancy` rows, syncs
  `VacancyProfession` through-rows in bulk.
- **No HTTP** — runs entirely on stored `title`s, safe against
  prod read-only credentials.

## 6. API (`fetcher/api.py`)

- `VacancyOut` (57-86): `professions: List[str]`;
  `VacanciesOut` (~100): `professions: List[str]` option list.
- `list_vacancies` (278-371): `include_professions` /
  `exclude_professions: List[str] = Query([])` mirroring
  industries (295-307); `prefetch_related('professions')` (342).
- `SavedVacancyFilter` + `SavedFilterIn` +
  `_check_saved_filter_names` (231-249, 536-565):
  `include_professions`/`exclude_professions` JSON lists —
  needs a small model migration for the two new JSON fields.
- Regen: `python manage.py export_openapi_schema --output
  frontend/openapi.json` && `cd frontend && npm run gen:types`
  (CI drift check will fail otherwise).

## 7. Frontend (`frontend/src/vacancies/`)

- `api.ts` (42-82): `professions`/`excludeProfessions` params on
  `VacancyParams`/`fetchVacancies`.
- `VacancyList.tsx`: `Draft`/`applyFilters`/param parsing
  (15-115); a Profession checkbox block cloned from the
  industries block (185-214); badge cell cloned from
  `industry-tag` (427-433).
- `SavedFiltersBar`: applied/staged props for the new lists.
- `npm run typecheck`, `npm test`, `npm run build`.

## 8. Admin (`fetcher/admin.py`)

Register `Profession` (list display: name, vacancy count).
Optionally register `Industry`/`Keyword`/`Vacancy` too — none are
registered today.

## 9. Tests (`fetcher/tests.py`)

- Classifier unit tests: parametrized titles covering every rule
  + the precedence pairs (driver-vs-manager, sysadmin-vs-office,
  it-vs-building architect, infosec-vs-guard, compound
  `pārdošanas projektu vadītājs`).
- `_build_vacancy`/`create_or_update_resources` assertions via
  the existing `API_CONFIG`/`response()` helpers (44-110).
- Command test: `--dry-run` reports counts; real run creates
  `Profession` + through-rows idempotently.
- Run only `python manage.py test fetcher` (sqlite per project
  rule).

## 10. Open questions

1. **`other` as a stored row vs no row** — plan stores `other`
   explicitly (symmetric include/exclude filtering, measurable
   coverage). Alternative: leave untagged and treat "no
   profession" as other.
2. **Multi-tag compounds** — v1 first-match-only. If wanted,
   `classify` can return a top-2 list (e.g. `pārdošanas projektu
   vadītājs` → project-manager + sales, once sales exists).
3. **Rules in DB?** — `PROFESSION_RULES` lives in code (like
   `industry_mapping` lives in config). A `ProfessionRule` table
   would make patterns admin-editable; defer unless taxonomy
   churn proves painful.
4. **AI fallback** — residual `other` bucket (~600 titled rows
   after rule tuning) could get an `ai_providers` AIJobSpec pass
   later; the JobClient infra already supports it. Not needed for
   v1.
5. **Seniority axis** — `junior/senior/lead` extracted during
   normalization could become a second field later.

## File checklist

| File | Change |
|---|---|
| `fetcher/models.py` | `Profession`, `VacancyProfession`, M2M, `SavedVacancyFilter` fields |
| `fetcher/migrations/00NN_*.py` | one generated migration |
| `fetcher/professions.py` | new — `PROFESSION_RULES`, `normalize_title`, `classify` |
| `fetcher/scraper.py` | cache+helper, `_pending_professions`, bulk INSERT |
| `fetcher/management/commands/classify_vacancy_professions.py` | new backfill command |
| `fetcher/management/commands/refetch_vacancies.py` | extend `_replace_links`/`_apply_fresh` |
| `fetcher/api.py` | schema + filter params + saved-filter plumbing |
| `fetcher/admin.py` | `Profession` registration |
| `fetcher/tests.py` | classifier + pipeline + command tests |
| `frontend/openapi.json`, `frontend/src/vacancies/{api.ts,VacancyList.tsx,...}` | regen + filter UI |
