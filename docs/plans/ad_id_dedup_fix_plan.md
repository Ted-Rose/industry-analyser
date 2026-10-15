# Ad ID Deduplication Fix Plan

## Executive Summary

**Problem**: ~19,900 duplicate rows (~46% of all rows) across the four
`classified_ads` tables. The same ss.com ad is stored multiple times
under different `ad_id` values.

**Root cause**: `ad_id` is built as `tr_<row_id>` + concatenated
listing-cell text (address, rooms, size, floor, project). The `tr_`
prefix alone is ss.com's stable, globally-unique ad id — everything
appended to it is volatile, so each variant mints a new `ad_id` and
defeats `unique=True`, `remove_redundant_results()`, and
`update_conflicts`/`ignore_conflicts`.

**Solution**: Use `str(row_id)` (the `tr_` id) alone as `ad_id`, plus
a one-time data migration that merges duplicate rows and consolidates
their sightings.

**Impact**: No schema change required (`ad_id` stays `CharField`).
Requires a data migration script and a DB backup before running it.

---

## Problem Statement

### Duplicate counts (measured 2026-09-29, production DB)

Grouped by the stable ss.com row id embedded in `ad_id`
(`substring(ad_id from 'tr_[0-9]+')`):

| Table | Rows | Distinct ads | Excess dup rows |
|---|---|---|---|
| `classified_ads_apartment_rent` | 17,975 | 10,656 | 7,319 (41%) |
| `classified_ads_apartment_sale` | 23,279 | 11,209 | 12,070 (52%) |
| `classified_ads_house_rent` | 2,152 | 2,072 | 80 |
| `classified_ads_house_sale` | 5,261 | 4,862 | 399 |

All `ad_id`s match `^tr_[0-9]+` — no malformed ids.

### How the same ad gets multiple `ad_id`s

Example — one ad (`tr_57014547`, link `.../jurmala/dzintari/bmhxh.html`)
stored 4 times:

```
tr_57014547Turaidas 2731071/2New          size=107  €950
tr_57014547DzintariTuraidas 2731071/2New  size=107  €950
tr_57014547DzintariTuraidas 273821/2New   size=82   €850
tr_57014547Turaidas 273821/2New           size=82   €850
```

Three distinct variance sources:

1. **Overlapping region pages render the address cell differently.**
   The same ad appears on parent-region and sub-region listing pages;
   `cells[3]` gets a district/town prefix on one but not the other
   (`'DzintariTuraidas 27'` vs `'Turaidas 27'`,
   `'BēneSniķeres 2B'` vs `'Bēnes pag.'`).
   Measured: 1,330 rent / 2,302 sale `tr_` ids span >1 `region_name`.

2. **Language-variant links and cells.** The same row's first `<a>`
   href is sometimes `/msg/en/...`, sometimes `/msg/lv/...` (all
   Region URLs are `/en/`; ss.com serves inconsistent href languages),
   and cell text differs by language (`New` vs `Jaun.`, `103-th` vs
   `103.`). Most dup groups span >1 link: 4,881 (rent) / 7,306 (sale).

3. **Seller/site edits.** Size `107→82`, `16→160`, project
   `103.`→`Specpr.` — each edit produces a new `ad_id`.

### Knock-on effects

- Every "new" `ad_id` triggers an extra enrichment HTTP request
  (wasted requests to ss.com).
- Sightings fragment across dup rows → `days_active` undercounts.
- 6,945 `tr_` ids (2,044 identical links) exist in BOTH rent and sale
  apartment tables — ads cross-posted/moved between `hand_over/` and
  `sell/`. Probably legitimate; **out of scope** for this fix.

### Secondary bugs found during investigation

- `apartment_scraper.py` `remove_redundant_results()` uses
  `ApartmentForSale.objects` (excludes `is_hidden=True`) instead of
  `all_objects` — hidden ads are re-enriched every run.
- `ApartmentForSale` `_write_sightings()` also uses `objects` —
  sightings silently skipped for hidden ads.
