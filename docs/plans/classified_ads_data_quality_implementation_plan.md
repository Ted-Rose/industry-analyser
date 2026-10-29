# classified_ads data-quality fix — implementation plan

Sequenced implementation plan for fixing classified_ads data
quality so per-region, per-house-type rent-vs-buy analysis is
trustworthy. Built from a live production audit (2026-10-29);
complements `classified_ads_remediation_plan.md` (WS1-WS4) and
`property_conflation_prevention_plan.md` — this file is the
actionable, verified-numbers version.

Business goal: identify regions and house types where purchase
price is low relative to achievable rent.

## Verified live numbers (2026-10-29, prod)

Row counts (visible `objects` / `all_objects`): AptRent
8861/14231; AptSale 8448/13990; HouseRent 1550/2632;
HouseSale 2728/5927.

- F1 evidence: 1673 ad_ids in BOTH HouseForRent+HouseForSale;
  947/1550 (61%) of VISIBLE house-rent rows hold sale prices
  (avg EUR 75,915/mo, median 20,000; true avg ~1,514, median
  ~1,200). 568/1550 visible rows contain LV sale keywords.
- F4 evidence: 805 cross-deal twin pairs (786 apt + 19 house),
  ~49/wk growth; ~3% property-count inflation; ~29%
  days_on_market understatement on affected units.
- F3 evidence: is_hidden rows still sighted in last 14d —
  HouseSale 1463, AptSale 1177, HouseRent 383, AptRent 478.
- F2 evidence (visible junk): size<=5 -> HouseRent 16 +
  HouseSale 21 + AptRent 1; ppsqm=0 -> 4; AptSale ppsqm<10 ->
  49; HouseSale ppsqm>20k -> 9; floor>max_floor -> 120;
  2 AptRent outliers (EUR 9.9k, EUR 11.4k monthly).
- F6 evidence: 146 malformed ad_ids still visible (70
  HouseSale); 35 frozen same-link groups (house side).
- Coverage: 54-63 of last 90 days scraped per table;
  `weekly:mon` cadence + 6-day GCP cooldown is the cause
  (scheduler runs daily already).
- post_date NULL: ~50-52% of visible house rows; +2/+3h
  naive-UTC skew; means last-renewal.
- Match coverage: ~95% of visible ads linked (auto/manual);
  zero 'unmatched' among visible.
- Analysis feasibility: apartments 60 regions with >=20 rent +
  >=20 sale; houses only ~6 regions after excluding
  dual-listed rent rows; same-unit rent+sale pairs: 399 apt,
  113 house.

## Conventions to respect

- 79-char lines; `logging.getLogger('classified_ads')`.
- `objects` managers hide `is_hidden` (and, for rent models
  after F1, `is_sale_misclassified`); use `all_objects` in
  admin/refetch/data-fix code.
- Prefer flag-and-filter (`is_hidden`, `is_sale_misclassified`)
  over deletes. Every prod-affecting command gets `--dry-run`.
- Migration files are committed; prod `migrate` is MANUAL
  (avnadmin .env is prod — never run migrate/tests without
  `DATABASE_URL=sqlite:///db.sqlite3`).
- New management commands subclass `BaseRefetchCommand`
  (refetch-type) or `BaseCommand` with `--dry-run` precedent
  (`link_ads_to_properties`, `validate_sightings`).
- One-off data-fix scripts live in `scripts/` (pattern:
  `scripts/hide_duplicate_link_ads.py` — pk-logged,
  `--dry-run`, `last_seen=F('last_seen')` to avoid auto_now
  bumps).

---

## F1 — House `is_sale_misclassified` flag + backfill (WS1)

- Add `is_sale_misclassified = BooleanField(default=False)` to
  `HouseForRent` (concrete class — mirror `ApartmentForRent`,
  `models.py:347`); migration.
- New `CleanHouseRentalManager` filtering
  `is_sale_misclassified=False, is_hidden=False` on
  `HouseForRent.objects` (mirror `models.py:333-339`).
- New command `flag_house_crosslistings --dry-run`: flag every
  `HouseForRent.all_objects` row whose `ad_id` exists in
  `HouseForSale.all_objects` (~1673 ids), plus the apartment
  heuristic (`apartment_scraper.py:32-50`) for keyword-only
  rows (~568 visible); log counts.
- Ingest: `HousingAdScraper` sets the flag via cross-deal
  ad_id lookup + heuristic; add flag to `bulk_create`
  `update_fields` (`housing_scraper.py:451-457`).
