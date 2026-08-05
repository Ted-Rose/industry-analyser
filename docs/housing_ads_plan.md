# Housing Ads Scraping — Implementation Plan

## 1. Current System Overview

The `classified_ads` app scrapes apartment listings from ss.com's `/flats/` category.

### How `SsComScraper` works

```
BaseScraper.run()
  └─ get_search_urls()          # yields paginated URLs per region × deal type
       └─ scrape_portal(url)
            ├─ parse_results()           # extracts rows from 10-col table → list[dict]
            ├─ remove_redundant_results()# drops already-known ads, records sightings
            └─ extract_resources()
                 ├─ enrich_result()      # fetches individual ad detail page
                 ├─ initiate_resource()  # builds ApartmentForRent / ApartmentForSale
                 └─ create_or_update_resources()  # bulk_create + sightings
```

**Key model relationships:**

```
Region (name, url, parent, scrape_enabled)
  ↓ FK
BaseApartmentAd  ← ApartmentForRent / ApartmentForSale
  ↓ FK
ApartmentForRentSighting / ApartmentForSaleSighting  (one row per day seen)
```

**Apartment table** (`parse_results` expects exactly 10 `<td>` per row):

| idx | field      | notes                          |
|-----|------------|--------------------------------|
| 0   | img/thumb  | ignored                        |
| 1   | status     | ignored                        |
| 2   | comment    | ad description text            |
| 3   | address    | district + street (multi-line) |
| 4   | rooms      |                                |
| 5   | size m²    |                                |
| 6   | floor/max  | "3/5" format                   |
| 7   | project    | building series (e.g. "104.")  |
| 8   | price/sqm  |                                |
| 9   | total price|                                |

---

## 2. Housing Ads on ss.com

### URL structure

```
Index page:     https://www.ss.com/lv/real-estate/homes-summer-residences/
Region level:   https://www.ss.com/lv/real-estate/homes-summer-residences/{region}/
Sub-region:     https://www.ss.com/lv/real-estate/homes-summer-residences/{region}/{sub}/
Listings:       https://www.ss.com/lv/real-estate/homes-summer-residences/{region}/{sub}/sell/
Pagination:     .../sell/page2.html, page3.html, ...
```

### Top-level regions (38 total)

`riga`, `jurmala`, `riga-region`, `aizkraukle-and-reg`, `aluksne-and-reg`,
`balvi-and-reg`, `bauska-and-reg`, `cesis-and-reg`, `daugavpils-and-reg`,
`dobele-and-reg`, `gulbene-and-reg`, `jekabpils-and-reg`, `jelgava-and-reg`,
`kraslava-and-reg`, `kuldiga-and-reg`, `liepaja-and-reg`, `limbadzi-and-reg`,
`ludza-and-reg`, `madona-and-reg`, `ogre-and-reg`, `preili-and-reg`,
`rezekne-and-reg`, `saldus-and-reg`, `talsi-and-reg`, `tukums-and-reg`,
`valka-and-reg`, `valmiera-and-reg`, `ventspils-and-reg`, `other`,
`houses-abroad-latvia`

Sub-regions exist for high-density areas (Riga has ~50 districts, Riga Region
has ~30 municipalities).

### House listing table (9 `<td>` per row)

| idx | header (LV)    | field        | notes                              |
|-----|----------------|--------------|------------------------------------|
| 0   | —              | img/thumb    | ignored                            |
| 1   | —              | status       | ignored                            |
| 2   | Sludinājumi    | comment      | ad description text                |
| 3   | Iela           | street       | street name + number               |
| 4   | m²             | size         | house floor area in m²             |
| 5   | Stāvi          | floors       | total number of storeys            |
| 6   | Ist.           | rooms        | room count                         |
| 7   | Zem. pl.       | land_area    | plot size, "239 m²" or "0.11 ha."  |
| 8   | Cena           | total_price  | single price column                |

**Key differences from apartments:**
- 9 cells instead of 10
- `land_area` replaces `project` and `price_per_sqm` (no sqm price in list view)
- `floors` = total storeys only (no current-floor concept)
- No separate "price per m²" column in the listing table

---

## 3. Proposed Architecture

### 3.1 Extend `classified_ads` (recommended)

Add housing models and a new scraper class inside the existing app.
This reuses `Region`, `Seller`, and the helper methods
(`_clean_price`, `_split_street`, `_parse_detail_page`).

**Rationale:**
- `Region` already has `name / url / parent / scrape_enabled` — housing
  regions differ only by URL path (`/homes-summer-residences/` vs `/flats/`).
  The unique constraint on `url` means apartment and housing regions coexist
  without collision.
- `Seller` is domain-agnostic (same seller can list both flats and houses).
- All shared HTML-parsing helpers live in `SsComScraper`; they can be
  extracted to a mixin or base class.

### 3.2 Alternative: New `housing_ads` app

Fully independent app. Cleaner separation but duplicates `Region`, `Seller`,
and shared helpers. Recommended only if the housing domain diverges
significantly from apartments over time.

---

## 4. Implementation Steps

### Step 1 — Add housing models to `classified_ads/models.py`

