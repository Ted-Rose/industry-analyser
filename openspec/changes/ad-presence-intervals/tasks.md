# Tasks

## 1. Models

- [ ] 1.1 backend: Add an abstract `BaseAdInterval` (fields:
  `ad` FK, `opened_on`, `last_seen_on`, `closed_on` null,
  `n_sightings`, `status` active/closed/stale) plus four
  concrete tables in `classified_ads/models.py` —
  apartment/house x rent/sale — each with explicit
  `db_table`, `unique_together(ad, opened_on)` and an
  `(ad, status)` index. Generate the migration file with
  `makemigrations` (do NOT run `migrate` — CI applies it).
- [ ] 1.2 backend: Add an abstract `BasePropertyEpisode`
  (`property` FK, `opened_on`, `closed_on` null, `n_ads`)
  with concrete apartment/house tables, explicit
  `db_table`, `unique_together` and indexes per existing
  model style; migration file as above.

## 2. Write path

- [ ] 2.1 backend: In `_write_sightings` (apartment +
  housing scrapers), upsert the ad's open interval on each
  sighted day: create if none open,
  `last_seen_on=today`, `n_sightings+=1`; a sighting after
  `closed_on` opens a NEW interval.
- [ ] 2.2 backend: On region-item completion
  (`runner.item_done` / end of `_region_search_urls`),
  increment the covered-absence count for the region's
  ads not seen this pass and close intervals reaching 2
  consecutive covered absences (`closed_on` = first
  covered-absence day, `status=closed`); reset the count
  on sighted ads. Uncovered days move neither counter.
- [ ] 2.3 backend: Mark open intervals `stale` when a
  region is disabled / not scraped within the stale
  threshold; never auto-close on uncovered days.
- [ ] 2.4 backend: Refresh `*PropertyEpisode` where ad→
  property links change (`link_ads_to_properties`, admin
  actions) — same pattern as `refresh_from_ads`, merging
  linked ads' intervals with ~7–14 day gap tolerance.

## 3. Backfill command

- [ ] 3.1 backend: New `rebuild_ad_intervals [--dry-run]
  [--batch-size N]` command — idempotent rebuild of
  intervals (then episodes) from sightings + reconstructed
  historical coverage + `ScrapeJobRunItem` DONE rows;
  same style as `backfill_program_shows`.

## 4. Consumers

- [ ] 4.1 backend: Switch `days_on_market` to merged
  episode calendar days; add the property-detail "open
  windows" list. Keep `days_active` counting sightings
  (or `Sum('intervals__n_sightings')` — equivalent while
  both exist).
- [ ] 4.2 both: Leave `/sightings/` daily report and
  `validate_sightings` untouched — sightings stay the
  append-only evidence log (retention option A).

## 5. Tests & docs

- [ ] 5.1 backend: `classified_ads/tests.py`: interval
  open/extend, 2-consecutive-miss closure, single covered
  miss stays open, uncovered days no-op, reopen → new
  interval, disabled-region → stale, episode merge across
  deal types, rebuild idempotency.
- [ ] 5.2 backend: Verify `python manage.py check`; scoped
  tests `DATABASE_URL=sqlite:///db.sqlite3
  python manage.py test classified_ads`.
- [ ] 5.3 backend: Update `AGENTS.md` (data-layer notes)
  and `docs/` index entries for the new read model.
