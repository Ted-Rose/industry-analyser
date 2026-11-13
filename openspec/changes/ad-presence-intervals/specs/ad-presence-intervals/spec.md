# Spec Delta

## Purpose

Ad open/close/reopen intervals compressed from daily
sightings, plus per-property on-market episodes merged
across linked ads — the derived read model answering "when
was it listed" and "how many days on the market".

## ADDED Requirements

### Requirement: Per-ad presence intervals

Each ad model family SHALL maintain interval records
capturing one listing window per ad: `opened_on`,
`last_seen_on`, `closed_on` (null while open),
`n_sightings`, and `status` (`active` | `closed` |
`stale`), with one concrete table per ad table
(apartment/house x rent/sale), `unique_together(ad,
opened_on)` and an `(ad, status)` index.

#### Scenario: First sighting opens an interval

- **WHEN** an ad is observed for the first time on day D
- **THEN** an interval exists with `opened_on=D`,
  `last_seen_on=D`, `closed_on` null, `n_sightings=1`,
  `status=active`

#### Scenario: Subsequent sighting extends the window

- **WHEN** an ad with an open interval is sighted on a
  later day
- **THEN** the same interval updates `last_seen_on` and
  increments `n_sightings` — no new row is created

### Requirement: Coverage-aware closure

An interval SHALL close only on a confirmed absence — a
day the ad's region was provably scraped (any sibling ad
in the region sighted that day, or a DONE
`ScrapeJobRunItem` for the region) while the ad itself was
not seen — and only after 2 consecutive covered absences.

#### Scenario: Confirmed absence closes the interval

- **WHEN** an ad is missing on 2 consecutive days its
  region was provably scraped
- **THEN** the interval gains `closed_on` = the first
  covered-absence day and `status=closed`

#### Scenario: Single covered miss is a hole, not a close

- **WHEN** an ad is absent on exactly one covered day
  between sightings
- **THEN** the interval stays open (`closed_on` null) and
  `n_sightings` simply does not grow

#### Scenario: Uncovered days cannot close

- **WHEN** the ad's region was not scraped on a day
- **THEN** that day counts neither toward nor against
  closure — "not scraped" is never treated as "closed"

### Requirement: Reappearance opens a new interval

When an ad is sighted again after its interval closed, a
NEW interval SHALL open rather than reopening the old one
— the closed-then-returned shape IS the delist-and-return
event.

#### Scenario: Delist-and-return produces two intervals

- **WHEN** an ad's interval has closed and the ad is
  sighted again on a later day
- **THEN** a second interval opens with `opened_on` =
  return day while the first keeps its `closed_on`

### Requirement: Stale status for unscaffolded regions

An open interval SHALL be marked `stale` — an honest
"we don't know" — when the ad's region has not been
scraped recently (e.g. the region is disabled or scrapes
are paused), instead of being closed.

#### Scenario: Disabled region goes stale, not closed

- **WHEN** a region stops being scraped while ads there
  still have open intervals
- **THEN** those intervals read `status=stale`, never
  `closed`

### Requirement: Property on-market episodes

Each property table SHALL derive episode records
(`opened_on`, `closed_on` null while open, `n_ads`) by
merging all linked ads' intervals across both deal types,
bridging gaps of ~7–14 days so a delete-and-repost chain
under a new ad_id continues the same unit's episode.

#### Scenario: days_on_market from episode days

- **WHEN** a property's linked ads span disjoint listing
  windows
- **THEN** `days_on_market` reflects merged episode
  calendar days — independent of how often scraping ran

#### Scenario: Reposted ad continues the episode

- **WHEN** an ad's interval closes and a different ad_id
  linked to the same property opens within the tolerance
  window
- **THEN** they merge into one episode, and `n_ads`
  records both ads

### Requirement: Sightings retained as evidence log

The `*Sighting` tables SHALL remain the append-only
source of truth; intervals and episodes are a derived
read model rebuildable from sightings plus coverage
evidence. `days_active`, `validate_sightings` and the
`/sightings/` report MUST keep working unchanged.

#### Scenario: Idempotent rebuild

- **WHEN** `rebuild_ad_intervals` is run (with or without
  `--dry-run`) after intervals already exist
- **THEN** it converges to the same interval set derived
  from sightings + coverage, making no spurious changes

#### Scenario: Re-derivation after logic change

- **WHEN** interval semantics change later
- **THEN** truncating and re-running the rebuild
  reproduces intervals from untouched sighting evidence
