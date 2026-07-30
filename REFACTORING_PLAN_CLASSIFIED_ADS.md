# Classified Ads Scraper Refactoring Plan

## Executive Summary

This refactoring plan addresses two main objectives:
1. **Split apartment listings** into separate `ApartmentForRent` and `ApartmentForSale` tables for better data organization and query performance
2. **Create a flexible architecture** to support scraping multiple product categories from ss.com (cars, clothes, electronics, etc.) in the future

**Important:** Phase 2 focuses on building the infrastructure and documentation to make adding new categories easy. It does not implement any new category scrapers (like cars) - those will be added later as needed.

## Current Architecture Analysis

### Current State
- Single `ClassifiedAd` model handles both rent and sell apartments
- `deal_type` field discriminates between rent/sell
- Hardcoded apartment-specific fields (rooms, floor, size, etc.)
- Scraper tightly coupled to apartment listing structure
- Region-based URL configuration specific to real estate

### Key Observations from Car Ad HTML
- ss.com uses consistent patterns across categories:
  - Breadcrumb navigation: `Vieglie auto / Jeep / Compass / Pārdod`
  - Options table with `class="options_list"` and `class="ads_opt_name"`/`class="ads_opt"`
  - Price in `class="ads_price"`
  - Description in `div#msg_div_msg`
  - Listing pages likely follow similar table structure
- Different categories have different attributes (e.g., cars: marka, year, motor, transmission)

## Refactoring Strategy

### Phase 1: Split Apartment Models (Foundation)
**Goal:** Separate rent and sell apartments into dedicated tables while maintaining existing functionality.

#### 1.1 Create New Models
**File:** `classified_ads/models.py`

Create two new models inheriting shared fields from an abstract base:

```python
class BaseApartmentAd(models.Model):
    """Abstract base for apartment listings"""
    ad_id = models.CharField(max_length=255, unique=True)
    comment = models.TextField(blank=True)
    link = models.URLField(max_length=500)
    region = models.ForeignKey('Region', ...)
    region_name = models.CharField(max_length=255, blank=True)
    district = models.CharField(max_length=255)
    street_name = models.CharField(max_length=255)
    street_no = models.CharField(max_length=50, blank=True)
    rooms = models.IntegerField()
    size = models.FloatField(help_text='Square metres')
    floor = models.IntegerField()
    max_floor = models.IntegerField()
    project = models.CharField(max_length=255)
    house_type = models.CharField(max_length=255, blank=True)
    facilities = models.CharField(max_length=500, blank=True)
    post_date = models.DateTimeField(null=True)
    seller = models.ForeignKey('Seller', ...)
    price_per_sqm = models.FloatField()
    total_price = models.FloatField()
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True

class ApartmentForRent(BaseApartmentAd):
    """Rental apartment listings"""
    monthly_price = models.FloatField()
    monthly_price_per_sqm = models.FloatField()
    # 120-month equivalent for comparison (current alt_price)
    total_price_120m = models.FloatField()
    price_per_sqm_120m = models.FloatField()
    
    class Meta:
        db_table = 'classified_ads_apartment_rent'
        verbose_name = 'Apartment for Rent'
        verbose_name_plural = 'Apartments for Rent'

class ApartmentForSale(BaseApartmentAd):
    """Sale apartment listings"""
    
    class Meta:
        db_table = 'classified_ads_apartment_sale'
        verbose_name = 'Apartment for Sale'
        verbose_name_plural = 'Apartments for Sale'
```

**Rationale:**
- Abstract base eliminates code duplication
- Separate tables improve query performance (no deal_type filtering needed)
- Rent-specific fields (monthly_price) make semantic sense
- Clearer naming: `monthly_price` vs `total_price`

#### 1.2 Create Sighting Models
**File:** `classified_ads/models.py`

```python
class ApartmentForRentSighting(models.Model):
    ad = models.ForeignKey(ApartmentForRent, on_delete=models.CASCADE, related_name='sightings')
    seen_on = models.DateField()
    
    class Meta:
        unique_together = [('ad', 'seen_on')]
        db_table = 'classified_ads_apartment_rent_sighting'

class ApartmentForSaleSighting(models.Model):
    ad = models.ForeignKey(ApartmentForSale, on_delete=models.CASCADE, related_name='sightings')
    seen_on = models.DateField()
    
    class Meta:
        unique_together = [('ad', 'seen_on')]
        db_table = 'classified_ads_apartment_sale_sighting'
```

