# Google Cloud Run Deployment Guide

This guide explains how to deploy the Industry Analyser Django application to Google Cloud Run with min instance count 0 and max instance count 1.

## Prerequisites

1. **Google Cloud SDK**: Install the [gcloud CLI](https://cloud.google.com/sdk/docs/install)
2. **Docker**: Ensure Docker is installed and running
3. **GCP Project**: Have a Google Cloud Platform project with billing enabled
4. **Required APIs**: Enable the following APIs in your GCP project:
   - Cloud Run API
   - Cloud Build API
   - Container Registry API

```bash
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable containerregistry.googleapis.com
```

## Configuration

### 1. Set up GCP Project

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud auth login
gcloud auth configure-docker
```

### 2. Create Secrets in Secret Manager

The application requires several environment variables. Store them as secrets:

```bash
gcloud secrets create django-secret-key --data-file=- <<< "your-secret-key-here"
gcloud secrets create database-url --data-file=- <<< "postgresql://user:pass@host:5432/dbname"
gcloud secrets create db-ssl-cert --data-file=path/to/ca.pem
gcloud secrets create gemini-api-key --data-file=- <<< "your-gemini-api-key"
gcloud secrets create hard-coded-password --data-file=- <<< "your-password"
```

Grant Cloud Run access to secrets:

```bash
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT_ID --format='value(projectNumber)')
gcloud secrets add-iam-policy-binding django-secret-key \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding database-url \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding db-ssl-cert \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding hard-coded-password \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

## Deployment Methods

### Method 1: Using the Deployment Script (Recommended)

```bash
GCP_PROJECT_ID=your-project-id ./deploy-cloudrun.sh
```

Optional environment variables:
- `GCP_PROJECT_ID`: Your GCP project ID (required)
- `GCP_REGION`: Deployment region (default: us-central1)

### Method 2: Manual Deployment

1. **Build and push the Docker image:**

```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/industry-analyser
```

2. **Deploy to Cloud Run:**

```bash
gcloud run deploy industry-analyser \
  --image gcr.io/YOUR_PROJECT_ID/industry-analyser \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 1 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 300 \
  --set-env-vars "DEBUG=False" \
  --set-secrets "SECRET_KEY=django-secret-key:latest,DATABASE_URL=database-url:latest,DB_SSL_CERT=db-ssl-cert:latest,GEMINI_API_KEY=gemini-api-key:latest,HARD_CODED_PASSWORD=hard-coded-password:latest"
```

### Method 3: Using Cloud Build (CI/CD)

The `cloudbuild.yaml` file is configured for automated deployments:

```bash
gcloud builds submit --config cloudbuild.yaml
```

Or set up a trigger for automatic deployments on git push:

```bash
gcloud builds triggers create github \
  --repo-name=industry-analyser \
  --repo-owner=YOUR_GITHUB_USERNAME \
  --branch-pattern="^main$" \
  --build-config=cloudbuild.yaml
```

## Instance Configuration

The deployment is configured with:
- **Min instances**: 0 (scales to zero when idle)
- **Max instances**: 1 (maximum one instance running)
- **Memory**: 512Mi
- **CPU**: 1
- **Timeout**: 300 seconds
- **Concurrency**: Default (80 requests per instance)

## Post-Deployment

### 1. Get Service URL

```bash
gcloud run services describe industry-analyser \
  --platform managed \
  --region us-central1 \
  --format 'value(status.url)'
```

### 2. Run Database Migrations

You can run migrations using Cloud Run jobs or by temporarily enabling SSH:

```bash
gcloud run services update industry-analyser \
  --command "python,manage.py,migrate" \
  --region us-central1
```

Or create a one-off job:

```bash
gcloud run jobs create industry-analyser-migrate \
  --image gcr.io/YOUR_PROJECT_ID/industry-analyser \
  --region us-central1 \
  --set-secrets "SECRET_KEY=django-secret-key:latest,DATABASE_URL=database-url:latest,DB_SSL_CERT=db-ssl-cert:latest" \
  --command "python" \
  --args "manage.py,migrate"

gcloud run jobs execute industry-analyser-migrate --region us-central1
```

### 3. Create Superuser

```bash
gcloud run jobs create industry-analyser-createsuperuser \
  --image gcr.io/YOUR_PROJECT_ID/industry-analyser \
  --region us-central1 \
  --set-secrets "SECRET_KEY=django-secret-key:latest,DATABASE_URL=database-url:latest,DB_SSL_CERT=db-ssl-cert:latest" \
  --command "python" \
  --args "manage.py,createsuperuser,--noinput,--email=admin@example.com"

gcloud run jobs execute industry-analyser-createsuperuser --region us-central1
```

## Monitoring and Logs

### View Logs

```bash
gcloud run services logs read industry-analyser \
  --region us-central1 \
  --limit 50
```

### Monitor Metrics

Visit the Cloud Run console:
```
https://console.cloud.google.com/run/detail/us-central1/industry-analyser/metrics
```

## Cost Optimization

With min instances set to 0:
- No charges when the service is idle
- Cold start latency when first request arrives (typically 2-5 seconds)
- Billed only for actual request processing time
- Max 1 instance ensures predictable costs

## Troubleshooting

### Check Service Status

```bash
gcloud run services describe industry-analyser \
  --region us-central1 \
  --format yaml
```

### Update Environment Variables

```bash
gcloud run services update industry-analyser \
  --region us-central1 \
  --set-env-vars "NEW_VAR=value"
```

### Update Secrets

```bash
echo "new-secret-value" | gcloud secrets versions add django-secret-key --data-file=-
```

### Rollback to Previous Revision

```bash
gcloud run services update-traffic industry-analyser \
  --region us-central1 \
  --to-revisions REVISION_NAME=100
```

## Security Considerations

1. **Secrets**: All sensitive data stored in Secret Manager
2. **HTTPS**: Cloud Run provides automatic HTTPS
3. **IAM**: Use least privilege access for service accounts
4. **ALLOWED_HOSTS**: Already configured to accept `.run.app` domains
5. **Authentication**: Consider adding Cloud IAM authentication for production

## Additional Resources

- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Django on Cloud Run](https://cloud.google.com/python/django/run)
- [Cloud Run Pricing](https://cloud.google.com/run/pricing)
