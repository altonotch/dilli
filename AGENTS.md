# Repository Guidelines

## Project Structure & Module Organization
- `backend/` contains the Django project (`config/`), domain apps (`whatsapp/`, `pricing/`, `stores/`, `catalog/`), and tests under each app’s `tests/` package.
- `osm/` holds helper scripts (`import_shop_points.sh`, flex styles) for optional OSM imports; they are currently offline and should not block local work.
- Locale assets live in `backend/locale/`, and environment settings are split across `config/settings/base.py`, `dev.py`, `test.py`, and `prod.py`.
- Database data for local Postgres runs out of `db/`; keep large artifacts (e.g., `.osm.pbf`) outside the repo when possible.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate`: create/activate the virtualenv.
- `pip install -r backend/requirements.txt`: install backend dependencies.
- `DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py migrate`: apply schema changes to the default (PostGIS-enabled) database.
- `DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py runserver 0.0.0.0:8000`: run the API locally.
- `DJANGO_SETTINGS_MODULE=config.settings.test python manage.py test`: execute the Django test suite with the faster test settings.
- `python manage.py makemessages -l he` / `compilemessages -l he`: maintain the Hebrew locale catalog.

## Coding Style & Naming Conventions
- Python code follows PEP 8 with 4-space indentation; prefer dataclasses for pure data holders (see `osm/repository.py`).
- Django apps use snake_case module names and PascalCase models/admin classes.
- Keep settings and secrets in `.env`; never hardcode API tokens.
- When touching WhatsApp flows, keep strings wrapped in `gettext()` and update `locale/he/LC_MESSAGES/`.

## Testing Guidelines
- Tests live alongside apps (e.g., `whatsapp/tests/`); name files `test_<feature>.py` and classes `Test<Feature>`.
- Use Django’s `TestCase`/`APITestCase` for DB-backed checks and mock external APIs (WhatsApp, Geoapify).
- Before opening a PR, run `python manage.py test` plus any focused suites you touched.

## Commit & Pull Request Guidelines
- Use concise, imperative commit messages (e.g., “Add WhatsApp deal flow session model”).
- Pull requests should describe the change, reference issue numbers when available, list testing steps, and include screenshots or sample payloads for user-facing flows (e.g., new WhatsApp replies).
- Surface schema or settings changes prominently so reviewers can run migrations/config updates without surprises.
