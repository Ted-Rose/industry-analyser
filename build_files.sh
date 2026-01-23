uv pip install --system -r requirements.txt --python 3.12

uv run --python 3.12 python3 industry_analyser/console_tasks/build.py create_ca_pem create_private_settings_json

# Collect static files
uv run --python 3.12 python3 manage.py collectstatic --noinput

# Create Vercel-compatible output vercel directory
mkdir -p .vercel/output/static
cp -r /vercel/path0/staticfiles/static* .vercel/output/static/

uv run --python 3.12 python3 manage.py makemigrations
uv run --python 3.12 python3 manage.py migrate