#### 1.3 Migration Strategy
**Files:** Create migrations in sequence

**Migration 1:** Create new tables
- Add `ApartmentForRent`, `ApartmentForSale`, and sighting models
- Keep old `ClassifiedAd` model temporarily

**Migration 2:** Data migration
```python
def migrate_data_forward(apps, schema_editor):
    ClassifiedAd = apps.get_model('classified_ads', 'ClassifiedAd')
    ApartmentForRent = apps.get_model('classified_ads', 'ApartmentForRent')
    ApartmentForSale = apps.get_model('classified_ads', 'ApartmentForSale')
    
    # Migrate rent ads
    for ad in ClassifiedAd.objects.filter(deal_type='RENT'):
        ApartmentForRent.objects.create(
            ad_id=ad.ad_id,
            monthly_price=ad.total_price,
            monthly_price_per_sqm=ad.price_per_sqm,
            total_price_120m=ad.alt_price,
            price_per_sqm_120m=ad.alt_price_per_sqm,
            # ... copy all other fields
        )
    
    # Migrate sell ads
    for ad in ClassifiedAd.objects.filter(deal_type='SELL'):
        ApartmentForSale.objects.create(
            ad_id=ad.ad_id,
            total_price=ad.total_price,
            price_per_sqm=ad.price_per_sqm,
            # ... copy all other fields
        )
    
    # Migrate sightings
    # ... similar logic
```

**Migration 3:** Remove old models
- Drop `ClassifiedAd` and `ClassifiedAdSighting` tables
- Clean up any remaining references

#### 1.4 Update Scraper
**File:** `classified_ads/scraper.py`

Split into two specialized scrapers:

```python
class BaseApartmentScraper(BaseScraper):
    """Base scraper for apartment listings"""
    
    def __init__(self, max_pages=100):
        super().__init__()
        self.max_pages = max_pages
        self.enrich_search_results = True
        self.validate_result = False
        self.excluded_resources = []
        self._current_region = None
    
    def get_search_urls(self):
        regions = Region.objects.filter(scrape_enabled=True)
        if not regions.exists():
            logger.warning('No regions enabled for scraping.')
            return
        
        for region in regions:
            self._current_region = region
            for page in range(1, self.max_pages + 1):
                if page == 1:
                    yield region.url + self.get_deal_suffix()
                else:
                    yield (region.url + self.get_deal_suffix() 
                           + 'page' + str(page) + '.html')
                if not self.last_search_had_results:
                    break
    
    def get_deal_suffix(self):
        """Override in subclass"""
        raise NotImplementedError
    
    def get_model_class(self):
        """Override in subclass"""
        raise NotImplementedError
    
    def get_sighting_model_class(self):
        """Override in subclass"""
        raise NotImplementedError
    
    # parse_results, enrich_result, _parse_detail_page remain mostly the same
    # but return generic dictionaries
    
    def initiate_resource(self, enriched_result):
        model_class = self.get_model_class()
        # Build kwargs based on model type
        return model_class(**self._build_model_kwargs(enriched_result))
    
    def _build_model_kwargs(self, data):
        """Override in subclass to map data to model fields"""
        raise NotImplementedError


class ApartmentRentScraper(BaseApartmentScraper):
    def get_deal_suffix(self):
        return 'hand_over/'
    
    def get_model_class(self):
        return ApartmentForRent
    
    def get_sighting_model_class(self):
        return ApartmentForRentSighting
    
    def _build_model_kwargs(self, data):
        return {
            'ad_id': data['ad_id'],
            'monthly_price': data['total_price'],
            'monthly_price_per_sqm': data['price_per_sqm'],
            'total_price_120m': data['alt_price'],
            'price_per_sqm_120m': data['alt_price_per_sqm'],
            # ... other fields
        }


class ApartmentSaleScraper(BaseApartmentScraper):
    def get_deal_suffix(self):
        return 'sell/'
    
    def get_model_class(self):
        return ApartmentForSale
    
    def get_sighting_model_class(self):
        return ApartmentForSaleSighting
    
    def _build_model_kwargs(self, data):
        return {
            'ad_id': data['ad_id'],
            'total_price': data['total_price'],
            'price_per_sqm': data['price_per_sqm'],
            # ... other fields
        }
```

#### 1.5 Update Management Commands
**File:** `classified_ads/management/commands/scrape_classified_ads.py`

