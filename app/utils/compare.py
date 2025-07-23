# app/utils/compare.py
import re
from html import unescape

FIELDS_TO_COMPARE = ("name", "regular_price", "description", "short_description")

_TAG_RE = re.compile(r"<[^>]+>")

def norm(val: str | None) -> str:
    """Normalize for comparison: None -> '', strip HTML tags/whitespace, collapse spaces."""
    if not val:
        return ""
    val = unescape(val)
    val = _TAG_RE.sub("", val)          # strip tags
    val = " ".join(val.split())         # collapse whitespace
    return val.strip()

def needs_update(current: dict, desired: dict) -> bool:
    for f in FIELDS_TO_COMPARE:
        if norm(current.get(f, "")) != norm(desired.get(f, "")):
            return True
    return False
