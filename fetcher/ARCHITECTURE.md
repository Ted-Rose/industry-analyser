# Fetcher App Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     PRODUCTION ENVIRONMENT                       │
│                                                                  │
│  ┌──────────────────┐         ┌─────────────────────────────┐  │
│  │ Cloud Scheduler  │         │   GCP Secret Manager        │  │
│  │                  │         │                             │  │
│  │  Cron: 0 2 * * * │         │  industry-analyser-         │  │
│  │  (Daily 2 AM)    │         │  fetcher-portals            │  │
│  └────────┬─────────┘         │                             │  │
│           │                   │  {                          │  │
│           │ HTTP POST         │    "1": {...},              │  │
│           ▼                   │    "2": {...}               │  │
│  ┌──────────────────┐         │  }                          │  │
│  │ Cloud Run Job    │         └──────────────┬──────────────┘  │
│  │ scrape-vacancy   │◄───────────────────────┘                 │
│  │                  │         Mounted as                       │
│  │ Timeout: 8000s   │         FETCHER_PORTALS_JSON             │
│  └────────┬─────────┘                                          │
│           │                                                     │
│           │ Executes                                            │
│           ▼                                                     │
│  ┌──────────────────────────────────────────────────┐          │
│  │ scripts/materialize_fetcher_config_and_scrape.py │          │
│  │                                                   │          │
│  │  1. Read FETCHER_PORTALS_JSON env var            │          │
│  │  2. Build fetcher/config_v2.json                 │          │
│  │  3. Run: python manage.py scrape_first_...       │          │
│  └────────┬─────────────────────────────────────────┘          │
│           │                                                     │
└───────────┼─────────────────────────────────────────────────────┘
            │
            ▼
