# Misclassified For-Sale Ads in Rental Apartment Table

**Date:** 2026-07-30  
**Table analysed:** `classified_ads_apartment_rent`  
**Total records at time of analysis:** 3,476 (count may grow with scraping)

---

## 1. Problem Statement

A significant number of entries in the rental apartment table
(`classified_ads_apartment_rent`) are actually apartments listed for
sale. Sellers have mistakenly posted them under the rental category on
the classified-ads portal. These records severely distort statistics:

| Metric | All records | Correct rentals only |
|---|---|---|
| Average price/sqm (€/month) | 94.27 | 9.86 |
| Average monthly price (€) | 5,454 | 777 |
| Median price/sqm (€/month) | 10.43 | 9.30 |

A realistic long-term rental in Latvia is **8–15 €/sqm/month**. The
median is unaffected because most records are genuine rentals, but the
mean is pulled significantly upward by ~520 misclassified sale ads.

---

## 2. Identification Signals

Two complementary signals identify misclassified records.

### 2.1 Price Signal — `monthly_price_per_sqm > 50`

The scraped `monthly_price` for these records is actually the **full
sale price** of the property. When divided by square metres it produces
a price/sqm figure that is impossible for a monthly rent.

| Price bucket (€/sqm/month) | Record count | Notes |
|---|---|---|
| < 5 | 480 | Very cheap, likely rural true rentals |
| 5 – 10 | 1,116 | Core of the market |
| 10 – 15 | 844 | Normal Riga pricing |
| 15 – 20 | 311 | Premium but realistic |
| 20 – 30 | 102 | High-end / short-term |
| 30 – 50 | 49 | Borderline: Jūrmala seasonal + rural sale ads |
| **50 – 100** | **38** | **Almost certainly misclassified** |
| **100 – 500** | **284** | **Misclassified** |
| **500 – 1,000** | **134** | **Misclassified** |
| **≥ 1,000** | **65** | **Misclassified** |

**520 records (15.1% of total)** exceed 50 €/sqm — a clear anomaly.

> **Note on the 30–50 range:** This range contains two distinct
> sub-populations: (a) legitimate **seasonal summer rentals in
> Jūrmala** (Majori, Bulduri, Dzintari, Dubulti — 21 records), and
> (b) rural for-sale apartments misclassified as rentals. The keyword
> signal below disambiguates them reliably.

### 2.2 Keyword Signal — Latvian/Russian Sale Language in `comment`

Comments frequently contain clear Latvian or Russian sale vocabulary.
Sellers often write without Latvian diacritical marks (ā→a, ē→e, etc.),
so both accented and unaccented variants must be checked.

| Keyword pattern | Unaccented variant | Language | Meaning |
|---|---|---|---|
| `%pārdod%` | `%pardod%` | LV | "sells / for sale" (pārdod, pārdodam) |
| `%pārdošan%` | `%pardosan%` | LV | "for sale" (pārdošanā, pārdošanas) |
| `%pārdots%` | `%pardots%` | LV | "has been sold / is being sold" |
| `%izpirkum%` | — | LV | "redemption rights" (izpirkuma, izpirkumu) |
| `%pirkt%` | — | LV | "to buy" |
| `%продаётся%` | — | RU | "is for sale" |
| `%Продаем%` | — | RU | "we sell" |
| `%Продается%` | — | RU | "is for sale" |
| `%Продам%` | — | RU | "will sell / for sale" |

> **Removed from earlier draft:** `%pirkum%` was too broad — it matches
> innocent phrases like "ikdienas **pirkumiem**" (everyday shopping) and
> "vinnējis **iepirkumu**" (won a procurement tender), generating
> confirmed false positives. Replaced with the more specific `%izpirkum%`
> which only matches redemption/purchase-right vocabulary.
>
> **Added:** Unaccented variants `%pardod%` and `%pardots%` — 24
> additional misclassified records were found using this pattern (sellers
> writing without macrons).

