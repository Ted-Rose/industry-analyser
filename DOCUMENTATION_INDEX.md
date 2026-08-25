# Documentation Index

Complete guide to all documentation in the Industry Analyser project.

## 🚀 Getting Started

**New to the project?** Start here:

1. **[LOCAL_SETUP.md](LOCAL_SETUP.md)** - Complete step-by-step setup guide
2. **[README.md](README.md)** - Project overview and quick start
3. **[.env.example](.env.example)** - Environment configuration template

## 📚 Core Documentation

### Main Project

| Document | Description | Audience |
|----------|-------------|----------|
| [LOCAL_SETUP.md](LOCAL_SETUP.md) | Complete local development setup guide | New developers |
| [README.md](README.md) | Project overview, quick start, common commands | Everyone |
| [.env.example](.env.example) | Environment variables template | Developers |
| [requirements.txt](requirements.txt) | Python dependencies | Developers |
| [pyproject.toml](pyproject.toml) | Project metadata and configuration | Developers |

### Fetcher App (Vacancy Scraper)

| Document | Description | Audience |
|----------|-------------|----------|
| [fetcher/README.md](fetcher/README.md) | Complete fetcher documentation | Developers working on scraper |
| [fetcher/ARCHITECTURE.md](fetcher/ARCHITECTURE.md) | System architecture and diagrams | Developers, architects |
| [fetcher/QUICK_REFERENCE.md](fetcher/QUICK_REFERENCE.md) | Quick command reference | Developers (daily use) |
| [docs/cvlv_api_integration_task.md](docs/cvlv_api_integration_task.md) | cv.lv API integration task details | Developers |

### Infrastructure

| Document | Description | Audience |
|----------|-------------|----------|
| [terraform/main.tf](terraform/main.tf) | Infrastructure as code (GCP) | DevOps, deployment |
| [terraform/variables.tf](terraform/variables.tf) | Terraform variables | DevOps |

## 📖 Documentation by Use Case

### "I want to set up the project locally"

1. Read **[LOCAL_SETUP.md](LOCAL_SETUP.md)** - Complete setup guide
2. Follow the checklist in LOCAL_SETUP.md
3. Refer to **[.env.example](.env.example)** for configuration
4. Check **[README.md](README.md)** for quick commands

### "I want to understand the fetcher/scraper"

1. Read **[fetcher/README.md](fetcher/README.md)** - Overview and how it works
2. Review **[fetcher/ARCHITECTURE.md](fetcher/ARCHITECTURE.md)** - System design
3. Use **[fetcher/QUICK_REFERENCE.md](fetcher/QUICK_REFERENCE.md)** - For commands
4. Check **[docs/cvlv_api_integration_task.md](docs/cvlv_api_integration_task.md)** - Recent fixes

### "I want to work on the fetcher"

