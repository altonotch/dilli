from __future__ import annotations

import re
from typing import Optional


UNIT_CANONICALS = [
    {
        "slug": "liter",
        "en": "Liter",
        "he": "ליטר",
        "aliases": ["liter", "litre", "ltr", "l", "ליטר", "ליט'", "ל'"],
    },
    {
        "slug": "milliliter",
        "en": "Milliliter",
        "he": "מיליליטר",
        "aliases": ["milliliter", "millilitre", "ml", "מיליליטר", "מ״ל", "מל"],
    },
    {
        "slug": "kilogram",
        "en": "Kilogram",
        "he": "קילוגרם",
        "aliases": ["kilogram", "kg", "kilo", "ק\"ג", "קג", "קילו", "קילוגרם"],
    },
    {
        "slug": "gram",
        "en": "Gram",
        "he": "גרם",
        "aliases": ["gram", "gr", "g", "גרם", "ג'", "גר"],
    },
    {
        "slug": "unit",
        "en": "Unit",
        "he": "יחידה",
        "aliases": ["unit", "piece", "pcs", "יחידה", "יח'", "יחידות"],
    },
    {
        "slug": "pack",
        "en": "Pack",
        "he": "חבילה",
        "aliases": ["pack", "package", "pkg", "חבילה", "חב'", "חב"],
    },
    {
        "slug": "bottle",
        "en": "Bottle",
        "he": "בקבוק",
        "aliases": ["bottle", "btl", "בקבוק"],
    },
    {
        "slug": "can",
        "en": "Can",
        "he": "פחית",
        "aliases": ["can", "פחית"],
    },
    {
        "slug": "bag",
        "en": "Bag",
        "he": "שקית",
        "aliases": ["bag", "sack", "שקית", "שק"],
    },
    {
        "slug": "tray",
        "en": "Tray",
        "he": "מגש",
        "aliases": ["tray", "מגש"],
    },
    {
        "slug": "box",
        "en": "Box",
        "he": "קופסה",
        "aliases": ["box", "pkg", "קופסה", "קופסא"],
    },
    {
        "slug": "jar",
        "en": "Jar",
        "he": "צנצנת",
        "aliases": ["jar", "צנצנת"],
    },
    {
        "slug": "tub",
        "en": "Tub",
        "he": "מיכל",
        "aliases": ["tub", "מיכל"],
    },
]

_TOKEN_RE = re.compile(r"[^a-z\u0590-\u05FF0-9]+", re.IGNORECASE)


def _contains_hebrew(value: str) -> bool:
    return any("\u0590" <= ch <= "\u05FF" for ch in value or "")


def _normalize_token(value: str) -> str:
    return _TOKEN_RE.sub("", (value or "").strip().lower())


def _match_unit(value: str) -> Optional[dict]:
    normalized = _normalize_token(value)
    for entry in UNIT_CANONICALS:
        aliases = entry.get("aliases", [])
        if normalized in {_normalize_token(alias) for alias in aliases}:
            return entry
        # Also allow direct match on canonical forms
        if normalized in (_normalize_token(entry["en"]), _normalize_token(entry["he"])):
            return entry
    return None


def resolve_unit_translation(value: str) -> dict:
    """Return dict with he/en labels for the provided unit text."""
    cleaned = (value or "").strip()
    if not cleaned:
        return {"he": "", "en": "", "slug": ""}
    match = _match_unit(cleaned)
    if match:
        return {"he": match["he"], "en": match["en"], "slug": match["slug"]}
    if _contains_hebrew(cleaned):
        return {"he": cleaned, "en": cleaned.title(), "slug": _normalize_token(cleaned)}
    capitalized = cleaned.title()
    return {"he": capitalized, "en": capitalized, "slug": _normalize_token(cleaned)}


def select_unit_for_locale(data: dict, locale: str) -> str:
    if locale.startswith("he"):
        return data.get("unit_type_he") or data.get("unit_type_en") or data.get("unit_type") or ""
    return data.get("unit_type_en") or data.get("unit_type_he") or data.get("unit_type") or ""


def get_unit_by_slug(slug: str) -> Optional[dict]:
    normalized = _normalize_token(slug)
    for entry in UNIT_CANONICALS:
        if _normalize_token(entry["slug"]) == normalized:
            return entry
    return None


def get_unit_label_for_locale(slug: str, locale: str) -> Optional[str]:
    entry = get_unit_by_slug(slug)
    if not entry:
        return None
    return entry["he"] if locale.startswith("he") else entry["en"]
