#!/bin/bash

set -e

PROJECT_ID="${GCP_PROJECT_ID:-your-project-id}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="industry-analyser"
IMAGE_NAME="gcr.io/$PROJECT_ID/$SERVICE_NAME"

echo "Deploying $SERVICE_NAME to Cloud Run..."
echo "Project: $PROJECT_ID"
echo "Region: $REGION"

if [ "$PROJECT_ID" = "your-project-id" ]; then
    echo "Error: Please set GCP_PROJECT_ID environment variable"
    echo "Usage: GCP_PROJECT_ID=your-project-id ./deploy-cloudrun.sh"
    exit 1
fi

echo "Building Docker image..."
gcloud builds submit --tag $IMAGE_NAME --project $PROJECT_ID

echo "Deploying to Cloud Run..."
# All runtime config lives in the single `env-file` secret — its
# payload is the full .env file, injected as DOTENV and loaded by
# industry_analyser/settings.py like a local .env.
gcloud run deploy $SERVICE_NAME \
  --image $IMAGE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 1 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 300 \
  --project $PROJECT_ID \
  --set-secrets "DOTENV=env-file:latest"

echo "Deployment complete!"
echo "Service URL:"
gcloud run services describe $SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --project $PROJECT_ID \
  --format 'value(status.url)'
