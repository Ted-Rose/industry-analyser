# classified_ads data-quality triage plan

Read-only audit of the production Aiven DB (2026-10 snapshot) plus code
review of `classified_ads/apartment_scraper.py` and
`classified_ads/housing_scraper.py`. Counts below use `all_objects`
(total rows incl. hidden); "visible" = the default `objects` manager
used by stats/views.

Table sizes: ApartmentForRent 11661 (6545 visible),
ApartmentForSale 12110 (6674), HouseForRent 2262 (1192),
HouseForSale 5319 (2160).

## Triage table

| # | Issue | Count (total / visible) | Root cause | Severity | Recommended action |
|---|-------|------------------------|------------|----------|--------------------|
| 1 | `size` <= 5 m² | 62: AptRent 2, HouseRent 20, HouseSale 40 (≈30 visible) | Housing `parse_results` does no size validation — `'size': cells[4]` raw string, only `total_price == 0` is skipped (`housing_scraper.py:177,206`). Apartment parser skips `size == 0` (`apartment_scraper.py:222`) but lets 1–5 m² through. `size=0` rows (6 rent + 14 sale) are all dual-listed sale ads (see #8a). | High (avg size, €/m²) | Add `size <= 0` skip + suspicious-small (<10 m²) flag in housing ingest; `is_hidden` quarantine on existing rows; DB check constraint `size > 0`. |
| 2 | `price_per_sqm` = 0 | 20: HouseRent 6, HouseSale 14 (total_price > 0 on all) | Consequence of #1: `price_per_sqm = total/size if size > 0 else 0.0` (`housing_scraper.py:375-377`). | High (drags avg €/m² to 0) | Fixed by #1 at ingest; quarantine + recompute or refetch existing 20 rows. |
| 3 | `post_date` NULL on houses | HouseRent 1877/2262 (83%), ~807/~1190 visible (68%); HouseSale 4542/5319 (85%), 1378/2160 visible (65%). Apartments nearly clean (AptRent 1, AptSale 14). | Whole-detail-enrichment produced nothing: `post_date` NULL ⟺ `seller` NULL (100% correlation — 1877 rent and 4542 sale rows have both NULL, every enriched row has both set). `enrich_result` either got `detail_response is None` (urllib3 retry exhaustion — `base.py:212-214`) or parsed an error/deleted page, then `enrich_result` still saved the partial row (`housing_scraper.py:304-306`). 1079 of the rent nulls have `first_seen` on 2026-08-10 (mass-scrape day → probable 429 storm). Once inserted, `remove_redundant_results` drops existing rows from future enrichment, so NULLs are permanent — no `refetch_house_ads` exists (only `refetch_apartment_ads`). Null-pd rows still accrue sightings (avg 10.2 vs 4.61) proving the ads are live and re-fetchable. | High (days-on-market/date stats) | Create `refetch_house_ads` on `BaseRefetchCommand` (needs `_parse_detail_for_refetch` on `HousingAdScraper`); scraper change: re-enrich re-sighted rows where `post_date IS NULL`; log detail-fetch failures to `excluded_resources`. |
| 4 | `rooms` = 0 on all house rows | 2262/2262 rent, 5319/5319 sale | Hardcoded `'rooms': 0` (`housing_scraper.py:205`) — the 9-cell house listing table has no rooms column; detail-page "Rooms:" is never parsed either. Faithful to listing-page source but discardable. | Medium (property matching, room stats) | Parse "Rooms:"/`"Istabas:"` from detail-page `ads_opt` table (pattern: `apartment_scraper.py:673 _ads_opt_value`); populate via the new refetch command; leave historical zeros documented. |
| 5 | Masked seller phones | 804/804 Seller rows: `(+371)NN-NN-***`; `contact_id` empty on all 804 | Masked at source — ss.com hides phone digits behind JS, `span#phone_td_*` text is literally masked (`apartment_scraper.py:629-633`, `housing_scraper.py:340-344`). `contact_id` extraction (`a[href*='/mail/']`) never matches — likely source markup change; dead code now. Distinct real numbers sharing a masked prefix merge into one Seller via `get_or_create(phone=...)` — silent collisions. | Medium (seller-based matching unreliable) | Leave values (source limitation); document that phone matching is prefix-level only; drop or fix contact_id extraction; never join sellers on masked phone alone. |
| 6 | Malformed `ad_id` (not `^tr_\d+$`) | 294: AptRent 85, AptSale 91, HouseRent 17, HouseSale 101; 147 still `is_hidden=False` | Legacy composite-id scheme (`tr_id` + listing-cell text) — see `docs/ad_id_dedup_fix_plan.md`. Notably ALL 294 have `first_seen` in a 4-minute window 2026-09-29 13:40–13:44, i.e. one backfill/fix run re-created them, not the live scraper (current code stores bare `row_id`, `apartment_scraper.py:253`). | Handled elsewhere | Cross-reference only — parallel quarantine task owns this; verify the 147 still-visible rows get flagged. |
| 7 | `post_date` > `first_seen` | AptRent 797, AptSale 3051 (25%), HouseRent 10, HouseSale 19; `post_date` > `last_seen`: 532 / 308 / 8 / 15 | Two compounding causes: (a) `TIME_ZONE='UTC'` while `timezone.make_aware(naive)` stamps ss.com's Latvia-local `Date:` as UTC (`apartment_scraper.py:618-624`, `housing_scraper.py:331-334`) — every `post_date` is +2/+3h ahead of truth (EET/EEST), so ads scraped within ~3h of posting get `post_date > first_seen`; (b) ss.com renewals bump the ad's `Date:`, and `post_date` is in `bulk_create` `update_fields` while `first_seen` is `auto_now_add`. | Medium (systematic skew in time stats) | Parse detail-page dates with `zoneinfo.ZoneInfo('Europe/Riga')` instead of default TZ; document that `post_date` = last-renewal date, so days-on-market must use `first_seen`/sightings, not `post_date`. |
| 8a | Dual-listed house ads | **1433 ad_ids appear in BOTH HouseForRent and HouseForSale** (63% of all house-rent rows); still visible: 707 rent / 536 sale | ss.com cross-lists "sell or rent" houses: identical `tr_id` and identical `link` scraped from both `hand_over/` and `sell/` pages, seconds apart in the same run (e.g. `tr_58116607` R+S at 2026-10-02 08:21:4x, `tr_57953791` at 2026-08-10 19:10:5x/19:11:0x). The ad's single displayed price is stored as `monthly_price` in rent AND `total_price` in sale. Result: 693/1186 visible house-rent rows (58%) have `monthly_price > 5000`; visible avg `monthly_price` = €76,434, falling to **€1,518** when dual-listed ids are excluded — rent price stats are dominated by sale prices. | **Critical** | Extend the `is_sale_misclassified` mechanism to HouseForRent (house ads have no such flag): cross-deal `ad_id` check at ingest (`remove_redundant_results`/`initiate_resource`) or heuristic (`monthly_price > ~3000`). Quarantine existing rent-side twins; decide canonical deal per ad (probably SELL — sample prices are sale-scale). |
| 8b | `floor` > `max_floor` (apts) | 99 AptRent, 64 AptSale (163 total); only 2 have `max_floor=0` parse fallback | `cells[6].split('/')` with `[0]`/`[-1]` (`apartment_scraper.py:225-233`) parses cleanly, so values like floor=12/max=9, floor=5/max=3 are stored as displayed — seller-entered reversed or inconsistent floor fields on ss.com; can't confirm without fetching (forbidden here). | Low | Log raw cell when `floor > max_floor`; optional ingest normalize (swap or flag); not worth a refetch. |
| 8c | Other smells | AptSale `price_per_sqm < 10`: 34 visible; `sightings=1`: AptRent 2004, AptSale 1446, HouseRent 126, HouseSale 305; blank `district`/`street_name`: 0 everywhere | AptSale cheap rows = garages/land/misc posted in flat-sale (no category filter beyond region URL). Single-sighting counts are expected churn (ad deleted after one scrape). | Low | Leave; consider a price floor sanity flag for AptSale. |

## Recurrence status (verified 2026-10-06)

- **Still producing bad data:** #1/#2 junk size/price (4 new
  house-sale rows in the last 7d — housing ingest has no validation),
  #7 post_date skew (the `make_aware` UTC-vs-Riga bug is live in
  scraper code — every new ad's `post_date` is +2/+3h off), #8a
  dual-listed houses (no flag mechanism exists — grows every scrape).