- Admin: `list_display`/`list_filter`/`list_editable`
  (admin.py ~266-299).
- Impact: house-rent median EUR 20k -> ~1.2k. Reversible.
- Prod ops: manual `migrate` + `flag_house_crosslistings`
  (dry-run first).

## F2 — Junk-row quarantine + ingest guards

- `scripts/quarantine_junk_ads.py` (`--dry-run`): `is_hidden`
  on size<=5 (38), ppsqm=0 (4), AptSale ppsqm<10 (49),
  HouseSale ppsqm>20k (9), floor>max_floor (120 apt),
  2 named AptRent outliers. Pk-logged like
  `hide_duplicate_link_ads.py`.
- Ingest guards in `housing_scraper.py` `parse_results`:
  skip size<=0; flag/keep-but-guard size<10. Optional
  `CheckConstraint(size__gt=0)` on house tables.
- Reversible (un-hide). ~260 visible rows quarantined.

## F3 — `reconcile_hidden_ads` command

- `is_hidden=True AND ad_id ~ '^tr_\d+$' AND sightings seen_on
  >= today-14d AND not in a same-link dup group with a visible
  canonical sibling` -> `is_hidden=False`. `--dry-run`, pk
  audit log, `last_seen=F('last_seen')`.
- ~3,501 rows un-hidden; HouseSale visible +49%. Reversible.

## F4 — `relink_property_ads --twin-fix` (WS2)

- For each `ad_id` in both deal tables where
  `rent.property_id != sale.property_id`: re-point rent FK to
  the sale twin's property, `property_match_status='manual'`,
  score 1.0, `refresh_from_ads()` both, delete emptied prop
  via `_vacate_property`/`_delete_if_orphan` machinery
  (`link_ads_to_properties.py:254-280`). Skip attribute-
  conflict pairs (>15% size / rooms disagreement -> review
  list). `--dry-run` default-safe.
- ~805 pairs consolidated. FK moves reversible via audit log;
  emptied-prop deletion is destructive-adjacent (derived
  data). After F1 and F9.

## F5 — Region stats: active-in-window

- `api.py` `_compute_apartment_region_stats` /
  `_compute_house_region_stats` (:448-565) + `region_ads_list`
  (:827+): replace `first_seen__date__gte/lte` with a
  sightings-EXISTS subquery (`seen_on` in [date_from,
  date_to]); use `all_objects`-semantics where appropriate so
  hidden-but-live ads' sightings still count correctly, and
  keep `objects` filtering on returned ad rows.
- Read-path only, fully reversible.

## F6 — House malformed/frozen ad_id residue

- Extend `scripts/hide_duplicate_link_ads.py` (or new
  `--swap-canonical` mode): in the 35 frozen same-link groups,
  un-hide the bare-`tr_` row and hide the visible composite-id
  row; hide remaining ~146 malformed-but-visible ids whose
  link has a clean sibling (70 HouseSale). `--dry-run`.
- Reversible (pk-logged flag swaps).

## F7 — `refetch_house_ads` + re-enrich-if-NULL self-heal

- `HousingAdScraper._parse_detail_for_refetch` (mirror
  `apartment_scraper.py:558-576`) returning post_date, seller,
  floors, land_area_sqm, comment, rooms, house_type (F8).
- New `refetch_house_ads` command on `BaseRefetchCommand`
  (`--filter "post_date__isnull=True" --fields ...`).
- Self-heal: `remove_redundant_results` in BOTH scrapers keeps
  existing rows with `post_date IS NULL` (or `rooms=0` for
  houses) in the enrichment queue instead of dropping them.
- ~6k house rows backfillable. Real HTTP — throttle via
  `BaseScraper.sleep`, never bypass the PoolManager.

## F8 — `house_type` + `rooms` on house models

- Add `house_type CharField(blank=True)` to `BaseHouseAd` +
  migration; populate `rooms` from detail page (today
  hardcoded 0, `housing_scraper.py:205`).
- `HousingAdScraper.enrich_result`: parse `ads_opt` table for
  `Rooms:`/`Istabas:` and `House type:`/`Mājas tips:` (helper
  pattern `apartment_scraper.py:673-687`).
- Expose `house_type` in `AdOut`/`LinkedAdOut`; regen
  `frontend/openapi.json` + `npm run gen:types`.
- Nullable fields, backfilled via F7 run. Reversible.

## F9 — Matcher hardening (WS4 prevention)

