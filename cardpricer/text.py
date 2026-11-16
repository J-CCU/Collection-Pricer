"""Text normalization and small parsing helpers shared by every game."""

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

# Known set aliases remain user-facing conveniences. Card treatments/variants are
# intentionally NOT maintained as a hard-coded list. The matcher learns available
# treatment metadata directly from Scryfall bulk data (frame_effects, promo_types,
# finishes, frame, and related flags), so new treatments can be recognized without
# another program update.



def norm(s):
    s = s or ""
    s = (s.replace("\u2019", "'").replace("\u2018", "'")
           .replace("\u2013", "-").replace("\u2014", "-")
           .replace("\u00a0", " "))
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s.strip().lower())

def compact(s):
    return re.sub(r"[^a-z0-9]", "", norm(s))

def collector_number_equal(a, b):
    """Compare collector numbers without treating leading zeros as meaningful."""
    a = norm(a)
    b = norm(b)
    if a == b:
        return True
    if re.fullmatch(r"0*\d+", a or "") and re.fullmatch(r"0*\d+", b or ""):
        return str(int(a)) == str(int(b))
    return False

def money(v):
    try:
        if v in (None, ""):
            return None
        return float(str(v).replace("$", "").replace(",", "").strip())
    except Exception:
        return None

def money_text(v):
    return "" if v is None else f"${v:,.2f}"

def round_cents(v):
    """Round to whole cents, half up (0.865 -> 0.87). Offers and Extended
    Value use this so each row and the TOTAL row add up to the cent."""
    if v is None:
        return None
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def unique(seq):
    out = []
    seen = set()
    for x in seq:
        k = norm(x)
        if k and k not in seen:
            seen.add(k)
            out.append(x)
    return out

def split_leading_quantity(text):
    """Extract a clearly leading quantity without mistaking collector numbers."""
    text=(text or "").strip()
    if not text:
        return text, None
    if re.match(r"^(?:#|no\.?\s*|collector(?:\s+number|\s+no\.?)?\s*)\d+", text, re.I):
        return text, None
    m=re.match(r"^(\d+)\s*([xX]\s+|\s+)(.+)$", text)
    if not m:
        return text, None
    qty=int(m.group(1))
    # "151 Booster Bundle", "2002 Collectors Tin": a bare number over 99 is
    # part of the name; a real count that large is written "120x".
    if qty > 99 and "x" not in m.group(2).lower():
        return text, None
    return (m.group(3).strip(), qty) if qty >= 1 else (text, None)

def _is_number_only(value):
    return bool(re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", value or ""))

def _header_index(headers, aliases):
    normalized = {norm(h): i for i, h in enumerate(headers)}
    for alias in aliases:
        if norm(alias) in normalized:
            return normalized[norm(alias)]
    return None

def parse_qty(v):
    try:
        return max(1, int(float(v)))
    except Exception:
        return 1

def _name_words(text):
    """Words for whole-word name comparison; apostrophes are dropped so
    "Mishras" equals "Mishra's" and "//" in split cards is ignored."""
    return re.findall(r"[a-z0-9]+", norm(text).replace("'", ""))

def _bigrams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}