- Same pattern in `housing_scraper.py`: `HouseForRent.objects` /
  `HouseForSale.objects` in `remove_redundant_results()` and
  `_write_sightings()` exclude `is_hidden=True` rows.
- `housing_scraper.py` uses `ignore_conflicts=True` on insert, so
  legitimate listing edits (price changes) are never reflected —
  inconsistent with apartments' `update_conflicts=True`.

## Solution Design

### Phase 1: Stabilize `ad_id` in both scrapers

**`classified_ads/apartment_scraper.py`** (`parse_results`, ~line 284):

```python
# Before
ad_id = str(
    str(row_id)
    + cells[3]
    + cells[4]
    + cells[5]
    + cells[6]
    + cells[7]
)

# After
ad_id = str(row_id)
```

**`classified_ads/housing_scraper.py`** (`parse_results`, ~line 220):
same change — `ad_id = str(row_id)`.

The `tr_` id is already unique per ad across all regions, languages,
and edits. `remove_redundant_results()` then recognizes returning ads
regardless of which region page surfaced them or whether the listing
text changed; `update_conflicts` refreshes changed fields on the same
row and `_write_sightings()` records the recurrence.

### Phase 2: Use `all_objects` where hidden rows matter

**`apartment_scraper.py`**:

- `remove_redundant_results()` (~line 426):
  `ApartmentForSale.objects` → `ApartmentForSale.all_objects`
  (rent already uses `all_objects`).
- `_write_sightings()` SELL branch (~line 556):
  `ApartmentForSale.objects` → `ApartmentForSale.all_objects`.

**`housing_scraper.py`**:

- `remove_redundant_results()` (~lines 302, 308):
  `HouseForRent.objects` → `HouseForRent.all_objects`,
  `HouseForSale.objects` → `HouseForSale.all_objects`.
- `_write_sightings()` (~lines 475, 501): same for both branches, so
  hidden ads still accumulate sightings.

### Phase 3: `update_conflicts` for houses (consistency fix)

`housing_scraper.py` `create_or_update_resources()` (~lines 458, 465)
uses `ignore_conflicts=True`. Once `ad_id` is stable, a price edit on
an existing ad would be silently dropped. Switch both bulk_creates to
the apartments pattern:

```python
HouseForRent.all_objects.bulk_create(
    rent_ads,
    update_conflicts=True,
    unique_fields=['ad_id'],
    update_fields=[
        'comment', 'link', 'price_per_sqm',
        'monthly_price', 'monthly_price_per_sqm',
        'total_price_120m', 'price_per_sqm_120m',
        'total_price', 'post_date', 'last_seen',
        'seller',
    ],
)
```

(and the analogous `HouseForSale` version.) Also switch
`HouseForRent.objects.bulk_create` → `all_objects` so hidden rows are
updated rather than skipped.

Note: `update_conflicts` requires `unique_fields` to match a real
unique constraint — `ad_id` is `unique=True`, so this works.

### Phase 4: One-time data migration (merge duplicates)

New script `scripts/dedupe_classified_ads.py` (standalone, like
`scripts/fix_apartment_addresses.py`) or a management command with
`--dry-run` and `--batch-size`. For each of the four tables:

1. Group rows by `tr_` prefix (`ad_id ~ '^tr_[0-9]+'`, extract prefix).
2. For each group with >1 row pick a **canonical row**:
   - Prefer the row with the most sightings (richest history);
     tie-break by earliest `first_seen`.
   - Carry `first_seen = min(first_seen across group)` and
     `last_seen = max(last_seen across group)` onto the canonical row.
3. Reassign sightings: insert `(canonical_ad_id, seen_on)` for every
   sighting on dup rows with `ignore_conflicts=True`
   (`unique_together(ad, seen_on)` dedupes overlaps), then the dup
   sightings are removed by FK cascade when dup rows are deleted.
4. Rewrite the canonical row's `ad_id` to the bare `tr_` prefix so
   future scrapes match it.
5. Delete the non-canonical rows.
6. Wrap each group in a transaction; log a summary per table.

