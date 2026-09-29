---
description: "Model manager and data-layer conventions in classified_ads and other apps"
trigger: model_decision
---

When working on models, admin, or data queries:

- `classified_ads` models have filtered default managers: `objects`
  excludes `is_hidden=True` (and `is_sale_misclassified=True` on
  `ApartmentForRent`). `all_objects` is the unfiltered manager — use it
  in `ModelAdmin.get_queryset`, refetch commands, and data-fix scripts,
  or rows will silently disappear. See `docs/django_notes.md`.
- Abstract bases `BaseApartmentAd`/`BaseHouseAd` back the concrete
  rent/sale models; add shared fields to the abstract class.
- Daily ad presence is tracked via `*Sighting` models
  (`unique_together(ad, seen_on)`); `days_active` = sighting count.
  Never create duplicate sighting rows for the same ad/day.
- `Region` is a self-referencing tree (`parent` FK) with
  `scrape_enabled` and `order_id`; only enabled regions are scraped.
- `Vacancy` uses `vacancy_portal_id` (unique) as the dedup key and M2M
  through-models (`VacancyIndustries`, `VacancyContainsKeyword`).
