# Create Alert Email Secret

## Step 1: Create the Secret with Your Email

Run this command and **replace `YOUR_EMAIL_HERE` with your actual email address**:

```bash
echo "YOUR_EMAIL_HERE" | gcloud secrets create industry-analyser-alert-email \
  --project=gen-lang-client-0833674612 \
  --replication-policy="automatic" \
  --data-file=-
```

### Example:
```bash
echo "john.doe@example.com" | gcloud secrets create industry-analyser-alert-email \
  --project=gen-lang-client-0833674612 \
  --replication-policy="automatic" \
  --data-file=-
```

## Step 2: Verify the Secret

```bash
gcloud secrets versions access latest \
  --secret=industry-analyser-alert-email \
  --project=gen-lang-client-0833674612
```

This should output your email address.

## Step 3: Apply Terraform

```bash
cd terraform
terraform plan
terraform apply
```

## Done! 🎉

You'll now receive email notifications whenever any Cloud Run job fails.

---

## Alternative: Interactive Method

If you prefer not to have your email in bash history:

```bash
gcloud secrets create industry-analyser-alert-email \
  --project=gen-lang-client-0833674612 \
  --replication-policy="automatic" \
  --data-file=-
```

Then paste your email and press **Ctrl+D** (or **Cmd+D** on Mac) to finish.

---

## Security Notes

✅ Your email is stored in Google Secret Manager (encrypted at rest)  
✅ Not stored in git or terraform.tfvars  
✅ Only accessible by authorized GCP services  
✅ Can be rotated/updated anytime  

## View in GCP Console

https://console.cloud.google.com/security/secret-manager/secret/industry-analyser-alert-email?project=gen-lang-client-0833674612

---

## Updating Your Email Later

```bash
echo "new-email@example.com" | gcloud secrets versions add industry-analyser-alert-email \
  --project=gen-lang-client-0833674612 \
  --data-file=-

cd terraform
terraform apply
```

## Deleting the Secret (Disable Alerts)

```bash
gcloud secrets delete industry-analyser-alert-email \
  --project=gen-lang-client-0833674612

cd terraform
terraform apply
```
