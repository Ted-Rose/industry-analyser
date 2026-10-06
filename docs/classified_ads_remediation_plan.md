# classified_ads — remediation plan (2026-10-05)

Master plan for the four issues surfaced by the health audit
(`docs/db_health_report_2026_10.md`). Source analyses:

- `docs/property_match_review_2026_10.md` — pair-level review
- `docs/cross_deal_stats_impact_validation.md` — stats impact
- `docs/property_conflation_prevention_plan.md` — conflation design
- `docs/ad_data_quality_plan.md` — data-quality triage
- `docs/duplicate_ad_rows_quarantine.md` — done: dup ad rows hidden

Ordered by stats impact. Each workstream lists implementation,
verification, and risks. Prod safety rules apply throughout: writes
only via reviewed commands/scripts, `--dry-run` first, never migrate
prod by hand.

## Which issues are still live (verified 2026-10-06)

| Workstream | Produces new bad data? |
|---|---|
| WS1 house dual-listing | **Yes** — no flag exists; every new sell-or-rent listing corrupts rent stats |
| WS2 cross-deal pairs | **Yes** — ~48 new apt pairs/week; re-run the relink periodically until WS4 prevention lands |
| WS3 `post_date` NULLs | No new occurrences (0/686 last-7d ads) — static backlog needing one backfill, plus the re-enrich fix to stay healed |
| WS4 conflation | Live mechanism — 4 known instances; new ones possible on every link run |

The completed quarantine (237 dup ad rows hidden) is historical-only:
all malformed `ad_id`s trace to a single 2026-09-29 import batch and
the current scraper produces none.

---

## WS1 — House dual-listing pollution (highest impact)

**Problem.** 1,433 `ad_id`s exist in both `HouseForRent` and
`HouseForSale` — ss.com "sell-or-rent" house listings scraped under
both `hand_over/` and `sell/`. `HouseForRent` has **no**
`is_sale_misclassified` mechanism (apartments do), so the sale price
lands in `monthly_price`: visible house-rent average reads ~€76,434/mo
instead of ~€1,518. 4 of 12 house cross-deal twin rows are fully
visible in `objects`.

**Implementation.**
1. Add `is_sale_misclassified` to `BaseHouseAd` (or a
   `is_crosslisted_sale` flag with the same semantics — decide name)
   + migration; exclude it in `VisibleHouseManager` for
   `HouseForRent` (mirror `CleanRentalManager`).
2. Backfill command `flag_house_crosslistings`: for every `ad_id`
   present in `HouseForSale`, flag the `HouseForRent` twin
   (`is_sale_misclassified=True`) — heuristic already proven on
   apartments: same `tr_*` id + same `link` = same listing.
   `--dry-run` first; expect ~700 visible rent rows flagged.
3. Scraper-side: in `HousingAdScraper`, when a rent row's `ad_id`
   already exists in `HouseForSale` (or vice versa), set the flag at
   ingest so new crosslistings are caught on entry.
4. Optionally also apply the apartment keyword/price heuristic
   (`is_sale_misclassified(comment, sqm_price)`) to house rents for
   genuinely-misfiled ads that have no sale twin.

**Verification.** Visible house-rent avg `monthly_price` drops to
~€1.5k; `objects.count()` delta equals flagged count; no change in
`HouseForSale` stats.

**Risks.** A true "rent AND sale" offer loses its rent row from rent
stats — acceptable (the listing is one ad; sale view keeps it). Flag
is reversible.

---

## WS2 — Merge/relink the ~626 cross-deal duplicate properties

**Problem.** Same `ad_id` linked to two different property rows
(629 apt + 12 house pairs — 626 confirmed, 5 attribute-conflict, 10
inside conflated props). Inflates `total_properties` ~3% and splits
one unit's market history in two (`avg_days_on_market` understated
~29% per affected unit).

**Implementation.**
1. Command `relink_crossdeal_twins [--dry-run]`: for every `ad_id`
   shared between a deal pair where `rent.property_id !=
   sale.property_id`:
   - re-link the rent row onto the **sale row's property** (the sale
     side is the real listing; the rent row is almost always
     `is_sale_misclassified`);
   - call `prop.refresh_from_ads()` on both props; delete the source
     property if it empties (same rule as `_vacate_property`);
   - set `property_match_status='manual'` + `property_match_score`
     =1.0 on the moved row so the trail is auditable.
   Skip pairs where the twin rows disagree on rooms/size >15%
   (the 5 attribute-conflict pairs — list for manual review) and any
   property in the conflated set (handled by WS4).
2. After relinking, re-run `link_ads_to_properties --relink` scoped to
   affected blocks to settle any secondary candidates.