- `property_matcher.py`/`link_ads_to_properties._link_ad`:
  (a) twin shortcut — sibling-table ad_id lookup via
  `all_objects`, link to twin's property if hard gates pass;
  (b) conflation alarms demoting auto->candidate (>=2
  apt_nos, overlapping same-deal ads, floor dissent,
  `street_no==''` without decisive evidence, multiple
  surviving candidates); (c) `N-M` street_no split
  (`^\d+-\d+$`); (d) `extract_apartment_no` additions
  (`кв. N`, `apt.`/`flat`, windowed `Nr.`).
- Unit tests in `classified_ads/tests.py` (suite exists,
  ~:1060-1289). Stops ~49 phantom props/week. Reversible.

## F10 — `audit_property_links` command

- Read-only command reporting TWIN_DIVERGED / APTNO_CONFLICT /
  FLOOR_CONFLICT / COEXISTING / BULK_ABSORB flags per
  conflation plan §3c. Produces F14's merge list.

## F11 — Scrape cadence + link scheduling

- `run_all_jobs.py:45-46` `weekly:mon` -> denser cadence
  (e.g. `dom:odd` or mon+thu); schedule
  `link_ads_to_properties` after the scrapes; relax
  `scrape_jobs/runner.py` `recent_scrape_exists(slug, days=6)`
  to match (e.g. days=1). No terraform change — scheduler
  already daily. Fully reversible config.

## F12 — Manager-aware `/sightings/` + `/properties/` counts

- `/sightings/` (api.py:890+): filter sighting counts to
  `ad__is_hidden=False` (+ `ad__is_sale_misclassified=False`
  on rent tables) or return raw+clean columns.
- `/properties/` (api.py:993+): `rent_ad_count`/`sale_ad_count`
  via filtered subqueries instead of raw `Count` join.
- After F1 (house flag exists). Read-path, reversible.

## F13 — Expose `*_120m` + `/regions/rent-vs-buy/` endpoint

- `AdOut` gains `total_price_120m`, `price_per_sqm_120m`
  (rent rows); clarify rent `total_price` semantics in schema.
- New `GET /api/classified-ads/regions/rent-vs-buy/`:
  per-region median `monthly_price_per_sqm` (rent) vs median
  `price_per_sqm` (sale) + price-to-annual-rent ratio +
  n_ads both sides, active-in-window (F5 semantics).
- Regen openapi.json + api-types. Depends on F1/F3/F5 for
  honest inputs (code-wise: after F5).

## F14 — Same-block duplicate-property merge

- `--merge` mode on `relink_property_ads` (or admin action)
  for the ~326 HIGH-confidence clusters F10 surfaces; re-point
  FKs + `refresh_from_ads()` + delete emptied prop.
- DESTRUCTIVE-ADJACENT: merged props can't cleanly unmerge.
  Human-reviewed list only; dry-run mandatory. After F10.

## F15 — `post_date` Europe/Riga parsing

- `apartment_scraper.py:618-624`, `housing_scraper.py:331-334`:
  `timezone.make_aware(naive, ZoneInfo('Europe/Riga'))`.
- Document `post_date` = last-renewal; days-on-market uses
  sightings/first_seen. Historical skew stays (documented).
- Bundle into the F7 scraper PR.

---

## PR slicing (sequential; each PR from fresh master)

| PR | Items | Branch | Notes |
|---|---|---|---|
| 1 | F11 + plan doc | feat/ca-dq-cadence | tiny config PR, ships this file |
| 2 | F1 | feat/ca-dq-house-flag | migration; prod ops listed |
| 3 | F2 | feat/ca-dq-junk-quarantine | script + ingest guards |
| 4 | F3 | feat/ca-dq-reconcile-hidden | command only, prod run manual |
| 5 | F6 | feat/ca-dq-frozen-adids | script extension |
| 6 | F5 | feat/ca-dq-active-in-window | api.py stats |
| 7 | F10 | feat/ca-dq-audit-links | read-only command |
| 8 | F9 | feat/ca-dq-matcher-hardening | matcher + tests |
| 9 | F4 | feat/ca-dq-twin-relink | after F1+F9 merged |
| 10 | F7+F8+F15 | feat/ca-dq-house-refetch | migrations + scraper |
| 11 | F12+F13 | feat/ca-dq-ratio-endpoint | API surface, regen types |
| 12 | F14 | feat/ca-dq-prop-merge | merge mode; destructive-adjacent |

Every PR: `python manage.py check` +
`DATABASE_URL=sqlite:///db.sqlite3 python manage.py test
classified_ads`; API-surface PRs additionally regen
openapi.json + `npm run gen:types` + frontend typecheck.
