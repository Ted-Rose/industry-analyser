# Design — property match review surface

Remainder of `docs/plans/
property_conflation_prevention_plan.md` phase 3 — phases
1–2 (audit command, `relink_property_ads`, twin shortcut,
conflation alarms → candidate demotion, `N-M` split,
`extract_apartment_no` recall) are already shipped; this
change covers only the review surface and scheduling.

## Shared flag computation

The changelist annotation, candidate-row display and the
audit command MUST share one flag-computation path so a
prop can never show "clean" in admin while the audit flags
it. `audit_property_links` already produces per-prop flag
sets with evidence (ad_ids, apt_nos, twin targets) — lift
that computation into a shared helper (e.g. beside
`property_links`) that both the command and admin
annotations call. Changelist performance: compute lazily
per displayed page (annotate via a custom column calling
the helper) or cache; do NOT run the full audit queryset
per row.

## Changelist column + filter

- `ApartmentPropertyAdmin` / `HousePropertyAdmin`:
  `list_display` gains a `conflation_flags` column
  (comma-joined flag names, short empty for clean) and
  `list_filter` gains a `SimpleListFilter` over flag
  presence/kind. Severity order follows the audit:
  TWIN_DIVERGED and APTNO_CONFLICT are decisive;
  FLOOR_CONFLICT/COEXISTING/BULK_ABSORB are review-only.

## Candidate-row twin evidence

The candidate property-link list (the `candidate_property`
review flow in `PropertyLinkActionsMixin`) gains a read-
only "twin divergence" display: for the candidate ad, the
sibling-deal row's linked property (id + address summary)
when it differs from the candidate target. Read-only —
the confirm/reject actions already exist and stay
unchanged; the evidence is what lets a reviewer catch a
13910-style approval.

## Merge action

"Merge into property" admin action on the property
changelists: pick target prop (action form or merge-onto-
last-selected), move each source prop's linked ads via the
same semantics `relink_property_ads --ads ... --to-prop`
uses (`property_match_status='manual'`,
`refresh_from_ads()` on source+target, source deleted when
emptied by `_delete_if_orphan`). Reuse the relink helper —
don't re-implement the move.

## Scheduled audit

Add `audit_property_links` to the scheduled cycle: either
an `audit` sub-job appended to the `all-jobs` JOBS list
after the linking job, or invoked at the tail of
`link_ads_to_properties` runs — prefer the explicit JOBS
entry so the UTC schedule is visible and `--only`-able.
Escalation: TWIN_DIVERGED or APTNO_CONFLICT > 0 logs at
ERROR (Sentry captures it — no new alerting infra);
counts always logged at INFO.

## Open points

- Whether `manual` needs a distinct `link_reason`/`audit`
  provenance for relinked vs human-confirmed rows (plan
  §3e) — decide during implementation; out of scope for the
  flags themselves.
- 618 single-target dup props are the merge action's
  expected first workload — dry-run via
  `relink_property_ads --twin-fix` output is the review
  queue.
