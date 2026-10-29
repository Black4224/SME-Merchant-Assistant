"""Forgiving person-name matching ("علي الجبوري" must find "علي صباح الجبوري")."""
import re

from app.services.text import normalize_text

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def name_tokens(value: str) -> list[str]:
    return [t for t in _PUNCT.sub(" ", normalize_text(value)).split() if t]


def name_matches(query: str, name: str) -> bool:
    """True if the normalised query is a substring of the name, or every query word is a word of the name."""
    q = normalize_text(query)
    if not q:
        return False
    if q in normalize_text(name):
        return True
    qt, nt = name_tokens(query), set(name_tokens(name))
    return bool(qt) and all(t in nt for t in qt)
