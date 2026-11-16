"""Language, grading and sealed-product clues found in titles."""

import re

# Language words/codes sellers put in titles. Multi-word entries come first
# so "Simplified Chinese" wins over "Chinese".
LANGUAGE_ALIASES = {
    "SIMPLIFIED CHINESE": "zhs", "TRADITIONAL CHINESE": "zht",
    "JAPANESE": "ja", "GERMAN": "de", "FRENCH": "fr", "ITALIAN": "it",
    "SPANISH": "es", "PORTUGUESE": "pt", "RUSSIAN": "ru", "KOREAN": "ko",
    "CHINESE": "zhs", "ENGLISH": "en", "ENG": "en",
    "JPN": "ja", "JP": "ja", "JAP": "ja", "TCH": "zht", "CHT": "zht",
    "SCH": "zhs", "CHS": "zhs", "ITL": "it", "ITA": "it", "GRM": "de",
    "GER": "de", "FRN": "fr", "FRE": "fr", "SPN": "es", "SPA": "es",
    "RUS": "ru", "KOR": "ko", "POR": "pt",
}

LANGUAGE_CODES = {"en", "ja", "de", "fr", "it", "es", "pt", "ru", "ko", "zhs", "zht", "zh", "ph"}

# Anything outside Latin, punctuation and common symbol blocks.
NON_LATIN_RE = re.compile(r"[^\x00-ɏḀ-ỿ -⅟←-⏿☀-➿]")

# Graders and grades: "PSA 10", "BGS 9.5", "CGC Gem Mint 10", "Beckett 9".
GRADED_RE = re.compile(
    r"\b(PSA|BGS|CGC|SGC|TAG|BECKETT)\s*(?:gem\s*mint\s*|mint\s*|pristine\s*)?(\d{1,2}(?:\.\d+)?)(?![\d.])", re.I)

# Sealed product. Bare "box"/"deck"/"pack" are left out because card names
# use them (Pandora's Box, Pack Rat, Deck of Fate).
SEALED_RE = re.compile(
    r"\bsealed\b|\bunopened\b|\bfactory\s+sealed\b|\bshrink\s*wrap(?:ped)?\b"
    r"|\bbooster\s+(?:box|pack|packs|display|case|brick|bundle)\b"
    r"|\b(?:collector|set|draft|play|jumpstart|vip|premium)\s+boosters?(?:\s+(?:box|pack|display|case))?\b"
    r"|\b(?:bundle|fat\s+pack|gift\s+bundle|gift\s+box|prerelease\s+(?:kit|pack)|starter\s+kit"
    r"|(?:commander|starter|theme|planeswalker|intro|challenger|duel|event|welcome|brawl)\s+decks?"
    r"|precon(?:structed)?(?:\s+deck)?|tournament\s+pack|deck\s*builder'?s\s+toolkit|premium\s+deck\s+series"
    r"|secret\s+lair\s+(?:drop|bundle))\b",
    re.I,
)

GRADED_WORD_RE = re.compile(r"\bgraded\b|\bslab(?:bed)?\b", re.I)

def language_code(value):
    """Map a language cell/word to a Scryfall language code, or None."""
    v = (value or "").strip()
    if not v:
        return None
    if v.upper() in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[v.upper()]
    if v.lower() in LANGUAGE_CODES:
        return v.lower()
    return None
