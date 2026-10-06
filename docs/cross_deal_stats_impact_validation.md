# Cross-Deal Duplicate Stats-Impact Validation

**Date:** 2026-10-05
**Validated by:** Read-only queries against production Aiven PostgreSQL
plus code analysis of `classified_ads/api.py`, `models.py`,
`apartment_scraper.py`, `housing_scraper.py`
**Status:** ⚠️ **Hypothesis partially holds — ad-level stats are clean,
property-level counts and the daily sightings report are inflated**

## Background

Audit finding (see `/tmp/property_match_review_report.md`, §1):
641 "cross-deal" duplicate pairs — the same ss.com `ad_id` exists as a
row in BOTH the rent and the sale ad table, linked to TWO DIFFERENT
canonical property rows (629 apartment pairs over 1,247 distinct
`ApartmentProperty` rows; 12 house pairs over 24 `HouseProperty` rows).
~91% of the apartment rent-side rows are flagged
`is_sale_misclassified=True`.

User hypothesis under test: *"those don't contribute to statistics
because of `is_sale_misclassified`."*

## Read-path audit (`classified_ads/api.py`)

| Endpoint / stat | Manager used | Verdict |
|---|---|---|
| `/ads/` ads table (api.py:571-636) | `model.objects` | ✅ Clean |
| `/regions/{id}/ads/` (api.py:799-856) | `model.objects` | ✅ Clean |
| Region stats `total_ads` (api.py:486-487, 546-547) | `objects` + `Count('id')` | ✅ Clean |
| Region stats `avg_price_per_sqm`, `avg_size`, `avg_days_tracked` | `objects` aggregate | ✅ Clean |
| Region stats `total_properties` (`_linked_property_stats` / `_distinct_linked_property_count`, api.py:390-430) | `objects` for ad→prop ids | ⚠️ Inflated, small (≤19 units/region row in the 30d window) |
| Region stats `avg_days_on_market` (api.py:406-417) | prop ids from `objects`; sightings via raw sighting managers (`ad__property__in`) | ⚠️ Distorted — split history understates per-unit days |
| `/sightings/` daily report (api.py:862-959) | sighting `objects`, no ad-flag filter | ⚠️ Inflated by design — raw scrape telemetry |
| `/properties/` list (api.py:962-1005) | `Property.objects` — no custom manager, all rows | ⚠️ Inflated ~3.0% (apartments) |
| `/properties/` `rent_ad_count`/`sale_ad_count` | `Count('rent_ads')` SQL join — ignores the ad managers' flag filters | ⚠️ Counts hidden/misclassified ads (verified: prop 100 annotates `rent_ad_count=1` while `prop.rent_ads.count()==0`) |
| `/properties/{kind}/{pk}/` detail + `days_on_market` (api.py:1013-1062, models.py:99-138) | `linked_ads()` → `all_objects` | ✅ By design, but `days_on_market` understates merged truth |
| Django admin (`admin.py`) | `all_objects` everywhere | ✅ By design |
| Scraper `_write_sightings` (apartment_scraper.py:526-556, housing_scraper.py:~480-535) | `all_objects`, no flag check | Sightings accrue on hidden/misclassified ads — feeds the report above |

Frontend (`frontend/src/classified_ads/`): `StatsResultsTable.tsx`
renders `total_ads`, `total_properties`, `avg_days_tracked`,
`avg_days_on_market`; `DailySightings.tsx` renders the per-day
`apartment_rent`/`apartment_sale`/… counts. No additional filtering
client-side — what the API returns is what the UI shows.

## Quantified impact

### a) Ad level — hypothesis holds

`ApartmentForRent.objects` (CleanRentalManager) excludes both
`is_sale_misclassified` and `is_hidden`:

- `ApartmentForRent`: 6,564 visible vs 11,680 total rows
  (5,116 excluded).
- 650 rent-table rows share an `ad_id` with a sale-table row:
  **601 misclassified**, 134 hidden, only **48 visible** in `objects`.
  All 650 carry `property_match_status` auto/manual (i.e. linked).
- In the default 30-day stats window: 3,068 visible rent ads; 258
  misclassified rows excluded.

Caveat — **the flag coverage is incomplete**: 48 apartment rent rows
and 4 house rent rows of cross-deal pairs are still visible in
`objects` (not flagged misclassified, not hidden). `HouseForRent` has
no `is_sale_misclassified` field at all — house cross-deal rent twins
can only be excluded via `is_hidden` (8 of 12 are hidden; the other 4
appear in rent ads tables and rent stats with the sale price shown as
a monthly price).

### b) Property level — hypothesis fails (~3% inflation)

Every pair = two property rows for one physical unit.

- `ApartmentProperty` total: **21,040 rows**. Confirmed-duplicate pairs
  ≈626 → **~626 redundant rows ≈ 3.0% inflation** of the property
  list (`/properties/`, `total_count`, district filter options).
- `HouseProperty` total: 5,653 rows; 12 pairs → ~12 redundant rows
  ≈ **0.2%**.
