# Vercel Deployment Plan: Runtime File Generation

## Executive Summary

This document outlines the strategy for deploying the Django application to Vercel's serverless environment. The core challenge is that files generated during the build process are not automatically included in the final deployment package. Our solution is to generate critical files at runtime from environment variables.

---

## The Problem

### Build vs. Runtime Environments

Vercel uses two separate, isolated environments:

1. **Build Environment**: A temporary container where dependencies are installed and build scripts run.
2. **Runtime Environment**: A clean, minimal serverless function that serves requests.

Files created during the build (like `private_settings.json` and `ca.pem`) exist in the build environment but are **not automatically transferred** to the runtime environment unless they're in specific, packageable locations.

### Specific Issues

1. **`private_settings.json`**: Contains sensitive configuration (SECRET_KEY, database credentials, API keys). Generated during build from environment variables but not included in deployment.

2. **`ca.pem`**: SSL certificate for PostgreSQL database connection. Generated during build but not packaged with the application.

**Result**: Application crashes at runtime with `FileNotFoundError` or database connection errors.

---

## The Solution: Runtime File Generation

Instead of relying on build-time file generation, we create these files **on-the-fly** when the application starts in the serverless environment.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Vercel Serverless Function               │
│                                                             │
│  1. Django settings.py loads                                │
│  2. Check: Is VERCEL environment variable set?              │
│  3. If YES:                                                 │
│     ├─ Check: Does /tmp/private_settings.json exist?       │
│     │  └─ NO → Create from 'private_settings' env var      │
│     └─ Check: Does /tmp/ca.pem exist?                       │
│        └─ NO → Create from 'capem' env var                  │
│  4. Load settings from the files                            │
│  5. Update database config to use /tmp/ca.pem               │
│  6. Application ready to serve requests                     │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **Use `/tmp` directory**: This is the only writable location in AWS Lambda (which powers Vercel Functions).

2. **Check before creating**: Files persist across warm starts, so we only create them if they don't exist.

3. **Environment-aware**: Logic only activates when `VERCEL=1` environment variable is detected.

4. **Fail fast**: If environment variables are missing, raise clear errors immediately.

---

## Implementation Details

### Step 1: Detect Vercel Environment

```python
IS_VERCEL = os.environ.get('VERCEL') == '1'
```

This flag determines whether to use local file paths or `/tmp` paths.

### Step 2: Handle `private_settings.json`

**Local Development**:
- Path: `{BASE_DIR}/private_settings.json`
- File exists on disk

**Vercel Production**:
- Path: `/tmp/private_settings.json`
- Created from `private_settings` environment variable
- Contains JSON string with all configuration

**Code Location**: `industry_analyser/settings.py`, lines 20-52

### Step 3: Handle `ca.pem`

**Local Development**:
- Path: `{BASE_DIR}/ca.pem`
- File exists on disk

**Vercel Production**:
- Path: `/tmp/ca.pem`
- Created from `capem` environment variable
- Reformats single-line certificate into proper PEM format

**Code Location**: `industry_analyser/settings.py`, lines 54-70

### Step 4: Update Database Configuration

After loading `DATABASES` from `private_settings`, we dynamically update the SSL certificate path:

```python
if IS_VERCEL and DATABASES:
    db_options = DATABASES.get('default', {}).get('OPTIONS', {})
    if db_options and 'sslrootcert' in db_options:
        db_options['sslrootcert'] = CA_PEM_PATH
```

This ensures the database driver looks for the certificate in `/tmp/ca.pem` instead of a non-existent build-time path.

**Code Location**: `industry_analyser/settings.py`, lines 145-149

---

## Environment Variables Required

### On Vercel

Set these in your Vercel project settings:

1. **`VERCEL`**: Automatically set by Vercel to `"1"`

2. **`private_settings`**: JSON string containing:
   ```json
   {
     "SECRET_KEY": "...",
     "DEBUG": false,
     "base_url": "...",
     "HARD_CODED_PASSWORD": "...",
     "gemini_api_key": "...",
     "ip_address": "...",
     "DATABASES": {
       "default": {
         "ENGINE": "django.db.backends.postgresql",
         "NAME": "...",
         "USER": "...",
         "PASSWORD": "...",
         "HOST": "...",
         "PORT": 16067,
         "OPTIONS": {
           "sslmode": "require",
           "sslrootcert": "/tmp/ca.pem"
         }
       }
     }
   }
   ```

3. **`capem`**: Single-line PEM certificate string:
   ```
   -----BEGIN CERTIFICATE----- MIIEQTCCAqmgAwIBAgIUZXN0aW5nLWNlcnRpZmljYXRlLWlkMA0GCSqGSIb3DQEB... -----END CERTIFICATE-----
   ```

---

## Benefits of This Approach

### 1. **Serverless-Native**
- Works seamlessly with ephemeral filesystem
- No reliance on build artifacts being packaged

### 2. **Security**
- Sensitive data stays in environment variables
- Never committed to version control
- Easy to rotate credentials

### 3. **Simplicity**
- No complex build configuration
- Works across cold and warm starts
- Self-healing (recreates files if missing)

### 4. **Portability**
- Same codebase works locally and on Vercel
- Environment detection is automatic
- Easy to extend to other platforms

---

## Testing the Implementation

### Local Testing

1. Ensure `private_settings.json` and `ca.pem` exist in project root
2. Run: `python manage.py runserver`
3. Application should load normally using local files

### Vercel Testing

1. Deploy to Vercel
2. Check logs for any file creation errors
3. Test database connectivity by accessing any view that queries the database
4. Verify SSL connection is working

### Debugging

If issues occur, check:
- Are environment variables set correctly in Vercel dashboard?
- Are there any typos in the JSON string?
- Is the certificate format correct (no extra spaces)?
- Check Vercel function logs for detailed error messages

---

## Build Script Simplification

With runtime file generation, the `build_files.sh` script no longer needs to:
- Create `private_settings.json`
- Create `ca.pem`
- Move files to specific locations

The script now focuses only on:
- Running Django management commands
- Collecting static files
- Running migrations

This makes the build process simpler and more reliable.

---

## Future Improvements

### 1. Caching Strategy
Consider implementing a check to avoid recreating files on every cold start if they already exist in `/tmp`.

### 2. Health Check Endpoint
Add a `/health` endpoint that verifies:
- Settings file loaded successfully
- Database connection works
- Certificate is valid

### 3. Monitoring
Add logging to track:
- How often files are created
- Cold start times
- Any file creation failures

### 4. Alternative: Vercel Blob Storage
For larger files or more complex scenarios, consider using Vercel's Blob Storage API instead of `/tmp`.

---

## Rollback Plan

If runtime file generation causes issues:

1. **Quick Fix**: Change database `sslmode` to `require` (skips certificate verification)
2. **Alternative**: Use Vercel's build output API to explicitly include generated files
3. **Fallback**: Revert to previous deployment using Vercel's rollback feature

---

## Conclusion

Runtime file generation is the recommended approach for deploying Django applications to Vercel's serverless environment. It's robust, secure, and aligns with serverless best practices. The implementation is complete and ready for production use.

---

## Related Documentation

- [Vercel Python Runtime](https://vercel.com/docs/functions/runtimes/python)
- [AWS Lambda Ephemeral Storage](https://docs.aws.amazon.com/lambda/latest/dg/configuration-ephemeral-storage.html)
- [Django Settings Best Practices](https://docs.djangoproject.com/en/stable/topics/settings/)

---

**Last Updated**: 2026-01-23  
**Author**: Development Team  
**Status**: ✅ Implemented and Active