- **Not recurring (frozen):** #3 post_date NULLs — 0 of the 686 house
  ads scraped in the last 7d are NULL; the backlog is static until
  `refetch_house_ads` runs. #6 malformed ad_ids — all 294 created in
  one 2026-09-29 import batch; the live scraper emits clean ids.
- **Source limitations (always present):** #4 house `rooms=0`, #5
  masked phones — will persist unless the detail-page parsing is
  extended / source changes.

## Ranked recommendations (impact on avg €/m², avg size, days-on-market)

1. **Fix dual-listed house ads (#8a).** Largest statistical corruption
   found: ~58% of visible house-rent rows carry sale prices
   (visible avg `monthly_price` €76,434 vs €1,518 without them).
   Add a house-side misclassification flag (reuse the
   `is_sale_misclassified` pattern from ApartmentForRent) plus a
   cross-table `ad_id` dedup at ingest; quarantine the ~700 visible
   rent-side twins.

2. **Backfill house `post_date`/`seller` (#3) via a new
   `refetch_house_ads` command** on `BaseRefetchCommand` — ~6,400 rows
   NULL (2,185 still visible), all fixable since the ads are still
   live (avg 10 sightings). Requires `_parse_detail_for_refetch` on
   `HousingAdScraper` and (to stop recurrence) re-enriching re-sighted
   rows whose `post_date` is still NULL — today
   `remove_redundant_results` drops them before enrichment forever.

3. **Size/price validation at house ingest (#1+#2).** Mirror the
   apartment guard (`apartment_scraper.py:222`): skip `size <= 0`,
   flag `size < 10` or `price_per_sqm` outliers; `is_hidden`-quarantine
   the ~60 junk rows; add `CheckConstraint(size__gt=0)` on the house
   tables so regressions surface.

Secondary (not top-3): parse post_date as `Europe/Riga` (#7); parse
"Rooms:" from house detail pages (#4); treat masked phones as
prefix-only keys (#5); floor>max_floor logging (#8b).
