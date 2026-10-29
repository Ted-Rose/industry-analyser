# Data Layer Specification

## Purpose

Defines the model/manager conventions of the scraped-data
tables: filtered default managers vs the unfiltered
`all_objects`, the daily `*Sighting` dedup pattern, the shared
`BaseRefetchCommand` ABC for bulk re-fetch commands, and the
explicit `db_table`/`unique_together`/abstract-base style.

## Requirements

### Requirement: Filtered default managers

`classified_ads` ad models SHALL hide flagged rows from the
default `objects` manager (`is_hidden=True` everywhere, plus
`is_sale_misclassified=True` on the for-rent models) and expose
the unfiltered queryset as `all_objects`. Admin, refetch
commands, and data-fix scripts MUST use `all_objects` or
flagged rows silently disappear.

#### Scenario: Hidden ad invisible to default queries

- **WHEN** an ad has `is_hidden=True`
- **THEN** `Model.objects` excludes it but
  `Model.all_objects` returns it

#### Scenario: Misclassified rental hidden

- **WHEN** an `ApartmentForRent`/`HouseForRent` has
  `is_sale_misclassified=True`
- **THEN** `objects` (CleanRentalManager) excludes it

#### Scenario: Admin must opt into all_objects

- **WHEN** a `ModelAdmin` serves a changelist for these models
- **THEN** it overrides `get_queryset` to use `all_objects`,
  or flagged rows are unreachable in admin

### Requirement: Daily sightings dedup

Each `*Sighting` model SHALL record one row per ad per day —
`seen_on` DateField with `unique_together(ad, seen_on)` — and
`days_active` on the ad counts its sighting rows. Duplicate
sighting rows for the same ad/day MUST NOT be created.

#### Scenario: Same ad scraped twice in one day

- **WHEN** a scrape encounters an ad already sighted today
- **THEN** no second sighting row is written; the existing one
  (or get_or_create) keeps the count at one

#### Scenario: days_active reflects sighting count

- **WHEN** an ad has been sighted on N distinct days
- **THEN** `days_active` returns N

### Requirement: BaseRefetchCommand contract

Bulk re-fetch commands SHALL subclass
`core_scraper.management.commands.base_refetch.BaseRefetchCommand`,
implement `get_model()`, `get_scraper_class()`, and
`get_default_update_fields()`, and inherit the common args:
`--ids`, `--filter "field__lookup=value"`, `--fields`,
`--dry-run`, `--limit`, `--batch-size` (default 100).

#### Scenario: No selector given

- **WHEN** the command runs with neither `--ids` nor
  `--filter`
- **THEN** it exits with `CommandError('Must provide either
  --ids or --filter argument')`

#### Scenario: Queryset prefers all_objects

- **WHEN** the target model defines `all_objects`
- **THEN** the command queries and `bulk_update`s through it
  (hidden/misclassified rows stay refetchable)

#### Scenario: Dry run makes no changes

- **WHEN** `--dry-run` is passed
- **THEN** no requests are sent and no rows are written; up to
  10 matching records are listed instead

#### Scenario: Batched writes

- **WHEN** refetched records accumulate changed fields
- **THEN** they are flushed with `bulk_update(batch,
  update_fields)` every `--batch-size` records and once at the
  end

### Requirement: Model style conventions

Data models SHALL declare explicit `db_table` names and
`unique_together` where dedup applies; shared field sets live
on abstract bases (`BaseApartmentAd`, `BaseHouseAd`) backing
the concrete rent/sale models, so a shared field is added
once.

#### Scenario: Adding a field common to rent and sale ads

- **WHEN** a column applies to both deal types
- **THEN** it is declared on the abstract base, not duplicated
  on the concrete models
