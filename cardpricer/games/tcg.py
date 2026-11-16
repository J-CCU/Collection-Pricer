"""Pokémon, Yu-Gi-Oh!, One Piece and Riftbound identification against the
TCGplayer catalog (TCGCSV).

A title is split into clues (number, set, finish, variant, condition, grade,
language) and a name. The name must match a card name exactly, or by a
strict typo-tolerant match. The clues then narrow the printings. When the
clues do not narrow it to one printing (e.g. "Pikachu", which has 133), the
row goes to MANUAL CHECK with the number of printings and their price range:
the printing can't be known without the card in hand.
"""

import heapq
import re
from difflib import SequenceMatcher

from ..clues import GRADED_RE, GRADED_WORD_RE, LANGUAGE_ALIASES, NON_LATIN_RE
from ..conditions import extract_title_condition
from ..sources.tcgcsv import choose_price
from ..text import _bigrams, _name_words, norm, unique

# Words in a title that name the game itself.
GAME_TITLE_WORDS = {
    "magic": ("mtg", "magic the gathering", "magic: the gathering"),
    "pokemon": ("pokemon", "pokémon", "ptcg", "pkmn"),
    "yugioh": ("yugioh", "yu-gi-oh!", "yu-gi-oh", "ygo"),
    "onepiece": ("one piece tcg", "one piece card game", "optcg"),
    "riftbound": ("riftbound",),
}

# Card-number shapes, most specific first.
NUMBER_PATTERNS = [
    re.compile(r"(?<![\w/])([A-Za-z]{0,4}\d{1,4}[a-zA-Z*]?\s?/\s?[A-Za-z]{0,4}\d{1,4})(?![\w/])"),  # 025/165, TG03/TG30
    re.compile(r"(?<![\w-])([A-Za-z0-9]{2,5}-[A-Za-z]{0,3}\d{1,4}[a-zA-Z]?)(?![\w-])"),             # LOB-EN001, OP01-120
    re.compile(r"(?<![\w-])((?:SWSH|SM|XY|BW|SVP|SV|HGSS|DP|NP|MEP|TG|GG|RC|SVE)\s?\d{1,3})(?![\w-])", re.I),
    re.compile(r"#\s?(\d{1,4}[a-zA-Z]?)\b"),
]

# Finish words -> words the TCGplayer subtype must contain (Pokémon:
# Normal / Holofoil / Reverse Holofoil / 1st Edition (Holofoil) / Unlimited
# (Holofoil); Yu-Gi-Oh: 1st Edition / Unlimited / Limited; One Piece and
# Riftbound: Normal / Foil).
FINISH_PHRASES = [
    (r"reverse\s+holo(?:foil)?|rev\s+holo|reverse|\brh\b", {"reverse"}),
    (r"1st\s+ed(?:ition|\.)?\s+holo(?:foil)?|first\s+edition\s+holo(?:foil)?", {"1st", "holofoil"}),
    (r"unlimited\s+holo(?:foil)?", {"unlimited", "holofoil"}),
    (r"1st\s+ed(?:ition|\.)?|first\s+edition|\b1st\b", {"1st"}),
    (r"\bunlimited\b|\bunl\b", {"unlimited"}),
    (r"\blimited\s+edition\b", {"limited"}),
    (r"non[\s-]?holo|non[\s-]?foil|nonfoil", {"normal"}),
    (r"\bholo(?:foil|graphic)?\b", {"holofoil"}),
    (r"\bfoil\b", {"foil"}),
]
# Variant / rarity words, kept as clues and checked against the product's
# name tags and rarity. Short forms map to TCGplayer's wording.
VARIANT_SYNONYMS = {
    "alt art": "alternate art", "aa": "alternate art", "sir": "special illustration rare",
    "ir": "illustration rare", "fa": "full art", "qcsr": "quarter century secret rare",
    "ex art": "extended art", "sar": "special art rare",
}
VARIANT_PHRASES = sorted({
    "special illustration rare", "illustration rare", "hyper rare", "secret rare", "ultra rare", "super rare",
    "ultimate rare", "starlight rare", "ghost rare", "quarter century secret rare", "platinum secret rare",
    "prismatic secret rare", "collector's rare", "gold rare", "premium gold rare", "rainbow rare", "shiny rare",
    "alternate art", "alt art", "full art", "extended art", "manga", "parallel", "overnumbered", "showcase",
    "special art", "sp", "sir", "ir", "aa", "fa", "qcsr", "sar", "shadowless", "prerelease", "staff", "stamped",
    "promo", "jumbo", "oversized", "signature", "textured", "gold", "shiny", "radiant", "error", "misprint",
}, key=len, reverse=True)

