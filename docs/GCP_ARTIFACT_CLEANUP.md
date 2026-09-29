# GCP Artifact Registry Cleanup

## Overview

This document describes the automated cleanup workflow for GCP Artifact Registry images to stay within free tier quotas.

## Problem

GCP's free tier includes limited Artifact Registry storage. Without cleanup:
- Old Docker images accumulate after each deployment
- Storage quota can be exceeded
- GCP's built-in cleanup policies can take up to 24 hours to execute

## Solution

The `.github/workflows/cleanup-artifacts.yml` workflow automatically deletes old images, keeping only the most recent tagged image.

## How It Works

### Triggers

1. **After successful deployments** - Runs automatically when these workflows complete successfully:
   - Deploy Django Web Service to Cloud Run
   - Deploy scraper jobs (Artifact Registry + Cloud Run)

2. **Daily schedule** - Runs at 2 AM UTC every day

3. **Manual trigger** - Can be run manually via GitHub Actions UI

### Cleanup Logic

1. Lists all tagged images sorted by update time (newest first)
2. Keeps only the most recent tag
3. Deletes old tags using `gcloud artifacts docker tags delete`
4. Deletes the now-untagged images using `gcloud artifacts docker images delete`

### Critical Implementation Details

**Why delete tags first?**
- GCP will reject deletion attempts on images that have tags
- Tags must be deleted before their associated images can be removed

**Error handling:**
- Tag deletion failures cause the workflow to fail (exit code 1)
- Untagged image deletion failures are treated as warnings (GCP may auto-clean)
- Tracks failure count and reports clearly

**Sorting:**
- Uses `~UPDATE_TIME` (descending) to get the most recently updated image
- This is more reliable than `createTime` for identifying the "latest" image

## Configuration

The workflow uses these environment variables:

```yaml
env:
  REGION: europe-north1
  REGISTRY_NAME: industry-analyser-app
  SERVICE_NAME: industry-analyser
```

Registry path: `europe-north1-docker.pkg.dev/${PROJECT_ID}/industry-analyser-app/industry-analyser`

## Expected Behavior

### Success (Green ✅)
- All old tags deleted successfully
- Untagged images deleted (or auto-cleaned by GCP)
- Only 1 tagged image remains
- Exit code 0

### Failure (Red ❌)
- Any tag deletion fails
- Shows error count
- Exit code 1

### Example Output

```
🔍 Checking Artifact Registry: europe-north1-docker.pkg.dev/PROJECT/industry-analyser-app/industry-analyser

Found 8 tagged image(s) in registry

Deleting 7 old tagged image(s)...

Deleting tag: europe-north1-docker.pkg.dev/.../industry-analyser:abc123
✅ Successfully deleted tag abc123

...

Deleting untagged images...

Deleting untagged image: sha256:def456...
✅ Successfully deleted untagged image

✅ Cleanup complete! All old images deleted successfully.

Remaining tagged images:
TAG         VERSION              UPDATE_TIME
xyz789      sha256:latest123...  2026-09-21T08:00:00
```

## Manual Execution

To run the cleanup manually:

1. Go to GitHub Actions tab
2. Select "Cleanup GCP Artifact Registry" workflow
3. Click "Run workflow"
4. Select branch (usually `master`)
5. Click "Run workflow"

## Monitoring

Check the workflow status:
- GitHub Actions tab shows success/failure
- Step summary shows cleanup details
- Logs show which images were deleted

## Benefits

1. **Cost Savings** - Stay within GCP free tier quotas
2. **Immediate Cleanup** - Don't wait 24h for GCP's auto-cleanup
3. **Automated** - Runs after every deployment and on schedule
4. **Reliable** - Proper error handling and failure detection
5. **Transparent** - Clear logging of what's being deleted

## Troubleshooting

### Workflow shows green but images aren't deleted

This was fixed in the current implementation. The workflow now:
- Tracks failures with a counter
- Uses `set -e` to exit on errors
- Returns exit code 1 if any critical operations fail

### "Cannot delete image because it is tagged"

This means tags weren't deleted first. The current implementation:
1. Deletes tags first
2. Then deletes untagged images

### "NOT_FOUND" errors

This can happen if:
- GCP auto-cleaned the untagged images (this is OK, treated as warning)
- Wrong image reference format was used (fixed in current implementation)

## Permissions Required

The service account (`GCP_SA_KEY` secret) needs:
- `roles/artifactregistry.writer` or equivalent
- Permission to delete images and tags in the Artifact Registry

## Related Files

- `.github/workflows/cleanup-artifacts.yml` - The cleanup workflow
- `.github/workflows/deploy-web-service.yml` - Web service deployment
- `.github/workflows/deploy-scraper-jobs.yml` - Scraper jobs deployment