```python
class Command(BaseCommand):
    help = 'Scrapes apartment listings from ss.com.'
    
    def add_arguments(self, parser):
        parser.add_argument('--max-pages', type=int, default=10)
        parser.add_argument(
            '--type',
            choices=['rent', 'sale', 'both'],
            default='both',
            help='Which apartment type to scrape'
        )
    
    def handle(self, *args, **options):
        scrapers = []
        if options['type'] in ['rent', 'both']:
            scrapers.append(ApartmentRentScraper(max_pages=options['max_pages']))
        if options['type'] in ['sale', 'both']:
            scrapers.append(ApartmentSaleScraper(max_pages=options['max_pages']))
        
        for scraper in scrapers:
            scraper.run()
```

#### 1.6 Update Admin
**File:** `classified_ads/admin.py`

Create separate admin classes for rent and sale:

```python
@admin.register(ApartmentForRent)
class ApartmentForRentAdmin(admin.ModelAdmin):
    list_display = [
        'region_name', 'district', 'rooms', 'size', 'floor',
        'monthly_price', 'monthly_price_per_sqm', 'post_date',
        'seller', 'days_active',
    ]
    # ... similar to current ClassifiedAdAdmin

@admin.register(ApartmentForSale)
class ApartmentForSaleAdmin(admin.ModelAdmin):
    list_display = [
        'region_name', 'district', 'rooms', 'size', 'floor',
        'total_price', 'price_per_sqm', 'post_date',
        'seller', 'days_active',
    ]
    # ... similar to current ClassifiedAdAdmin
```

#### 1.7 Update Views
**File:** `classified_ads/views.py`

Create separate views or add type parameter:

**Option A:** Separate views (cleaner URLs, simpler logic)
```python
def rent_ads_table(request):
    qs = ApartmentForRent.objects.all().order_by('-post_date')
    # ... filtering logic
    return render(request, 'classified_ads/rent_ads_table.html', context)

def sale_ads_table(request):
    qs = ApartmentForSale.objects.all().order_by('-post_date')
    # ... filtering logic
    return render(request, 'classified_ads/sale_ads_table.html', context)
```

**Option B:** Single view with type parameter (less duplication)
```python
def ads_table(request, ad_type='rent'):
    if ad_type == 'rent':
        qs = ApartmentForRent.objects.all()
        price_field = 'monthly_price'
    else:
        qs = ApartmentForSale.objects.all()
        price_field = 'total_price'
    # ... rest of logic
```

Update `region_stats` views similarly to handle both types.

#### 1.8 Update URLs
**File:** `classified_ads/urls.py`

```python
urlpatterns = [
    path('', views.index, name='index'),
    path('rent/', views.rent_ads_table, name='rent_ads_table'),
    path('sale/', views.sale_ads_table, name='sale_ads_table'),
    path('rent/stats/', views.rent_region_stats, name='rent_region_stats'),
    path('sale/stats/', views.sale_region_stats, name='sale_region_stats'),
    # ... etc
]
```

#### 1.9 Update Templates
**Files:** `classified_ads/templates/classified_ads/*.html`

- Update navigation to show separate "Rent" and "Sale" sections
- Update filter forms to remove deal_type dropdown
- Update table headers to show appropriate price fields

---

### Phase 2: Generalize Architecture for Multiple Categories

**Goal:** Build the infrastructure and documentation to make adding new ss.com categories (cars, clothes, electronics, etc.) straightforward in the future. This phase does not implement any new category scrapers - it creates the foundation for easy extension.

#### 2.1 Create Category Configuration System
**File:** `classified_ads/models.py`

```python
class Category(models.Model):
    """Defines a scrapable category from ss.com"""
    CATEGORY_APARTMENT_RENT = 'apartment_rent'
    CATEGORY_APARTMENT_SALE = 'apartment_sale'
    CATEGORY_CAR = 'car'
    CATEGORY_CLOTHING = 'clothing'
    # ... add more as needed
    
    CATEGORY_CHOICES = [
        (CATEGORY_APARTMENT_RENT, 'Apartments for Rent'),
        (CATEGORY_APARTMENT_SALE, 'Apartments for Sale'),
        (CATEGORY_CAR, 'Cars'),
        (CATEGORY_CLOTHING, 'Clothing'),
    ]
    
    code = models.CharField(max_length=50, unique=True, choices=CATEGORY_CHOICES)
    name = models.CharField(max_length=255)
    base_url = models.URLField(max_length=500)
    scraper_class = models.CharField(
        max_length=255,
        help_text='Python path to scraper class, e.g., classified_ads.scrapers.CarScraper'
    )
    model_class = models.CharField(
        max_length=255,
        help_text='Python path to model class, e.g., classified_ads.models.CarAd'
    )
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return self.name


class SubCategory(models.Model):
    """Sub-categories within a category (e.g., Jeep/Compass under Cars, or clothing types)"""
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='subcategories')
    name = models.CharField(max_length=255)
    url = models.URLField(max_length=500, unique=True)
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='children'
    )
    scrape_enabled = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Sub-categories'
    
    def __str__(self):
        return f"{self.category.name} - {self.name}"
```

