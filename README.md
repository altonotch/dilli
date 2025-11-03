# Dilli — WhatsApp backend

This repository contains a minimal Django backend that integrates with the WhatsApp Cloud API.

The backend supports Hebrew (RTL) and English (LTR) messaging, with a small locale lifecycle and Django i18n.

- Webhook: `backend/whatsapp/views.py`
- Helpers: `backend/whatsapp/utils.py`
- Settings: `backend/config/settings.py`


## Managing translations (Django i18n)
Django uses GNU gettext catalogs for translations. In this project we keep catalogs in a central directory:

- `LOCALE_PATHS = [BASE_DIR / 'locale']`
- Languages enabled: `('he', 'Hebrew')`, `('en', 'English')`

We normalize all runtime locale values to `"he"` or `"en"` via `normalize_locale()` and select the language at render-time with `translation.override(locale)`.

### Prerequisites
Install the gettext CLI tools on the machine (or Docker image) where you run i18n commands:

- macOS: `brew install gettext && brew link --force gettext`
- Ubuntu/Debian: `sudo apt-get install gettext`
- Alpine: `apk add gettext`
- Windows: Chocolatey `choco install gettext` or MSYS2, ensure `msgfmt` and `xgettext` are on PATH

### 1) Mark strings for translation
Wrap user-facing strings in `gettext` (`_`) and render them under `translation.override(locale)`.

Example (already implemented for the intro message):

```python
from django.utils import translation
from django.utils.translation import gettext as _

from whatsapp.utils import normalize_locale

def get_intro_message(locale: str) -> str:
    loc = normalize_locale(locale)
    with translation.override(loc):
        return _(
            'Welcome to "Dilli" — deals from the supermarket near you.\n'
            'What would you like to do?\n'
            '1) Find a deal\n'
            '2) Add a deal\n'
            '3) How it works'
        )
```

Notes:
- Keep English as the source message (msgid).
- For the very first contact message, we intentionally keep a bilingual prompt so it’s understandable even before a locale is chosen.

### 2) Generate message catalogs (.po)
Run from the project root and ignore large/unrelated directories:

```bash
python manage.py makemessages -l he -i db -i docker -i venv -i .venv
# Optional: also create English catalogs (usually not needed)
python manage.py makemessages -l en -i db -i docker -i venv -i .venv
# Later updates for all existing languages
python manage.py makemessages -a -i db -i docker -i venv -i .venv
```

This creates/updates files like:
- `backend/locale/he/LC_MESSAGES/django.po` (or `locale/he/...` if you keep it at project root)

### 3) Edit translations
Open the `.po` file and fill `msgstr` for each `msgid`.

The `msgid` for the intro message (must match exactly, including newlines):

```po
#: backend/whatsapp/utils.py:NN
msgid "Welcome to \"Dilli\" — deals from the supermarket near you.\nWhat would you like to do?\n1) Find a deal\n2) Add a deal\n3) How it works"
msgstr "ברוך/ה הבא/ה ל\"דיללי\" — דילים מהסופר לידך.\nמה תרצה/י לעשות?\n1) למצוא דיל\n2) להוסיף דיל\n3) איך זה עובד"
```

Tips:
- Newlines and punctuation must match the source string used in `_()`.
- You can use a PO editor (Poedit, Lokalise, Weblate) or a text editor.

### 4) Compile catalogs (.mo)
Compile `.po` files into binary `.mo` files that Django loads at runtime:

```bash
python manage.py compilemessages
```

This produces files like `backend/locale/he/LC_MESSAGES/django.mo`.

### 5) Verify translations
Quick local checks in the Django shell:

```bash
python manage.py shell
```

```python
from whatsapp.utils import get_intro_message
print(get_intro_message('en'))  # English
print(get_intro_message('he'))  # Hebrew from .po (or Hebrew fallback if not compiled yet)
```

You can also test ad‑hoc strings:

```python
from django.utils import translation
from django.utils.translation import gettext as _
with translation.override('he'):
    print(_('Please choose your language'))  # if added to catalogs
```

### 6) Adding a new language
1. Add `(code, name)` to `LANGUAGES` in `backend/config/settings.py` (e.g., `('ar', 'Arabic')`).
2. Generate catalogs: `python manage.py makemessages -l ar -i db -i docker -i venv -i .venv`
3. Translate `locale/ar/LC_MESSAGES/django.po`.
4. Compile: `python manage.py compilemessages`.
5. Ensure `normalize_locale()` (if used) maps to your new code, or update logic accordingly.

### 7) CI/CD and development workflow
- Ensure gettext tools are available in your CI or Docker image.
- Option A: Build `.mo` files in CI (recommended) and deploy them with the image/artifacts.
- Option B: Commit compiled `.mo` files (simple, but larger diffs). Many teams prefer to compile in CI instead.

Makefile helpers (optional):

```makefile
messages:
	python manage.py makemessages -a -i db -i docker -i venv -i .venv

compilemessages:
	python manage.py compilemessages
```

### 8) Troubleshooting
- No translation shows: Did you run `compilemessages` after editing `.po`?
- Wrong or missing text: Does the `msgid` match exactly (including newlines/quotes)?
- Language not selected: Ensure the code calls `translation.override(locale)` with a supported language code (`'he'`/`'en'`).
- Catalog not found: Verify `LOCALE_PATHS` or app-level `locale/` exists and file layout is `locale/<lang>/LC_MESSAGES/django.(po|mo)`.

### Notes on WhatsApp and BiDi
- WhatsApp handles Hebrew RTL well, but mixed RTL/LTR text can be improved by isolating spans (RLI/LRI/PDI). Consider adding helpers if messages start to include mixed content.
- Payloads are sent as UTF‑8 JSON with `ensure_ascii=False` (already configured) so Hebrew appears correctly in logs and WhatsApp.
