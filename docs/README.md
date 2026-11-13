# Documentation

Technical notes, analyses, and decision records for this project.

---

## Runbooks & Command Guides

| Document | Description |
|---|---|
| [Refetch command usage](refetch_command_usage.md) | `BaseRefetchCommand` architecture, all options, examples, VS Code debug configs |
| [Vacancy refetch usage](vacancy_refetch_usage.md) | `refetch_vacancies` — refreshing cv.lv vacancies, companies, keywords, OCR |

## Django Patterns & Gotchas

| Document | Description |
|---|---|
| [Django notes](django_notes.md) | Recurring patterns and pitfalls — includes the custom manager / Admin visibility caveat |

## Pipelines

| Document | Description |
|---|---|
| [News pipeline](news_pipeline.md) | RSS scraping, keyword topic classification, Jaccard story clustering and digest relevance scoring |

## Research & Analysis (`research/`)

Point-in-time audits and validation reports against the production
database. Counts reflect the snapshot date in each title; treat
findings as history, not current state.

| Document | Description |
|---|---|
| [Misclassified sale ads analysis](research/misclassified_sale_ads_analysis.md) | How for-sale apartments end up in the rental table, how to detect them, and the `is_sale_misclassified` flag approach |
| [Duplicate sightings validation](research/duplicate_sightings_validation.md) | Confirms `(ad, seen_on)` dedup prevents double sightings |
| [Duplicate ad rows quarantine](research/duplicate_ad_rows_quarantine.md) | Same-link duplicate rows hidden via `is_hidden` (2026-10 fix) |
| [DB health report 2026-10](research/db_health_report_2026_10.md) | Production DB health audit + dedup findings |
| [Property match review 2026-10](research/property_match_review_2026_10.md) | Probable-duplicate property review (confidence-tiered) |
| [Cross-deal stats impact validation](research/cross_deal_stats_impact_validation.md) | Do cross-deal dupes pollute stats? Validation |

## Plans (`plans/`)

Frozen history — each file carries a status header. All new
planning goes through OpenSpec (`openspec/changes/`); do not add
files here (AGENTS.md rule 11).

## Reference

| Document | Description |
|---|---|
| [Changelog](../changelog.md) | Feature log, to-do items, and operational notes |
| [Coding diary](../coding_diary.md) | Development notes and setup instructions |
