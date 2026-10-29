"""Arabic-aware text normalisation for search and duplicate detection."""
import re
import unicodedata

_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u0640]")  # tashkeel + tatweel
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ؤ": "و", "ئ": "ي"})


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = _DIACRITICS.sub("", text).translate(_DIGITS).translate(_LETTERS)
    return re.sub(r"\s+", " ", text).strip().casefold()
