# The @vercel/python builder automatically handles dependency installation.
# This script runs *after* dependencies are installed.

\
set -e # Exit immediately if a command exits with a non-zero status.

# Run build tasks that need the Django environment
python3 industry_analyser/console_tasks/build.py create_ca_pem create_private_settings_json

# Move the generated settings file into the app directory to include it in the deployment
mv private_settings.json industry_analyser/

# Collect static files
python3 manage.py collectstatic --noinput

# Run database migrations
python3 manage.py makemigrations
python3 manage.py migrate
timeout 3m python3 manage.py scrape_first_vacancy_portal