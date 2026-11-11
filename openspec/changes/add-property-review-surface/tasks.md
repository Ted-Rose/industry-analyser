# Tasks

## 1. Shared flag helper

- [ ] 1.1 backend: Lift `audit_property_links`' per-prop
  flag computation (TWIN_DIVERGED, APTNO_CONFLICT,
  FLOOR_CONFLICT, COEXISTING, BULK_ABSORB + evidence) into
  a shared helper next to `classified_ads/property_links`
  so the command, admin annotations and candidate display
  share one code path; refactor the command to call it.
  Keep it page-scopeable (flags for a given prop id set).

## 2. Admin surface

- [ ] 2.1 backend: `ApartmentPropertyAdmin` +
  `HousePropertyAdmin`: `conflation_flags` column +
  `SimpleListFilter` for flag presence/kind, computed via
  the shared helper without a full audit per row.
- [ ] 2.2 backend: Candidate property-link review rows
  show read-only twin-divergence evidence (the sibling-
  deal twin's linked property when it differs from the
  candidate target) ahead of the confirm/reject actions.
- [ ] 2.3 backend: "Merge into property" admin action on
  both property changelists — moves source props' ads via
  the `relink_property_ads` semantics
  (`match_status='manual'`, `refresh_from_ads`, orphan
  cleanup); reuse the relink helper.

## 3. Scheduled audit

- [ ] 3.1 backend: Schedule `audit_property_links` —
  prefer an explicit JOBS entry in the `all-jobs` list
  after the linking job (or a documented tail-call);
  TWIN_DIVERGED / APTNO_CONFLICT > 0 logs at ERROR,
  counts always at INFO.
- [ ] 3.2 backend: Terraform/scheduler wiring only if the
  JOBS entry needs it; otherwise code-only.

## 4. Tests & docs

- [ ] 4.1 backend: `classified_ads/tests.py`: flag-filter
  correctness on seeded conflation fixtures, merge action
  moves + orphan cleanup, escalator fires on seeded
  TWIN_DIVERGED.
- [ ] 4.2 backend: `python manage.py check`;
  `DATABASE_URL=sqlite:///db.sqlite3 python manage.py
  test classified_ads`.
- [ ] 4.3 backend: Update `docs/django_notes.md` /
  admin-surface docs and `AGENTS.md` if the admin surface
  gains a documented convention.
