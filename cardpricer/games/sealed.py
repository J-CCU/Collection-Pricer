"""Sealed product (booster boxes, packs, ETBs, decks, ...) for every game.

TCGplayer lists sealed product as products with no card number and no
rarity. A title is matched on its words: the set and the product type must
agree, and extra product words on either side ("Case", "Half", "Pokemon
Center", "Collector") count against a candidate, so a Booster Box never
prices as a Booster Box Case.
"""

import re
from difflib import SequenceMatcher

from ..conditions import extract_title_condition
from ..text import _name_words

# Words that change what the product is. A candidate that has one of these
# and the title doesn't (or the reverse) is a different product.
PRODUCT_WORDS = {"case", "half", "display", "box", "pack", "packs", "bundle", "booster", "collector", "set",
                 "draft", "play", "jumpstart", "elite", "trainer", "etb", "tin", "mini", "blister", "deck",
                 "commander", "starter", "theme", "prerelease", "kit", "premium", "collection", "sleeved",
                 "center", "exclusive", "build", "battle", "ultra", "art", "structure", "tuck", "double",
                 "master", "multipack", "retail", "hobby", "japanese", "korean", "chinese"}
# A case / half box / master case is a different product at a very
# different price; mismatching one of these weighs heavily.
MAJOR_WORDS = {"case", "half", "master", "multipack"}
FILLER_WORDS = {"sealed", "factory", "new", "unopened", "english", "the", "of", "a", "and", "x", "mtg", "magic",
                "pokemon", "yugioh", "ygo", "optcg", "riftbound", "tcg", "card", "game", "cards", "with", "in",
                "brand", "nib", "nisb", "shrink", "shrinkwrap", "shrinkwrapped", "wrapped", "sealed:",
                "1st", "edition", "unlimited"}
SYNONYMS = {"etb": ["elite", "trainer", "box"], "bb": ["booster", "box"], "upc": ["ultra", "premium", "collection"],
            "boosterbox": ["booster", "box"], "packs": ["pack"], "decks": ["deck"], "boxes": ["box"],
            "displays": ["display"], "pokémon": ["pokemon"]}


# Different names for the same product shape ("Booster Display" is what
# TCGplayer calls a Magic / One Piece booster box).
KIND_EQUIVALENTS = {"display": "box"}


def _words(text):
    # "[Set of 2]", "(Set of 4)": several units, a different product.
    text = re.sub(r"\bset\s+of\s+\d+\b", " multipack ", text or "", flags=re.I)
    out = []
    for w in _name_words(text):
        out.extend(SYNONYMS.get(w, [w]))
    return out


def _kinds(words):
    return {KIND_EQUIVALENTS.get(w, w) for w in words if w in PRODUCT_WORDS}


class SealedMatcher:
    def __init__(self, catalogs):
        """catalogs: {game: Catalog}"""
        self.products = []
        self.by_word = {}
        for game, cat in catalogs.items():
            if not cat:
                continue
            for p in cat.products.values():
                if not p["sealed"]:
                    continue
                group_words = set(_words(p["group_name"])) | {p["group_abbr"].lower()} - {""}
                words = set(_words(p["name"])) | group_words
                entry = (p, words, group_words)
                self.products.append(entry)
                for w in words - PRODUCT_WORDS - FILLER_WORDS:
                    self.by_word.setdefault(w, []).append(entry)

    def match(self, raw, games=None):
        """Return (product or None, score, review, top candidate names)."""
        _cond, text = extract_title_condition(raw or "")
        words = [w for w in _words(text) if w not in FILLER_WORDS]
        if not words:
            return None, 0.0, "SEALED - NO NAME", []
        title_kind = _kinds(words)
        title_rest = set(words) - PRODUCT_WORDS
        pool = {}
        for w in title_rest:
            for entry in self.by_word.get(w, ()):
                pool[entry[0]["id"]] = entry
        scored = []
        for p, pwords, group_words in pool.values():
            if games and p["game"] not in games:
                continue
            p_kind = _kinds(pwords)
            p_rest = pwords - PRODUCT_WORDS - FILLER_WORDS
            rest_hit = len(title_rest & p_rest) / max(1, len(title_rest))
            kind_extra = len(p_kind - title_kind)       # product words the title didn't say
            kind_missing = len(title_kind - p_kind)     # title words this product lacks
            # Name words beyond the set name that the title never mentioned
            # ("Nightmare" Bundle when the title says just "Bundle").
            name_extra = len(p_rest - group_words - title_rest)
            seq = SequenceMatcher(None, " ".join(words), " ".join(_words(p["name"]))).ratio()
            major = len((p_kind ^ title_kind) & MAJOR_WORDS)
            score = (rest_hit * 0.6 + seq * 0.4 - 0.15 * kind_extra - 0.2 * kind_missing - 0.1 * name_extra
                     - 0.3 * major)
            scored.append((score, p))
        if not scored:
            return None, 0.0, "SEALED - NO MATCH", []
        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        top = [f"{p['name']} ({p['group_name']})" for _s, p in scored[:3]]
        if best_score >= 0.6 and best_score - second >= 0.05:
            return best, best_score, "", top
        if best_score >= 0.6:
            return None, best_score, "SEALED - SEVERAL PRODUCTS MATCH", top
        return None, best_score, "SEALED - NO CONFIDENT MATCH", top
