# Local Development Setup Guide

Complete guide to setting up the Industry Analyser project on your local
machine for development.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
- [Database Setup](#database-setup)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Fetcher App Setup](#fetcher-app-setup)
- [Verification](#verification)
- [Common Issues](#common-issues)
- [Development Workflow](#development-workflow)

## Prerequisites

### Required Software

- **Python 3.12.x** (project requires `~=3.12.0`)
- **Git** (for version control)
- **pip** (Python package manager, comes with Python)
- **virtualenv** or **venv** (for isolated Python environments)

### Optional but Recommended

- **PostgreSQL** (for production-like database, optional for local dev)
- **Docker** (if you want to run PostgreSQL in a container)
- **gcloud CLI** (for production deployment)

### Check Your Python Version

```bash
python3 --version
# Should output: Python 3.12.x
```

If you don't have Python 3.12, install it:

**macOS** (using Homebrew):
```bash
brew install python@3.12
```

**Ubuntu/Debian**:
```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-dev
```

**Windows**:
Download from [python.org](https://www.python.org/downloads/)

## Initial Setup

### 1. Clone the Repository

```bash
git clone <repository-url> industry-analyser
cd industry-analyser
```

### 2. Create Virtual Environment

**macOS/Linux**:
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows**:
```bash
python -m venv venv
.\venv\Scripts\activate
```

You should see `(venv)` in your terminal prompt.

### 3. Install Dependencies

**Option A: Using pip** (recommended for development):
```bash
pip install -r requirements.txt
```

**Option B: Using uv** (faster, if you have it):
```bash
uv pip install -r requirements.txt
```

### 4. Verify Installation

```bash
python -c "import django; print(f'Django {django.get_version()}')"
# Should output: Django 5.x.x (or similar)
```

## Database Setup

You have two options for local development:

### Option A: SQLite (Easiest, Recommended for Quick Start)

SQLite requires no additional setup - it's a file-based database that Django
creates automatically.

**Advantages**:
- No installation required
- Zero configuration
- Perfect for development

**Disadvantages**:
- Not production-like
- Limited concurrency
- Some features differ from PostgreSQL

**Setup**: Just use the default `.env` configuration (see Configuration
section below).

### Option B: PostgreSQL (Production-Like)

**Advantages**:
- Matches production environment
- Full feature set
- Better for testing production scenarios

**Installation**:

**macOS** (using Homebrew):
```bash
brew install postgresql@15
brew services start postgresql@15
```

**Ubuntu/Debian**:
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
```

**Docker** (any OS):
```bash
docker run --name industry-analyser-db \
  -e POSTGRES_PASSWORD=devpassword \
  -e POSTGRES_USER=devuser \
  -e POSTGRES_DB=industry_analyser \
  -p 5432:5432 \
  -d postgres:15
```

**Create Database**:
```bash
# If using local PostgreSQL
createdb industry_analyser

# Or connect and create manually
psql postgres
CREATE DATABASE industry_analyser;
CREATE USER devuser WITH PASSWORD 'devpassword';
GRANT ALL PRIVILEGES ON DATABASE industry_analyser TO devuser;
\q
```

## Configuration

### 1. Create Environment File

Copy the example environment file:

```bash
cp .env.example .env
```

### 2. Edit `.env` File

Open `.env` in your editor and configure:

**For SQLite** (default, easiest):
```bash
# Database Configuration
DATABASE_URL=sqlite:///db.sqlite3

# Django Settings
SECRET_KEY=your-secret-key-here-change-this-in-production
DEBUG=True
HARD_CODED_PASSWORD=admin123

# API Keys (optional for basic functionality)
GEMINI_API_KEY=your-gemini-api-key-here
OMDB_KEY=your-omdb-key-here

# Other Settings
BASE_URL=http://127.0.0.1:8000
```

**For PostgreSQL**:
```bash
# Database Configuration
DATABASE_URL=postgresql://devuser:devpassword@localhost:5432/industry_analyser

# Django Settings
SECRET_KEY=your-secret-key-here-change-this-in-production
DEBUG=True
HARD_CODED_PASSWORD=admin123

# API Keys (optional)
GEMINI_API_KEY=your-gemini-api-key-here
OMDB_KEY=your-omdb-key-here

# Other Settings
BASE_URL=http://127.0.0.1:8000
```

**Generate a Secret Key**:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 3. Run Migrations

Create the database tables:

```bash
python manage.py migrate
```

You should see output like:
```
Running migrations:
  Applying contenttypes.0001_initial... OK
  Applying auth.0001_initial... OK
  Applying fetcher.0001_initial... OK
  ...
```

### 4. Create Superuser

Create an admin account:

```bash
python manage.py createsuperuser
```

Follow the prompts:
- Username: `admin` (or your choice)
- Email: `admin@example.com` (or your choice)
- Password: (enter a password)

### 5. Load Initial Data (Optional)

If there are fixtures or initial data:

```bash
# Load keywords for fetcher
python manage.py loaddata fetcher/fixtures/keywords.json

# Load industries
python manage.py loaddata fetcher/fixtures/industries.json
```

**Note**: Check if these fixture files exist first:
```bash
ls -la fetcher/fixtures/
```

If they don't exist, you'll need to create keywords and industries manually
through the admin interface or Django shell.

## Running the Application

### 1. Start Development Server

```bash
python manage.py runserver
```

You should see:
```
Starting development server at http://127.0.0.1:8000/
Quit the server with CONTROL-C.
```

### 2. Access the Application

Open your browser and navigate to:

- **Main site**: http://127.0.0.1:8000/
- **Admin interface**: http://127.0.0.1:8000/admin/

Login with the superuser credentials you created.

### 3. Verify Static Files

If static files aren't loading:

```bash
python manage.py collectstatic --noinput
```

## Fetcher App Setup

The fetcher app scrapes job vacancies from various portals. It requires
additional configuration.

### 1. Create Fetcher Configuration

The fetcher uses a local configuration file that's gitignored:

```bash
# Create the config file
cat > fetcher/config_v2.json << 'EOF'
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
        "2": "2",
        "3": "3",
        "4": "4",
        "5": "5",
        "6": "6",
        "7": "7",
        "8": "8",
        "9": "9",
        "10": "it",
        "11": "11",
        "12": "12",
        "13": "13",
        "14": "14",
        "15": "15",
        "16": "16",
        "17": "17",
        "18": "18",
        "19": "19",
        "20": "20"
      }
    }
  }
}
EOF
```

**Note**: This file is gitignored to prevent accidental commits of sensitive
or environment-specific data.

### 2. Create Keywords in Database

You need keywords in the database for the scraper to work:

```bash
python manage.py shell
```

```python
from fetcher.models import Keyword

# Create some test keywords
keywords = [
    'python', 'django', 'javascript', 'react', 'node.js',
    'java', 'spring', 'php', 'laravel', 'ruby',
    'devops', 'aws', 'docker', 'kubernetes', 'terraform'
]

for kw in keywords:
    Keyword.objects.get_or_create(name=kw.lower(), defaults={'only_filter': False})

print(f"Created {Keyword.objects.count()} keywords")
exit()
```

### 3. Create Industries (Optional)

```bash
python manage.py shell
```

```python
from fetcher.models import Industry

industries = [
    ('1', 'Administration'),
    ('2', 'Finance'),
    ('3', 'Construction'),
    ('it', 'Information Technology'),
    ('5', 'Sales'),
    ('6', 'Service'),
    ('7', 'Healthcare'),
    ('8', 'Education'),
]

for code, name in industries:
    Industry.objects.get_or_create(name=code, defaults={'display_name': name})

print(f"Created {Industry.objects.count()} industries")
exit()
```

### 4. Test the Scraper

Run a test scrape with limited keywords:

```bash
# Limit to just 1-2 keywords for testing
python manage.py shell
```

```python
from fetcher.models import Keyword

# Temporarily disable most keywords
test_keywords = ['python']
Keyword.objects.exclude(name__in=test_keywords).update(only_filter=True)
print(f"Active keywords: {list(Keyword.objects.filter(only_filter=False).values_list('name', flat=True))}")
exit()
```

```bash
# Run the scraper
python manage.py scrape_first_vacancy_portal
```

You should see output like:
```
INFO Searching URL: https://www.cv.lv/api/v1/vacancy-search-service/search?limit=1000&keywords[]=python
INFO Created 33 new vacancies.
INFO Created or updated 33 resources
```

**Restore all keywords**:
```bash
python manage.py shell -c "from fetcher.models import Keyword; Keyword.objects.all().update(only_filter=False)"
```

## Verification

### Check Everything is Working

1. **Web server running**:
   ```bash
   curl http://127.0.0.1:8000/
   # Should return HTML
   ```

2. **Admin accessible**:
   - Visit http://127.0.0.1:8000/admin/
   - Login with superuser credentials

3. **Database connected**:
   ```bash
   python manage.py dbshell
   # Should open database shell
   # Type \q (PostgreSQL) or .quit (SQLite) to exit
   ```

4. **Migrations applied**:
   ```bash
   python manage.py showmigrations
   # All should show [X] (applied)
   ```

5. **Static files working**:
   - Admin interface should have proper styling
   - If not, run: `python manage.py collectstatic`

6. **Fetcher configured**:
   ```bash
   python manage.py shell -c "from fetcher.scraper import VacancyScrapper; s = VacancyScrapper(1); print(s.config)"
   # Should print portal configuration
   ```

## Common Issues

### Issue: `ModuleNotFoundError: No module named 'django'`

**Solution**: Activate virtual environment
```bash
source venv/bin/activate  # macOS/Linux
.\venv\Scripts\activate   # Windows
```

### Issue: `django.db.utils.OperationalError: no such table`

**Solution**: Run migrations
```bash
python manage.py migrate
```

### Issue: `ImproperlyConfigured: Set the SECRET_KEY environment variable`

**Solution**: Create `.env` file with `SECRET_KEY`
```bash
cp .env.example .env
# Edit .env and set SECRET_KEY
```

### Issue: PostgreSQL connection refused

**Solution**: Check PostgreSQL is running
```bash
# macOS
brew services list | grep postgresql

# Linux
sudo systemctl status postgresql

# Docker
docker ps | grep postgres
```

### Issue: `fetcher/config_v2.json` not found

**Solution**: Create the config file (see Fetcher App Setup above)

### Issue: Static files not loading (no CSS in admin)

**Solution**: Collect static files
```bash
python manage.py collectstatic --noinput
```

### Issue: Port 8000 already in use

**Solution**: Use a different port
```bash
python manage.py runserver 8001
```

Or kill the process using port 8000:
```bash
# macOS/Linux
lsof -ti:8000 | xargs kill -9

# Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

### Issue: `psycopg2` installation fails

**Solution**: Install system dependencies

**macOS**:
```bash
brew install postgresql
```

**Ubuntu/Debian**:
```bash
sudo apt install libpq-dev python3-dev
```

**Or use binary version** (already in requirements.txt):
```bash
pip install psycopg2-binary
```

## Development Workflow

### Daily Workflow

1. **Activate virtual environment**:
   ```bash
   source venv/bin/activate
   ```

2. **Pull latest changes**:
   ```bash
   git pull
   ```

3. **Install new dependencies** (if requirements.txt changed):
   ```bash
   pip install -r requirements.txt
   ```

4. **Run migrations** (if models changed):
   ```bash
   python manage.py migrate
   ```

5. **Start development server**:
   ```bash
   python manage.py runserver
   ```

### Making Changes

1. **Create a new branch**:
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make your changes**

3. **Run migrations** (if you changed models):
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

4. **Test your changes**:
   ```bash
   # Run the development server
   python manage.py runserver
   
   # Or run specific management commands
   python manage.py scrape_first_vacancy_portal
   ```

5. **Commit and push**:
   ```bash
   git add .
   git commit -m "Description of changes"
   git push origin feature/my-feature
   ```

### Running Management Commands

**List all available commands**:
```bash
python manage.py help
```

**Common commands**:
```bash
# Database
python manage.py migrate
python manage.py makemigrations
python manage.py dbshell

# Users
python manage.py createsuperuser
python manage.py changepassword <username>

# Scrapers
python manage.py scrape_first_vacancy_portal
python manage.py scrape_blogs
python manage.py scrape_apartment_ads
python manage.py scrape_housing_ads

# Data
python manage.py loaddata <fixture>
python manage.py dumpdata <app> > fixture.json

# Shell
python manage.py shell
python manage.py shell -c "from fetcher.models import Vacancy; print(Vacancy.objects.count())"
```

### Django Shell Quick Reference

```bash
python manage.py shell
```

```python
# Import models
from fetcher.models import Vacancy, Keyword, Industry
from classified_ads.models import ApartmentAd
from django.contrib.auth.models import User

# Query data
Vacancy.objects.all()
Vacancy.objects.filter(company_name__icontains='google')
Vacancy.objects.count()

# Create data
keyword = Keyword.objects.create(name='python', only_filter=False)

# Update data
Keyword.objects.filter(name='python').update(only_filter=True)

# Delete data
Vacancy.objects.filter(state='EXPIRED').delete()

# Exit
exit()
```

### Testing the Fetcher

**Quick test** (1 keyword):
```bash
python manage.py shell -c "
from fetcher.models import Keyword
Keyword.objects.exclude(name='python').update(only_filter=True)
"
python manage.py scrape_first_vacancy_portal
python manage.py shell -c "
from fetcher.models import Keyword
Keyword.objects.all().update(only_filter=False)
"
```

**Check results**:
```bash
python manage.py shell -c "
from fetcher.models import Vacancy
from django.utils import timezone
from datetime import timedelta
recent = timezone.now() - timedelta(hours=1)
count = Vacancy.objects.filter(last_seen__gte=recent).count()
print(f'Vacancies scraped in last hour: {count}')
"
```

### Resetting the Database

**SQLite** (easiest):
```bash
rm db.sqlite3
python manage.py migrate
python manage.py createsuperuser
```

**PostgreSQL**:
```bash
# Drop and recreate database
dropdb industry_analyser
createdb industry_analyser
python manage.py migrate
python manage.py createsuperuser
```

## Project Structure

```
industry-analyser/
├── .env                          # Environment variables (gitignored)
├── .env.example                  # Example environment file
├── manage.py                     # Django management script
├── requirements.txt              # Python dependencies
├── pyproject.toml               # Project metadata
├── db.sqlite3                   # SQLite database (gitignored)
├── venv/                        # Virtual environment (gitignored)
│
├── industry_analyser/           # Main Django project
│   ├── settings.py              # Django settings
│   ├── urls.py                  # URL routing
│   └── wsgi.py                  # WSGI config
│
├── fetcher/                     # Vacancy scraper app
│   ├── models.py                # Vacancy, Keyword, Industry models
│   ├── scraper.py               # Scraping logic
│   ├── config_v2.json           # Local config (gitignored)
│   ├── README.md                # Fetcher documentation
│   ├── ARCHITECTURE.md          # Architecture diagrams
│   ├── QUICK_REFERENCE.md       # Quick commands
│   └── management/
│       └── commands/
│           └── scrape_first_vacancy_portal.py
│
├── classified_ads/              # Apartment scraper app
│   ├── models.py
│   ├── scraper.py
│   └── management/commands/
│
├── blogs/                       # Blog scraper app
│   └── ...
│
├── core_scraper/                # Shared scraping base classes
│   └── base.py
│
├── docs/                        # Documentation
│   └── README.md
│
└── terraform/                   # Infrastructure as code
    └── main.tf
```

## Next Steps

After completing the setup:

1. **Explore the admin interface**: http://127.0.0.1:8000/admin/
2. **Read the fetcher documentation**: `fetcher/README.md`
3. **Check the project docs**: `docs/README.md`
4. **Review the changelog**: `changelog.md`
5. **Try running different scrapers**

## Additional Resources

- **Django Documentation**: https://docs.djangoproject.com/
- **cv.lv API Docs**: https://www.cv.lv/api/doc/swagger-ui/index.html
- **Project Documentation**: `docs/`
- **Fetcher Architecture**: `fetcher/ARCHITECTURE.md`
- **Quick Reference**: `fetcher/QUICK_REFERENCE.md`

## Getting Help

If you encounter issues:

1. Check this guide's [Common Issues](#common-issues) section
2. Review the fetcher troubleshooting guide: `fetcher/README.md#troubleshooting`
3. Check recent git commits for context
4. Review the task documentation in `docs/`

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | `sqlite:///db.sqlite3` | Database connection string |
| `SECRET_KEY` | Yes | - | Django secret key (generate with random string) |
| `DEBUG` | No | `False` | Enable debug mode (set to `True` for development) |
| `HARD_CODED_PASSWORD` | No | - | Admin password for quick access |
| `GEMINI_API_KEY` | No | - | Google Gemini API key (for AI features) |
| `OMDB_KEY` | No | - | OMDB API key (for movie data) |
| `BASE_URL` | No | `http://127.0.0.1:8000` | Base URL for the application |
| `ALLOWED_HOST_IP` | No | - | Additional allowed host (e.g., LAN IP) |
| `FETCHER_PORTALS_JSON` | No | - | Portal config (production only, uses file locally) |
| `DB_SSL_CERT` | No | - | Database SSL certificate (production only) |

## Quick Start Checklist

- [ ] Python 3.12 installed
- [ ] Repository cloned
- [ ] Virtual environment created and activated
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] `.env` file created and configured
- [ ] Migrations run (`python manage.py migrate`)
- [ ] Superuser created (`python manage.py createsuperuser`)
- [ ] Development server running (`python manage.py runserver`)
- [ ] Admin interface accessible (http://127.0.0.1:8000/admin/)
- [ ] `fetcher/config_v2.json` created
- [ ] Keywords created in database
- [ ] Test scrape successful

You're all set! Happy coding! 🚀