```python
class BaseHouseAd(models.Model):
    ad_id          = models.CharField(max_length=255, unique=True)
    comment        = models.TextField(blank=True)
    link           = models.URLField(max_length=500)
    region         = models.ForeignKey(
                         'Region', null=True, blank=True,
                         on_delete=models.SET_NULL,
                         related_name='%(class)s_ads')
    region_name    = models.CharField(max_length=255, blank=True)
    district       = models.CharField(max_length=255)
    street_name    = models.CharField(max_length=255)
    street_no      = models.CharField(max_length=50, blank=True)
    rooms          = models.IntegerField()
    size           = models.FloatField(help_text='House floor area m²')
    floors         = models.IntegerField(
                         help_text='Total number of storeys')
    land_area_sqm  = models.FloatField(
                         null=True, blank=True,
                         help_text='Plot area in m²')
    post_date      = models.DateTimeField(null=True)
    seller         = models.ForeignKey(
                         'Seller', null=True, blank=True,
                         on_delete=models.SET_NULL,
                         related_name='%(class)s_ads')
    price_per_sqm  = models.FloatField()
    total_price    = models.FloatField()
    first_seen     = models.DateTimeField(auto_now_add=True)
    last_seen      = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    @property
    def days_active(self):
        return self.sightings.count()


class HouseForSale(BaseHouseAd):
    class Meta:
        db_table = 'classified_ads_house_sale'


class HouseForSaleSighting(models.Model):
    ad       = models.ForeignKey(HouseForSale, on_delete=models.CASCADE,
                                 related_name='sightings')
    seen_on  = models.DateField()

    class Meta:
        unique_together = [('ad', 'seen_on')]
        db_table = 'classified_ads_house_sale_sighting'
```

> **Rent ads for houses:** ss.com does list houses for rent under
> `hand_over/`. A `HouseForRent` model (mirroring `ApartmentForRent` with
> `monthly_price` fields) can be added when rental data is needed.

### Step 2 — Land-area parsing helper

```python
def _parse_land_area(raw: str) -> float | None:
    """
    Convert land area string to m².
    Handles:  "239 m²", "0.11 ha.", "1200"
    Returns None if unparseable.
    """
    raw = raw.strip()
    if not raw or raw == '-':
        return None
    ha_match = re.search(r'([\d.,]+)\s*ha', raw, re.IGNORECASE)
    if ha_match:
        return float(ha_match.group(1).replace(',', '.')) * 10_000
    m2_match = re.search(r'([\d\s,]+)', raw)
    if m2_match:
        try:
            return float(
                m2_match.group(1).replace(',', '').replace(' ', '')
            )
        except ValueError:
            return None
    return None
```

### Step 3 — New scraper class `HousingAdScraper`

Create `classified_ads/housing_scraper.py` (or add to `scraper.py`):

```python
HOUSING_BASE = 'https://www.ss.com/en/real-estate/homes-summer-residences/'

HOUSING_DEAL_SUFFIXES = {
    'sell/': 'SELL',
    # 'hand_over/': 'RENT',  # enable when HouseForRent model exists
}


class HousingAdScraper(BaseScraper):
    """
    Scrapes house/summer-residence listings from ss.com
    /real-estate/homes-summer-residences/.
    """

    def __init__(self, max_pages=100):
        super().__init__()
        self.max_pages = max_pages
        self.enrich_search_results = True
        self.validate_result = False
        self.excluded_resources = []
        self._current_region = None
        self._current_deal_type = None

    def get_search_urls(self):
        # Only regions whose URL contains homes-summer-residences
        regions = Region.objects.filter(
            scrape_enabled=True,
            url__contains='homes-summer-residences',
        )
        if not regions.exists():
            logger.warning('No housing regions enabled for scraping.')
            return

        for region in regions:
            self._current_region = region
            for suffix, deal_type in HOUSING_DEAL_SUFFIXES.items():
                self._current_deal_type = deal_type
                for page in range(1, self.max_pages + 1):
                    if page == 1:
                        yield region.url + suffix
                    else:
                        yield (
                            region.url + suffix
                            + 'page' + str(page) + '.html'
                        )
                    if not self.last_search_had_results:
                        break

    def parse_results(self, response) -> list[dict]:
        if response is None:
            return []
        soup = BeautifulSoup(response.data, 'html.parser')
        results = []
        for row in soup.find_all('tr'):
            tds = row.find_all('td')
            cells = [td.text for td in tds]
            if len(cells) != 9:   # house table has 9 columns
                continue
            row_id = row.get('id')
            if not row_id:
                continue

            link = ''
            for a_tag in row.find_all('a'):
                href = a_tag.get('href', '')
                if href:
                    link = 'https://www.ss.com' + href
                    break

            total_price = self._clean_price(cells[8])
            if total_price == 0.0:
                continue

            try:
                rooms = int(cells[6]) if cells[6].strip().isdigit() else 0
            except (ValueError, TypeError):
                rooms = 0

            try:
                floors = int(cells[5]) if cells[5].strip().isdigit() else 0
            except (ValueError, TypeError):
                floors = 0

            try:
                size = float(
                    cells[4].replace(',', '').strip()
                ) if cells[4].strip() else 0.0
            except (ValueError, TypeError):
                size = 0.0

            land_area = _parse_land_area(cells[7])

            price_per_sqm = (
                round(total_price / size, 2)
                if size > 0 else 0.0
            )

            address_lines = [
                line.strip()
                for line in tds[3].get_text('\n').split('\n')
                if line.strip()
            ]
            street_source = address_lines[-1] if address_lines else ''
            street_name, street_no = self._split_street(street_source)

            ad_id = str(
                row_id + cells[3] + cells[4]
                + cells[5] + cells[6] + cells[7]
            )

            results.append({
                'ad_id': ad_id,
                'deal_type': self._current_deal_type,
                'district': self._current_region.name,
                'region_name': self._current_region.name,
                'link': link,
                'comment': str(cells[2]),
                'street_name': street_name,
                'street_no': street_no,
                'rooms': rooms,
                'size': size,
                'floors': floors,
                'land_area_sqm': land_area,
                'price_per_sqm': price_per_sqm,
                'total_price': total_price,
            })
        return results

    # Reuse helpers from SsComScraper unchanged:
    # _split_street, _clean_price, _parse_detail_page
    # (either duplicate or extract to a shared mixin/base)

    def remove_redundant_results(self, resources):
        ...  # same pattern as SsComScraper — drop existing ad_ids,
             # write sightings for ones already in DB

    def enrich_result(self, partial_result):
        detail_response = self.make_request(partial_result['link'])
        detail = self._parse_detail_page(detail_response)
        return {**partial_result, **detail}

    def initiate_resource(self, enriched_result):
        # build HouseForSale / HouseForRent instance

    def create_or_update_resources(self, ads):
        # bulk_create + write sightings
```