- Of the 1,247 apartment props in pairs, **580 have ZERO visible
  linked ads** — invisible to all `objects`-based stats, but still
  listed in `/properties/` and accruing sightings.
- Region-stats `total_properties` (distinct linked props among
  visible ads): a pair double-counts only when BOTH twin props have a
  visible ad in the window+region — **45 apartment pairs all-time,
  19 pairs in the default 30-day window** (combined deal type; RENT
  only: 1; SELL only: 1). Houses: 0 in the 30d window. Against
  ~11,911 distinct linked apartment props this is **≤0.4%** — small,
  but non-zero.
- All 629 pairs share the same root parent region (615 differ only at
  leaf level), so the 19 double-counts land inside the selected
  parent's `total_properties`; on the sub-region children view they
  can inflate two different child rows.

### c) Daily sightings report — inflated by design

`_write_sightings` uses `all_objects` and never checks
`is_hidden`/`is_sale_misclassified` — flagged ads keep accruing one
sighting row per day while ss.com still lists them.

Last 30 days:

| Table | Total sightings | On invisible-to-`objects` ads | On cross-deal rows |
|---|---|---|---|
| ApartmentForRentSighting | 36,475 | 9,508 (26.4%) | 2,910 (8.0%) |
| ApartmentForSaleSighting | 51,282 | — (hidden only: 10.3%) | 7,710 (15.0%) |
| HouseForRentSighting | 8,072 | 1,568 (19.4%) | 31 (0.4%) |
| HouseForSaleSighting | 21,186 | 5,835 (27.5% hidden) | 54 (0.3%) |

- 3,673 (10.1%) of apartment-rent sightings are on misclassified ads;
  2,560 of those are on cross-deal rows.
- Each active shared listing adds **1 to `apartment_rent` AND 1 to
  `apartment_sale`** on the same day — `apartment_total` and
  `grand_total` double-count it (~2.9k such double-counted sighting
  days per 30d window).
- This is raw scrape telemetry (a sighting did happen), but as a
  "distinct active listings" proxy the rent column overstates reality
  by ~8-10%.

### d) `days_on_market` — split, not inflated per se

`BaseProperty.days_on_market` and `_linked_property_stats` union
sighting dates across ALL linked ads (`all_objects` semantics —
misclassified sightings do count). Because the pair splits one unit's
history across two property rows:

- Median sighting-date overlap between twin props: **10 days**
  (mean 11.7) — the listing is scraped in both categories on the same
  days.
- Sum of per-prop day counts: 24,198 vs merged union 16,954 → the
  split shows ~18.9 avg days/prop vs **26.4 days/unit merged**
  (~29% understatement per affected unit, in addition to counting it
  twice in `total_properties`).
- The prop holding the rent-side row misses a median **10 days** vs
  the merged view (mean 10.8, max 42); the sale-side prop misses
  median 1 (mean 3.9). The misclassified row's ongoing sightings keep
  padding the phantom prop's `last_seen`/`days_on_market` instead of
  the real one.

## Recurrence (verified 2026-10-06)

This validation is a point-in-time snapshot — the underlying cause is
**still live**: 48 apartment + 1 house cross-deal pairs formed in the
7 days before this note. Every new `is_sale_misclassified` rent row
keeps minting a phantom property until the matcher twin-shortcut
(`docs/property_conflation_prevention_plan.md`) and the relink pass
(`docs/classified_ads_remediation_plan.md` WS2) land; expect the
property-level inflation to keep growing ~3% per ~2 months at the
current rate.

## Verdict vs. hypothesis

| Claim | Result |
|---|---|
| "Misclassified rent rows don't reach ad-level stats" | ✅ True — `objects` excludes them; `total_ads`, price/size avgs, `avg_days_tracked`, ads tables are clean |
| "…so the cross-deal pairs don't contribute to statistics" | ⚠️ Mostly false at property level: ~626 phantom property rows inflate `/properties/` ~3.0%, `total_properties` by ≤19 rows per region stat (≤0.4%), split `days_on_market` (~29% understatement per affected unit), and their rent-side rows keep feeding the daily sightings report (~8-10% of the rent column, double-counted in totals) |

## Recommendation

The correct fix is **merging, not hiding** — the rows are already
hidden from `objects`:

1. For the ~626 confirmed-duplicate apartment pairs (and analogous
   house pairs), re-link the rent-side ad row to the sale twin's
   property (or merge the two property rows and
   `refresh_from_ads()`). This removes the phantom from
   `/properties/`, fixes `total_properties`, and reunifies
   `days_on_market`. The 10 CONFLATED and 5 ATTRIBUTE_CONFLICT pairs
   need the special handling described in the review report.
2. Optionally add an `is_sale_misclassified`-style flag or relink
   pass for `HouseForRent` (4 visible cross-deal twins pollute house
   rent tables/stats today).
3. Sightings: leave as-is (they are factual telemetry) — or annotate
   the `/sightings/` UI so users know flagged ads are included.
