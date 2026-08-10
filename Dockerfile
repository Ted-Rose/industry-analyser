FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

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