**Rationale:**
- `Category` defines high-level product types
- `SubCategory` provides hierarchical organization within categories (car brands/models, clothing types, etc.)
- For apartments, `Region` model is preserved and linked to subcategories for geographic organization
- For non-location-based categories (cars, clothing), `SubCategory` is used directly
- Configuration-driven approach allows adding new categories without code changes
- `scraper_class` and `model_class` enable dynamic loading

#### 2.2 Keep Region Model, Link to SubCategory
**File:** `classified_ads/models.py`

The `Region` model will be preserved for apartment listings, as it represents a domain-specific concept (geographic locations). For Phase 2, we'll link regions to subcategories:

```python
class Region(models.Model):
    """Geographic regions for location-based categories (apartments)"""
    name = models.CharField(max_length=255)
    url = models.URLField(max_length=500, unique=True)
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='sub_regions',
    )
    scrape_enabled = models.BooleanField(default=False)
    
    # New field to link to category system
    rent_subcategory = models.ForeignKey(
        SubCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='rent_regions',
        help_text='Links to apartment rent subcategory'
    )
    sale_subcategory = models.ForeignKey(
        SubCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sale_regions',
        help_text='Links to apartment sale subcategory'
    )
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name
```

**Rationale:**
- Keeps existing apartment-specific logic intact
- `Region` remains a meaningful domain concept for real estate
- Two subcategory links allow different configurations for rent vs sale
- Other categories (cars, clothing) use `SubCategory` directly without regions
- Minimal changes to existing apartment scraper code

#### 2.3 Create Generic Scraper Base
**File:** `classified_ads/base_scraper.py`

```python
class SsComBaseScraper(BaseScraper):
    """Base scraper for all ss.com categories"""
    
    category_code = None  # Override in subclass
    
    def __init__(self, max_pages=100):
        super().__init__()
        self.max_pages = max_pages
        self.enrich_search_results = True
        self.validate_result = False
        self.excluded_resources = []
        self._current_subcategory = None
    
    def get_category(self):
        """Get category configuration"""
        return Category.objects.get(code=self.category_code)
    
    def get_search_urls(self):
        """Generate URLs from enabled subcategories"""
        category = self.get_category()
        subcategories = SubCategory.objects.filter(
            category=category,
            scrape_enabled=True
        )
        
        if not subcategories.exists():
            logger.warning(f'No subcategories enabled for {category.name}')
            return
        
        for subcategory in subcategories:
            self._current_subcategory = subcategory
            yield from self._generate_subcategory_urls(subcategory)
    
    def _generate_subcategory_urls(self, subcategory):
        """Generate paginated URLs for a subcategory"""
        for page in range(1, self.max_pages + 1):
            if page == 1:
                yield subcategory.url
            else:
                yield f"{subcategory.url}page{page}.html"
            
            if not self.last_search_had_results:
                break
    
    def parse_results(self, response):
        """Parse listing page - override for category-specific logic"""
        raise NotImplementedError
    
    def parse_detail_page(self, response):
        """Parse detail page - override for category-specific logic"""
        raise NotImplementedError
    
    def extract_common_fields(self, soup):
        """Extract fields common to all categories"""
        result = {
            'comment': '',
            'post_date': None,
            'phone': '',
            'contact_id': '',
        }
        
        # Extract description
        msg_div = soup.find('div', id='msg_div_msg')
        if msg_div:
            for tag in msg_div.find_all(['table', 'div']):
                tag.decompose()
            result['comment'] = msg_div.get_text(separator='\n', strip=True)
        
        # Extract post date
        for td in soup.find_all('td', 'msg_footer'):
            if 'Date' in td.text:
                raw = td.text[6:].strip()
                try:
                    naive = datetime.strptime(raw, '%d.%m.%Y %H:%M')
                    result['post_date'] = timezone.make_aware(naive)
                except ValueError:
                    pass
                break
        
        # Extract contact info
        prefix_span = soup.find('span', id=re.compile(r'^phone_td_'))
        if prefix_span:
            result['phone'] = prefix_span.get_text(strip=True)
        
        mail_link = soup.find('a', href=re.compile(r'/mail/'))
        if mail_link:
            href = mail_link.get('href', '')
            result['contact_id'] = href.split('/')[-1].replace('.html', '')
        
        return result
    
    def extract_price(self, soup):
        """Extract price from detail page"""
        price_td = soup.find('td', class_='ads_price')
        if price_td:
            price_span = price_td.find('span', class_='ads_price')
            if price_span:
                price_text = price_span.get_text(strip=True)
                return self._clean_price(price_text)
        return 0.0
    
    def extract_attributes(self, soup):
        """Extract attributes from options_list table"""
        attributes = {}
        options_table = soup.find('table', class_='options_list')
        if not options_table:
            return attributes
        
        for row in options_table.find_all('tr'):
            name_td = row.find('td', class_='ads_opt_name')
            value_td = row.find('td', class_='ads_opt')
            
            if name_td and value_td:
                key = name_td.get_text(strip=True).rstrip(':')
                value = value_td.get_text(strip=True)
                attributes[key] = value
        
        return attributes
```

