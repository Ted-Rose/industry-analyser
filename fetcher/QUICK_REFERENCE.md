# Fetcher Quick Reference

Quick commands and snippets for common operations.

## Table of Contents

- [Local Development](#local-development)
- [Production Operations](#production-operations)
- [Database Queries](#database-queries)
- [Configuration](#configuration)
- [Debugging](#debugging)

## Local Development

### Run Scraper

```bash
# Activate virtual environment
source venv/bin/activate

# Run scraper for portal 1 (cv.lv)
python manage.py scrape_first_vacancy_portal
```

### Test with Limited Keywords

```bash
# Start Django shell
python manage.py shell
```

```python
from fetcher.models import Keyword

# Set only specific keywords active
test_keywords = ['python', 'django', 'javascript']
Keyword.objects.exclude(name__in=test_keywords).update(only_filter=True)

# Exit shell and run scraper
# python manage.py scrape_first_vacancy_portal

# Restore all keywords (in shell again)
Keyword.objects.all().update(only_filter=False)
```

### Check Configuration

```python
from fetcher.scraper import VacancyScrapper

scraper = VacancyScrapper(portal_id=1)
print(scraper.config)
print(f"Enrich mode: {scraper.enrich_search_results}")

# Check search URLs
urls = list(scraper.get_search_urls())
print(f"Total URLs: {len(urls)}")
print(f"First URL: {urls[0]}")
```

### Test API Endpoint Directly

```bash
# Test cv.lv API
curl -v "https://www.cv.lv/api/v1/vacancy-search-service/search?limit=1&keywords=python" \
  | python3 -m json.tool

# Check Content-Type header
curl -I "https://www.cv.lv/api/v1/vacancy-search-service/search?limit=1&keywords=python"
```

## Production Operations

### View Secret

```bash
# Set project
gcloud config set project gen-lang-client-0833674612

# View latest version
gcloud secrets versions access latest \
  --secret="industry-analyser-fetcher-portals"

# Pretty print
gcloud secrets versions access latest \
  --secret="industry-analyser-fetcher-portals" \
  | python3 -m json.tool
```

### Update Secret

```bash
# Prepare JSON file (portals object only, not full config)
cat > /tmp/portals.json << 'EOF'
{
  "1": {
    "id": "1",
    "type": "api",
    "base_url": "https://www.cv.lv",
    "search_href": "/api/v1/vacancy-search-service/search",
    "keywords_param": "keywords",
    "limit_param": "limit",
    "vacancy_base_url": "https://www.cv.lv",
    "vacancy_base_href": "/lv/vacancy/",
    "industry_mapping": { ... }
  }
}
EOF

# Create new version
gcloud secrets versions add industry-analyser-fetcher-portals \
  --data-file=/tmp/portals.json

# Verify
gcloud secrets versions access latest \
  --secret="industry-analyser-fetcher-portals"
```

### List Secret Versions

```bash
gcloud secrets versions list industry-analyser-fetcher-portals
```

### Cloud Run Job Operations

```bash
# List jobs
gcloud run jobs list --region=europe-north1

# Describe job (when enabled)
gcloud run jobs describe scrape-vacancy --region=europe-north1

# View job logs (when enabled)
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=scrape-vacancy" \
  --limit 50 \
  --format json

# Manually trigger job (when enabled)
gcloud run jobs execute scrape-vacancy --region=europe-north1
```

### Cloud Scheduler Operations

```bash
# List schedulers
gcloud scheduler jobs list --location=europe-west1

# Describe scheduler (when enabled)
gcloud scheduler jobs describe scrape-vacancy-trigger \
  --location=europe-west1

# Manually trigger (when enabled)
gcloud scheduler jobs run scrape-vacancy-trigger \
  --location=europe-west1
```

## Database Queries

### Check Recent Vacancies

```python
from fetcher.models import Vacancy
from django.utils import timezone
from datetime import timedelta

# Vacancies from last hour
recent = timezone.now() - timedelta(hours=1)
new_vacancies = Vacancy.objects.filter(last_seen__gte=recent)
print(f"Recent vacancies: {new_vacancies.count()}")

# Show details
for v in new_vacancies[:5]:
    print(f"\n{v.vacancy_portal_id}: {v.title}")
    print(f"  Company: {v.company_name}")
    print(f"  Salary: {v.salary_from} - {v.salary_to}")
    print(f"  Keywords: {list(v.keywords.values_list('name', flat=True))}")
```

### Check for Duplicates

```python
from fetcher.models import Vacancy
from django.db.models import Count

# Find duplicate vacancy_portal_ids
duplicates = Vacancy.objects.values('vacancy_portal_id').annotate(
    count=Count('id')
).filter(count__gt=1)

print(f"Duplicate portal IDs: {duplicates.count()}")
for dup in duplicates:
    print(f"  Portal ID {dup['vacancy_portal_id']}: {dup['count']} entries")
```

### Vacancy Statistics

```python
from fetcher.models import Vacancy, Keyword
from django.db.models import Count, Avg

# Total vacancies
total = Vacancy.objects.count()
print(f"Total vacancies: {total}")

# By state
by_state = Vacancy.objects.values('state').annotate(count=Count('id'))
for item in by_state:
    print(f"  {item['state']}: {item['count']}")

# Average salary
avg_salary = Vacancy.objects.aggregate(
    avg_from=Avg('salary_from'),
    avg_to=Avg('salary_to')
)
print(f"Average salary: {avg_salary['avg_from']} - {avg_salary['avg_to']}")

# Top keywords
top_keywords = Keyword.objects.annotate(
    vacancy_count=Count('vacancy')
).order_by('-vacancy_count')[:10]

print("\nTop 10 keywords:")
for kw in top_keywords:
    print(f"  {kw.name}: {kw.vacancy_count} vacancies")
```

### Clean Up Old Vacancies

```python
from fetcher.models import Vacancy
from django.utils import timezone
from datetime import timedelta

# Find vacancies not seen in 90 days
cutoff = timezone.now() - timedelta(days=90)
old_vacancies = Vacancy.objects.filter(last_seen__lt=cutoff)

print(f"Vacancies not seen in 90 days: {old_vacancies.count()}")

# Optional: Delete them
# old_vacancies.delete()
```

## Configuration

### Local Config Structure

```json
{
  "keywords_list": [
    "python",
    "django"
  ],
  "portals": {
    "1": {
      "id": "1",
      "type": "api",
      "base_url": "https://www.cv.lv",
      "search_href": "/api/v1/vacancy-search-service/search",
      "keywords_param": "keywords",
      "limit_param": "limit",
      "vacancy_base_url": "https://www.cv.lv",
      "vacancy_base_href": "/lv/vacancy/",
      "industry_mapping": {
        "1": "1",
        "10": "it"
      }
    }
  }
}
```

### Production Secret Structure

**Important**: The secret contains **only the portals object**, not the full
config!

```json
{
  "1": {
    "id": "1",
    "type": "api",
    "base_url": "https://www.cv.lv",
    "search_href": "/api/v1/vacancy-search-service/search",
    "keywords_param": "keywords",
    "limit_param": "limit",
    "vacancy_base_url": "https://www.cv.lv",
    "vacancy_base_href": "/lv/vacancy/",
    "industry_mapping": {
      "1": "1",
      "10": "it"
    }
  }
}
```

### Extract Config from Local File

```bash
cd /path/to/industry-analyser

# Extract just the portals section for GCP secret
python3 << 'EOF'
import json
with open('fetcher/config_v2.json', 'r') as f:
    config = json.load(f)
    portals = config['portals']
    print(json.dumps(portals, indent=2))
EOF
```

## Debugging

### Enable Debug Logging

```python
import logging

# Set fetcher logger to DEBUG
logging.getLogger('fetcher').setLevel(logging.DEBUG)

# Set core_scraper logger to DEBUG
logging.getLogger('core_scraper').setLevel(logging.DEBUG)

# Run scraper
from fetcher.scraper import VacancyScrapper
scraper = VacancyScrapper(portal_id=1)
scraper.run()
```

### Inspect HTTP Response

```python
from fetcher.scraper import VacancyScrapper

scraper = VacancyScrapper(portal_id=1)
url = list(scraper.get_search_urls())[0]

# Make request
response = scraper.make_request(url)

# Check response
print(f"Status: {response.status}")
print(f"Headers: {response.headers}")
print(f"Content-Type: {response.headers.get('Content-Type')}")

# View raw data
print(f"Data (first 500 chars): {response.data[:500]}")

# Parse JSON
import json
data = json.loads(response.data.decode('utf-8'))
print(f"Vacancies count: {len(data.get('vacancies', []))}")
```

### Test Keyword Matching

```python
from fetcher.scraper import VacancyScrapper

scraper = VacancyScrapper(portal_id=1)

# Test content extraction
result = {
    'positionTitle': 'Senior Python Developer',
    'positionContent': 'We are looking for a Django expert...',
    'employerName': 'Tech Company'
}

content = scraper._extract_searchable_content(result)
print(f"Searchable content: {content}")

# Test keyword matching
keywords = scraper._find_keywords_in_content(content)
print(f"Matched keywords: {[k.name for k in keywords]}")
```

### Test Datetime Parsing

```python
from django.utils.dateparse import parse_datetime

# Test ISO 8601 with timezone
date_str = "2026-08-25T06:38:12.000+00:00"
parsed = parse_datetime(date_str)
print(f"Parsed: {parsed}")
print(f"Type: {type(parsed)}")
print(f"Timezone: {parsed.tzinfo}")
```

### Check Portal Configuration

```python
from fetcher.scraper import VacancyScrapper
import json

# Load all portals
for portal_id in [1, 2, 3]:
    try:
        scraper = VacancyScrapper(portal_id=portal_id)
        print(f"\nPortal {portal_id}:")
        print(f"  Base URL: {scraper.config.get('base_url')}")
        print(f"  Search href: {scraper.config.get('search_href')}")
        print(f"  Type: {scraper.config.get('type', 'HTML')}")
        print(f"  Enrich: {scraper.enrich_search_results}")
        
        # Get first URL
        urls = list(scraper.get_search_urls())
        if urls:
            print(f"  Sample URL: {urls[0]}")
    except Exception as e:
        print(f"\nPortal {portal_id}: ERROR - {e}")
```

### Monitor Scraping Progress

```python
from fetcher.models import Vacancy
from django.utils import timezone
import time

# Before scraping
before_count = Vacancy.objects.count()
before_time = timezone.now()

print(f"Starting count: {before_count}")
print(f"Start time: {before_time}")

# Run scraper in another terminal
# python manage.py scrape_first_vacancy_portal

# After scraping
time.sleep(60)  # Wait for scraper to finish
after_count = Vacancy.objects.count()
after_time = timezone.now()

new_count = after_count - before_count
duration = (after_time - before_time).total_seconds()

print(f"\nEnding count: {after_count}")
print(f"New vacancies: {new_count}")
print(f"Duration: {duration}s")
print(f"Rate: {new_count/duration:.2f} vacancies/second")
```

### Test Single Keyword

```python
from fetcher.scraper import VacancyScrapper

scraper = VacancyScrapper(portal_id=1)

# Build URL for single keyword
base_url = scraper.config['base_url'] + scraper.config['search_href']
test_url = base_url + "?limit=10&keywords[]=python"

print(f"Testing URL: {test_url}")

# Scrape
response = scraper.make_request(test_url)
results = scraper.parse_results(response)

print(f"Results found: {len(results)}")

# Process first result
if results:
    first = results[0]
    print(f"\nFirst result:")
    print(f"  ID: {first.get('id')}")
    print(f"  Title: {first.get('positionTitle')}")
    print(f"  Company: {first.get('employerName')}")
    print(f"  Salary: {first.get('salaryFrom')} - {first.get('salaryTo')}")
```

## Common Issues

### Issue: "No results found"

```python
# Debug the API response
from fetcher.scraper import VacancyScrapper
import json

scraper = VacancyScrapper(portal_id=1)
url = list(scraper.get_search_urls())[0]
response = scraper.make_request(url)

print(f"Status: {response.status}")
print(f"Content-Type: {response.headers.get('Content-Type')}")

data = json.loads(response.data.decode('utf-8'))
print(f"Keys in response: {data.keys()}")
print(f"Vacancies: {len(data.get('vacancies', []))}")
```

### Issue: IntegrityError on duplicate

```python
# Check for existing vacancy before creating
from fetcher.models import Vacancy

portal_id = 1645116
existing = Vacancy.objects.filter(vacancy_portal_id=portal_id).first()

if existing:
    print(f"Vacancy {portal_id} already exists:")
    print(f"  ID: {existing.id}")
    print(f"  Title: {existing.title}")
    print(f"  Last seen: {existing.last_seen}")
else:
    print(f"Vacancy {portal_id} does not exist")
```

### Issue: Datetime parsing error

```python
# Test datetime parsing
from django.utils.dateparse import parse_datetime

test_dates = [
    "2026-08-25T06:38:12.000+00:00",  # ISO 8601 with timezone
    "2026-08-25 06:38:12",             # Simple format
    "2026-08-25",                      # Date only
]

for date_str in test_dates:
    try:
        parsed = parse_datetime(date_str)
        print(f"✅ '{date_str}' → {parsed}")
    except Exception as e:
        print(f"❌ '{date_str}' → ERROR: {e}")
```

## Performance Monitoring

### Measure Scraping Time

```bash
# Time the scraper
time python manage.py scrape_first_vacancy_portal
```

### Count Requests

```python
from fetcher.scraper import VacancyScrapper

scraper = VacancyScrapper(portal_id=1)
urls = list(scraper.get_search_urls())

print(f"Total keywords: {len(urls)}")
print(f"Estimated time (1s per request): {len(urls)}s")
print(f"Estimated time (2s per request): {len(urls) * 2}s")
```

### Database Query Performance

```python
from django.db import connection
from django.test.utils import CaptureQueriesContext

with CaptureQueriesContext(connection) as queries:
    # Run your code here
    from fetcher.models import Vacancy
    vacancies = list(Vacancy.objects.all()[:100])

print(f"Total queries: {len(queries)}")
for q in queries[:5]:
    print(f"  {q['sql'][:100]}...")
```
