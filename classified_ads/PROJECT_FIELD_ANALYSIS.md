# Project Field Standardization Analysis

## Current State

### Data Distribution

**ApartmentForRent (32 records):**
- 6 unique values
- No empty values

**ApartmentForSale (31 records):**
- 5 unique values  
- No empty values

### Unique Values Found

Combined across both models:
1. **Recon.** - 28 records (44.4%)
2. **Pre-war house** - 15 records (23.8%)
3. **New** - 12 records (19.0%)
4. **Spec. pr.** - 3 records (4.8%)
5. **Stalin project** - 3 records (4.8%)
6. **Czech pr.** - 1 record (1.6%)
7. **Chrusch.** - 1 record (1.6%)

## Standardization Recommendation

### ✅ **YES - Field can be standardized**

The field has:
- Only 7 unique values across 63 records
- Clear patterns (building types/eras)
- No empty values
- Consistent naming conventions

### Proposed Implementation

**Option 1: Django Choices Field (Recommended)**

```python
class BaseApartmentAd(models.Model):
    PROJECT_CHOICES = [
        ('RECON', 'Reconstructed'),
        ('PREWAR', 'Pre-war house'),
        ('NEW', 'New project'),
        ('SPEC', 'Special project'),
        ('STALIN', 'Stalin project'),
        ('CZECH', 'Czech project'),
        ('CHRUSCH', 'Khrushchyovka'),
    ]
    
    project = models.CharField(
        max_length=20,
        choices=PROJECT_CHOICES,
    )
```

**Option 2: Separate Model (For future expansion)**

```python
class BuildingProject(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    def __str__(self):
        return self.name

class BaseApartmentAd(models.Model):
    project = models.ForeignKey(
        'BuildingProject',
        on_delete=models.PROTECT,
    )
```

## Migration Strategy

1. **Create new field** with choices
2. **Data migration** to map existing values:
   - "Recon." → "RECON"
   - "Pre-war house" → "PREWAR"
   - "New" → "NEW"
   - "Spec. pr." → "SPEC"
   - "Stalin project" → "STALIN"
   - "Czech pr." → "CZECH"
   - "Chrusch." → "CHRUSCH"
3. **Remove old field**
4. **Update scraper** to use standardized values

## Benefits

- **Data integrity**: Prevents typos and variations
- **Query performance**: Indexed choices
- **UI consistency**: Dropdown in admin
- **Validation**: Automatic at database level
- **Maintainability**: Clear documentation of valid values

## Scraper Impact

The scraper will need to map scraped values to standardized choices.
This should be done in the parsing logic before saving to database.