### Step 4 — Refactor shared helpers

Extract `_split_street`, `_clean_price`, and `_parse_detail_page` from
`SsComScraper` into a shared mixin `SsComParserMixin` (or a module-level
function). Both `SsComScraper` and `HousingAdScraper` inherit from it.

```
BaseScraper
  └─ SsComParserMixin  (shared: _clean_price, _split_street,
  │                              _parse_detail_page)
  ├─ SsComScraper        (apartments, /flats/)
  └─ HousingAdScraper    (houses,    /homes-summer-residences/)
```

### Step 5 — Region sync command

Add `classified_ads/management/commands/sync_housing_regions.py`.
Clone the logic of `sync_regions.py` with
`BASE_LV = '/lv/real-estate/homes-summer-residences/'`.

This populates `Region` rows whose URLs contain `homes-summer-residences`.
Admins toggle `scrape_enabled` as usual via the Django admin.

### Step 6 — Management command

Add `classified_ads/management/commands/scrape_housing_ads.py`:

```python
class Command(BaseCommand):
    help = 'Scrapes house listings from ss.com.'

    def add_arguments(self, parser):
        parser.add_argument('--max-pages', type=int, default=10)

    def handle(self, *args, **options):
        scraper = HousingAdScraper(max_pages=options['max_pages'])
        scraper.run()
```

### Step 7 — Migrations

```bash
python manage.py makemigrations classified_ads
python manage.py migrate
```

### Step 8 — Admin registration

Register `HouseForSale` and `HouseForSaleSighting` in
`classified_ads/admin.py` following the same pattern as
`ApartmentForSaleAdmin`.

---

## 5. Data Differences & Edge Cases

| Concern | Notes |
|---|---|
| **Land area units** | ss.com shows "239 m²" or "0.11 ha." — normalise to m² |
| **Missing size** | Some listings omit floor area; skip or store `size=0` |
| **Floors vs floor** | Houses only expose total storeys; store in `floors`, set `floor=0` |
| **Price/sqm absent** | Not in the listing table; derive from `total_price / size` |
| **3-level hierarchy** | Some regions have sub-regions (e.g., Riga → Centrs). The existing `Region.parent` FK already supports this |
| **Rent listings** | `hand_over/` suffix exists on ss.com; defer `HouseForRent` model to a follow-up |
| **"Mājas ārpus Latvijas"** | Houses outside Latvia — may have no meaningful region; safe to skip or capture in `Cits` |
| **Ad-ID uniqueness** | Composed from `row_id + address + size + floors + rooms + land_area` — same formula as apartments |

---

## 6. Suggested File Changes

```
classified_ads/
├── models.py           MODIFY  — add BaseHouseAd, HouseForSale,
│                                  HouseForSaleSighting
├── scraper.py          MODIFY  — extract SsComParserMixin; add
│                                  HousingAdScraper (or new file)
├── admin.py            MODIFY  — register HouseForSale + sighting
├── management/commands/
│   ├── sync_housing_regions.py   NEW
│   └── scrape_housing_ads.py     NEW
└── migrations/
    └── 00XX_add_house_models.py  AUTO-GENERATED
```

---

## 7. Out of Scope (future work)

- `HouseForRent` model and rent scraping
- Price-history charts / analytics views for houses
- Geocoding street addresses to lat/lng
- Misclassification detection (less relevant for houses than for apartments)