# Names sellers use for sets that differ from TCGplayer's set name.
SET_NICKNAMES = {
    "pokemon": {"151": "SV: Scarlet & Violet 151", "base": "Base Set", "base set unlimited": "Base Set",
                "shadowless": "Base Set (Shadowless)", "1st edition base set": "Base Set (Shadowless)"},
}

# Per game: words used in card names that must not be read as conditions.
NAME_WORDS = {"pokemon": ("ex",), "onepiece": ("sp",), "yugioh": (), "riftbound": ()}

# Sealed words beyond the shared SEALED_RE. These only count when the rest of
# the title is not a card name ("Structure Deck" is also a set name).
TCG_SEALED_RE = re.compile(
    r"\b(?:elite\s+trainer\s+box|etb|blister|booster\s+bundle|build\s*(?:&|and)\s*battle|premium\s+collection"
    r"|ultra[\s-]premium\s+collection|upc|collection\s+box|mini\s+tin|tin|booster\s+display|display\s+box"
    r"|display|sleeved\s+booster|structure\s+deck|starter\s+deck|tuck\s+box|double\s+pack|deck\s+set"
    r"|booster\s+pack|booster\s+box|booster|case|half\s+booster\s+box)\b", re.I)


def number_key(num):
    """Comparable card number: "025/165" -> "25/165", "TG03" -> "tg3"."""
    s = re.sub(r"\s+", "", norm(num)).replace("*", "")
    return re.sub(r"\d+", lambda m: str(int(m.group())), s)


def core_name(name):
    """Card identity name: tags and trailing numbers removed.
    "Nami (OP01-016) (SP)" -> "Nami", "Pikachu - 173/165" -> "Pikachu"."""
    s = re.sub(r"\s*\([^()]*\)", "", name or "")
    s = re.sub(r"\s*\[[^\[\]]*\]", "", s)
    s = re.sub(r"\s+-\s+[A-Za-z0-9]*\d[A-Za-z0-9/\-]*\s*$", "", s)
    return s.strip()


def name_key(name):
    return " ".join(_name_words(name))


def product_tags(product):
    """Variant tags TCGplayer puts in brackets, excluding pure numbers/codes."""
    tags = re.findall(r"\(([^()]*)\)", product["name"]) + re.findall(r"\[([^\[\]]*)\]", product["name"])
    return [t for t in tags if not re.fullmatch(r"[A-Za-z]{0,4}\d{1,4}[a-z]?|[A-Za-z0-9]{2,5}-[A-Za-z]{0,3}\d{1,4}", t.strip())]


def is_promo(product):
    return (norm(product.get("rarity", "")) in {"promo", "pr"}
            or "promo" in norm(product.get("group_name", "")))


def variant_text(product):
    return norm(" ".join(product_tags(product) + [product.get("rarity", "")]))


