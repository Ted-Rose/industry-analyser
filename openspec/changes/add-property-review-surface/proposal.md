# Proposal

## Why

The property-conflation fixes (audit command, twin shortcut,
candidate-demotion alarms — `docs/plans/
property_conflation_prevention_plan.md`, phases 1–2 shipped)
moved detection into the matcher and a manual audit command,
but left the review surface unbuilt. The alarms deliberately
trade auto-link volume for candidate-queue volume, yet the
admin shows no "this property already contains other units"
signal — the exact gap that let a human approve the 13910
conflation. Phase 3 of that plan (admin conflation flags,
twin-divergence display, merge action, scheduled audit) is
still pending; this change covers that remainder only.

## What Changes

- Property changelists (`ApartmentPropertyAdmin`,
  `HousePropertyAdmin`) gain a conflation-flags column and
  filter, annotated by the same checks
  `audit_property_links` reports (TWIN_DIVERGED,
  APTNO_CONFLICT, FLOOR_CONFLICT, COEXISTING, BULK_ABSORB).
- Candidate property-link review rows show twin-divergence
  evidence so a 13910-style manual approval gets stopped at
  the screen.
- Optional "Merge into property" admin action for the ~618
  single-target duplicate properties the audit identified —
  today they need per-ad moves.
- `audit_property_links` gets a scheduled run (next to the
  linking job in the `all-jobs` cycle or its own sub-job)
  with an alert/log-escalation when TWIN_DIVERGED or
  APTNO_CONFLICT counts exceed 0.

## Capabilities

### New Capabilities
- `property-match-review`: the admin review surface and
  scheduled audit that surface property-conflation evidence
  to humans before bad links are approved and after they
  slip through.

### Modified Capabilities
<!-- None: matcher/linking behavior is unchanged — this adds
     read-only annotations, one admin action, and a scheduled
     invocation of an existing command. -->

## Impact

Backend only (`classified_ads/admin.py`, scheduled-job
wiring in `scrape_jobs` / `terraform` JOBS list if a new
sub-job is needed). Read-only annotations on changelists;
the merge action writes property FKs through the existing
relink semantics (`match_status='manual'`,
`refresh_from_ads`, orphan cleanup). No API or frontend
changes.
