# Spec Delta

## Purpose

The admin review surface and scheduled audit that surface
property-conflation evidence (diverged cross-deal twins,
conflicting apartment numbers, batch absorption) to humans
before bad links are approved and after they slip through.

## ADDED Requirements

### Requirement: Conflation flags on property changelists

The property admin changelists SHALL expose the same
conflation flags `audit_property_links` reports
(TWIN_DIVERGED, APTNO_CONFLICT, FLOOR_CONFLICT, COEXISTING,
BULK_ABSORB) as a column and filter, so suspect properties
are discoverable without running the audit command.

#### Scenario: Suspect property is filterable

- **WHEN** a property's linked ads' cross-deal twins point
  to >=2 distinct properties
- **THEN** the changelist shows TWIN_DIVERGED on that row
  and the flags filter can isolate it

#### Scenario: Clean property shows no flag

- **WHEN** a property trips none of the audit checks
- **THEN** its flags column is empty

### Requirement: Twin divergence on candidate review

The candidate property-link review surface SHALL show
cross-deal twin-divergence evidence for the candidate, so a
manual approval cannot proceed blind to conflicting twin
targets.

#### Scenario: Diverged twin visible at approval time

- **WHEN** a reviewer opens a candidate whose ad's sibling-
  deal twin is linked to a different property
- **THEN** the review surface displays the twin's property
  target before the confirm/reject actions

### Requirement: Merge property admin action

An admin action SHALL merge selected duplicate properties
into a chosen target by moving their linked ads through
the existing relink semantics (match status `manual`,
`refresh_from_ads()` on source and target, orphan property
cleanup).

#### Scenario: Merge consolidates a duplicate property

- **WHEN** a reviewer merges duplicate property A into
  target property B
- **THEN** A's ads land on B with `manual` match status,
  A is deleted once empty, and both properties' derived
  fields refresh

### Requirement: Scheduled conflation audit

`audit_property_links` SHALL run on a schedule (its own
sub-job or alongside the linking job in the `all-jobs`
cycle) and escalate — log at error level or alert — when
TWIN_DIVERGED or APTNO_CONFLICT counts exceed 0.

#### Scenario: Regression surfaces without manual runs

- **WHEN** a link run creates a new twin divergence
- **THEN** the next scheduled audit flags it and the
  escalation fires, without anyone invoking the command
  by hand

#### Scenario: Clean audit stays quiet

- **WHEN** the audit finds zero decisive flags
- **THEN** it logs/report-counts normally with no
  escalation
