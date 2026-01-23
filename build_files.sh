# The @vercel/python builder automatically handles dependency installation.
# This script runs *after* dependencies are installed.

set -e # Exit immediately if a command exits with a non-zero status.

# Run build tasks that need the Django environment
python3 industry_analyser/console_tasks/build.py create_ca_pem create_private_settings_json

# Collect static files
python3 manage.py collectstatic --noinput

# Run database migrations
python3 manage.py makemigrations
python3 manage.py migrate