Ordering note: the code change and the migration are independent —
old composite `ad_id`s are grouped by the same `tr_` prefix as new
bare ones, so the script cleans up stragglers either way. Run the
script soon after deploy to limit a transient dup wave.

**Do NOT run `makemigrations`/`migrate`** — no schema change. Per
project guardrails, the user runs the script themselves after taking
a backup.

### Phase 5: Optional — canonicalize `link` language

`link` will still flip between `/msg/en/` and `/msg/lv/` across
scrapes (cosmetic; `update_conflicts` overwrites it). If a stable
`link` is wanted, normalize the href in `parse_results` to one
language, e.g. `link.replace('/msg/lv/', '/msg/en/')`. Both forms
serve the same ad page. Low priority — dedup no longer depends on it.

## Implementation Steps

### Step 1: Backup

```bash
# User runs — prod Postgres
pg_dump ... > backup_before_ad_id_dedup.sql
```

### Step 2: Scraper changes

1. `apartment_scraper.py`: `ad_id = str(row_id)`; `objects` →
   `all_objects` in `remove_redundant_results()` and SELL
   `_write_sightings()`.
2. `housing_scraper.py`: `ad_id = str(row_id)`; `objects` →
   `all_objects` in `remove_redundant_results()` and both
   `_write_sightings()` branches; `bulk_create` → `all_objects` +
   `update_conflicts` with `unique_fields=['ad_id']`.

### Step 3: Verify

```bash
python manage.py check
python manage.py test classified_ads
```

Optional small local scrape to sanity-check (`--max-pages 1`) — hits
the live site, keep it minimal.

### Step 4: Data migration

1. Write `scripts/dedupe_classified_ads.py` with `--dry-run`.
2. User runs `python scripts/dedupe_classified_ads.py --dry-run`,
   reviews counts, then runs it for real.
3. Run `python manage.py validate_sightings` afterwards.

### Step 5: Post-fix verification queries

```sql
SELECT count(*),
       count(DISTINCT substring(ad_id from 'tr_[0-9]+'))
FROM classified_ads_apartment_rent;
-- count(*) should equal distinct count

SELECT count(*) FROM classified_ads_apartment_rent
WHERE ad_id !~ '^tr_[0-9]+$';
-- 0 rows; all ad_ids are bare tr_ ids
```

Repeat for the other three tables. Re-run after the next scheduled
scrape — the numbers should stay equal (no new dupes).

## Rollback Plan

1. Code changes: `git revert <commit>`.
2. Data migration is **not** lossless-reversible (dup rows are
   deleted; sightings are merged onto canonical rows). Restore from
   the Step 1 `pg_dump` backup if needed.
3. Deploying the reverted code without restoring the DB is also safe:
   composite `ad_id`s would simply resume minting dupes — no crash.

## Risks & Notes

- **Transient dup window**: between code deploy and running the dedup
  script, a scraped ad with an old composite `ad_id` produces one new
  bare-`tr_` row per ad. The dedup script cleans these (it groups by
  prefix regardless of suffix).
- **`tr_` id reuse**: assumed stable and never recycled by ss.com —
  consistent with all observed data.
- **Cross-posted rent/sale ads** (6,945 `tr_` ids in both tables):
  untouched by this fix — different models, arguably separate
  listings. Revisit separately if undesired.
- **`remove_redundant_results` batching**: incoming `ad_id__in`
  lookups now match more often (returning ads), which is the intended
  behavior — sighting writes already dedupe via `ignore_conflicts`.

## Success Criteria

- `rows == distinct tr_ ids` for all four tables post-migration.
- No new `ad_id` containing anything but `tr_<digits>` after deploy.
- `days_active` on surviving rows equals total sightings previously
  spread across their dup group (verify a few known groups, e.g.
  `tr_57014547`).
- Next scheduled scrape completes with `remove_redundant_results`
  filtering returning ads instead of re-creating them (check logs for
  reduced "Saved N ads" counts vs. sighting counts).
