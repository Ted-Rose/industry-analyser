# Vercel Environment Variables Configuration

This document lists all environment variables required for deploying the Django application to Vercel.

## Required Environment Variables

### Core Django Settings

| Variable | Description | Example | Required |
|----------|-------------|---------|----------|
| `SECRET_KEY` | Django secret key for cryptographic signing | `django-insecure-xyz123...` | ✅ Yes |
| `DEBUG` | Enable/disable debug mode | `False` | ✅ Yes |
| `BASE_URL` | Base URL of your application | `https://yourapp.vercel.app` | No |
| `HARD_CODED_PASSWORD` | Application-specific password | `your-password` | No |
| `GEMINI_API_KEY` | Google Gemini API key for AI features | `AIza...` | No |

### Database Configuration

| Variable | Description | Example | Required |
|----------|-------------|---------|----------|
| `DB_NAME` | PostgreSQL database name | `industry_analyser` | ✅ Yes |
| `DB_USER` | Database username | `avnadmin` | ✅ Yes |
| `DB_PASSWORD` | Database password | `AVNS_...` | ✅ Yes |
| `DB_HOST` | Database host | `industryanalyser.aivencloud.com` | ✅ Yes |
| `DB_PORT` | Database port | `16067` | No (default: 5432) |
| `DB_SSL_CERT` | SSL certificate for database (single line) | `-----BEGIN CERTIFICATE----- MII...` | No |

### Automatic Variables

| Variable | Description | Set By |
|----------|-------------|--------|
| `VERCEL` | Indicates running on Vercel | Vercel (automatically set to `"1"`) |

## Setting Environment Variables in Vercel

### Via Vercel Dashboard

1. Go to your project in Vercel Dashboard
2. Navigate to **Settings** → **Environment Variables**
3. Add each variable with its value
4. Select the environments (Production, Preview, Development)
5. Click **Save**

### Via Vercel CLI

```bash
vercel env add SECRET_KEY
# Enter the value when prompted

# Or set multiple at once
vercel env add DB_NAME
vercel env add DB_USER
vercel env add DB_PASSWORD
vercel env add DB_HOST
```

## Environment-Specific Configuration

### Production

All variables should be set for the **Production** environment.

### Preview (Staging)

You can use the same values as production or create separate test database credentials.

### Development

For local development with `vercel dev`, you can:
1. Use a `.env` file (not committed to git)
2. Or use `private_settings.json` (current local setup)

## Database SSL Certificate Format

The `DB_SSL_CERT` variable should contain the certificate as a **single line** with spaces instead of newlines:

```
-----BEGIN CERTIFICATE----- MIIEQTCCAqmgAwIBAgIUZXN0aW5nLWNlcnRpZmljYXRlLWlkMA0GCSqGSIb3DQEB... -----END CERTIFICATE-----
```

The application will automatically reformat it into proper PEM format at runtime.

## Example Configuration

Here's a complete example of all required variables:

```bash
# Core Settings
SECRET_KEY=django-insecure-your-secret-key-here-change-this
DEBUG=False
BASE_URL=https://industry-analyser.vercel.app
GEMINI_API_KEY=AIzaSyC...

# Database
DB_NAME=defaultdb
DB_USER=avnadmin
DB_PASSWORD=AVNS_xyz123...
DB_HOST=industryanalyser-industryanalyser.c.aivencloud.com
DB_PORT=16067
DB_SSL_CERT=-----BEGIN CERTIFICATE----- MIIEQTCCAqmgAwIBAgIUZXN0aW5nLWNlcnRpZmljYXRlLWlkMA0GCSqGSIb3DQEB... -----END CERTIFICATE-----
```

## Security Best Practices

1. **Never commit** environment variables to git
2. **Rotate secrets** regularly (SECRET_KEY, DB_PASSWORD)
3. **Use different** database credentials for production and preview
4. **Enable** Vercel's environment variable encryption
5. **Limit access** to environment variables in team settings

## Troubleshooting

### Missing Required Variable

If you see an error like:
```
ValueError: Required environment variable 'DB_NAME' is not set
```

**Solution**: Add the missing variable in Vercel Dashboard → Settings → Environment Variables

### Database Connection Fails

If you see:
```
psycopg2.OperationalError: could not connect to server
```

**Check**:
1. All `DB_*` variables are set correctly
2. Database host is accessible from Vercel
3. Database credentials are valid
4. SSL certificate is provided if required

### Certificate Format Issues

If you see:
```
could not read root certificate file
```

**Solution**: Ensure `DB_SSL_CERT` is formatted as a single line with spaces, not newlines

## Migration from Old Setup

If you're migrating from the old `private_settings` JSON approach:

### Old Format (JSON string in one variable)
```json
{
  "SECRET_KEY": "...",
  "DEBUG": false,
  "DATABASES": {...}
}
```

### New Format (Individual variables)
```
SECRET_KEY=...
DEBUG=False
DB_NAME=...
DB_USER=...
```

**Benefits of new approach**:
- ✅ Easier to manage individual settings
- ✅ Better security (can set different permissions per variable)
- ✅ Follows Vercel best practices
- ✅ Simpler to update single values
- ✅ No JSON escaping issues

## Local Development

For local development, continue using `private_settings.json`:

```json
{
  "SECRET_KEY": "django-insecure-local-dev-key",
  "DEBUG": true,
  "BASE_URL": "http://localhost:8000",
  "HARD_CODED_PASSWORD": "test",
  "gemini_api_key": "your-key",
  "ip_address": "192.168.1.100",
  "DATABASES": {
    "default": {
      "ENGINE": "django.db.backends.postgresql",
      "NAME": "industry_analyser",
      "USER": "postgres",
      "PASSWORD": "password",
      "HOST": "localhost",
      "PORT": "5432"
    }
  }
}
```

The application automatically detects whether it's running on Vercel or locally and uses the appropriate configuration method.

---

**Last Updated**: 2026-01-23  
**Related Documentation**: VERCEL_DEPLOYMENT_PLAN.md