class NameIndex:
    """Exact and strict typo-tolerant lookup over one game's card names."""

    def __init__(self, keys):
        self.keys = set(keys)
        self.by_length = {}
        self.by_token = {}
        for k in self.keys:
            c = k.replace(" ", "")
            self.by_length.setdefault(len(c), []).append(k)
            for tok in k.split():
                if len(tok) >= 3:
                    self.by_token.setdefault(tok, []).append(k)
        self.cache = {}

    def fuzzy(self, query):
        """(key, ratio) for a confident single best match, else (None, ratio)."""
        q = name_key(query)
        if q in self.cache:
            return self.cache[q]
        qc = q.replace(" ", "")
        if len(qc) < 4:
            return None, 0.0
        pool = set()
        for tok in q.split():
            pool.update(self.by_token.get(tok, ()))
        radius = max(2, min(6, len(qc) // 5))
        for ln in range(max(1, len(qc) - radius), len(qc) + radius + 1):
            pool.update(self.by_length.get(ln, ()))
        if len(pool) > 600:
            qg = _bigrams(qc)
            pool = heapq.nlargest(600, pool, key=lambda k: len(qg & _bigrams(k.replace(" ", ""))) / len(qg | _bigrams(k.replace(" ", ""))))
        scored = sorted(((SequenceMatcher(None, qc, k.replace(" ", "")).ratio(), k) for k in pool), reverse=True)
        if not scored:
            return None, 0.0
        best_ratio, best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        ok = best_ratio >= (0.86 if len(qc) >= 8 else 0.9) and (best_ratio - second >= 0.05 or best_ratio >= 0.95)
        result = (best if ok else None, best_ratio)
        self.cache[q] = result
        return result


class TCGMatcher:
    """Identify cards of one TCGCSV game."""

    def __init__(self, game, catalog):
        self.game = game
        self.catalog = catalog
        self.by_core = {}
        self.by_number = {}
        for p in catalog.products.values():
            if p["sealed"]:
                continue
            self.by_core.setdefault(name_key(core_name(p["name"])), []).append(p)
            if p["number"]:
                for part in re.split(r"\s*//\s*", p["number"]):
                    key = number_key(part)
                    self.by_number.setdefault(key, []).append(p)
                    if "/" in key:
                        self.by_number.setdefault(key.split("/")[0], []).append(p)
        self.names = NameIndex(self.by_core)
        self.set_lookup = {}       # phrase -> {groupId}
        self.set_abbrs = set()     # upper-case abbreviations, matched case-sensitively
        # Full set names first; shortened forms ("Evolving Skies" for
        # "SWSH07: Evolving Skies", "Base Set" for "Base Set (Shadowless)")
        # only where they don't name another set exactly.
        short_keys = []
        for gid, g in catalog.groups.items():
            name = g.get("name", "")
            self.set_lookup.setdefault(name_key(name), set()).add(gid)
            short = {norm(re.sub(r"\s*\([^()]*\)", "", name))}
            m = re.match(r"^([A-Za-z0-9&\- ]{1,12}):\s*(.+)$", name)
            if m:
                short.update({norm(m.group(2)), norm(re.sub(r"\s*\([^()]*\)", "", m.group(2)))})
                if re.search(r"\d", m.group(1)):
                    short.add(norm(m.group(1)))
            short_keys += [(name_key(k), gid) for k in short if k]
            abbr = (g.get("abbreviation") or "").strip()
            if len(abbr) >= 2:
                self.set_abbrs.add(abbr.upper())
                self.set_lookup.setdefault("abbr:" + abbr.upper(), set()).add(gid)
                # "ST01" and "ST-01" are the same code.
                self.set_lookup.setdefault("abbr:" + re.sub(r"[^A-Z0-9]", "", abbr.upper()), set()).add(gid)
        full = set(self.set_lookup)
        for key, gid in short_keys:
            if key and key not in full:
                self.set_lookup.setdefault(key, set()).add(gid)
        for alias, target in SET_NICKNAMES.get(game, {}).items():
            gids = self.set_lookup.get(name_key(target))
            if gids:
                self.set_lookup.setdefault(name_key(alias), set()).update(gids)

    # ------------------------------------------------------------ parsing
    def parse(self, raw):
        """Split a title into clues and a name (dict shaped like Magic's)."""
        work = (raw or "").replace("’", "'")
        parsed = {"raw": raw, "game": self.game, "finish": "", "finish_explicit": False, "finish_words": set(),
                  "variant_terms": [], "serialized": False, "signed": bool(re.search(r"\bsigned\b", work, re.I)),
                  "set_groups": set(), "set_cues": [], "number": "", "language": "", "language_tokens": [],
                  "graded": False, "grader": "", "grade": "", "sealed": False, "set_product": False}
        parsed["row_condition"], work = extract_title_condition(work, NAME_WORDS.get(self.game, ()))

        g = GRADED_RE.search(work)
        if g or GRADED_WORD_RE.search(work):
            parsed["graded"] = True
            if g:
                parsed["grader"] = "BGS" if g.group(1).upper() == "BECKETT" else g.group(1).upper()
                parsed["grade"] = g.group(2)
        work = GRADED_WORD_RE.sub(" ", GRADED_RE.sub(" ", work))

        for token, lang in LANGUAGE_ALIASES.items():
            if token in self.set_abbrs:
                continue  # "POR" is a Pokémon set before it is Portuguese
            pat = r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])"
            if re.search(pat, work, re.I):
                if token in {"JP", "JPN", "JAP"} and re.search(r"\bJP\s+(?:alternate|alt)\s+art\b", work, re.I):
                    continue
                parsed["language"] = lang
                work = re.sub(pat, " ", work, flags=re.I)
        if not parsed["language"] and NON_LATIN_RE.search(work):
            parsed["language"] = "non-latin"

        for words in GAME_TITLE_WORDS.values():
            for w in words:
                work = re.sub(r"(?<![\w])" + re.escape(w) + r"(?![\w])", " ", work, flags=re.I)

        for pat in NUMBER_PATTERNS:
            m = pat.search(work)
            if m:
                parsed["number"] = m.group(1)
                work = work[:m.start()] + " " + work[m.end():]
                break

        tags = re.findall(r"\(([^()]*)\)|\[([^\[\]]*)\]", work)
        work = re.sub(r"\([^()]*\)|\[[^\[\]]*\]", " ", work)
        tag_text = " ".join(a or b for a, b in tags)

        for pattern, words in FINISH_PHRASES:
            for src in ("tag", "work"):
                text = tag_text if src == "tag" else work
                m = re.search(pattern, text, re.I)
                if m:
                    parsed["finish_words"] |= words
                    if src == "work":
                        work = work[:m.start()] + " " + work[m.end():]
                    else:
                        tag_text = tag_text[:m.start()] + " " + tag_text[m.end():]
        if parsed["finish_words"]:
            parsed["finish_explicit"] = True

        # Set phrases: longest first, abbreviations only when written in capitals.
        def strip_sets(text):
            words = text.split()
            found = set()
            i = 0
            kept = []
            while i < len(words):
                hit = None
                for j in range(min(len(words), i + 8), i, -1):
                    chunk = words[i:j]
                    phrase = name_key(" ".join(chunk))
                    if phrase and phrase in self.set_lookup:
                        hit = (j, self.set_lookup[phrase])
                        break
                    if j == i + 1 and chunk[0].strip(",.;").upper() == chunk[0].strip(",.;") \
                            and "abbr:" + chunk[0].strip(",.;") in self.set_lookup:
                        hit = (j, self.set_lookup["abbr:" + chunk[0].strip(",.;")])
                        break
                if hit:
                    found |= hit[1]
                    i = hit[0]
                else:
                    kept.append(words[i])
                    i += 1
            return " ".join(kept), found

        def strip_variants(text):
            found = []
            for phrase in VARIANT_PHRASES:
                pat = r"(?<![\w'])" + re.escape(phrase) + r"(?![\w'])"
                if re.search(pat, text, re.I):
                    found.append(VARIANT_SYNONYMS.get(phrase, phrase))
                    text = re.sub(pat, " ", text, flags=re.I)
            return text, found

        # Sets before variants, so "Base Set Shadowless" is read as a set.
        tag_text, tag_variants = strip_variants(tag_text)
        variants = list(tag_variants)
        for t in [t.strip() for t in re.split(r"\s{2,}|,", tag_text) if t.strip()]:
            rest, groups = strip_sets(t)
            if groups and not rest.strip():
                parsed["set_groups"] |= groups
            else:
                variants.append(t)  # unknown tags still count as variant clues
        no_sets, groups = strip_sets(work)
        parsed["set_groups"] |= groups
        no_sets_no_variants, word_variants = strip_variants(no_sets)
        parsed["variant_terms"] = unique(variants + word_variants)
        parsed["set_cues"] = sorted({self.catalog.groups[g]["name"] for g in parsed["set_groups"]})

        def clean(text):
            return re.sub(r"\s+", " ", re.sub(r"(?:^|\s)[-–—,:|*]+(?=\s|$)", " ", text)).strip(" -,:|*")

        name = clean(no_sets_no_variants)
        # "Pikachu MEW 25": a bare trailing number next to a set is the card number.
        m = re.search(r"\s(\d{1,3}[a-z]?)$", name)
        if m and not parsed["number"] and (parsed["set_groups"] or self.by_core.get(name_key(name[:m.start()]))):
            parsed["number"] = m.group(1)
            name = name[:m.start()].strip()
        parsed["name"] = name
        # Readings where a stripped word was really part of the card name
        # ("Radiant Charizard", a card named like a set). The most specific
        # reading that is a real card name wins.
        parsed["name_options"] = unique([clean(no_sets), name, clean(strip_variants(work)[0]), clean(work)])
        return parsed

    # ----------------------------------------------------------- matching
    def _pick_subtype(self, product, parsed):
        """(subtype, price row, review) for the requested or default finish."""
        rows = product.get("prices") or {}
        priced = [s for s, r in rows.items() if choose_price(r)[0] is not None] or list(rows)
        if not priced:
            return "", None, ""
        want = parsed.get("finish_words") or set()
        if want:
            def words_of(s):
                w = set(norm(s).split())
                if "holofoil" in w:
                    w.add("foil")
                return w
            fits = [s for s in priced if want <= words_of(s) and ("reverse" in want or "reverse" not in words_of(s))]
            if not fits and want == {"holofoil"}:
                fits = [s for s in priced if "foil" in words_of(s) and "reverse" not in words_of(s)]
            if not fits and want == {"foil"}:
                fits = [s for s in priced if "holofoil" in words_of(s) and "reverse" not in words_of(s)]
            if fits:
                return fits[0], rows[fits[0]], ""
            review = f"REQUESTED FINISH NOT FOUND ({' '.join(sorted(want))})"
        else:
            review = ""
        order = ["Normal", "Unlimited", "Unlimited Holofoil", "Holofoil", "Foil", "Limited", "1st Edition",
                 "1st Edition Holofoil", "Reverse Holofoil"]
        choices = sorted(priced, key=lambda s: order.index(s) if s in order else len(order))
        pick = choices[0]
        editions = {s for s in priced if s.startswith(("1st Edition", "Unlimited"))}
        if not review and len(editions) >= 2 and not want:
            review = "ASSUMED EDITION (Unlimited)"
        return pick, rows[pick], review

    def price_range(self, products, parsed):
        vals = []
        for p in products:
            _s, row, _r = self._pick_subtype(p, parsed)
            v = choose_price(row)[0] if row else None
            if v is not None:
                vals.append(v)
        return (min(vals), max(vals)) if vals else (None, None)

    def candidates(self, parsed):
        """(products, match type) for the parsed title's name."""
        options = [o for o in parsed.get("name_options") or [parsed.get("name", "")] if self.by_core.get(name_key(o))]
        if options:
            best = max(options, key=lambda o: len(name_key(o)))
            if name_key(best) != name_key(parsed.get("name", "")):
                # Words kept in the name are no longer variant/set clues.
                kept = set(name_key(best).split())
                parsed["variant_terms"] = [v for v in parsed["variant_terms"] if not set(name_key(v).split()) <= kept]
                parsed["set_groups"] = {g for g in parsed["set_groups"]
                                        if not set(name_key(self.catalog.groups[g]["name"]).split()) <= kept}
            parsed["name"] = best
            return list(self.by_core[name_key(best)]), "EXACT"
        words = name_key(parsed.get("name", "")).split()
        by_number = self.by_number.get(number_key(parsed["number"]), []) if parsed.get("number") else []
        if by_number and not words:
            return list(by_number), "NUMBER"
        # A shortened name with a card number: "Ash Blossom RA01-EN008".
        if by_number and words:
            fit = [p for p in by_number if set(words) <= set(name_key(core_name(p["name"])).split())]
            if fit:
                return fit, "NUMBER"
        # Extra words before/after a real card name that describe the
        # printing ("Mirror Force Blue", "Holo Charizard"). Accepted only
        # when the product's tags, rarity or set confirm those words, so
        # "Lotus of the Abyss" never becomes a card called "Lotus".
        for size in range(len(words) - 1, 0, -1):
            for start in range(0, len(words) - size + 1):
                hits = self.by_core.get(" ".join(words[start:start + size]))
                if not hits:
                    continue
                extra = set(words[:start] + words[start + size:])
                fit = [p for p in hits
                       if extra <= set(name_key(" ".join([variant_text(p), p["name"], p["group_name"]])).split())]
                if fit:
                    parsed["name"] = " ".join(words[start:start + size])
                    parsed["variant_terms"] = unique(parsed["variant_terms"] + [" ".join(sorted(extra))])
                    return fit, "EXACT"
        # The start of exactly one card's name: "Ash Blossom" is
        # "Ash Blossom & Joyous Spring".
        if len(words) >= 2:
            head = " ".join(words) + " "
            longer = {k for k in self.names.by_token.get(words[0], ()) if k.startswith(head)}
            if len(longer) == 1:
                key = longer.pop()
                parsed["name"] = key
                return list(self.by_core[key]), "PARTIAL NAME"
        key, _ratio = self.names.fuzzy(parsed.get("name", ""))
        if key:
            return list(self.by_core[key]), "FUZZY"
        return [], "NO MATCH"

    def match(self, parsed):
        """Identify the printing. Returns a result dict for the engine."""
        cands, mtype = self.candidates(parsed)
        result = {"product": None, "subtype": "", "row": None, "match_type": mtype, "review": "",
                  "confidence": {"EXACT": 1.0, "NUMBER": 0.97, "PARTIAL NAME": 0.9, "FUZZY": 0.9}.get(mtype, 0.0),
                  "printings": 0, "low": None, "high": None}
        if not cands:
            result["review"] = "NO MATCH"
            return result
        if "code card" not in norm(parsed.get("raw", "")):
            cands = [p for p in cands if norm(p.get("rarity", "")) != "code card"] or cands

        notes = []
        related = []
        if parsed.get("set_groups"):
            in_set = [p for p in cands if p["group_id"] in parsed["set_groups"]]
            if in_set:
                # Sets named after this one ("Base Set (Shadowless)" for "Base
                # Set") stay in reserve: TCGplayer files 1st Edition Base Set
                # cards there, so a requested finish may only exist there.
                set_keys = [name_key(self.catalog.groups[g]["name"]) for g in parsed["set_groups"]]
                related = [p for p in cands if p["group_id"] not in parsed["set_groups"]
                           and any(name_key(p["group_name"]).startswith(k) for k in set_keys)]
                cands = in_set
                if len({p["group_id"] for p in cands}) > 1:
                    regular = [p for p in cands if "(" not in p["group_name"]]
                    if regular:
                        cands = regular
            else:
                notes.append("SET NOT FOUND FOR THIS CARD")
        if parsed.get("number"):
            key = number_key(parsed["number"])
            by_num = [p for p in cands if any(number_key(x) == key or number_key(x).split("/")[0] == key
                                              for x in re.split(r"\s*//\s*", p["number"] or ""))]
            if by_num:
                cands = by_num
            else:
                notes.append("NUMBER NOT FOUND FOR THIS CARD")
            # "OP01-016", "ST01-001", "LOB-005": the prefix is the set the
            # number belongs to. Reprints in decks / demo packs share the
            # number, so the original set wins unless another set was named.
            prefix = re.match(r"([A-Za-z]+\d*)-", parsed["number"])
            if prefix and not parsed.get("set_groups") and len(cands) > 1:
                code = prefix.group(1).lower()
                home = [p for p in cands if re.sub(r"[^a-z0-9]", "", p["group_abbr"].lower()) == code]
                if home:
                    cands = home
                    base = [p for p in cands if "(" not in p["group_name"]]
                    if base:
                        cands = base
        clues = [set(name_key(v).split()) for v in parsed.get("variant_terms") or []]
        if clues:
            def fits(p):
                words = set(name_key(" ".join([variant_text(p), p["name"], p["group_name"]])).split())
                if "parallel" in words:
                    words |= {"alternate", "art"}  # One Piece calls alt arts "Parallel"
                return all(c <= words for c in clues)
            fit = [p for p in cands if fits(p)]
            if len(fit) > 1:
                # "Secret Rare" means Secret Rare, not Quarter Century or
                # Platinum Secret Rare: keep the closest variant wording.
                wanted = set().union(*clues)
                def extra(p):
                    return len(set(name_key(" ".join(product_tags(p) + [p.get("rarity", "")])).split()) - wanted)
                least = min(extra(p) for p in fit)
                fit = [p for p in fit if extra(p) == least]
            if fit:
                cands = fit
            else:
                notes.append("VARIANT NOT CONFIRMED")
        else:
            # Without a variant word, the plain printing is meant, not the
            # alternate-art / manga / starlight version of the same number,
            # and the main-set card, not an event promo with the same number.
            if parsed.get("number") or parsed.get("set_groups"):
                plain = [p for p in cands if not product_tags(p)]
                if plain:
                    cands = plain
                not_promo = [p for p in cands if not is_promo(p)]
                if not_promo:
                    cands = not_promo
        if parsed.get("finish_words"):
            def has_finish(p):
                return not self._pick_subtype(p, parsed)[2].startswith("REQUESTED")
            with_finish = [p for p in cands if has_finish(p)] or [p for p in related if has_finish(p)]
            if with_finish:
                cands = with_finish

        cands = list({p["id"]: p for p in cands}.values())
        result["printings"] = len(cands)
        if len(cands) > 1:
            low, high = self.price_range(cands, parsed)
            result.update(low=low, high=high, review="; ".join(notes))
            result["candidates"] = cands
            return result
        product = cands[0]
        subtype, row, sub_review = self._pick_subtype(product, parsed)
        if mtype == "FUZZY":
            notes.insert(0, "FUZZY MATCH")
        if sub_review:
            notes.append(sub_review)
        result.update(product=product, subtype=subtype, row=row, review="; ".join(notes))
        return result