#### 2.4 Document How to Add New Categories
**File:** `docs/ADDING_NEW_CATEGORIES.md`

Create comprehensive documentation for adding new product categories in the future. This document should include:

**Documentation Contents:**

1. **Overview of the Category System**
   - Explanation of Category, SubCategory, and how they work
   - When to use Region vs SubCategory

2. **Step-by-Step Guide to Add a New Category**
   - Create the model (with example)
   - Create the scraper (with example)
   - Register in admin
   - Add to Category choices
   - Create management command or use dynamic runner

3. **Example: Adding Car Scraping** (reference implementation)
   ```python
   # Example model structure
   class CarAd(models.Model):
       ad_id = models.CharField(max_length=255, unique=True)
       link = models.URLField(max_length=500)
       subcategory = models.ForeignKey(SubCategory, ...)
       
       # Car-specific fields based on ss.com HTML structure
       brand = models.CharField(max_length=100)
       model = models.CharField(max_length=100)
       year = models.IntegerField(null=True, blank=True)
       engine = models.CharField(max_length=100, blank=True)
       # ... other fields from options_list table
       
       # Common fields (copy from BaseApartmentAd pattern)
       price = models.FloatField()
       comment = models.TextField(blank=True)
       post_date = models.DateTimeField(null=True)
       seller = models.ForeignKey(Seller, ...)
       first_seen = models.DateTimeField(auto_now_add=True)
       last_seen = models.DateTimeField(auto_now=True)
   
   # Example scraper structure
   class CarScraper(SsComBaseScraper):
       category_code = Category.CATEGORY_CAR
       
       def parse_results(self, response):
           # Parse listing page table structure
           # Similar to apartment scraper but with car-specific columns
           pass
       
       def parse_detail_page(self, response):
           # Use extract_common_fields() for shared data
           # Use extract_attributes() for options_list table
           # Map ss.com field names to model fields
           pass
   ```

4. **Common Patterns and Utilities**
   - Using `extract_common_fields()` for description, date, contact
   - Using `extract_attributes()` for options_list table
   - Using `extract_price()` for price extraction
   - Handling different listing page table structures

5. **Testing Checklist**
   - Test listing page parsing
   - Test detail page parsing
   - Test scraping end-to-end
   - Verify data in admin
   - Check sightings tracking

**Rationale:**
- Documentation-first approach ensures future developers can easily extend
- Car example serves as reference without committing to implementation
- Keeps Phase 2 focused on infrastructure, not specific categories
- Allows flexibility to add any category (cars, clothing, electronics) later

#### 2.5 Create Dynamic Scraper Runner
**File:** `classified_ads/management/commands/scrape_ss_com.py`

