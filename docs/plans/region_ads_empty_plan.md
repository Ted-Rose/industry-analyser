# Region-ads link from Rent vs Buy renders "0 results" — fix plan

> **Status**: Implemented. `RentVsBuy.tsx` builds `regionAdsUrl`
> with `date_from`/`date_to`/`deal_type` (ranked rows link
> `deal_type=ALL`), and `region_ads_list` supports `ALL` merged
> rent+sale output; a missing/blank `deal_type` still returns an
> empty table by design.


## Bug

On `/classified-ads/rent-vs-buy`, each ranked row's region label links
to the region ads page, e.g.
`/classified-ads/apartments/regions/2444/ads`. The landing page shows
"0 results" / "No ads found for this region in the selected time
period." even though the report row aggregated real ads
(prod: `n_rent_ads=27`, `n_sale_ads=39`, median rent 300 €/mo).

## Root cause

Two layers:

1. **The link carries no query params.**
   `frontend/src/classified_ads/routes/RentVsBuy.tsx:440` renders
   `<Link to={regionAds(row.region.id)}>` where
   `regionAds` (`frontend/src/classified_ads/urls.ts:12`) produces a
   bare path — no `date_from`, `date_to`, or `deal_type`.

2. **The API treats a missing `deal_type` as "show nothing" —
   deliberately.** `region_ads_list`
   (`classified_ads/api.py:1375-1443`) branches:

   - `deal_type == 'RENT'` → rent model queryset
   - `deal_type == 'SELL'` → sale model queryset
   - **anything else (blank, missing, invalid) → `objects.none()`**
     (`api.py:1421-1422`)

   This is a documented contract ("A missing/blank deal_type still
   yields an empty table"), locked in by
   `test_region_ads_list_blank_deal_type_is_empty`
   (`classified_ads/tests.py:626`) and by the stats pages' UX:
   `RegionStats`/`RegionStatsChildren` show `NoDealTypeNote`
   (`RegionStats.tsx:240`) telling the user to pick a deal type, and
   their row links pass `deal_type=` explicitly
   (`RegionStatsChildren.tsx:155`).

Verified against prod
(`https://industryanalyser.vercel.app/api/classified-ads/`):

| Request | `total_count` |
|---|---|
| `regions/2444/ads/?kind=apartment` (no deal_type) | **0** |
| `…&deal_type=RENT` | 80 |
| `…&deal_type=SELL` | 87 |
| `…&deal_type=rent` (lowercase) | 0 |
| `…&deal_type=ALL` | 0 (no such mode today) |

Secondary gaps in the same link:

- **Window mismatch.** `rent_vs_buy_ranked` takes `days` (UI default
  30 for apartments, **90 for houses**); `region_ads_list` always
  defaults to the last `STATS_DEFAULT_DAYS=30`. Coincides only for
  the apartment default — a houses or custom-days report already
  links to the wrong window even before `deal_type` is considered.
- **No "both deals" mode.** A ranked row aggregates rent AND sale
  ads; the endpoint accepts exactly one deal at a time. Linking with
  `deal_type=RENT` alone would show half the cohort.

## Semantic caveat (accepted, documented)

The ranked cell cohort is *narrower* than what any region-ads page can
show: the ranking filters to whole-unit monthly lets
(`rate_period in ('','month')`, `is_room_share=False`, 2–50 €/m²),
drops sale rows <10 €/m², groups by the ad's **exact** region FK
(no descendant rollup) and by the `group_by` dimension (property
type / rooms bucket). The region-ads endpoint lists the whole
**subtree** with none of those filters. So the linked page will show
**more** ads than the `n_rent_ads`/`n_sale_ads` counts — for leaf
regions like 2444 the subtree is the node itself; for parent-level
residual rows it is a superset. The page answers "which ads are
active in this region in the window", not "the exact median cohort".
That is the right drill-down UX; no extra filters are added.

## Fix

### Backend — `classified_ads/api.py`

In `region_ads_list`, add an explicit `deal_type='ALL'` branch that
returns rent **and** sale ads merged:

- Build the rent and sale querysets exactly as the existing
  `RENT`/`SELL` branches do (same `region_id__in=region_ids` +
  `_sighted_ad_ids` active-in-window filter, same `objects` managers).
- Annotate each queryset with
  `days_active_count=Count('sightings', distinct=True)` (moved
  per-queryset — today it is applied after the branch).
- Merge into a list sorted by `-first_seen`
  (`first_seen` is `auto_now_add` on both models) and paginate the
  list — `Paginator` accepts a plain list.
- Keep blank/unrecognized `deal_type` → `objects.none()`
  (`test_region_ads_list_blank_deal_type_is_empty` stays green; the
  stats pages' "pick a deal type" flow is unchanged).
- `AdOut` already covers the union of both models' fields and
  `resolve_deal` returns the real 'Rent'/'Sell' per row — no schema
  change needed.
- Update the endpoint docstring (it feeds the OpenAPI description):
  `'ALL' returns both deals merged; blank/unknown stays empty.`

`deal_type` stays a free `str` (max_length=10 fits 'ALL'). Do **not**
switch to an enum — invalid values must keep the lenient empty-list
behavior, matching the retired templates.

### Frontend — `frontend/src/classified_ads/`

- **`routes/RentVsBuy.tsx` (~line 440):** build the link with the
  report's own window and the new both-deals mode:
  `` `${regionAds(row.region.id)}?date_from=${data.date_from}&date_to=${data.date_to}&deal_type=ALL` ``.
  `data.date_from`/`data.date_to` are already returned by
  `rent_vs_buy_ranked` (`RentVsBuyRankedOut`), so the linked window
  always matches the report's — including `days=90` houses and
  custom windows. The `regionAds` callback signature changes from
  `(regionId) => string` to `(regionId) => string` still, but the
  caller needs `data` — pass a builder that closes over
  `data.date_from`/`data.date_to`, or compute the href inline in the
  region cell (simplest: pass `data` down or build
  `regionAdsUrl(row)` inside `RankedTable`).
- **Optional polish (recommended, same PR):** wrap the `n rent` /
  `n sale` count cells in links to the same page with
  `deal_type=RENT` / `deal_type=SELL` (+ same dates) for
  deal-specific drill-down.
- **`routes/RegionAdsList.tsx`:**
  - Banner (`data.deal_type` line ~205): map the raw value to a
    label — `{RENT:'Rent', SELL:'Sell', ALL:'Rent + Sell'}` — so it
    doesn't literally show "Deal type: ALL".
  - Deal badge column: today the Type badge column renders only for
    `kind === 'apartment'` (lines 67-81). A mixed list is ambiguous
    for houses — render the badge column for both kinds (always-on
    is simpler and still accurate for single-deal views).
  - Back link (lines 56-60): `data.deal_type` echoes 'ALL' through
    to the stats pages, whose deal-type `<Select>` has no ALL option
    and whose `NoDealTypeNote` is keyed on `!data.deal_type`
    (`RegionStats.tsx:230`, `RegionStatsChildren.tsx:169`). Two
    one-line options — pick the second:
    1. strip 'ALL' from the back link's `deal_type` (blank →
       combined stats + the note appears); or
    2. keep passing it through and widen the note condition to
       `data.deal_type !== 'RENT' && data.deal_type !== 'SELL'` on
       both stats pages (backend already treats 'ALL' like blank —
       combined totals, null averages).
- **`api.ts`:** update `fetchRegionAds`' docstring ("empty unless
  deal_type is 'RENT'/'SELL'; 'ALL' merges both").

### Generated artifacts

- Regenerate the OpenAPI schema + types — the endpoint docstring is
  part of `frontend/openapi.json` and CI diffs it
  (`frontend-checks.yml`):
  `python manage.py export_openapi_schema` then
  `(cd frontend && npm run gen:types)`.
- Rebuild the committed bundle: `cd frontend && npm run build`
  (outputs to `frontend_dist/`).
- Bump `PWA_CACHE_VERSION` in `fetcher/views.py` (`v26` → `v27`) —
  required on every shipped frontend change so clients drop the old
  service-worker cache.

## Tests

### Backend — `classified_ads/tests.py`

- `test_region_ads_list_all_deal_type`: rent ad + sale ad in the
  region subtree, both sighted today →
  `GET …/ads/?kind=apartment&deal_type=ALL` returns
  `total_count == 2` and both `ad_id`s; per-row `deal` is 'Rent' and
  'Sell' respectively.
- Same for `kind=house` if house fixtures are handy (the merge
  branch is kind-agnostic — one test suffices).
- Keep `test_region_ads_list_blank_deal_type_is_empty` and the
  existing RENT-only tests unchanged.
- Edge: `deal_type=ALL` on a region whose only ads are sighted
  outside the window → `total_count == 0` (active-in-window filter
  still applies).

### Frontend — `RentVsBuy.test.tsx`

- Assert the region-name link's `href` contains
  `deal_type=ALL`, `date_from=<out.date_from>` and
  `date_to=<out.date_to>` (fixture already returns
  `2024-05-01`/`2024-05-31`).
- If the per-deal count links are added: `n_rent_ads` cell links
  with `deal_type=RENT`, `n_sale_ads` with `deal_type=SELL`.

## Other call sites

`regionAds(` has exactly two callers
(`grep -rn "regionAds(" frontend/src`):

- `RentVsBuy.tsx:440` — the broken one (this fix).
- `RegionStatsChildren.tsx:155` — already passes
  `date_from`/`date_to`/`deal_type` explicitly; blank `deal_type`
  there stays blank by design (NoDealTypeNote UX). **Unchanged.**

## Verification

- `python manage.py check`
- `DATABASE_URL=sqlite:///db.sqlite3 python manage.py test classified_ads`
- `cd frontend && npm run typecheck && npm test && npm run build`
  (node via nvm: `export NVM_DIR="$HOME/.nvm"; source
  "$NVM_DIR/nvm.sh"; nvm use v22.2.0`)
- `python manage.py export_openapi_schema` + `npm run gen:types` —
  openapi.json/api-types.ts must be committed (CI drift check).

## UI verification (manual)

1. `./dev.sh` (or the deployed preview), open
   `/classified-ads/rent-vs-buy`.
2. Click a region name (e.g. "Rīga / Latgales priekšpilsēta") —
   lands on `/apartments/regions/<id>/ads?date_from=…&date_to=…
   &deal_type=ALL` and renders a mixed Rent/Sell list, count > 0,
   banner shows the report's window and "Deal type: Rent + Sell"
   (or similar friendly label).
3. Switch the report to `kind=house` (90-day default) and click a
   region — the linked ads page's banner window matches the report's
   90-day window, not 30 days.
4. From the ads page click "Back to …" — lands on the stats page
   with combined stats and the "select a deal type" note (no broken
   select).
5. Region stats flow regression check:
   `/apartments/regions/stats` → children → ads link still behaves:
   with a deal type picked it lists that deal's ads; with "All"
   (blank) it still shows the note and the ads page is empty.
