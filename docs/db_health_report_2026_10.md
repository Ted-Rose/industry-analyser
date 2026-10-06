# classified_ads — Database Health Report (2026-10-05)

Read-only audit of the production Aiven PostgreSQL against the
dedup/normalization work shipped in commits `a921581` (canonical
properties), `b833b94` (stable `tr_*` ad ids), `763bc58`/`45ca9e8`
(Project model + FK), `c85f79b` (`is_hidden`) and related.

Companion document: `docs/property_match_review_2026_10.md` — the
pair-level duplicate review the numbers below are drawn from.

## Verdict

The schema-level dedup machinery is sound: **every integrity check
passed**. The remaining duplication lives at the property level — the
same physical unit split across multiple `*Property` rows — plus a
small tail of literal duplicate ad rows from a legacy `ad_id` parsing
bug.

## Checks that passed (0 anomalies)

| Check | Result |
|---|---|
| `property_match_status` vs `property`/`candidate_property` FK coherence | 0 inconsistencies in all 4 ad tables |
| Orphan properties (no linked ads) | 0 / 21,040 apt + 5,653 house |
| Dangling `property_id` | 0 |
| Linked ads violating matcher hard-rejects vs their property (rooms / size>15%) | 0 |
| Address drift between linked ads and their property (normalized street/no) | 0 / 23,466 apt ads |
| `Seller` duplicate phones or contact_ids | 0 / 803 |
| `Region` dup (name, category, parent) | 0 / 1,064 |
| `project_raw` set but `project` FK null | 0 / 23,635 apt ads |
| `region_name` set but `region` FK null | 0 |
| Ads with zero sightings | 0 |
| Sighting duplicates | impossible (`unique_together`) |
| `first_seen > last_seen` | 0 |
| Property `first_seen`/`last_seen` vs linked ads (min/max) | fully in sync |

## Volumes

| Table | Rows | Notes |
|---|---|---|
| ApartmentForRent | 11,579 | 4,357 hidden, 1,146 `is_sale_misclassified` |
| ApartmentForSale | 12,056 | 5,436 hidden |
| HouseForRent | 2,252 | 1,070 hidden |
| HouseForSale | 5,295 | 3,159 hidden |
| ApartmentProperty / HouseProperty | 21,040 / 5,653 | ~1.1 / ~1.3 linked ads each |
| Sightings (4 tables) | ~277k | 2026-07-08 … 10-03 |

Match status: `auto` 26k, `manual` 3,130, `unmatched` 206 (all ≤2
days old — pending the next `link_ads_to_properties` run, not stuck),
`candidate` 0 (review queue empty — all resolved to `manual`).

## Issues found

### 1. Literal duplicate ad rows — ~308 surplus rows

Same `link` stored as 2–3 rows in one table under malformed `ad_id`s
(e.g. `tr_54290794Skolas 23606/6Spec. pr.`, `tr_5788233925`) — legacy
artifacts predating `b833b94`. 294 malformed `ad_id`s total.
Distribution: 83/123/16/82 dup-link groups (apt rent / apt sale /
house rent / house sale). 125 groups resolve to one property anyway;
**179 are split across different property rows**. Handled by
quarantine (`is_hidden=True`) — see
`docs/duplicate_ad_rows_quarantine.md`.

### 2. Cross-deal duplicate properties — 641 pairs

The same `ad_id` (same ss.com listing, identical link) scraped into
both the rent and sale table and linked to **two different property
rows**: 629 apartment + 12 house pairs. Root cause: ~91% of the rent
rows are `is_sale_misclassified` (a sale listing scraped in the rent
category), so each side matched independently. Ad-level stats are
clean (`objects` excludes misclassified rent ads) but `total_properties`
in region stats is inflated — see
`docs/cross_deal_stats_impact_validation.md`.

### 3. Conflated properties — 3 confirmed

Sale ads lack `apartment_no`, so same-stairwell units with identical
rooms/size pass all hard rejects and auto-merge:

| Property | Address | Units absorbed |
|---|---|---|
| 13910 | Smārdes pag., Šlokenbeka 5 | apts 3/7/8/11 |
| 16071 | Seda, Miera 3 | apts 1/4/12 |
| 16072 | Seda, Saules 4 | apts 4/6 |

Prevention design: `docs/property_conflation_prevention_plan.md`.

### 4. Probable duplicate properties (same-block pairs)

4,797 same-block property pairs score ≥0.45 against the matcher's
rubric. Review (full detail in `property_match_review_2026_10.md`):

| Confidence | Pairs | Meaning |
|---|---|---|
| HIGH | 557 | 326 mergeable clusters — identical comments / same seller / repost signature |
| MEDIUM | 972 | plausible, needs manual look (mostly same-building distinct units) |
| LOW | 3,268 | probably distinct units |

`apartment_no` is almost never populated on sale ads — the blocker
cannot separate same-stairwell units; that is the bulk of MEDIUM.

### 5. Minor data quality

~62 ads `size ≤ 5m²`, ~20 nonpositive prices, `post_date` NULL on
most house ads, `rooms=0` on all house ads (source limitation),
masked seller phones. Triage + plan:
`docs/ad_data_quality_plan.md`.

### 6. Unmatched ads

206 ads `unmatched`; all first_seen ≤2 days ago, none hidden — they
wait for the next linking pass. Best-match scores all <0.45 (6
"likely same", 4 plausible) — the matcher is not leaking candidates.

## Issue lifecycle (verified 2026-10-06)

Which issues are still producing bad data vs. frozen history:

| Issue | Status | Evidence |
|---|---|---|
| Malformed `ad_id` / dup ad rows | **Historical** — fixed state | All 294 malformed ids created in one batch 2026-09-29 13:40–13:44 (a one-off re-import, not the live scraper); quarantined 10-05 |
| House `post_date`/`seller` NULLs | **Static backlog** | 0 of 686 house ads scraped in the last 7d have NULLs — the Aug-10 failure storm ended, but the backlog never heals (rows dropped from enrichment permanently) → `refetch_house_ads` |
| Cross-deal duplicate properties | **Ongoing — still forming** | 48 apt + 1 house pairs formed in the last 7d; every new `is_sale_misclassified` rent row keeps creating a phantom property until the matcher twin-shortcut lands |
| Junk rows (`size≤5`, `price≤0`) | **Ongoing, trickling** | 4 new house-sale junk ads in the last 7d — housing scraper has no size/price guard |
| Conflated properties | **Ongoing risk** | Mechanism (degenerate `street_no=''` blocks, no `apartment_no` on sale ads) is live — only 4 instances so far by luck |
| House dual-listing price pollution | **Ongoing — worst live leak** | No `is_sale_misclassified` on house tables; every new sell-or-rent listing keeps corrupting rent stats |
| Unmatched queue | **Normal churn** | 206 → 593 in one day — new scrapes awaiting the next `link_ads_to_properties` run; drains itself |

## Structural notes (not defects)

- Sighting rows only exist on days someone scraped — the
  classified-ads Cloud Run jobs/schedulers are commented out in
  `terraform/main.tf`, so ~40% of days have zero coverage. "Ad not
  seen" ≠ "ad closed". This motivated the interval design in
  `docs/ad_presence_intervals_plan.md`.
- `HouseForRent`/`HouseForSale` store `rooms=0` — the source listing
  has no room count; `HouseProperty.rooms` is therefore always 0 and
  `rooms` cannot be used to match houses.