```python
import importlib

class Command(BaseCommand):
    help = 'Scrapes classified ads from ss.com for any category.'
    
    def add_arguments(self, parser):
        parser.add_argument('--max-pages', type=int, default=10)
        parser.add_argument(
            '--category',
            type=str,
            help='Category code to scrape (e.g., car, apartment_rent)'
        )
    
    def handle(self, *args, **options):
        category_code = options.get('category')
        
        if category_code:
            categories = Category.objects.filter(
                code=category_code,
                is_active=True
            )
        else:
            categories = Category.objects.filter(is_active=True)
        
        for category in categories:
            self.stdout.write(f"Scraping {category.name}...")
            
            # Dynamically load scraper class
            module_path, class_name = category.scraper_class.rsplit('.', 1)
            module = importlib.import_module(module_path)
            scraper_class = getattr(module, class_name)
            
            # Run scraper
            scraper = scraper_class(max_pages=options['max_pages'])
            scraper.run()
            
            self.stdout.write(
                self.style.SUCCESS(f"✓ {category.name} complete")
            )
```

---

### Phase 3: Cleanup and Optimization

#### 3.1 Consolidate Common Patterns
- Extract shared model fields into mixins
- Create reusable template components
- Standardize admin configurations

#### 3.2 Add Category-Specific Views
- Generic list/detail views that work for any category
- Category-specific filtering and statistics
- Cross-category search functionality

#### 3.3 Performance Optimization
- Add database indexes for common queries
- Implement caching for statistics
- Optimize bulk operations

#### 3.4 Testing
- Unit tests for each scraper
- Integration tests for scraping pipeline
- Migration tests for data integrity

---

## Implementation Checklist

### Phase 1: Apartment Split (Estimated: 2-3 days)
- [ ] Create `BaseApartmentAd` abstract model
- [ ] Create `ApartmentForRent` and `ApartmentForSale` models
- [ ] Create sighting models for both types
- [ ] Write and test data migration
- [ ] Update `BaseApartmentScraper` and subclasses
- [ ] Update management command
- [ ] Update admin configuration
- [ ] Update views (rent/sale separation)
- [ ] Update URLs
- [ ] Update templates
- [ ] Test scraping for both types
- [ ] Remove old `ClassifiedAd` model

### Phase 2: Generic Architecture (Estimated: 2-3 days)
- [ ] Create `Category` and `SubCategory` models
- [ ] Add `rent_subcategory` and `sale_subcategory` fields to `Region` model
- [ ] Create apartment rent/sale subcategory records and link to regions
- [ ] Create `SsComBaseScraper` base class with common extraction methods
- [ ] Refactor apartment scrapers to use new base (keep Region-based logic)
- [ ] Create dynamic scraper runner command
- [ ] Add category management to admin
- [ ] Create comprehensive documentation (`docs/ADDING_NEW_CATEGORIES.md`) with car scraping example
- [ ] Test that apartment scraping still works with new architecture

### Phase 3: Cleanup (Estimated: 1-2 days)
- [ ] Extract common model mixins
- [ ] Create generic views
- [ ] Add comprehensive tests
- [ ] Performance optimization
- [ ] Documentation updates

---

## Risk Mitigation

### Data Loss Prevention
- Keep old models until migration is verified
- Create database backup before migrations
- Test migrations on copy of production data
- Implement rollback migrations

### Backward Compatibility
- Maintain old URLs with redirects during transition
- Keep old management commands as deprecated wrappers
- Gradual deprecation with warnings

### Performance Concerns
- Monitor query performance after split
- Add indexes proactively
- Test with production-scale data
- Implement pagination early

---

## Future Enhancements

### Multi-Portal Support
- Abstract beyond ss.com to support other classified ad portals
- Portal-specific scraper adapters
- Unified data model across portals

### Advanced Features
- Price trend analysis per category
- Alert system for new listings matching criteria
- Automated listing quality scoring
- Duplicate detection across categories

### API Development
- REST API for accessing listings
- GraphQL endpoint for flexible queries
- Webhook notifications for new listings

---

## Conclusion

This refactoring plan provides a clear path from the current apartment-only system to a flexible, extensible classified ads platform:

- **Phase 1** (2-3 days): Splits rent/sale apartments into dedicated tables with proper data migration
- **Phase 2** (2-3 days): Builds the Category/SubCategory infrastructure and comprehensive documentation for adding new product types
- **Phase 3** (1-2 days): Cleanup, optimization, and testing

After completion, adding new categories (cars, clothing, electronics, etc.) will be straightforward by following the documented patterns. The phased approach allows for incremental delivery and testing, minimizing risk while maximizing future flexibility.
