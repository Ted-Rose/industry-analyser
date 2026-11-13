# Documentation Index

Map of the documentation in this repository. For agent-facing
conventions (commands, rules, known gaps) see `AGENTS.md` —
where a doc disagrees with the code, the code wins.

## Getting started

- [README.md](README.md) — project overview, quick start,
  common commands.
- [LOCAL_SETUP.md](LOCAL_SETUP.md) — full local setup guide
  (predates the prod-by-default `DATABASE_URL` — see
  AGENTS.md).
- [.env.example](.env.example) — environment variable
  template.
- [AGENTS.md](AGENTS.md) — agent/developer conventions,
  commands, rules, known gaps.
- [changelog.md](changelog.md) — append-only feature log and
  to-do notes.
- [coding_diary.md](coding_diary.md) — append-only
  development/setup notes.

## App documentation

- [fetcher/README.md](fetcher/README.md) — vacancy scraper
  overview and how it works.
- [fetcher/ARCHITECTURE.md](fetcher/ARCHITECTURE.md) — system
  architecture and data flow.
- [fetcher/QUICK_REFERENCE.md](fetcher/QUICK_REFERENCE.md) —
  quick command reference.
- [blogs/BLOG_SCRAPER_CALLSTACK.md](blogs/BLOG_SCRAPER_CALLSTACK.md)
  — blog scraper call-path reference.

## docs/ — runbooks & references

Index: [docs/README.md](docs/README.md)

- [docs/refetch_command_usage.md](docs/refetch_command_usage.md)
  — `BaseRefetchCommand` architecture, options, examples,
  VS Code debug configs.
- [docs/vacancy_refetch_usage.md](docs/vacancy_refetch_usage.md)
  — `refetch_vacancies` usage: vacancies, companies,
  keywords, OCR.
- [docs/news_pipeline.md](docs/news_pipeline.md) — news
  pipeline: RSS scrape, topic classification, clustering,
  digest scoring.
- [docs/django_notes.md](docs/django_notes.md) — Django
  patterns/gotchas (custom manager admin visibility, etc.).

## docs/research/ — audits & reports

Point-in-time production audits and validation reports.
Counts reflect each report's snapshot date — history, not
current state.

- [misclassified_sale_ads_analysis.md][res-misclass]
  — for-sale ads in the rent table; origin of
  `is_sale_misclassified` (2026-07).
- [duplicate_sightings_validation.md][res-dupsight]
  — `(ad, seen_on)` dedup validation (2026-09).
- [duplicate_ad_rows_quarantine.md][res-quar]
  — same-link duplicate rows hidden via `is_hidden` (2026-10).
- [db_health_report_2026_10.md][res-dbhealth]
  — production DB health audit + dedup findings.
- [property_match_review_2026_10.md][res-propreview]
  — confidence-tiered duplicate-property review.
- [cross_deal_stats_impact_validation.md][res-crossdeal]
  — do cross-deal dupes pollute stats? Validation.

## docs/plans/ — frozen history

Design plans kept as history; each carries a status header.
The directory is frozen — all new planning goes through
OpenSpec (AGENTS.md rule 11).

- [docs/plans/ad_data_quality_plan.md](docs/plans/ad_data_quality_plan.md)
  — Implemented: classified_ads data-quality triage & fixes.
- [news_digest_relevance_plan.md][plan-newsrel]
  — Implemented: news digest relevance defect fixes.
- [property_conflation_prevention_plan.md][plan-conflation]
  — Partial: phases 1–2 shipped; phase 3 →
  `openspec/changes/add-property-review-surface/`.
- [docs/plans/region_ads_empty_plan.md](docs/plans/region_ads_empty_plan.md)
  — Implemented: Rent-vs-Buy region-ads "0 results" fix.
- [react_frontend_migration/][plan-reactmig]
  — Implemented: Django-template → React+Vite SPA migration.

## OpenSpec — planning layer

`openspec/specs/` holds capability specs describing current,
code-verified behavior. `openspec/changes/` holds proposed
changes (proposal/design/tasks + spec deltas) that merge
into specs on archive. Workflow and rules: AGENTS.md
"OpenSpec" section; run `openspec list` /
`openspec list --specs` for the live inventory.

## Infrastructure

- [terraform/MONITORING.md](terraform/MONITORING.md) —
  monitoring and alerting notes.
- [terraform/SETUP_ALERTS.md](terraform/SETUP_ALERTS.md) —
  alert setup guide.
- `terraform/*.tf` — infrastructure as code (GCP);
  Terraform-managed, no local apply.

## Where new docs go

- Runbook / command guide → `docs/` + row in
  `docs/README.md` and this index.
- Audit / validation / analysis report → `docs/research/`.
- Feature plan / design / investigation → OpenSpec change
  (`openspec/changes/`), never a new `docs/plans/` file.
- App-level reference → `<app>/README.md` /
  `ARCHITECTURE.md` / `QUICK_REFERENCE.md`.
- Update this index and `docs/README.md` whenever a doc is
  added, moved, or removed.

---

**Last updated**: 2026-11 (docs reorganization — research
reports under `docs/research/`, plan statuses, OpenSpec
conversions)

[res-misclass]: docs/research/misclassified_sale_ads_analysis.md
[res-dupsight]: docs/research/duplicate_sightings_validation.md
[res-quar]: docs/research/duplicate_ad_rows_quarantine.md
[res-dbhealth]: docs/research/db_health_report_2026_10.md
[res-propreview]: docs/research/property_match_review_2026_10.md
[res-crossdeal]: docs/research/cross_deal_stats_impact_validation.md
[plan-newsrel]: docs/plans/news_digest_relevance_plan.md
[plan-conflation]: docs/plans/property_conflation_prevention_plan.md
[plan-reactmig]: docs/plans/react_frontend_migration/README.md
