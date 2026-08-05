# Django Notes & Patterns

Recurring patterns, gotchas, and decisions specific to this project.

---

## Custom Default Manager Hides Records from Django Admin

**Context:** `ApartmentForRent` uses a custom default manager
(`CleanRentalManager`) that filters out records where
`is_sale_misclassified = True`. This keeps misclassified for-sale ads
out of all application queries automatically.

**The gotcha:** Django Admin also calls `Model.objects` (the default
manager) to build its querysets. With the custom manager in place,
flagged records become **completely invisible** in the Admin panel —
they cannot be viewed, edited, or have their flag toggled.

**The fix:** Override `get_queryset` on the `ModelAdmin` to use the
unfiltered `all_objects` manager instead.

```python
# classified_ads/admin.py

@admin.register(ApartmentForRent)
class ApartmentForRentAdmin(admin.ModelAdmin):
    list_display = (
        'ad_id', 'district', 'rooms', 'size',
        'monthly_price', 'monthly_price_per_sqm',
        'is_sale_misclassified',
    )
    list_filter = ('is_sale_misclassified', 'district')
    list_editable = ('is_sale_misclassified',)
    show_full_result_count = False

    def get_queryset(self, request):
        # Bypass CleanRentalManager so flagged records remain visible
        return self.model.all_objects.get_queryset()
```

`list_editable = ('is_sale_misclassified',)` allows the flag to be
bulk-toggled directly from the changelist without opening each record —
useful for manual review of borderline cases.

**Rule of thumb:** Any time a model overrides the default manager to
filter rows, the corresponding `ModelAdmin` must explicitly opt in to
the base manager via `get_queryset`. The same applies to inline admins
(`InlineModelAdmin.get_queryset`).

**Reference:** [Django docs — Managers and admin
](https://docs.djangoproject.com/en/stable/topics/db/managers/#custom-managers-and-model-inheritance)

---

## Related Documents

- [Misclassified sale ads analysis](misclassified_sale_ads_analysis.md)
  — full analysis of the data quality issue that led to introducing
  `is_sale_misclassified`
