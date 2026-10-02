# React frontend — built in a node stage so the final image has no
# node_modules; only frontend_dist/ is copied over.
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
# --include=dev: parity with build_files.sh — if NODE_ENV=production
# ever propagates here, plain `npm ci` would skip devDependencies
# (vite/tsc) and break `npm run build` below.
RUN npm ci --include=dev
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /frontend_dist /app/frontend_dist

# Build-time env vars so settings import works during collectstatic —
# the Cloud Run runtime overrides them via --update-env-vars.
# Keep this strict: a silent failure here ships a site with no JS/CSS.
ENV SECRET_KEY=build-time-dummy-secret
ENV DATABASE_URL=sqlite:///db.sqlite3
ENV DEBUG=False
ENV BASE_URL=http://localhost

RUN python manage.py collectstatic --noinput

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV DJANGO_SETTINGS_MODULE=industry_analyser.settings
ENV PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 industry_analyser.wsgi:application"]