Of the 520 price-flagged records, with the refined keyword list:
- **413 (79.4%)** contain at least one sale keyword
- **107 (20.6%)** have no keywords (developer projects "Island Park" /
  "AlmaHome" using neutral language — caught by price signal only)

---

## 3. Case Study: Sigulda District

Sigulda was chosen because it is small (10 records) with a clear mix
of 9 genuine rentals and 1 misclassified sale ad.

### Record 11490 — misclassified

```
monthly_price = 88,000 EUR   monthly_price_per_sqm = 2,378 €/sqm
```

Comment key phrases:
- *"ar izpirkuma tiesībām"* — with purchase/redemption rights
- *"Dzīvokļa vērtība 88000 eur"* — Apartment value 88,000 EUR
- *"Pirmā iemaksa – 10% no dzīvokļa pirkuma cenas"* — First payment
  = 10% of purchase price
- *"Šobrīd pieejami izdevīgi kreditēšanās piedāvājumi"* — Bank
  financing available

This is a **rent-to-own** listing: a sale price has been entered as
the monthly rent.

### Impact on Sigulda averages

| Filter | Records | Avg €/sqm/month | Avg monthly € |
|---|---|---|---|
| All | 10 | 247.25 | 9,266 |
| Exclude price > 50 | 9 | 10.50 | 518 |
| Exclude sale keywords | 9 | 10.50 | 518 |

A monthly rent of **~518 EUR** for a 2–3 room apartment in Sigulda is
realistic. The single misclassified record inflates the average monthly
price from €518 to €9,266 — a **17× distortion**.

---

## 4. Full Dataset Validation

Four filtering strategies, applied globally (3,476 total records):

| Strategy | Records kept | Avg €/sqm | Avg monthly € | Removed |
|---|---|---|---|---|
| Baseline | 3,476 | 94.11 | 5,444 | — |
| **A — Price ≤ 50 €/sqm** | 2,944 | 10.09 | 786 | 532 |
| **B — Keywords only (original)** | 3,019 | 47.52 | 3,123 | 457 |
| **C — Price ≤ 50 + original keywords** | 2,902 | 9.85 | 774 | 574 |
| **C+ — Price ≤ 50 + refined keywords** | 2,908 | 9.86 | 774 | 568 |

- **Strategy A** alone: misses records with sale keywords but price ≤ 50
  (64 additional misclassifications in the 30–50 €/sqm zone)
- **Strategy B** alone: misses developer-style ads with no sale keywords
  (avg stays at 47 €/sqm — still distorted)
- **Strategy C** (combined): most accurate, 9.85 €/sqm
- **Strategy C+** (refined keywords): 6 fewer false positives than C
  while matching nearly identical averages — the recommended approach

**C+ keeps 6 more legitimate records** than C by removing the broad
`%pirkum%` grocery-shopping false matches, with no measurable accuracy
loss (9.86 vs 9.85 €/sqm).

---

## 5. Cross-District Validation

### 5.1 Approach A — False Positive Test (Jūrmala Seasonal Rentals)

A key concern was that the 50 €/sqm price threshold would incorrectly
exclude legitimate **high-season summer rentals in Jūrmala**. Queries
across all major Jūrmala districts showed:

| District | Records | Excluded by A | Avg €/sqm (all) | Avg €/sqm (A) |
|---|---|---|---|---|
| Dzintari | 53 | 0 | 14.17 | 14.17 |
| Majori | 42 | 0 | 15.00 | 15.00 |
| Bulduri | 38 | 0 | 13.99 | 13.99 |
| Dubulti | 30 | 0 | 15.56 | 15.56 |
| Lielupe | 7 | 0 | 11.68 | 11.68 |
| Ķemeri | 12 | **12** | 930.50 | — |

**Result:** The 50 €/sqm threshold does NOT remove any legitimate Jūrmala
seasonal rentals. Even peak-summer beach apartments in Majori and Bulduri
stay below 50 €/sqm. Ķemeri (930 €/sqm) is correctly identified as
entirely misclassified.