┌───────────────────────────────────────────────────────────────┐
│                  LOCAL DEVELOPMENT ENVIRONMENT                 │
│                                                                │
│  ┌──────────────────────┐                                     │
│  │ fetcher/config_v2.json│  (gitignored)                      │
│  │                       │                                     │
│  │ {                     │                                     │
│  │   "portals": {...}    │                                     │
│  │ }                     │                                     │
│  └──────────┬────────────┘                                     │
│             │                                                   │
│             │ Read by                                           │
│             ▼                                                   │
│  ┌──────────────────────────────────────┐                     │
│  │ python manage.py                     │                     │
│  │   scrape_first_vacancy_portal        │                     │
│  └──────────┬───────────────────────────┘                     │
│             │                                                   │
└─────────────┼───────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SCRAPER EXECUTION FLOW                      │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ VacancyScrapper.__init__(portal_id)                        │ │
│  │                                                             │ │
│  │  • Load config (env var or file)                           │ │
│  │  • Set enrich_search_results flag                          │ │
│  │  • Cache keywords list                                     │ │
│  └────────────────────┬───────────────────────────────────────┘ │
│                       │                                          │
│                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ run()                                                       │ │
│  │                                                             │ │
│  │  for url in get_search_urls():                             │ │
│  │      resources = scrape_portal(url)                        │ │
│  │      create_or_update_resources(resources)                 │ │
│  └────────────────────┬───────────────────────────────────────┘ │
│                       │                                          │
│                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ get_search_urls()                                          │ │
│  │                                                             │ │
│  │  • Query Keyword.objects.filter(only_filter=False)         │ │
│  │  • Build URL for each keyword:                             │ │
│  │    base_url + search_href + ?limit=1000&keywords[]=python  │ │
│  │                                                             │ │
│  │  Yields: https://www.cv.lv/api/v1/vacancy-search-service/  │ │
│  │          search?limit=1000&keywords[]=python               │ │
│  └────────────────────┬───────────────────────────────────────┘ │
│                       │                                          │
│                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ scrape_portal(url)                                         │ │
│  │                                                             │ │
│  │  1. response = make_request(url)                           │ │
│  │  2. results = parse_results(response)                      │ │
│  │  3. pruned = remove_redundant_results(results)             │ │
│  │  4. return extract_resources(pruned)                       │ │
│  └────────────────────┬───────────────────────────────────────┘ │
│                       │                                          │
│                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ parse_results(response)                                    │ │
│  │                                                             │ │
│  │  if 'application/json' in Content-Type:                    │ │
│  │      data = json.loads(response.data)                      │ │
│  │      return data['vacancies']                              │ │
│  │  else:                                                      │ │
│  │      soup = BeautifulSoup(response.data)                   │ │
│  │      return soup.find_all('div', class_="...")             │ │
│  └────────────────────┬───────────────────────────────────────┘ │
│                       │                                          │
│                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ extract_resources(results)                                 │ │
│  │                                                             │ │
│  │  if enrich_search_results:                                 │ │
│  │      # HTML mode: enrich each result                       │ │
│  │      for result in results:                                │ │
│  │          enriched = enrich_result(result)                  │ │
│  │          resource = initiate_resource(enriched)            │ │
│  │  else:                                                      │ │
│  │      # API mode: direct processing                         │ │
│  │      return initiate_resources(results)                    │ │
│  └────────────────────┬───────────────────────────────────────┘ │
│                       │                                          │
│                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ initiate_resources(results)                                │ │
│  │                                                             │ │
│  │  for result in results:                                    │ │
│  │      # Parse datetime fields                               │ │
│  │      first_seen = parse_datetime(result['publishDate'])    │ │
│  │      deadline = parse_datetime(result['expirationDate'])   │ │
│  │                                                             │ │
│  │      # Create UNSAVED Vacancy instance                     │ │
│  │      vacancy = Vacancy(                                    │ │
│  │          vacancy_portal_id=result['id'],                   │ │
│  │          title=result['positionTitle'],                    │ │
│  │          company_name=result['employerName'],              │ │
│  │          salary_from=result['salaryFrom'],                 │ │
│  │          salary_to=result['salaryTo'],                     │ │
│  │          first_seen=first_seen,                            │ │
│  │          application_deadline=deadline,                    │ │
│  │          ...                                                │ │
│  │      )                                                      │ │
│  │                                                             │ │
│  │      # Store M2M data for later                            │ │
│  │      vacancy._pending_industries = [...]                   │ │
│  │      vacancy._pending_keywords = [...]                     │ │
│  │                                                             │ │
│  │      vacancies.append(vacancy)                             │ │
│  │                                                             │ │
│  │  return vacancies                                          │ │
│  └────────────────────┬───────────────────────────────────────┘ │
│                       │                                          │
│                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ create_or_update_resources(vacancies)                      │ │
│  │                                                             │ │
│  │  # Separate new vs existing                                │ │
│  │  existing_ids = Vacancy.objects.filter(                    │ │
│  │      vacancy_portal_id__in=[v.id for v in vacancies]       │ │
│  │  ).values_list('vacancy_portal_id', flat=True)             │ │
│  │                                                             │ │
│  │  new_vacancies = []                                        │ │
│  │  update_vacancies = []                                     │ │
│  │                                                             │ │
│  │  for vacancy in vacancies:                                 │ │
│  │      if vacancy.vacancy_portal_id in existing_ids:         │ │
│  │          # Update existing                                 │ │
│  │          existing.last_seen = now()                        │ │
│  │          existing.save()                                   │ │
│  │          update_vacancies.append(existing)                 │ │
│  │      else:                                                  │ │
│  │          new_vacancies.append(vacancy)                     │ │
│  │                                                             │ │
│  │  # Bulk create new vacancies                               │ │
│  │  Vacancy.objects.bulk_create(new_vacancies)                │ │
│  │                                                             │ │
│  │  # Add M2M relationships                                   │ │
│  │  for vacancy in new_vacancies + update_vacancies:          │ │
│  │      for industry in vacancy._pending_industries:          │ │
│  │          vacancy.industries.add(industry)                  │ │
│  │      for keyword in vacancy._pending_keywords:             │ │
│  │          vacancy.keywords.add(keyword)                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## Data Flow

```
┌──────────────┐
│  cv.lv API   │
│              │
│  GET /api/v1/│
│  vacancy-    │
│  search-     │
│  service/    │
│  search      │
└──────┬───────┘
       │
       │ HTTP GET
       │ ?limit=1000&keywords[]=python
       │
       ▼
┌──────────────────────────────────────┐
│  JSON Response                        │
│                                       │
│  {                                    │
│    "vacancies": [                     │
│      {                                │
│        "id": 1645116,                 │
│        "positionTitle": "...",        │
│        "employerName": "...",         │
│        "salaryFrom": 1000.0,          │
│        "salaryTo": 2000.0,            │
│        "publishDate": "2026-08-25...",│
│        "expirationDate": "2026-09...",│
│        "categories": [5, 6, 20],      │
│        "keywords": []                 │
│      }                                │
│    ],                                 │
│    "workTimes": {...},                │
│    "categories": {...}                │
│  }                                    │
└──────┬───────────────────────────────┘
       │
       │ Parse JSON
       │
       ▼
┌──────────────────────────────────────┐
│  Vacancy Model Instance               │
│                                       │
│  vacancy_portal_id: 1645116           │
│  title: "..."                         │
│  company_name: "..."                  │
│  salary_from: 1000.0                  │
│  salary_to: 2000.0                    │
│  url: "https://www.cv.lv/lv/vacan... │
│  first_seen: datetime(2026-08-25...)  │
│  last_seen: datetime(now)             │
│  application_deadline: datetime(...)  │
│  state: "CREATED"                     │
│                                       │
│  M2M:                                 │
│  industries: [Industry(5), ...]       │
│  keywords: [Keyword('python'), ...]   │
└──────┬───────────────────────────────┘
       │
       │ Save to DB
       │
       ▼
┌──────────────────────────────────────┐
│  PostgreSQL Database                  │
│                                       │
│  fetcher_vacancy                      │
│  ├─ id (PK)                           │
│  ├─ vacancy_portal_id (UNIQUE)        │
│  ├─ title                             │
│  ├─ company_name                      │
│  ├─ salary_from                       │
│  ├─ salary_to                         │
│  ├─ url                               │
│  ├─ first_seen                        │
│  ├─ last_seen                         │
│  ├─ application_deadline              │
│  └─ state                             │
│                                       │
│  fetcher_vacancy_industries (M2M)     │
│  fetcher_vacancy_keywords (M2M)       │
└───────────────────────────────────────┘
```

