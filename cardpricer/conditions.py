"""Card condition vocabulary: any spelling -> NM/LP/MP/HP/DMG."""

import re

from .text import norm

# ------------------------------------------------------------
# Card condition vocabulary
# ------------------------------------------------------------
# Every condition is normalized to the TCGplayer scale: NM, LP, MP, HP, DMG.
# Other marketplace scales are mapped onto it:
#   Card Kingdom:      NM / EX / VG / G           -> NM / LP / MP / HP
#   Legacy US grading: M / NM / SP / PL           -> NM / NM / LP / MP
#   Cardmarket:        MT / NM / EX / GD / PL / PO -> NM / NM / LP / HP / MP / DMG
# Where scales disagree (Cardmarket "LP" is roughly TCGplayer MP), the US
# meaning wins because prices come from TCGplayer via Scryfall.
CONDITION_ORDER = ("NM", "LP", "MP", "HP", "DMG")

CONDITION_ALIASES = {
    "near mint": "NM", "nm": "NM", "mint": "NM", "mt": "NM", "gem mint": "NM",
    "near mint or better": "NM", "nm/m": "NM", "nm-m": "NM",
    "lightly played": "LP", "light played": "LP", "lp": "LP",
    "slightly played": "LP", "sp": "LP", "excellent": "LP", "ex": "LP",
    "moderately played": "MP", "mp": "MP", "played": "MP", "pl": "MP",
    "very good": "MP", "vg": "MP",
    "heavily played": "HP", "heavy played": "HP", "hp": "HP", "good": "HP", "gd": "HP",
    "damaged": "DMG", "dmg": "DMG", "dm": "DMG", "poor": "DMG", "po": "DMG",
}

# Single letters are only trusted in an explicit condition column.
CONDITION_SHORT_ALIASES = {"m": "NM", "g": "HP", "d": "DMG"}

# Words that can appear in a card title, so they are only treated as a
# condition when they trail the title or sit in parentheses/brackets.
CONDITION_TRAILING_ONLY = {"mint", "mt", "excellent", "good", "very good", "played",
                           "poor", "po", "pl", "gd", "dm", "gem mint"}

_COND_ALT = "|".join(sorted((re.escape(k).replace(r"\ ", r"\s+") for k in CONDITION_ALIASES),
                            key=len, reverse=True))

_COND_TITLE_RE = re.compile(
    r"(?<![\w'])((?:" + _COND_ALT + r")(?:\s*[/-]\s*(?:" + _COND_ALT + r"))?)"
    r"(?:\+|-(?!\s*\d))?(?:\s+condition)?(?![\w'])",
    re.I,
)

_COND_TRAILER_RE = re.compile(r"^(?:\s|[)\]|,;*–—-]|\([^()]*\))*$")

def normalize_condition(value, allow_short=True):
    """Map any condition spelling to NM/LP/MP/HP/DMG, or a range like "LP/MP".

    Returns None when the value is not a recognizable condition.
    """
    # Exports write "near_mint" (ManaBox) or "Good (Lightly Played)" (Deckbox,
    # where the bracketed text is the TCGplayer grade); try that text first.
    inner = re.search(r"\(([^()]+)\)", value or "")
    if inner and not re.fullmatch(r"\s*\(([^()]+)\)\s*", value or ""):
        found = normalize_condition(inner.group(1), allow_short)
        if found:
            return found
    n = re.sub(r"\s+", " ", norm(value).replace("_", " ").strip(" .*()[]"))
    if not n:
        return None
    aliases = dict(CONDITION_ALIASES)
    if allow_short:
        aliases.update(CONDITION_SHORT_ALIASES)
    if n in aliases:
        return aliases[n]
    n = n.rstrip("+-").strip()
    if n in aliases:
        return aliases[n]
    parts = [p.strip().rstrip("+-").strip() for p in re.split(r"\s*(?:/|-|\bto\b)\s*", n)]
    mapped = [aliases.get(p) for p in parts if p]
    if not mapped or None in mapped:
        return None
    found = sorted(set(mapped), key=CONDITION_ORDER.index)
    return found[0] if len(found) == 1 else f"{found[0]}/{found[-1]}"

def extract_title_condition(text, name_words=()):
    """Find a condition written in a card title and remove it from the title.

    Returns (condition or "", cleaned text). If several conditions appear,
    the last one wins. Words that can be part of a card name (Good, Mint,
    Played, ...) only count when they trail the title or are bracketed.
    name_words are words a game uses in card names ("ex" in "Charizard ex",
    "SP" in One Piece) and are never read as a condition.
    """
    found = ""
    spans = []
    for m in _COND_TITLE_RE.finditer(text or ""):
        phrase = m.group(1)
        words = {norm(p) for p in re.split(r"\s*[/-]\s*", phrase)}
        if words & set(name_words):
            continue
        if words & CONDITION_TRAILING_ONLY:
            bracketed = (re.search(r"[(\[]\s*$", text[:m.start()])
                         and re.match(r"\s*[)\]]", text[m.end():]))
            if not bracketed and not _COND_TRAILER_RE.match(text[m.end():]):
                continue
        cond = normalize_condition(phrase, allow_short=False)
        if not cond:
            continue
        found = cond
        spans.append(m.span())
    cleaned = text or ""
    for start, end in reversed(spans):
        cleaned = cleaned[:start] + " " + cleaned[end:]
    if spans:
        cleaned = re.sub(r"[(\[]\s*[)\]]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;|*-")
    return found, cleaned

def _looks_like_condition(value):
    return normalize_condition(value, allow_short=False) is not None
