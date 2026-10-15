# Ad presence intervals — research & design (2026-10-05)

Motivation: `*Sighting` tables store one row per (ad, day) — ~277k
rows in ~3 months — but the question users actually ask is *"when was
this ad open, when did it close, when did it come back?"* and per
property *"how many days was this unit on the market?"*. Daily rows
answer that only indirectly, and a single property can accumulate tens
of sighting-derived rows across reposted ads.

## Current mechanism

- Write path: `ApartmentAdScraper._write_sightings` /
  `HousingAdScraper` bulk-insert `(ad, seen_on=today)` for both newly
  saved ads and already-known ads re-observed in a region listing
  (`unique_together(ad, seen_on)` + `ignore_conflicts`).
- Consumers: `ad.days_active` = `sightings.count()` (ads tables,
  `refresh_from_ads` best-ad pick, `avg_days_tracked`);
  `prop.days_on_market` = union of sighting dates across linked ads
  (property detail, `avg_days_on_market`); `/sightings/` daily report;
  `validate_sightings`; admin inlines.

## Key data findings (production, Oct 2026)

- **Coverage is sparse.** The classified-ads Cloud Run jobs and
  schedulers are commented out in `terraform/main.tf` — scrapes run
  manually. Only 53–56 of 88 days have any sightings; median
  per-region coverage ≈ 44% of days. Absence in the data mostly means
  "not scraped", not "ad closed". Nothing in the schema records a
  closure today — `last_seen` just stops moving.
- **Naive interval compression is poor** (2.8×) because interior gaps
  are mostly non-scrape days. Splitting only on *confirmed absence*
  (the ad's region was provably scraped that day and the ad was
  missing) compresses ~277k sightings → ~49k intervals (5–7×), each
  semantically meaningful:

  | Table | Sightings | Ads | Coverage-aware intervals |
  |---|---|---|---|
  | apt_rent | 84k | 11.6k | 16.3k |
  | apt_sale | 121k | 12.1k | 21.4k |
  | house_rent | 20k | 2.3k | 2.8k |
  | house_sale | 52k | 5.3k | 7.8k |

- **~3,200 apt-sale ads show ≥1 confirmed-absence gap** — genuine
  delist-and-return events (or page-depth misses; see edge cases).
- **Coverage is reconstructible historically**: "region R was scraped
  on day D" is proven whenever any ad in R has a sighting on D
  (page 1+ was fetched). Going forward, `ScrapeJobRunItem` DONE rows
  (bookkeeping exists since 2026-10-02) give authoritative per-region
  per-day coverage.

## Proposed model

Two levels, following repo conventions (abstract base + concrete
tables, explicit `db_table`, `unique_together`).

### Level 1 — `*AdInterval` (4 concrete tables)

```
ad FK | opened_on | last_seen_on | closed_on (null) |
n_sightings | status: active | closed | stale
```

- `opened_on` / `last_seen_on`: first/last observed day of the window.
- `closed_on`: first day the ad's region was provably scraped without
  the ad — actual delisting is inside `(last_seen_on, closed_on]`.
- `status=stale`: still open but the region hasn't been scraped
  recently — honest "we don't know" given manual scraping.
- `n_sightings` preserves `days_active` exactly.
- Reappearance after a covered absence opens a **new interval** —
  that *is* the "reopened" event.
- `unique_together(ad, opened_on)`; index `(ad, status)`.

### Level 2 — `*PropertyEpisode` (2 concrete tables)

`property FK | opened_on | closed_on (null) | n_ads` — derived by
merging all linked ads' intervals (both deal types) with a small gap
tolerance (~7–14 days bridges delete-and-repost chains, where a new
ad_id continues the same unit's listing). ~1–3 rows per property.
`days_on_market` becomes episode calendar days — a truer "time on
market" than counting observed days, and independent of scrape
cadence.

## Write-path changes

1. `_write_sightings`: also upsert the ad's open interval —
   `last_seen_on=today`, `n_sightings+=1`; create one if none open.
2. Region-item completion (`runner.item_done` / end of
   `_region_search_urls`): close open intervals of that region's ads
   not seen this pass (`closed_on=today`, `status=closed`).
3. Episodes refreshed where links change (`link_ads_to_properties`,
   admin actions) — same pattern as `refresh_from_ads`.

Backfill: `rebuild_ad_intervals [--dry-run]` command — idempotent,
rebuilds from sightings + reconstructed coverage +
`ScrapeJobRunItem`s; same style as `backfill_program_shows`.

## Consumer updates

- `days_active` → `Sum('intervals__n_sightings')` annotation (or keep
  counting sightings — either is correct while both exist).
- `days_on_market` → episode day-count; property detail gains an
  "open windows" list (the user-facing payoff).
- `/sightings/` report and `validate_sightings` unchanged if
  sightings are retained.

## Sighting retention options

- **A (recommended)**: keep sightings as the append-only evidence
  log; intervals/episodes are the derived read model. ~2M rows/yr is
  trivial for Postgres; preserves re-derivation, `validate_sightings`,
  and the daily report. If volume matters later, a rolling prune
  follows the `prune_ai_requests` precedent.
- **B**: drop sightings after cutover — intervals carry counts, but
  day-level evidence is gone and "seen 30/30 covered days" vs "2/30"
  becomes indistinguishable.
- **C**: rolling ~90-day sighting window + permanent intervals.

## Edge cases

- **False closures**: the scraper stops at the first empty page /
  redirect — an ad beyond the reached pages looks absent. Mitigate:
  close only after **2 consecutive covered absences**; a single missed
  covered day is a hole (kept inside the interval, `n_sightings` just
  doesn't grow).
- **Region disabled** → intervals go `stale`, not `closed`.
- Same-`ad_id` flicker (delist→relist same listing) → multiple
  intervals is honest data; episode-level tolerance absorbs the noise.
- Cross-deal same `ad_id` rows (rent+sale copy of one listing) each
  get their own interval — property episodes merge them.