## Configuration Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    CONFIGURATION SOURCES                     │
└─────────────────────────────────────────────────────────────┘

PRODUCTION:
┌──────────────────────┐
│ GCP Secret Manager   │
│                      │
│ industry-analyser-   │
│ fetcher-portals      │
│                      │
│ Version: 2           │
│ Created: 2026-08-25  │
└──────────┬───────────┘
           │
           │ Mounted as env var
           │
           ▼
┌──────────────────────────────────┐
│ Cloud Run Job Environment        │
│                                  │
│ FETCHER_PORTALS_JSON='{          │
│   "1": {                         │
│     "id": "1",                   │
│     "type": "api",               │
│     "base_url": "https://...",   │
│     ...                          │
│   }                              │
│ }'                               │
└──────────┬───────────────────────┘
           │
           │ Read by script
           │
           ▼
┌──────────────────────────────────────────┐
│ materialize_fetcher_config_and_scrape.py │
│                                          │
│ portals = json.loads(                    │
│     os.environ['FETCHER_PORTALS_JSON']   │
│ )                                        │
│                                          │
│ config = {                               │
│     "keywords_list": [...],              │
│     "portals": portals                   │
│ }                                        │
│                                          │
│ # Write to file                          │
│ with open('fetcher/config_v2.json'):     │
│     json.dump(config)                    │
└──────────┬───────────────────────────────┘
           │
           │ Creates file
           │
           ▼
┌──────────────────────────┐
│ fetcher/config_v2.json   │
│ (runtime-generated)      │
└──────────┬───────────────┘
           │
           │ Read by scraper
           │
           ▼
┌──────────────────────────┐
│ VacancyScrapper          │
│ load_config()            │
└──────────────────────────┘


LOCAL DEVELOPMENT:
┌──────────────────────────┐
│ fetcher/config_v2.json   │
│ (manually created)       │
│ (gitignored)             │
└──────────┬───────────────┘
           │
           │ Read directly
           │
           ▼
┌──────────────────────────┐
│ VacancyScrapper          │
│ load_config()            │
│                          │
│ if FETCHER_PORTALS_JSON: │
│     # Production         │
│ else:                    │
│     # Local file         │
└──────────────────────────┘
```

## Class Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                      BaseScraper                             │
│                  (core_scraper/base.py)                      │
│                                                              │
│  Abstract Methods:                                           │
│  • get_search_urls() → List[str]                            │
│  • parse_results(response) → List                           │
│  • remove_redundant_results(results) → List                 │
│  • initiate_resources(results) → List[Model]                │
│  • create_or_update_resources(resources) → None             │
│                                                              │
│  Provided Methods:                                           │
│  • run() - Main execution loop                              │
│  • scrape_portal(url) - Single portal scrape                │
│  • make_request(url) - HTTP with retry                      │
│  • sleep(domain) - Rate limiting                            │
│  • extract_resources(results) - API/HTML routing            │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           │ Inherits
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    VacancyScrapper                           │
│                   (fetcher/scraper.py)                       │
│                                                              │
│  Implements:                                                 │
│  • get_search_urls() - Build URLs from keywords             │
│  • parse_results() - Parse JSON or HTML                     │
│  • remove_redundant_results() - Currently no-op             │
│  • initiate_resources() - Create Vacancy instances          │
│  • create_or_update_resources() - Persist to DB             │
│                                                              │
│  Additional Methods:                                         │
│  • _extract_searchable_content() - Combine text fields      │
│  • _find_keywords_in_content() - Regex keyword matching     │
│                                                              │
│  Properties:                                                 │
│  • config - Portal configuration                            │
│  • keywords - Keyword.objects manager                       │
│  • industries - Industry.objects manager                    │
│  • keywords_list - Cached keyword list                      │
│  • enrich_search_results - API vs HTML mode flag            │
└─────────────────────────────────────────────────────────────┘
```

