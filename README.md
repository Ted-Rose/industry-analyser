# Industry Analyser

A Django application that scrapes and analyses Latvian classified-ad
portals for rental and sale apartments, job vacancies, and other
industry data.

## Quick start

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server (Unix)
source venv/bin/activate
python manage.py runserver

# Run development server (Windows)
.\venv\Scripts\activate
python manage.py runserver
```

## Documentation

All technical notes, analyses, and planning documents live in
[`docs/`](docs/README.md).

## Key files

| Path | Purpose |
|---|---|
| `classified_ads/` | Apartment rental & sale scraper, models, views |
| `core_scraper/` | Shared scraping base classes |
| `vacancies/` | Job vacancy scraper |
| `blogs/` | Blog content scraper |
| `changelog.md` | Feature log and to-do list |
| `coding_diary.md` | Operational notes and setup commands |
