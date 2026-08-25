# Industry Analyser

A Django application that scrapes and analyses Latvian classified-ad
portals for rental and sale apartments, job vacancies, and other
industry data.

## Quick Start

**New to the project?** See the complete setup guide: **[LOCAL_SETUP.md](LOCAL_SETUP.md)**

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env and set SECRET_KEY, DATABASE_URL, etc.

# 4. Run migrations
python manage.py migrate

# 5. Create superuser
python manage.py createsuperuser

# 6. Run development server
python manage.py runserver
```

Visit http://127.0.0.1:8000/admin/ to access the admin interface.

## Documentation

- **[LOCAL_SETUP.md](LOCAL_SETUP.md)** - Complete local development setup guide
- **[docs/](docs/README.md)** - Technical notes, analyses, and planning documents
- **[fetcher/README.md](fetcher/README.md)** - Vacancy scraper documentation
- **[fetcher/ARCHITECTURE.md](fetcher/ARCHITECTURE.md)** - System architecture diagrams
- **[fetcher/QUICK_REFERENCE.md](fetcher/QUICK_REFERENCE.md)** - Quick command reference

## Project Structure

| Path | Purpose |
|---|---|
| `fetcher/` | Job vacancy scraper (cv.lv, likeit.lv) |
| `classified_ads/` | Apartment rental & sale scraper |
| `blogs/` | Blog content scraper |
| `core_scraper/` | Shared scraping base classes |
| `industry_analyser/` | Main Django project settings |
| `docs/` | Technical documentation |
| `terraform/` | Infrastructure as code (GCP) |
| `changelog.md` | Feature log and to-do list |
| `coding_diary.md` | Operational notes and setup commands |

## Common Commands

```bash
# Run scrapers
python manage.py scrape_first_vacancy_portal  # Job vacancies
python manage.py scrape_apartment_ads          # Apartment ads
python manage.py scrape_blogs                  # Blog posts

# Database
python manage.py makemigrations                # Create migrations
python manage.py migrate                       # Apply migrations
python manage.py dbshell                       # Database shell

# Django shell
python manage.py shell                         # Interactive Python shell
python manage.py shell -c "..."                # Run one-liner

# Development
python manage.py runserver                     # Start dev server
python manage.py collectstatic                 # Collect static files
```

## Quick Troubleshooting

**Virtual environment not activated?**
```bash
source venv/bin/activate  # macOS/Linux
.\venv\Scripts\activate   # Windows
```

**Missing dependencies?**
```bash
pip install -r requirements.txt
```

**Database errors?**
```bash
python manage.py migrate
```

**No .env file?**
```bash
cp .env.example .env
# Edit .env and set required variables
```

For detailed troubleshooting, see [LOCAL_SETUP.md](LOCAL_SETUP.md#common-issues).
