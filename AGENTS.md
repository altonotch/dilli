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
- `DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py makemigrations`: generate migrations whenever you introduce model changes.
- `DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py runserver 0.0.0.0:8000`: run the API locally.
- `DJANGO_SETTINGS_MODULE=config.settings.test python manage.py test`: execute the Django test suite with the faster test settings.
- `python manage.py makemessages -l he` / `compilemessages -l he`: maintain the Hebrew locale catalog; always regenerate strings after English copy changes and ensure every Hebrew translation entry is filled in before committing.

## Coding Style & Naming Conventions
- Python code follows PEP 8 with 4-space indentation; prefer dataclasses for pure data holders (see `osm/repository.py`).
- Django apps use snake_case module names and PascalCase models/admin classes.
- Keep settings and secrets in `.env`; never hardcode API tokens.
- When touching WhatsApp flows, keep strings wrapped in `gettext()` and update `locale/he/LC_MESSAGES/`.
- Maintain structured logging (use `logger` instances already in modules) whenever you ship new logic so production issues can be diagnosed quickly; avoid removing existing debug logs unless they leak sensitive data.

## Testing Guidelines
- Tests live alongside apps (e.g., `whatsapp/tests/`); name files `test_<feature>.py` and classes `Test<Feature>`.
- Use Django’s `TestCase`/`APITestCase` for DB-backed checks and mock external APIs (WhatsApp, Geoapify).
- Every change should ship with automated tests that cover the new happy path plus at least one representative failure/edge case so regressions are caught early.
- Before opening a PR, run `python manage.py test` plus any focused suites you touched.
- Always run the suite against Postgres (the default test database); do **not** switch settings to SQLite for speed or convenience.

## Commit & Pull Request Guidelines
- Use concise, imperative commit messages (e.g., “Add WhatsApp deal flow session model”).
- Pull requests should describe the change, reference issue numbers when available, list testing steps, and include screenshots or sample payloads for user-facing flows (e.g., new WhatsApp replies).
- Surface schema or settings changes prominently so reviewers can run migrations/config updates without surprises.

## Backwards Compatibility Expectations
- Do not introduce backward compatible shims unless explicitly requested; optimize for the current requirements first.
- When you plan to rewrite or significantly refactor existing functionality, check with stakeholders whether backward compatibility is required before shipping the change.