## Database Schema

```
┌─────────────────────────────────────────────────────────────┐
│                      fetcher_vacancy                         │
├─────────────────────────────────────────────────────────────┤
│ id                      INTEGER PRIMARY KEY                  │
│ vacancy_portal_id       INTEGER UNIQUE NOT NULL              │
│ title                   VARCHAR(255)                         │
│ company_name            VARCHAR(255)                         │
│ salary_from             DECIMAL(10,2)                        │
│ salary_to               DECIMAL(10,2)                        │
│ url                     VARCHAR(500)                         │
│ first_seen              TIMESTAMP WITH TIME ZONE             │
│ last_seen               TIMESTAMP WITH TIME ZONE             │
│ application_deadline    TIMESTAMP WITH TIME ZONE             │
│ state                   VARCHAR(50)                          │
└─────────────────────────────────────────────────────────────┘
                           │
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
        ▼                                     ▼
┌───────────────────────┐         ┌───────────────────────┐
│ fetcher_vacancy_      │         │ fetcher_vacancy_      │
│ industries            │         │ keywords              │
├───────────────────────┤         ├───────────────────────┤
│ id                    │         │ id                    │
│ vacancy_id (FK)       │         │ vacancy_id (FK)       │
│ industry_id (FK)      │         │ keyword_id (FK)       │
└───────────────────────┘         └───────────────────────┘
        │                                     │
        │                                     │
        ▼                                     ▼
┌───────────────────────┐         ┌───────────────────────┐
│ fetcher_industry      │         │ fetcher_keyword       │
├───────────────────────┤         ├───────────────────────┤
│ id                    │         │ id                    │
│ name VARCHAR(255)     │         │ name VARCHAR(255)     │
│ ...                   │         │ only_filter BOOLEAN   │
└───────────────────────┘         │ added TIMESTAMP       │
                                  └───────────────────────┘
```

## Error Handling & Retry Logic

```
┌─────────────────────────────────────────────────────────────┐
│                    HTTP Request Flow                         │
└─────────────────────────────────────────────────────────────┘

make_request(url)
    │
    ├─► sleep(domain)  # Rate limiting (1-1s per domain)
    │
    ├─► urllib3.PoolManager.request()
    │       │
    │       │ Retry Strategy:
    │       │ • Total retries: 3
    │       │ • Backoff factor: 30
    │       │ • Status codes: [429, 500, 502, 503, 504]
    │       │
    │       ├─► Success (200) ──────────► Return response
    │       │
    │       ├─► Retry 1 (wait 30s)
    │       │
    │       ├─► Retry 2 (wait 60s)
    │       │
    │       ├─► Retry 3 (wait 120s)
    │       │
    │       └─► MaxRetryError ──────────► Log error, return None
    │
    └─► Return response or None
```

## Keyword Matching Strategy

```
┌─────────────────────────────────────────────────────────────┐
│                  Two-Step Keyword Matching                   │
└─────────────────────────────────────────────────────────────┘

Step 1: Portal Keywords
┌──────────────────────┐
│ API Response         │
│ {                    │
│   "keywords": [      │
│     "python",        │
│     "django"         │
│   ]                  │
│ }                    │
└──────────┬───────────┘
           │
           ├─► Match against Keyword.objects
           │
           └─► vacancy._pending_keywords.append(keyword)


Step 2: Content Scanning
┌──────────────────────────────────────┐
│ Searchable Content                   │
│                                      │
│ title + description + company_name   │
│ → "Senior Python Developer at..."    │
└──────────┬───────────────────────────┘
           │
           ├─► For each keyword in Keyword.objects.all():
           │       pattern = r'\b' + escape(keyword) + r'\b'
           │       if re.search(pattern, content, IGNORECASE):
           │           matched_keywords.append(keyword)
           │
           └─► vacancy._pending_keywords.extend(matched_keywords)


Final Result:
┌──────────────────────────────────────┐
│ vacancy.keywords (M2M)               │
│                                      │
│ • python (from portal)               │
│ • django (from portal)               │
│ • developer (from content scan)      │
│ • senior (from content scan)         │
└──────────────────────────────────────┘
```
