# 1. Create a virtual environment using Python 3.12
echo "Creating virtual environment..."
uv venv --python 3.12

# 2. Install dependencies into the virtual environment
echo "Installing dependencies..."
uv pip install -r requirements.txt

# 3. Run build & management commands using the virtual environment
echo "Running build tasks..."
uv run python3 industry_analyser/console_tasks/build.py create_ca_pem create_private_settings_json

echo "Collecting static files..."
uv run python3 manage.py collectstatic --noinput

# Create Vercel-compatible output directory
mkdir -p .vercel/output/static
cp -r staticfiles/* .vercel/output/static/

echo "Running database migrations..."
uv run python3 manage.py makemigrations
uv run python3 manage.py migrate