**Verification.** Shared-`ad_id`-different-property count → 0 for the
626; property totals drop by ~626 apt + ~12 house; sample-check 10
merged properties' `linked_ads()` + `days_on_market`.

**Risks.** The misclassified rent row is hidden from `objects`
already — merging mainly repairs property-level stats, low risk.
Attribute-conflict pairs documented for human decision.

---

## WS3 — `refetch_house_ads` + re-enrich policy for failed detail fetches

**Problem.** ~6.4k house ads (83–85% of both house tables) have
`post_date`/`seller` NULL — the detail-page enrichment failed once
(429s on the 2026-08-10 mass scrape) and `remove_redundant_results`
drops existing ads from enrichment forever, so they never recover.
`refetch_apartment_ads` exists but no house equivalent.

**Implementation.**
1. Implement `HousingAdScraper._parse_detail_for_refetch` (pattern
   already exists in `ApartmentAdScraper`) and a
   `refetch_house_ads` command on `BaseRefetchCommand`
   (`--filter "post_date__isnull=True" --fields
   post_date,seller,floors,land_area_sqm,comment` etc.).
2. Scraper fix: when `remove_redundant_results` finds an existing ad
   with `post_date IS NULL` (or `seller IS NULL`), keep it in the
   enrichment queue instead of dropping it — self-healing on the next
   scrape pass.
3. Optionally widen to apartments: ~14 apt-sale + 1 apt-rent null
   post_dates — already covered by `refetch_apartment_ads`
   (`scripts/refetch_null_post_dates.sh` wraps it).

**Verification.** `--dry-run` sample output shows parsed fields;
after a test batch of ~50, `post_date` null count drops; no errors
logged.

**Risks.** Real HTTP load — run throttled/batched during low traffic;
respect `BaseScraper` pool/throttle (never raw requests).

---

## WS4 — Fix the 4 conflated properties + prevention

**Problem.** 4 confirmed `ApartmentProperty` rows absorbed ads for
multiple units (13910 Šlokenbeka 5, 16071 Miera 3, 16072 Saules 4,
16037 Jaunpils). Root cause: degenerate `street_no=''` blocks +
`apartment_no` absent on sale ads + same seller/boilerplate comments.
Full design + per-ad re-linking lists in
`docs/property_conflation_prevention_plan.md`.

**Remediation (now).**
1. Command `relink_property_ads --twin-fix` (or ad-hoc script):
   execute the doc's exact ad→target-property moves for the 12 ads
   (each has a cross-deal `ad_id` twin on the correct single-unit
   prop — the twin tells the truth); source props dissolve via the
   empty-delete rule. `--dry-run` first.

**Prevention (next).**
2. **Twin shortcut in the matcher**: at link time, if the ad's
   `ad_id` exists in the sibling deal table, prefer the twin's
   property directly (passes rooms/size gates) — fixes future
   conflation *and* prevents new WS2-style splits.
3. **Conflation alarms demoting auto→candidate**: prop already holds
   ≥2 distinct apt_nos; overlapping same-deal ads; floor dissent;
   degenerate `street_no=''` block without decisive evidence;
   multiple surviving candidates.
4. **`audit_property_links` command**: periodic flags incl.
   TWIN_DIVERGED (the detector that found prop 16037) — cheap
   standing check after each link run.
5. `extract_apartment_no` recall: add `кв. N` / `dz. N` patterns
   (verified ~13 clean hits); keep false-positive-heavy patterns out.

**Verification.** The 4 props' linked ads reduce to one unit each;
`audit_property_links` reports TWIN_DIVERGED=0 on re-run.

**Risks.** Stricter matching → more `candidate` queue entries and
more singleton properties; false splits < false merges, acceptable.

---

## Sequencing & dependencies

```
WS1 (house flag)      ── independent, do first (biggest live stats win)
WS2 (twin relink)     ── after WS1 flags exist so moved rows stay hidden
WS4 remediation       ── before WS2 mass run (conflated props excluded
                          from twin relink until un-conflated)
WS4 prevention        ── before next bulk `--relink`
WS3 (refetch)         ── independent, any time (network-bound)
```

## Out of scope / later

- `AdInterval`/`PropertyEpisode` model — `docs/ad_presence_intervals_plan.md`.
- Malformed `ad_id` normalization (36 "frozen" canonical rows +
  ~147 malformed-but-unique rows): needs ad_id rewrite via
  `scripts/dedupe_classified_ads.py` — separate task.
- Masked seller phones merging distinct sellers — source limitation;
  document in `ad_data_quality_plan.md`.
- Region-stats `avg_days_on_market` semantics revisit once WS2 lands.
