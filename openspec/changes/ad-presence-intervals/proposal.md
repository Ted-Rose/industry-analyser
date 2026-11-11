# Proposal

## Why

`*Sighting` tables store one row per (ad, day) — ~277k rows
in ~3 months — but the questions users actually ask are
*"when was this ad open, when did it close, when did it come
back?"* and, per property, *"how many days was this unit on
the market?"*. Daily rows answer that only indirectly, and a
single property accumulates tens of sighting-derived rows
across reposted ads. Absence in the data today is ambiguous:
with scrapes running manually (the classified-ads Cloud Run
jobs/schedulers are commented out in `terraform/main.tf`),
"not scraped" and "ad closed" are indistinguishable, and
nothing records a closure — `last_seen` just stops moving.

## What Changes

- New derived read model: four concrete `*AdInterval` tables
  (apartment/house x rent/sale) recording `opened_on`,
  `last_seen_on`, `closed_on` (null while open),
  `n_sightings` and `status` (`active`/`closed`/`stale`),
  `unique_together(ad, opened_on)`, index `(ad, status)`.
- Coverage-aware interval semantics: an interval closes only
  on a *confirmed absence* — a day when the ad's region was
  provably scraped and the ad was missing — and only after 2
  consecutive covered absences (the scraper stops at the
  first empty page, so a single missed day is a hole, not a
  closure). Reappearance after a covered absence opens a NEW
  interval (the "reopened" event).
- Region-scrape coverage is reconstructed historically
  ("region R was scraped on day D" is proven whenever any ad
  in R has a sighting on D) and, going forward, read from
  `ScrapeJobRunItem` DONE rows (bookkeeping exists since
  2026-10-02). Region disabled → `stale`, not `closed`.
- Two concrete `*PropertyEpisode` tables
  (`property FK | opened_on | closed_on | n_ads`) derived by
  merging linked ads' intervals across both deal types with
  a ~7–14 day gap tolerance bridging delete-and-repost
  chains; `days_on_market` becomes episode calendar days.
- Write-path updates: `_write_sightings` upserts the ad's
  open interval; region-item completion closes unseen ads'
  open intervals; episodes refresh where links change
  (`link_ads_to_properties`, admin actions).
- New `rebuild_ad_intervals [--dry-run]` management command
  — idempotent rebuild from sightings + reconstructed
  coverage + `ScrapeJobRunItem`s (same style as
  `backfill_program_shows`).
- Sightings are RETAINED as the append-only evidence log
  (retention option A): intervals/episodes are the derived
  read model, `validate_sightings` and the `/sightings/`
  daily report keep working, re-derivation stays possible.
- Prod findings motivating the design (Oct 2026, 88-day
  window): only 53–56 days have any sightings, median
  per-region coverage ≈44% of days; coverage-aware
  compression reduces ~277k sightings → ~49k intervals;
  ~3,200 apt-sale ads show ≥1 confirmed-absence gap.

## Capabilities

### New Capabilities
- `ad-presence-intervals`: ad open/close/reopen intervals
  compressed from daily sightings, and per-property
  on-market episodes merged across linked ads — the derived
  read model answering "when was it listed" and "how long
  on the market".

### Modified Capabilities
<!-- None: sightings, days_active, validate_sightings and
     the /sightings/ report are unchanged under retention
     option A — data-layer requirements stand. -->

## Impact

Backend only (`classified_ads`): new models + migrations,
`_write_sightings` / region-item completion write-path
hooks, `link_ads_to_properties` episode refresh, a new
`rebuild_ad_intervals` command, and consumer changes
(property detail "open windows" list; `days_on_market`
switches to episode day-count; `days_active` may read
`Sum('intervals__n_sightings')` or keep counting sightings
— equivalent while both exist). No API contract or frontend
changes required for the read model itself; surfacing open
windows in the SPA is a later, optional step.
