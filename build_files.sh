#!/bin/bash
set -e # Exit immediately if a command exits with a non-zero status.

# NOTE: Vercel no longer invokes this file — the build is driven by
# [tool.vercel.scripts] build in pyproject.toml (auto-detected Django
# project, uv-installed deps). This script is kept as a documented,
# manually-runnable equivalent of that pipeline.
#
# Vercel's build image uses a uv-managed Python (PEP 668), which refuses
# pip installs into the system environment — build inside a venv instead.
if command -v uv >/dev/null 2>&1; then
  # Pin to 3.12 (same as requires-python in pyproject.toml): newer
  # Pythons may lack psycopg2-binary wheels.
  uv venv --python 3.12 /tmp/build-venv
  source /tmp/build-venv/bin/activate
  uv pip install -r requirements.txt
else
  python3 -m venv /tmp/build-venv
  source /tmp/build-venv/bin/activate
  python3 -m pip install -r requirements.txt
fi

# Run build tasks that need the Django environment
python3 industry_analyser/console_tasks/build.py create_ca_pem

# Build the React frontend → frontend_dist/ (a STATICFILES_DIRS entry,
# so collectstatic ships it to the CDN below).
# --include=dev: build envs may set NODE_ENV=production, which would
# skip devDependencies (vite/tsc) and break the build below.
npm ci --prefix frontend --include=dev
npm run build --prefix frontend
# Keep node_modules (~67MB) out of any serverless function bundle.
rm -rf frontend/node_modules

# Collect static files
python3 manage.py collectstatic --noinput

python3 manage.py makemigrations
python3 manage.py migrate
timeout 3m python3 manage.py scrape_vacancies
