from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Pattern


# Zero-width and bidi controls commonly seen in chat apps
_ZW_CHARS = {
    "\u200b",
    "\u200c",
    "\u200d",
    "\ufeff",
}
_BIDI_CHARS = {
    "\u200e",
    "\u200f",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
}

# Hebrew niqqud (combining marks) range
_NIQQUD_START, _NIQQUD_END = 0x0591, 0x05C7

# Common dash and quote variants (including Hebrew geresh/gershayim)
_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u05be"  # includes maqaf
_QUOTES = "\u2018\u2019\u201a\u201b\u201c\u201d\u201e\u201f\u05f3\u05f4"

_RE_MULTISPACE = re.compile(r"\s+")
# Safe repeated-letters collapse for Hebrew and Latin letters
_RE_REPEAT_SAFE = re.compile(r"([A-Za-z\u0590-\u05FF])\1{2,}")


def strip_niqqud(s: str) -> str:
    return "".join(ch for ch in s or "" if not (_NIQQUD_START <= ord(ch) <= _NIQQUD_END))


def normalize_for_match(s: str) -> str:
    """Normalize free-form user text for robust matching.

    This function is intended for keyword/category comparisons and fuzzy text
    matching of short fields. It should not be used for numeric parsing.
    """
    if not s:
        return ""
    # Unicode normalization
    s = unicodedata.normalize("NFKC", s)
    # Strip invisible and direction controls
    s = "".join(ch for ch in s if ch not in _ZW_CHARS and ch not in _BIDI_CHARS)
    # Remove niqqud (Hebrew diacritics)
    s = strip_niqqud(s)
    # Canonicalize quotes and dashes
    s = s.translate({ord(ch): "'" for ch in _QUOTES})
    s = s.translate({ord(ch): "-" for ch in _DASHES})
    # Unicode-friendly lowercase
    s = s.casefold()
    # Collapse long repeated letters (e.g., כןןן => כן)
    s = _RE_REPEAT_SAFE.sub(r"\1\1", s)
    # Keep letters, numbers, spaces, and hyphens only
    s = re.sub(r"[^0-9A-Za-z\u0590-\u05FF\s-]", "", s)
    # Normalize whitespace
    s = _RE_MULTISPACE.sub(" ", s).strip()
    return s


@dataclass(frozen=True)
class KeywordSet:
    words: set[str]
    patterns: tuple[Pattern[str], ...] = ()


# Centralized keyword registry by semantic category and locale
_RE_HE_SKIP = re.compile(r"^דלג(ו)?$")

KEYWORDS: dict[str, dict[str, KeywordSet]] = {
    "cancel": {
        "en": KeywordSet({"cancel", "stop", "end", "quit"}),
        "he": KeywordSet({"בטל", "ביטול", "סיים", "סיום"}),
    },
    "yes": {
        "en": KeywordSet({"yes", "y", "yeah", "yep", "si"}),
        "he": KeywordSet({"כן"}),
    },
    "no": {
        "en": KeywordSet({"no", "n", "nope", "not"}),
        "he": KeywordSet({"לא", "אין"}),
    },
    "skip": {
        "en": KeywordSet({
            "skip",
            "n/a",
            "na",
            "none",
            "unknown",
            "dont know",
            "don't know",
            "generic",
            "no brand",
            "no branch",
        }),
        "he": KeywordSet({"דלג", "דלגו", "אין", "בלי", "אין מותג", "בלי מותג", "אין סניף", "בלי סניף", "לא יודע", "לא ידוע"}, patterns=(
            _RE_HE_SKIP,
        )),
    },
    "city_change": {
        "en": KeywordSet({"change city", "change", "other city"}),
        "he": KeywordSet({"שנה עיר", "שנו עיר", "עיר אחרת", "שינוי עיר"}),
    },
}


def _lang_of(locale: str | None) -> str:
    if not locale:
        return "en"
    s = (locale or "").strip().lower()
    return "he" if s.startswith("he") else "en"


def is_keyword_norm(text_norm: str, category: str, locale: str | None = None) -> bool:
    """Match a normalized text against a semantic keyword category.

    Use this when you already normalized with normalize_for_match.
    """
    t = (text_norm or "").strip()
    if not t:
        return False
    lang = _lang_of(locale)
    options = KEYWORDS.get(category, {})
    ks = options.get(lang) or options.get("en")
    if not ks:
        return False
    if t in ks.words:
        return True
    return any(p.fullmatch(t) for p in ks.patterns)


def is_keyword(text: str, category: str, locale: str | None = None) -> bool:
    """Normalize the given text and match it to a keyword category."""
    return is_keyword_norm(normalize_for_match(text), category, locale)