> Note: a separate anomaly exists for **event-rental records** (concert
> weekends in Liepāja — "Prāta Vētra", "Summer Sound"). These have high
> absolute monthly prices (7,000–16,500 EUR) but normal €/sqm (3–10)
> because they are large apartments rented for 1–2 nights. They pass the
> filter correctly but are not representative long-term rentals. This is a
> separate data quality issue outside the scope of this analysis.

### 5.2 Approach B — False Negative Test (Developer Ads Without Keywords)

Two developer projects expose the weakness of keyword-only filtering:

| Project | District | Records | Avg monthly | Avg €/sqm | Keywords found |
|---|---|---|---|---|---|
| Island Park | Zaķusala | 8 | 143,220 EUR | 2,832 | **0** |
| AlmaHome | Aplokciems | 10+ | 116,500 EUR | 2,300+ | **0** |

Both use neutral marketing language ("Piedāvājumā …", "pieejami dzīvokļi
…") with no sale vocabulary. **Strategy B passes all 18 of these records**
while Strategy A (and C+) correctly removes them via the price threshold.

### 5.3 Approach C+ — Per-District Results

Validation across selected districts with the refined C+ filter:

**Riga districts (large, no misclassification expected):**

| District | Records | Removed | Avg €/sqm (all) | Avg €/sqm (C+) |
|---|---|---|---|---|
| Centrs | 707 | 2 (0.3%) | 12.20 | 12.18 |
| Āgenskalns | 162 | 2 (1.2%) | 12.44 | 12.40 |
| Pļavnieki | 95 | 0 | 8.39 | 8.39 |
| Purvciems | 88 | 0 | 7.97 | 7.97 |
| Imanta | 85 | 0 | 8.17 | 8.17 |
| Teika | 82 | 0 | 11.34 | 11.34 |
| Ziepniekkalns | 62 | 1 (1.6%) | 9.60 | 8.48 |
| Jugla | 45 | 0 | 9.46 | 9.46 |
| Mežciems | 45 | 0 | 10.04 | 10.04 |
| Mežaparks | 38 | 0 | 12.29 | 12.29 |
| Vecmīlgrāvis | 29 | 0 | 7.40 | 7.40 |

8 out of 11 major Riga districts: **zero records removed**. The 2 removed
from Centrs and Āgenskalns are borderline rent-to-own/dual-listing records
(not clean long-term rentals). Impact on district averages: < 0.1 €/sqm.

**Problem districts (correctly cleaned):**

| District | Records | Removed | Avg €/sqm (all) | Avg €/sqm (C+) |
|---|---|---|---|---|
| Aplokciems | 20 | 18 (90%) | 1,987 | 10.72 |
| Sigulda | 10 | 1 (10%) | 247.25 | 10.50 |
| Skrunda | 9 | 8 (89%) | 336.19 | 3.70 |
| Nīgrandes pag. | 12 | 12 (100%) | 90.29 | — |
| Zaķusala | 8 | 8 (100%) | 2,832 | — |
| Liepāja | 204 | 0 | 3.88 | 3.88 |
| Jelgava | 124 | 0 | 6.70 | 6.70 |

Cities outside Riga with clean rental markets (Liepāja, Jelgava) pass
through unmodified. Districts that are entirely composed of misclassified
for-sale ads return NULL — correct behaviour.

**Cleaned averages after C+ filter (reference values):**

| District | Clean records | Avg monthly € | Avg €/sqm |
|---|---|---|---|
| Mežaparks | 38 | 735 | 12.29 |
| Centrs | 705 | 759 | 12.18 |
| Āgenskalns | 160 | 545 | 12.40 |
| Teika | 82 | 639 | 11.34 |
| Sigulda | 9 | 518 | 10.50 |
| Mežciems | 45 | 519 | 10.04 |
| Jugla | 45 | 429 | 9.46 |
| Ziepniekkalns | 61 | 484 | 8.48 |
| Pļavnieki | 95 | 492 | 8.39 |
| Imanta | 85 | 493 | 8.17 |
| Purvciems | 88 | 543 | 7.97 |
| Jelgava | 124 | 493 | 6.70 |
| Liepāja | 204 | — * | 3.88 |

*Liepāja avg monthly is skewed by event-rental records (see note in 5.1).

All values are consistent with publicly available Latvian rental market
data.

### 5.4 Entirely Misclassified Districts (C+ removes 100%)

The following districts have **no genuine rental records** in the table —
every entry is a for-sale ad entered in the wrong category:

| District | Records | Avg listed price | Avg listed €/sqm |
|---|---|---|---|
| Bēnes pag. | 22 | 13,395 | 256 |
| Gailīšu pag. | 16 | 21,050 | 331 |
| Lielplatones pag. | 14 | 19,929 | 329 |
| Smārdes pag. | 14 | 47,387 | 1,111 |
| Auru pag. | 14 | 23,371 | 448 |
| Nīgrandes pag. | 12 | 6,633 | 90 |
| Ķemeri | 12 | 60,333 | 931 |
| Rundāles pag. | 12 | 31,500 | 520 |
| Auce | 10 | 19,560 | 388 |
| Dobeles pag. | 10 | 10,500 | 241 |
| Nīcas pag. | 10 | 46,500 | 793 |
| Mālpils pag. | 8 | 28,563 | 619 |
| Šķēdes pag. | 8 | 5,113 | 75 |
| Naudītes pag. | 8 | 15,775 | 228 |
| Durbe | 8 | 22,375 | 383 |
| Zaķusala | 8 | 143,220 | 2,832 |
| … | … | … | … |

These districts should produce no results (or display a "no rental data"
message) rather than showing distorted averages as if they were rentals.

### 5.5 False Positive Analysis for Approach C+

**Genuine false positives confirmed: 5–8 records total** (out of 2,908
passing C+).

| Root cause | Records affected | Fix applied |
|---|---|---|
| `%pirkum%` matching "pirkumiem" (grocery shopping) | 5 | Replaced with `%izpirkum%` |
| `%pārdošan%` matching "autostāvvietām (īrei/**pārdošanai**)" | 2 | Accepted (tiny impact) |
| `%pirkt%` matching "**atpirkt**" (buy back — rental with purchase option) | 1 | Accepted (gray area) |

The remaining false positives are **ambiguous dual listings** (owner
renting AND selling simultaneously) — excluding these from rental
statistics is arguably correct, since their long-term rental price is
uncertain.

**False positive rate after refinement: < 0.03%** (< 9 records out of
3,476 total).

---

## 6. Approaches for Categorisation

The validated C+ keyword list used in all code samples below:

```python
# Validated — see Section 5 for false-positive / false-negative analysis
SALE_KEYWORDS = [
    # Latvian — accented
    '%pārdod%', '%pārdošan%', '%pārdots%', '%izpirkum%', '%pirkt%',
    # Latvian — unaccented (common in informal ads)
    '%pardod%', '%pardosan%', '%pardots%',
    # Russian
    '%продаётся%', '%Продаем%', '%Продается%', '%Продам%',
]
PRICE_THRESHOLD = 50  # €/sqm/month — above this = sale price
```

### Approach 1 — Application-level Filter (No DB Change) ⭐ Quickest

Add a reusable filter to every Django queryset that accesses rental
data.

```python
def clean_rental_qs(qs):
    """Exclude misclassified for-sale ads (Strategy C+)."""
    from django.db.models import Q
    keyword_filter = Q()
    for kw in SALE_KEYWORDS:
        keyword_filter |= Q(comment__ilike=kw)
    return qs.filter(
        monthly_price_per_sqm__lte=PRICE_THRESHOLD
    ).exclude(keyword_filter)
```

**Pros:** Zero migrations, immediate effect, reversible.  
**Cons:** Every query path must call the helper. Easy to forget in new
views or management commands.

**Validated result:** Removes 568 records, avg drops from 94 to
9.86 €/sqm. False positive rate < 0.03%.

---

### Approach 2 — Boolean Flag Column on `ApartmentForRent` ⭐ Recommended

Add `is_sale_misclassified = BooleanField(default=False)` to the
model. Populate it via a data migration using the price + keyword
logic, then filter it in the default queryset.

```python
class ApartmentForRent(BaseApartmentAd):
    monthly_price = models.FloatField()
    monthly_price_per_sqm = models.FloatField()
    total_price_120m = models.FloatField()
    price_per_sqm_120m = models.FloatField()
    is_sale_misclassified = models.BooleanField(default=False)

    class Meta:
        db_table = 'classified_ads_apartment_rent'
```

A custom default manager excludes flagged records automatically:

```python
class CleanRentalManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(
            is_sale_misclassified=False
        )

class ApartmentForRent(BaseApartmentAd):
    ...
    objects = CleanRentalManager()
    all_objects = models.Manager()  # bypass when needed
```

> **Django Admin caveat:** Django Admin uses `Model.objects` (the default
> manager) by default. With `CleanRentalManager` as `objects`, flagged
> records will be **invisible** in Admin — you cannot see or toggle them.
> Override `show_full_result_count` and `get_queryset` on the `ModelAdmin`
> to use `all_objects` instead:
>
> ```python
> @admin.register(ApartmentForRent)
> class ApartmentForRentAdmin(admin.ModelAdmin):
>     list_display = (
>         'ad_id', 'district', 'rooms', 'size',
>         'monthly_price', 'monthly_price_per_sqm',
>         'is_sale_misclassified',
>     )
>     list_filter = ('is_sale_misclassified', 'district')
>     list_editable = ('is_sale_misclassified',)
>     show_full_result_count = False
>
>     def get_queryset(self, request):
>         # Use the unfiltered manager so all records are visible in Admin
>         return self.model.all_objects.get_queryset()
> ```
>
> With `list_editable = ('is_sale_misclassified',)` the flag can be
> toggled directly from the changelist without opening each record.

Data migration SQL to auto-populate (~568 records flagged):

```sql
UPDATE classified_ads_apartment_rent
SET is_sale_misclassified = TRUE
WHERE monthly_price_per_sqm > 50
   OR comment ILIKE '%pārdod%'   OR comment ILIKE '%pardod%'
   OR comment ILIKE '%pārdošan%' OR comment ILIKE '%pardosan%'
   OR comment ILIKE '%pārdots%'  OR comment ILIKE '%pardots%'
   OR comment ILIKE '%izpirkum%'
   OR comment ILIKE '%pirkt%'
   OR comment ILIKE '%продаётся%'
   OR comment ILIKE '%Продаем%'
   OR comment ILIKE '%Продается%'
   OR comment ILIKE '%Продам%';
-- Expected: ~568 rows updated
```

The scraper should also set this flag at ingest time using the same
logic, so newly scraped misclassified ads are flagged immediately.

**Pros:**  
- Persistent and explicit — flag survives re-scrapes  
- Reversible — original data intact, flag can be flipped  
- Admin override (above) makes manual review and bulk-toggling trivial  
- Handles rent-to-own ambiguity gracefully  

**Cons:**  
- Requires one migration  
- Need to audit all existing querysets to confirm they use `objects`
  (and not `all_objects`) so the filter is applied consistently  

---

### Approach 3 — Database View `v_rental_apartments_clean`

Create a PostgreSQL view that embeds the filter logic. Map it to a
separate unmanaged Django model for read-only analytics use.

```sql
CREATE OR REPLACE VIEW v_rental_apartments_clean AS
SELECT *
FROM classified_ads_apartment_rent
WHERE monthly_price_per_sqm <= 50
  AND comment NOT ILIKE '%pārdod%'   AND comment NOT ILIKE '%pardod%'
  AND comment NOT ILIKE '%pārdošan%' AND comment NOT ILIKE '%pardosan%'
  AND comment NOT ILIKE '%pārdots%'  AND comment NOT ILIKE '%pardots%'
  AND comment NOT ILIKE '%izpirkum%'
  AND comment NOT ILIKE '%pirkt%'
  AND comment NOT ILIKE '%продаётся%'
  AND comment NOT ILIKE '%Продаем%'
  AND comment NOT ILIKE '%Продается%'
  AND comment NOT ILIKE '%Продам%';
```

**Pros:** Filter is centralised in DB, no Django model change for the
main table.  
**Cons:** Two models diverge; writes go to the base table; view cannot
be updated via ORM; Aiven may require elevated privileges for view
creation.

---

### Approach 4 — Move Records to `ApartmentForSale` Table

Physically migrate misclassified rows into `classified_ads_apartment_sale`.

**Pros:** Cleanest data integrity.  
**Cons:**  
- `ApartmentForRent` has columns that `ApartmentForSale` does not
  (`monthly_price`, `monthly_price_per_sqm`, `total_price_120m`,
  `price_per_sqm_120m`) — data loss on migration  
- For rent-to-own records the "correct" table is ambiguous  
- Irreversible without backup  
- New misclassified scraped records need ongoing migration logic  

**Verdict:** Not recommended. The schema mismatch and ongoing
operational burden outweigh the data-integrity benefit.

---

## 7. Special Case: Rent-to-Own Ads (`izpirkuma tiesībām`)

At least **9 records** use the Latvian term for "redemption/purchase
rights" — these are rent-to-own agreements that are genuinely both
rentals and sales. Options:

1. Flag as `is_sale_misclassified = TRUE` (exclude from rental stats)
   — conservative choice, simple  
2. Add a separate `is_rent_to_own` flag — more granular, enables a
   future rent-to-own section  
3. Create a third model `ApartmentRentToOwn` — most expressive, but
   significant overhead

For analytics purposes option 1 is simplest: the listed price is a
sale price, not a monthly rent, so excluding from rental averages is
correct regardless.

---

## 8. Recommended Implementation Plan

1. **Immediate (no migrations):** Apply the C+ filter helper (Approach
   1) to all views and aggregation queries. Use `monthly_price_per_sqm
   __lte=50` + refined keyword exclusions.

2. **Short term:** Implement Approach 2 — add `is_sale_misclassified`
   boolean column, write a Django data migration running the SQL from
   Section 6, update the scraper ingest logic to auto-flag on creation.

3. **Scraper update:** At ingest time, evaluate each new
   `ApartmentForRent` record against the C+ conditions and set
   `is_sale_misclassified = True` immediately if matched.

4. **Do not implement** Approach 4 (physical move to sale table) —
   schema mismatch and irreversibility make it high risk for minimal
   gain.

---

## 9. Summary of Validated Numbers

| Fact | Value |
|---|---|
| Total rental records (at analysis time) | 3,476 |
| Misclassified by price > 50 €/sqm | 532 (15.3 %) |
| Of those: also have sale keywords | 413 (77.6 %) |
| Of those: no keywords (developer ads) | 119 (22.4 %) |
| Extra misclassified: price ≤ 50 but sale keywords | ~36 additional |
| Total flagged by C+ strategy | ~568 (16.3 %) |
| Districts with 100% misclassified records | 20+ |
| Confirmed false positives (C+) | < 9 (0.03 %) |
| Realistic avg rental €/sqm after C+ filter | **9.86 €/sqm/month** |
| Realistic avg monthly rental after C+ filter | **~774 €** |
| Pre-filter avg (distorted) | 94.11 €/sqm / 5,444 € avg monthly |
