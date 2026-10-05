#!/bin/bash
set -e # Exit immediately if a command exits with a non-zero status.

# NOTE: invoked via vercel.json "buildCommand". The pyproject
# [tool.vercel.scripts] build only runs under framework-preset
# detection, which this project doesn't get — the deployment ships
# file-based api/ functions instead. This script is the shared entry
# for both paths; keep it in sync with pyproject.toml.
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
# Python-runtime build images may lack Node entirely — skip rather
# than fail the deploy (SPAs render a manifest diagnostic instead).
if command -v npm >/dev/null 2>&1; then
  npm ci --prefix frontend --include=dev
  npm run build --prefix frontend
  # Keep node_modules (~67MB) out of any serverless function bundle.
  rm -rf frontend/node_modules
else
  echo "npm not available in build env — skipping frontend build"
fi

# Collect static files
python3 manage.py collectstatic --noinput

# No migrate/scrape here: production migrations run via the
# run-migrations GitHub workflow, and scraping during a web deploy
# would hammer portals on every push.
