# app/utils/compare.py
import os
import re
from html import unescape
from decimal import Decimal, InvalidOperation

# Fields we diff in both preview + bulk update
FIELDS_TO_COMPARE = ("name", "regular_price", "description", "short_description")

# Optional % tolerance for price differences (env override)
# e.g. PRICE_TOLERANCE_PCT=0 (default = exact match)
PRICE_TOL_PCT = Decimal(os.getenv("PRICE_TOLERANCE_PCT", "0"))

_TAG_RE = re.compile(r"<[^>]+>")


def norm(val: str | None) -> str:
    """Normalize for comparison: None -> '', strip HTML tags/whitespace, collapse spaces."""
    if not val:
        return ""
    val = unescape(val)
    val = _TAG_RE.sub("", val)
    val = " ".join(val.split())
    return val.strip()


def _to_decimal(v):
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return None


def prices_equal(a, b, tol: str = "0.005") -> bool:
    """
    Absolute tolerance compare (≤ tol). Treat None/"" both sides as equal.
    """
    da, db = _to_decimal(a), _to_decimal(b)
    if da is None and db is None:
        return True
    if da is None or db is None:
        return False
    return (da - db).copy_abs() <= Decimal(tol)


def prices_close(a, b) -> bool:
    """
    Percentage tolerance compare (≤ PRICE_TOL_PCT).
    If PRICE_TOL_PCT == 0, falls back to exact equality.
    """
    da, db = _to_decimal(a), _to_decimal(b)
    if da is None and db is None:
        return True
    if da is None or db is None:
        return False
    if PRICE_TOL_PCT == 0:
        return da == db
    base = db if db != 0 else Decimal("1")
    diff_pct = (da - db).copy_abs() / base * Decimal("100")
    return diff_pct <= PRICE_TOL_PCT


def needs_update(desired: dict, current: dict) -> bool:
    """
    desired: payload we want to push
    current: Woo product json

    Numeric compare for price (both absolute & optional % tolerance),
    text compare (normalized) for everything else.
    """
    for f in FIELDS_TO_COMPARE:
        if f == "regular_price":
            # If we didn't compute a price, don't force an update
            if desired.get(f) in (None, ""):
                continue

            if not prices_equal(desired.get(f), current.get(f)) and not prices_close(
                desired.get(f), current.get(f)
            ):
                return True
        else:
            if norm(desired.get(f, "")) != norm(current.get(f, "")):
                return True
    return False
