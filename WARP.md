# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

Repository overview
- Python 3.13 Django project (Django 5.x) under backend/, with Django REST Framework and django-axes enabled.
- Single app whatsapp exposing a Meta/WhatsApp webhook at /whatsapp/webhook/.
- Postgres 17 with PostGIS via docker-compose on localhost:5436.
- Environment variables are loaded from backend/.env.

Key commands
- Database (Docker Compose)
  - Start DB: docker compose up -d postgres
  - Stop DB: docker compose down
  - Connect (psql): PGPASSWORD=postgres psql -h localhost -p 5436 -U postgres -d dilli
- Python setup (venv + minimal deps)
  - python3 -m venv .venv && source .venv/bin/activate
  - pip install -U pip
  - pip install django djangorestframework django-axes python-dotenv django-extensions "psycopg[binary]"
- Environment (.env at backend/.env)
  - Required keys (placeholders):
    - SECRET_KEY=...  DEBUG=true
    - DB_NAME=dilli  DB_USER=postgres  DB_PASSWORD=postgres  DB_HOST=localhost  DB_PORT=5436
    - META_APP_SECRET={{META_APP_SECRET}}  WHATSAPP_VERIFY_TOKEN={{WHATSAPP_VERIFY_TOKEN}}  WA_SALT={{WA_SALT}}
    - WHATSAPP_ACCESS_TOKEN={{WHATSAPP_ACCESS_TOKEN}}  WHATSAPP_PHONE_NUMBER_ID={{WHATSAPP_PHONE_NUMBER_ID}}  # required for outbound auto-intro
- Django workflows (run from repo root)
  - Migrate DB: python backend/manage.py migrate
  - Run dev server: python backend/manage.py runserver 127.0.0.1:8000
  - System checks: python backend/manage.py check
  - Create admin user: python backend/manage.py createsuperuser
- Tests (Django test runner)
  - All tests: python backend/manage.py test
  - Single test (example): python backend/manage.py test whatsapp.tests.TestClass.test_method
- Lint/format
  - No repository linter/formatter config is present.

Architecture and important details
- Project wiring (backend/config)
  - INSTALLED_APPS includes rest_framework, axes, whatsapp. Axes middleware and authentication backend are enabled; they mainly affect admin/login flows.
  - URLs: /admin/ and /whatsapp/ (includes whatsapp.urls).
  - Database: PostgreSQL via django.db.backends.postgresql, defaults to host=localhost port=5436 (see settings.py). All DB/Auth/secret config comes from backend/.env (loaded with python-dotenv).
  - DRF throttling: two SimpleRateThrottle classes are configured with rates in settings.py: ip (120/min) and wa_hash (60/min).
- WhatsApp app (backend/whatsapp)
  - Endpoint: /whatsapp/webhook/
    - GET: Meta verification handshake. Returns hub.challenge when hub.verify_token matches WHATSAPP_VERIFY_TOKEN.
    - POST: Verifies X-Hub-Signature-256 using HMAC-SHA256 with META_APP_SECRET. Parses payload entry[].changes[].value.messages[]. For each message, normalizes the sender ID, computes a salted SHA-256 hash (compute_wa_hash) and upserts a WAUser, updating last_seen.
    - Throttling: IPRateThrottle and WaHashRateThrottle bound to the view; WaHashRateThrottle derives identity from X-WA-Hash header or request body.
  - Model: WAUser (UUID pk) stores wa_id_hash (identity), optional wa_last4 and display_name, locale/city/tz, consent_ts, last_seen, role and is_active. Indexed by last_seen. Admin is registered with filters and limited read-only fields.
  - Utilities: normalize_wa_id strips non-digits; compute_wa_hash requires WA_SALT and raises if missing.
- Docker Compose (docker-compose.yml)
  - Single service postgres built from docker/postgres (PostGIS-enabled image). Exposes host port 5436 and uses a named volume pgdata so init scripts run on first start.

Operational notes
- Ensure META_APP_SECRET and WA_SALT are set; missing values will cause signature verification to fail and/or webhook processing to raise at compute_wa_hash.
- For local development, start postgres first, then run migrations before hitting the webhook endpoint.
- Admin UI available at /admin/ after createsuperuser; axes is enabled to protect authentication.
