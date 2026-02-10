# The @vercel/python builder automatically handles dependency installation.
# This script runs *after* dependencies are installed.

\
set -e # Exit immediately if a command exits with a non-zero status.

# Run build tasks that need the Django environment
python3 industry_analyser/console_tasks/build.py create_ca_pem create_private_settings_json

# Move the generated settings file into the app directory to include it in the deployment
mv private_settings.json industry_analyser/

# Collect static files
python3.12 manage.py collectstatic --noinput

# Create Vercel-compatible output vercel directory
mkdir -p .vercel/output/static
cp -r /vercel/path0/staticfiles/static* .vercel/output/static/

python3.12 manage.py makemigrations
python3.12 manage.py migrate
timeout 3m python3.12 manage.py scrape_first_vacancy_portal