1. **[fetcher/README.md](fetcher/README.md)** - Understand the architecture
2. **[fetcher/QUICK_REFERENCE.md](fetcher/QUICK_REFERENCE.md)** - Common commands
3. **[LOCAL_SETUP.md](LOCAL_SETUP.md#fetcher-app-setup)** - Setup instructions
4. **[fetcher/ARCHITECTURE.md](fetcher/ARCHITECTURE.md)** - Deep dive into design

### "I want to deploy to production"

1. **[fetcher/README.md](fetcher/README.md#production-deployment)** - Production setup
2. **[terraform/main.tf](terraform/main.tf)** - Infrastructure configuration
3. **[fetcher/QUICK_REFERENCE.md](fetcher/QUICK_REFERENCE.md#production-operations)** - GCP commands
4. **[docs/cvlv_api_integration_task.md](docs/cvlv_api_integration_task.md)** - Recent changes

### "I'm debugging an issue"

1. **[LOCAL_SETUP.md](LOCAL_SETUP.md#common-issues)** - Common issues
2. **[fetcher/README.md](fetcher/README.md#troubleshooting)** - Fetcher troubleshooting
3. **[fetcher/QUICK_REFERENCE.md](fetcher/QUICK_REFERENCE.md#debugging)** - Debug commands
4. **[README.md](README.md#quick-troubleshooting)** - Quick fixes

## 📋 Documentation by Topic

### Setup & Configuration

- **[LOCAL_SETUP.md](LOCAL_SETUP.md)** - Complete setup guide
  - Prerequisites
  - Initial setup
  - Database setup (SQLite vs PostgreSQL)
  - Environment configuration
  - Verification steps
  - Common issues

- **[.env.example](.env.example)** - Environment variables
  - Database configuration
  - Django settings
  - API keys
  - Production settings

- **[fetcher/README.md](fetcher/README.md#configuration)** - Fetcher config
  - Local vs production configuration
  - Configuration schema
  - Portal configuration
  - GCP Secret Manager

### Architecture & Design

- **[fetcher/ARCHITECTURE.md](fetcher/ARCHITECTURE.md)** - System architecture
  - System overview diagram
  - Data flow diagram
  - Configuration flow
  - Class hierarchy
  - Database schema
  - Error handling
  - Keyword matching

- **[fetcher/README.md](fetcher/README.md#how-it-works)** - Scraping flow
  - API vs HTML scraping
  - Keyword matching
  - Database operations
  - Date/time handling

### Operations & Commands

- **[fetcher/QUICK_REFERENCE.md](fetcher/QUICK_REFERENCE.md)** - Quick commands
  - Local development
  - Production operations
  - Database queries
  - Debugging
  - Performance monitoring

- **[README.md](README.md#common-commands)** - Common commands
  - Scrapers
  - Database
  - Django shell
  - Development

### Deployment & Infrastructure

- **[terraform/main.tf](terraform/main.tf)** - Infrastructure as code
  - Cloud Run jobs
  - Cloud Scheduler
  - Secret Manager
  - IAM permissions

- **[fetcher/README.md](fetcher/README.md#production-deployment)** - Production
  - Cloud Run job architecture
  - Configuration management
  - Environment variables
  - Updating production config
  - Deployment status

### Troubleshooting

- **[LOCAL_SETUP.md](LOCAL_SETUP.md#common-issues)** - Setup issues
  - Module not found
  - Database errors
  - Configuration errors
  - Port conflicts
  - Static files

- **[fetcher/README.md](fetcher/README.md#troubleshooting)** - Fetcher issues
  - No results found
  - IntegrityError
  - Datetime parsing
  - Configuration not loading
  - Timeouts

- **[fetcher/QUICK_REFERENCE.md](fetcher/QUICK_REFERENCE.md#common-issues)** - Debug commands
  - API response debugging
  - Duplicate checking
  - Datetime testing
  - Performance monitoring

## 🔍 Quick Reference

### File Locations

```
industry-analyser/
├── LOCAL_SETUP.md                    # Setup guide
├── README.md                         # Project overview
├── DOCUMENTATION_INDEX.md            # This file
├── .env.example                      # Config template
├── requirements.txt                  # Dependencies
│
├── fetcher/
│   ├── README.md                     # Fetcher docs
│   ├── ARCHITECTURE.md               # Architecture
│   ├── QUICK_REFERENCE.md            # Commands
│   ├── config_v2.json                # Local config (gitignored)
│   └── scraper.py                    # Implementation
│
├── docs/
│   ├── README.md                     # Docs index
│   └── cvlv_api_integration_task.md  # Task details
│
└── terraform/
    ├── main.tf                       # Infrastructure
    └── variables.tf                  # Variables
```

### Common Commands

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser

# Development
python manage.py runserver
python manage.py shell
python manage.py scrape_first_vacancy_portal

# Production
gcloud secrets versions access latest --secret="industry-analyser-fetcher-portals"
gcloud secrets versions add industry-analyser-fetcher-portals --data-file=/tmp/portals.json
gcloud run jobs execute scrape-vacancy --region=europe-north1
```

### Key Concepts

**Configuration Sources**:
- **Local**: `fetcher/config_v2.json` (gitignored file)
- **Production**: `FETCHER_PORTALS_JSON` env var from GCP Secret Manager

**Scraper Modes**:
- **API mode**: `type: "api"` in config, JSON parsing, no enrichment
- **HTML mode**: No `type` field, HTML parsing, enrichment enabled

**Database Options**:
- **SQLite**: File-based, easy setup, development only
- **PostgreSQL**: Production-like, full features, recommended for testing

## 📝 Documentation Standards

### When to Update Documentation

- **Code changes**: Update relevant README and architecture docs
- **Configuration changes**: Update config examples and schema
- **New features**: Add to README, update architecture if needed
- **Bug fixes**: Update troubleshooting sections
- **Deployment changes**: Update production deployment docs

### Documentation Locations

- **Project-wide**: Root README.md, LOCAL_SETUP.md
- **App-specific**: `<app>/README.md`, `<app>/ARCHITECTURE.md`
- **Quick reference**: `<app>/QUICK_REFERENCE.md`
- **Task details**: `docs/<task>.md`
- **Infrastructure**: `terraform/` comments and README

## 🎯 Documentation Checklist

When adding new features or making changes:

- [ ] Update relevant README files
- [ ] Update architecture diagrams if structure changed
- [ ] Add examples to QUICK_REFERENCE if new commands
- [ ] Update LOCAL_SETUP if setup process changed
- [ ] Update .env.example if new environment variables
- [ ] Update troubleshooting if new common issues
- [ ] Update this index if new documentation added

## 📞 Getting Help

1. **Check documentation** - Start with this index
2. **Search existing docs** - Use Cmd+F / Ctrl+F
3. **Check git history** - `git log` for context
4. **Review recent changes** - Check recent commits
5. **Ask for help** - With specific error messages

## 🔗 External Resources

- **Django Documentation**: https://docs.djangoproject.com/
- **cv.lv API Docs**: https://www.cv.lv/api/doc/swagger-ui/index.html
- **Google Cloud Run**: https://cloud.google.com/run/docs
- **Terraform**: https://www.terraform.io/docs

## 📊 Documentation Statistics

- **Total documentation files**: 8+
- **Total lines of documentation**: 3,500+
- **Setup guides**: 1 (LOCAL_SETUP.md)
- **App-specific docs**: 3 (fetcher/)
- **Quick references**: 1 (fetcher/QUICK_REFERENCE.md)
- **Architecture docs**: 1 (fetcher/ARCHITECTURE.md)

## ✨ Recent Updates

**2026-08-25**:
- Created comprehensive LOCAL_SETUP.md
- Created fetcher/README.md with full documentation
- Created fetcher/ARCHITECTURE.md with diagrams
- Created fetcher/QUICK_REFERENCE.md with commands
- Updated main README.md with better structure
- Created this documentation index
- Fixed cv.lv API integration
- Updated GCP Secret Manager configuration

---

**Last Updated**: 2026-08-25  
**Maintained By**: Development Team  
**Version**: 1.0
