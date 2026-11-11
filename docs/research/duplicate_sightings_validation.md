# Duplicate Sightings Validation Report

**Date:** 2026-09-02  
**Validated by:** Database queries and code analysis  
**Status:** ✅ **PASSED - No duplicates found**

## Executive Summary

The `apartment_scraper.py` is **NOT creating duplicate sightings** for the same date. The implementation correctly prevents duplicates through:

1. Database-level UNIQUE constraints on `(ad_id, seen_on)`
2. Django's `bulk_create()` with `ignore_conflicts=True`
3. Proper handling in the `_write_sightings()` method

## Validation Results

### 1. Historical Data Analysis

**Total Records Checked:**
- Rent sightings: **53,724**
- Sale sightings: **98,582**
- **Total: 152,306 sightings**

**Duplicate Groups Found:**
- Rent duplicates: **0**
- Sale duplicates: **0**

✅ **Result:** No duplicates found in entire historical dataset

### 2. Database Constraints

Both sighting tables have proper UNIQUE constraints:

**Rent Sightings Table:**
```sql
CONSTRAINT classified_ads_apartment_ad_id_seen_on_87e94e92_uniq 
UNIQUE (ad_id, seen_on)
```

**Sale Sightings Table:**
```sql
CONSTRAINT classified_ads_apartment_ad_id_seen_on_ca1b7176_uniq 
UNIQUE (ad_id, seen_on)
```

✅ **Result:** Database constraints properly enforced

### 3. Code Implementation Analysis

**Location:** `classified_ads/apartment_scraper.py`, lines 518-542

The `_write_sightings()` method implementation:

```python
def _write_sightings(self, ad_ids, deal_type):
    today = date.today()
    if deal_type == 'RENT':
        ads = ApartmentForRent.all_objects.filter(ad_id__in=ad_ids)
        sightings = [
            ApartmentForRentSighting(ad=ad, seen_on=today)
            for ad in ads
        ]
        ApartmentForRentSighting.objects.bulk_create(
            sightings,
            ignore_conflicts=True,  # ← Key feature
        )
    else:
        ads = ApartmentForSale.objects.filter(ad_id__in=ad_ids)
        sightings = [
            ApartmentForSaleSighting(ad=ad, seen_on=today)
            for ad in ads
        ]
        ApartmentForSaleSighting.objects.bulk_create(
            sightings,
            ignore_conflicts=True,  # ← Key feature
        )
```

**How it prevents duplicates:**
- `ignore_conflicts=True` tells Django to skip records that violate the UNIQUE constraint
- If a sighting for `(ad_id, seen_on)` already exists, it's silently ignored
- No error is raised, and the scraper continues normally

✅ **Result:** Implementation is correct and safe

### 4. Edge Case Testing

**Scenario:** Running the scraper twice on the same day

**Test Results:**
```
Attempt 1: bulk_create returned 1 object, DB count: 1
Attempt 2: bulk_create returned 1 object, DB count: 1
```

**Note:** `bulk_create` returns the objects it attempted to create, but the database constraint prevents the actual insertion. The final count remains 1.

✅ **Result:** Duplicates are prevented even when scraper runs multiple times

### 5. Recent Activity (Last 30 Days)

**Sightings Created:**
- Rent: 43,351 sightings
- Sale: 77,391 sightings

**Daily Rent Sightings (Last 10 Days):**
```
2026-09-02: 1,449 sightings
2026-09-01: 5,415 sightings
2026-08-31: 4,921 sightings
2026-08-25:   991 sightings
2026-08-21:   496 sightings
2026-08-20:   650 sightings
2026-08-19: 2,628 sightings
2026-08-18: 2,586 sightings
2026-08-17: 2,494 sightings
2026-08-16: 2,466 sightings
```

✅ **Result:** Normal operation, no anomalies detected

### 6. Top Active Ads Analysis

**Most Frequently Seen Ads (Rent):**

1. **Āgenskalns | 1rm | 23m²**
   - Total sightings: 27
   - Active period: 57 days (2026-07-08 to 2026-09-02)
   - Frequency: 0.47 sightings/day

2. **Čiekurkalns | 1rm | 31m²**
   - Total sightings: 25
   - Active period: 57 days
   - Frequency: 0.44 sightings/day

3. **Čiekurkalns | 1rm | 30m²**
   - Total sightings: 25
   - Active period: 57 days
   - Frequency: 0.44 sightings/day

**Observation:** Ads have at most 1 sighting per day, confirming no duplicates

✅ **Result:** Sighting patterns are normal and expected

## How the System Works

### Scraper Flow

1. **Scraper runs** (can be multiple times per day)
2. **For each ad found:**
   - If ad doesn't exist: Create ad + create sighting
   - If ad exists: Update ad + attempt to create sighting
3. **Sighting creation:**
   - `bulk_create(sightings, ignore_conflicts=True)`
   - If `(ad_id, today)` already exists → silently skip
   - If `(ad_id, today)` doesn't exist → create new sighting

### Why This Design is Robust

1. **Database-level protection:** Even if code has bugs, DB won't allow duplicates
2. **Idempotent operations:** Running scraper multiple times has same result
3. **No error handling needed:** `ignore_conflicts=True` makes it graceful
4. **Performance:** `bulk_create` is efficient for batch operations

## Model Definition

From `classified_ads/models.py`:

```python
class ApartmentForRentSighting(models.Model):
    ad = models.ForeignKey(
        ApartmentForRent,
        on_delete=models.CASCADE,
        related_name='sightings',
    )
    seen_on = models.DateField()

    class Meta:
        unique_together = [('ad', 'seen_on')]  # ← Prevents duplicates
        db_table = 'classified_ads_apartment_rent_sighting'
```

## Conclusion

### ✅ Validation Passed

The apartment scraper is working correctly and **NOT creating duplicate sightings**. The system has multiple layers of protection:

1. **Model-level:** `unique_together = [('ad', 'seen_on')]`
2. **Database-level:** UNIQUE constraint enforced by PostgreSQL
3. **Code-level:** `ignore_conflicts=True` handles conflicts gracefully

### Recommendations

1. **No changes needed** - The current implementation is correct
2. **Continue monitoring** - Periodic validation queries can be run to ensure ongoing correctness
3. **Document this behavior** - This report serves as documentation for future reference

### Validation Query

To re-run this validation in the future, use:

```python
from classified_ads.models import (
    ApartmentForRentSighting, ApartmentForSaleSighting
)
from django.db.models import Count

# Check for duplicates
rent_dups = (
    ApartmentForRentSighting.objects
    .values('ad_id', 'seen_on')
    .annotate(count=Count('id'))
    .filter(count__gt=1)
)

sale_dups = (
    ApartmentForSaleSighting.objects
    .values('ad_id', 'seen_on')
    .annotate(count=Count('id'))
    .filter(count__gt=1)
)

print(f'Rent duplicates: {rent_dups.count()}')
print(f'Sale duplicates: {sale_dups.count()}')
```

Expected output: `0` for both queries.

---

**Report Generated:** 2026-09-02  
**Total Records Validated:** 152,306 sightings  
**Duplicates Found:** 0  
**Status:** ✅ PASSED
