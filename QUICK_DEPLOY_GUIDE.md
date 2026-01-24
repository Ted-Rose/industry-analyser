# Quick Deploy Guide to Vercel

## Prerequisites

- Vercel account
- Project connected to GitHub repository
- Database credentials (PostgreSQL)

## Step-by-Step Deployment

### 1. Push Code to GitHub

```bash
git push origin fix/vercel-deployment
```

### 2. Set Environment Variables in Vercel

Go to: **Vercel Dashboard → Your Project → Settings → Environment Variables**

Add these variables for **Production** environment:

#### Core Settings (Required)
```
SECRET_KEY = your-secret-key-here
DEBUG = False
```

#### Database Settings (Required)
```
DB_NAME = your_database_name
DB_USER = your_database_user
DB_PASSWORD = your_database_password
DB_HOST = your-database-host.com
DB_PORT = 16067
```

#### Database SSL Certificate (If Required)
```
DB_SSL_CERT = -----BEGIN CERTIFICATE----- MIIEQTCCAqm... -----END CERTIFICATE-----
```
*Note: This should be a single line with spaces, not newlines*

#### Optional Settings
```
BASE_URL = https://your-app.vercel.app
GEMINI_API_KEY = your-gemini-api-key
HARD_CODED_PASSWORD = your-password
```

### 3. Deploy

Option A: **Automatic Deployment**
- Vercel will automatically deploy when you push to the connected branch

Option B: **Manual Deployment**
```bash
vercel --prod
```

### 4. Verify Deployment

1. **Check Build Logs**
   - Go to Vercel Dashboard → Deployments
   - Click on the latest deployment
   - Review build logs for any errors

2. **Test Application**
   - Visit your Vercel URL
   - Check that pages load correctly
   - Verify database connectivity

3. **Run Migrations** (if needed)
   - You may need to run migrations manually
   - Use Vercel CLI or add a migration step

## Troubleshooting

### Build Fails

**Check:**
- All required environment variables are set
- `requirements.txt` is up to date
- No syntax errors in Python files

### Database Connection Fails

**Check:**
- All `DB_*` variables are correct
- Database allows connections from Vercel IPs
- SSL certificate is provided if required

### Static Files Not Loading

**Check:**
- `STATIC_ROOT` is set correctly in settings.py
- Static files route in `vercel.json` is correct

## Quick Reference

### Environment Variables Template

Copy this template and fill in your values:

```bash
# Core
SECRET_KEY=
DEBUG=False

# Database
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=16067
DB_SSL_CERT=

# Optional
BASE_URL=
GEMINI_API_KEY=
HARD_CODED_PASSWORD=
```

### Vercel CLI Commands

```bash
# Deploy to production
vercel --prod

# Deploy to preview
vercel

# View logs
vercel logs

# List environment variables
vercel env ls

# Add environment variable
vercel env add VARIABLE_NAME
```

## Next Steps After Deployment

1. ✅ Verify all pages load correctly
2. ✅ Test database queries
3. ✅ Check admin panel access
4. ✅ Test scraper functionality (if applicable)
5. ✅ Set up monitoring/alerts
6. ✅ Configure custom domain (optional)

## Support

- **Vercel Documentation**: https://vercel.com/docs
- **Project Documentation**: See `VERCEL_ENV_VARS.md` and `VERCEL_MIGRATION_SUMMARY.md`

---

**Last Updated**: 2026-01-23
