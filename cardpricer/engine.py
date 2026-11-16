"""Runs a list through matching and pricing and builds output rows.

Per row:
  1. Game: a Game column, game words in the title, a game-specific card
     number (LOB-EN001, OP01-120), or which game's catalog has the name.
  2. Sealed product -> sealed matcher, priced with the sealed buy table.
  3. Cards -> that game's matcher (Magic: Scryfall; others: TCGplayer).
  4. Price: condition value first, then the buy % range (pricing.price_offer).
Graded, foreign-language and unidentifiable printings go to MANUAL CHECK.
"""

import re
from collections import Counter

from .clues import GRADED_RE, SEALED_RE, language_code
from .conditions import normalize_condition
from .games.magic import (choose_candidate, set_matches, effective_finish, expand_card_name_shorthand, image_url,
                          matched_display_name, parse_dirty_title, prewarm_fuzzy_multiprocess, price_card,
                          set_price_catalog, special_rules_for, tcgplayer_product)
from .games.sealed import SealedMatcher
from .games.tcg import FINISH_PHRASES, GAME_TITLE_WORDS, TCG_SEALED_RE, TCGMatcher, core_name, name_key
from .listread import read_list
from .pricing import DEFAULT_SEALED_TIERS, SPECIAL_RULE_LABELS, normalize_special_rules, price_offer
from .sources.tcgcsv import GAMES, choose_price
from .text import _is_number_only, compact, money, money_text, norm, round_cents, unique

OUTPUT_COLUMNS = [
    "Status", "Game", "Input", "Quantity", "Matched Name", "Set", "Set Code", "Collector Number",
    "Finish", "Variant / Treatment", "Rarity", "Serialized", "Graded", "Grade",
    "Condition Assumption", "Condition Source", "Match Type", "Confidence", "Review Flag",
    "Market Price", "Condition Value", "Buy %", "Price Used", "Price Source", "Price Notes",
    "Extended Value", "Product ID", "TCGplayer URL", "Scryfall URL", "Image URL",
]

MANUAL_CHECK_PREFIX = "MANUAL CHECK"
GUESS = "__guess__"  # detect_game: no catalog knows this exact name
GAME_ORDER = ("magic", "pokemon", "yugioh", "onepiece", "riftbound")
STATUS_LABELS = {0: "GUARANTEED", 1: "NEEDS CHECKING", 2: "SEALED", 3: "MANUAL CHECK", 4: "UNPRICED", 5: "UNKNOWN"}

# Card numbers that only one game uses.
GAME_NUMBER_HINTS = [
    (re.compile(r"\b[A-Z0-9]{2,5}-(?:EN|E|DE|FR|IT|SP|PT|JP|KR|AE)[A-Z]?\d{2,3}\b"), "yugioh"),
    (re.compile(r"\b(?:OP|ST|EB|PRB)\d{2}-\d{3}\b", re.I), "onepiece"),
]


def manual_check_tags(parsed):
    """Rows that are never auto-priced and why."""
    tags = []
    if parsed.get("sealed_unmatched"):
        tags.append("SEALED PRODUCT")
    elif parsed.get("sealed_unpriced"):
        tags.append("SEALED PRODUCT (NO PRICE)")
    elif parsed.get("set_product"):
        tags.append("SET PRODUCT")
    if parsed.get("graded"):
        tags.append(" ".join(x for x in ("GRADED", parsed.get("grader"), parsed.get("grade")) if x))
    if parsed.get("language") and parsed.get("language") != "en":
        tags.append(f"FOREIGN ({parsed['language']})")
    if parsed.get("ambiguous"):
        tags.append("AMBIGUOUS PRINTING - needs set or number")
    return tags


def make_row(game, raw, qty, parsed, ident, review, condition, buy_tiers, condition_source="",
             special_rules=None, sealed_tiers=None):
    """Build one output row. ident describes the matched card/product (or is
    None) and carries its market price."""
    manual = manual_check_tags(parsed)
    if manual:
        review = f"{MANUAL_CHECK_PREFIX}: {', '.join(manual)}" + (("; " + review) if review else "")
    ident = ident or {}
    p = ident.get("price")
    source = ident.get("price_source", "")
    note = ident.get("price_note", "")
    cond_value = buy_pct = price_used = None
    if manual and ident.get("name"):
        reference = (f"Reference price {money_text(p)} (not used)" if p is not None
                     else ident.get("price_range") or "No reference price")
        note = f"Price manually: {', '.join(t.split(' (')[0].split(' - ')[0].lower() for t in manual)}. {reference}"
        p, source = None, ""
    if p is not None and ident.get("sealed"):
        _c, cond_value, buy_pct, price_used = price_offer(p, sealed_tiers or DEFAULT_SEALED_TIERS, None, (), {})
        condition = ""
        if buy_pct is not None:
            note += f"; sealed: {buy_pct:g}% buy range"
    elif p is not None:
        specials = ident.get("specials") or []
        all_cards = normalize_special_rules(special_rules).get("all")
        cond_pct, cond_value, buy_pct, price_used = price_offer(
            p, buy_tiers, condition, [r for _k, r in specials], all_cards)
        if cond_pct is not None:
            note += f"; {condition} = {cond_pct:g}% of NM -> {money_text(cond_value)}"
            plain_pct = price_offer(p, buy_tiers, condition, (), all_cards)[0]
            if cond_pct < plain_pct:
                labels = " + ".join(SPECIAL_RULE_LABELS[k] for k, _r in specials)
                note += f" ({labels} value used instead of {plain_pct:g}%)"
            if buy_pct is not None:
                note += f"; {buy_pct:g}% buy range"
    price_used = round_cents(price_used)
    extended = round_cents(price_used * qty) if price_used is not None else None
    return {
        "Status": "",
        "Game": GAMES[game]["label"] if game in GAMES else "",
        "Input": raw,
        "Quantity": qty,
        "Matched Name": ident.get("name", ""),
        "Set": ident.get("set", ""),
        "Set Code": ident.get("set_code", ""),
        "Collector Number": ident.get("number", ""),
        "Finish": ident.get("finish", parsed.get("finish", "")),
        "Variant / Treatment": ", ".join(parsed.get("variant_terms") or []),
        "Rarity": ident.get("rarity", ""),
        "Serialized": "YES" if parsed.get("serialized") else "",
        "Graded": "YES" if parsed.get("graded") else "",
        "Grade": (parsed.get("grader", "") + " " + parsed.get("grade", "")).strip(),
        "Condition Assumption": condition,
        "Condition Source": condition_source if condition else "",
        "Match Type": ident.get("match_type", "NO MATCH"),
        "Confidence": f"{ident.get('confidence', 0.0):.0%}",
        "Review Flag": review,
        "Market Price": money_text(p),
        "Condition Value": money_text(cond_value) if not ident.get("sealed") else "",
        "Buy %": f"{buy_pct:.1f}%" if buy_pct is not None else "",
        "Price Used": money_text(price_used),
        "Price Source": source,
        "Price Notes": note.lstrip("; "),
        "Extended Value": money_text(extended),
        "Product ID": ident.get("product_id", ""),
        "TCGplayer URL": ident.get("tcgplayer_url", ""),
        "Scryfall URL": ident.get("scryfall_url", ""),
        "Image URL": ident.get("image", ""),
    }


# ------------------------------------------------------------------ columns
def _apply_common_columns(parsed, item):
    """Condition, grade and language columns, shared by every game."""
    condition = (item.get("condition") or "").strip()
    grade = (item.get("grade") or "").strip()
    language = (item.get("language") or "").strip()

    if grade and norm(grade) not in {"ungraded", "raw", "no", "none", "n/a", "-"}:
        m = GRADED_RE.search(grade)
        parsed["graded"] = True
        parsed["grader"] = m.group(1).upper() if m else parsed.get("grader", "")
        parsed["grade"] = m.group(2) if m else (grade if not parsed.get("grade") else parsed["grade"])
    if item.get("product_id"):
        parsed["product_id"] = str(item["product_id"]).strip()

    parsed["condition_source"] = "Title" if parsed.get("row_condition") else ""
    if condition:
        normalized = normalize_condition(condition)
        if normalized:
            parsed["row_condition"] = normalized
            parsed["condition_source"] = "CSV column"
        else:
            parsed.setdefault("parse_warnings", []).append(f"UNRECOGNIZED CONDITION '{condition}'")

    if language:
        code = language_code(language)
        if code:
            parsed["language"] = code
        else:
            parsed["language"] = language
            parsed.setdefault("parse_warnings", []).append(f"UNRECOGNIZED LANGUAGE '{language}'")
    return parsed


def _apply_row_indicators(parsed, item):
    """Magic: explicit columns are stronger than text inference (exports such
    as Title | Condition | Foil? keep finish/condition outside the title)."""
    _apply_common_columns(parsed, item)
    foil = norm(item.get("foil") or "")
    set_hints = [s.strip() for s in (item.get("set") or "").split(" | ") if s.strip()]
    collector_hint = (item.get("collector") or "").strip()

    if foil in {"normal", "nonfoil", "non-foil", "no", "n", "false", "0", "regular", "standard", "unlimited",
                "1st edition", "1st edition normal", "limited"}:
        parsed["finish"] = "nonfoil"
        parsed["finish_explicit"] = True
    elif foil in {"f", "yes", "y", "true"} or "foil" in foil or "holo" in foil or "etched" in foil:
        parsed["finish"] = "etched" if "etched" in foil else "foil"
        parsed["finish_explicit"] = True

    for set_hint in set_hints:
        parsed.setdefault("set_cues", []).append(set_hint)
    if collector_hint and re.fullmatch(r"\d{1,4}[A-Za-z]?", collector_hint):
        parsed["collector_number"] = collector_hint

    parsed["set_cues"] = unique(parsed.get("set_cues") or [])
    return parsed


def _apply_tcg_columns(parsed, item, matcher):
    """Other games: finish, set and number columns become matcher clues."""
    _apply_common_columns(parsed, item)
    finish = item.get("foil") or ""
    for pattern, words in FINISH_PHRASES:
        if re.search(pattern, finish, re.I):
            parsed["finish_words"] |= words
            parsed["finish_explicit"] = True
            break
    if norm(finish) in {"normal", "regular", "standard", "no", "false", "n"}:
        parsed["finish_words"] = {"normal"}
    for s in (item.get("set") or "").split(" | "):
        s = s.strip()
        if not s:
            continue
        groups = (matcher.set_lookup.get(name_key(s)) or matcher.set_lookup.get("abbr:" + s.upper())
                  or matcher.set_lookup.get("abbr:" + re.sub(r"[^A-Z0-9]", "", s.upper())))
        if groups:
            parsed["set_groups"] |= groups
    parsed["set_cues"] = sorted({matcher.catalog.groups[g]["name"] for g in parsed["set_groups"]})
    if item.get("collector"):
        parsed["number"] = item["collector"].strip()
    return parsed


def _item_key(item):
    """Rows with identical text and columns share one parse."""
    return tuple(sorted((k, str(v)) for k, v in item.items() if k not in ("quantity", "row_number")))


# --------------------------------------------------------------- the engine
class Engine:
    def __init__(self, magic_db=None, tcgcsv=None, log=print):
        self.magic_db = magic_db
        self.log = log
        self.matchers = {}
        catalogs = {}
        if tcgcsv is not None:
            for game in GAMES:
                cat = tcgcsv.catalog(game) if tcgcsv.has_data(game) else None
                catalogs[game] = cat
                if cat and game != "magic":
                    self.matchers[game] = TCGMatcher(game, cat)
        set_price_catalog(catalogs.get("magic"))
        self.sealed = SealedMatcher(catalogs) if any(catalogs.values()) else None
        self.games = [g for g in GAME_ORDER if (g == "magic" and magic_db) or g in self.matchers]

    # ---- vocabulary for the list reader
    def known_name(self, value):
        db = self.magic_db
        if db and (db.names.get(norm(value)) or db._compact_name_map.get(compact(value))):
            return True
        key = name_key(value)
        return any(key in m.by_core for m in self.matchers.values())

    def known_set(self, value):
        db = self.magic_db
        if db and (norm(value) in db._set_lookup or compact(value) in db._set_lookup):
            return True
        key = name_key(value)
        return any(key in m.set_lookup or "abbr:" + value.strip().upper() in m.set_lookup
                   for m in self.matchers.values())

    # ---- game detection
    def _magic_name_hit(self, raw):
        db = self.magic_db
        if not db:
            return False
        if db._embedded_exact_name(expand_card_name_shorthand(raw)):
            return True
        return bool(db.names.get(parse_dirty_title(raw)["name_norm"]))

    def _tcg_name_hit(self, game, raw):
        m = self.matchers[game]
        parsed = m.parse(raw)
        return any(m.by_core.get(name_key(o)) for o in parsed["name_options"])

    def name_hits(self, raw):
        return [g for g in self.games
                if (self._magic_name_hit(raw) if g == "magic" else self._tcg_name_hit(g, raw))]

    def explicit_game(self, item):
        """Game stated by a column, title words or a game-only card number."""
        texts = [item.get("game") or "", item.get("raw") or ""]
        for game, words in GAME_TITLE_WORDS.items():
            for text in texts:
                if any(re.search(r"(?<![\w])" + re.escape(w) + r"(?![\w])", text, re.I) for w in words):
                    return game
        if norm(item.get("game") or "") in {"magic", "mtg"}:
            return "magic"
        for pattern, game in GAME_NUMBER_HINTS:
            if pattern.search((item.get("raw") or "") + " " + (item.get("collector") or "")):
                return game
        return None

    def clear_game(self, item):
        """(game or None, name hits): the game when only one is possible."""
        explicit = self.explicit_game(item)
        if explicit and explicit in self.games:
            return explicit, [explicit]
        hits = self.name_hits(item["raw"])
        return (hits[0] if len(hits) == 1 else None), hits

    def detect_game(self, item, default_game, file_game=None, clear=None):
        """(game, note). A name found in several games, or in none (a typo),
        goes to the game most of the file is in; the screen's default game
        only decides when the file gives no hint."""
        game, hits = clear or self.clear_game(item)
        if game:
            return game, ""
        preferred = [g for g in (file_game, default_game) if g in self.games]
        if hits:
            game = next((g for g in preferred if g in hits), hits[0])
            others = ", ".join(GAMES[g]["label"] for g in hits if g != game)
            return game, f"GAME ASSUMED ({GAMES[game]['label']}; also a {others} name)"
        return (preferred[0] if preferred else self.games[0]), GUESS

    def guess_order(self, item, first):
        """Games to try for a name no catalog knows exactly (typos), the
        ones its card-number shape points to first."""
        text = (item.get("raw") or "") + " " + (item.get("collector") or "")
        hinted = []
        if re.search(r"\b[A-Za-z0-9]{2,5}-[A-Za-z]{0,3}\d{2,4}\b", text):
            hinted += ["yugioh", "onepiece"]
        if re.search(r"\d{1,3}[a-z]?\s?/\s?\d{2,3}\b", text):
            hinted += ["pokemon", "riftbound"]
        order = unique(hinted + [first] + list(self.games))
        return [g for g in order if g in self.games]

    def parse_for(self, game, item):
        raw = item["raw"]
        if game == "magic":
            parsed = _apply_row_indicators(parse_dirty_title(raw), item)
            db = self.magic_db
            parsed["set_cues"] = unique([db._set_lookup.get(norm(c)) or db._set_lookup.get(compact(c)) or c
                                         for c in parsed.get("set_cues") or []])
            return parsed
        return _apply_tcg_columns(self.matchers[game].parse(raw), item, self.matchers[game])

    def identify(self, game, item, parsed):
        if game == "magic":
            return self.identify_magic(item, parsed)
        return self.identify_tcg(game, parsed)

    def is_sealed(self, raw):
        if SEALED_RE.search(raw) or re.search(r"^\s*(?:complete\s+)?set\b|\bfactory\s+set\b", raw, re.I):
            return True
        return bool(TCG_SEALED_RE.search(raw)) and not self.name_hits(raw)

    # ---- per-game identification -> ident dict
    def identify_magic(self, item, parsed):
        db = self.magic_db
        cands, mtype = db.candidates(parsed)
        card, conf, review = choose_candidate(cands, parsed, mtype)
        if (card and not parsed.get("language") and card.get("lang") not in ("", "en")
                and norm(parsed.get("name", "")) == norm(card.get("printed_name", ""))
                and norm(parsed.get("name", "")) != norm(card.get("name", ""))):
            parsed["language"] = card["lang"]  # written with a foreign printed name
        cues = parsed.get("set_cues") or []
        if card and cues and not any(set_matches(card, c) for c in cues):
            # "Sheoldred" + DMU: the card in that set is "Sheoldred, the
            # Apocalypse". Use the one longer name printed in the named set.
            longer = self._magic_name_in_set(parsed.get("name", ""), cues)
            if longer:
                parsed["name"], parsed["name_norm"] = longer, norm(longer)
                card, conf, review = choose_candidate(db.names[norm(longer)], parsed, "NORMALIZED")
                mtype = "NORMALIZED"
                review = "; ".join(x for x in ("NAME COMPLETED FROM SET", review) if x)
            else:
                review = "; ".join(x for x in ("SET NOT FOUND FOR THIS CARD", review) if x)
        if not card:
            return None, (review if review and review != "NO MATCH" else "NO MATCH"), mtype
        price, source, note = price_card(card, parsed)
        product, _row = tcgplayer_product(card, parsed)
        if source.startswith("TCGplayer Low"):
            review = "; ".join(x for x in (review, "LOW PRICE ONLY (no market price)") if x)
        ident = {
            "name": matched_display_name(card, parsed), "set": card.get("set_name", ""), "set_code": card.get("set", ""),
            "number": card.get("collector_number", ""), "finish": effective_finish(card, parsed), "rarity": "",
            "match_type": mtype, "confidence": conf, "price": price, "price_source": source, "price_note": note,
            "product_id": product["id"] if product else (card.get("tcgplayer_id") or ""),
            "tcgplayer_url": product["url"] if product else "", "scryfall_url": card.get("scryfall_uri", ""),
            "image": image_url(card), "specials": special_rules_for(card, parsed, self._special_rules),
        }
        return ident, review, mtype

    def _magic_name_in_set(self, name, cues):
        """The one card whose name starts with name and is printed in a cue set."""
        db = self.magic_db
        words = norm(name).split()
        if not words:
            return None
        exact, loose = set(), set()
        wanted = {norm(c) for c in cues}
        for key in db._token_name_index.get(words[0], ()):
            if key.startswith(norm(name) + ",") or key.startswith(norm(name) + " "):
                cards = db.names.get(key, ())
                if any(norm(c.get("set_name", "")) in wanted or norm(c.get("set", "")) in wanted for c in cards):
                    exact.add(cards[0]["name"])
                elif any(set_matches(c, cue) for c in cards for cue in cues):
                    loose.add(cards[0]["name"])
        found = exact or loose
        return found.pop() if len(found) == 1 else None

    def identify_tcg(self, game, parsed):
        m = self.matchers[game]
        if parsed.get("product_id"):
            product = m.catalog.get(parsed["product_id"])
            if product:
                subtype, row, sub_review = m._pick_subtype(product, parsed)
                result = {"product": product, "subtype": subtype, "row": row, "match_type": "PRODUCT ID",
                          "confidence": 1.0, "review": sub_review}
            else:
                result = m.match(parsed)
        else:
            result = m.match(parsed)
        if result["product"] is None:
            if result.get("printings", 0) > 1:
                parsed["ambiguous"] = True
                low, high = result["low"], result["high"]
                rng = (f"{result['printings']} possible printings, {money_text(low)}-{money_text(high)}"
                       if low is not None else f"{result['printings']} possible printings")
                first = result["candidates"][0]
                ident = {"name": core_name(first["name"]),
                         "match_type": result["match_type"], "confidence": result["confidence"],
                         "price_range": rng}
                return ident, result["review"], result["match_type"]
            return None, result["review"] or "NO MATCH", result["match_type"]
        p = result["product"]
        price, basis = choose_price(result["row"])
        review = result["review"]
        if basis.startswith("TCGplayer Low"):
            review = "; ".join(x for x in (review, "LOW PRICE ONLY (no market price)") if x)
        ident = {
            "name": p["name"], "set": p["group_name"], "set_code": p["group_abbr"], "number": p["number"],
            "finish": result["subtype"], "rarity": p["rarity"], "match_type": result["match_type"],
            "confidence": result["confidence"], "price": price, "price_source": basis,
            "price_note": "Price from TCGplayer (TCGCSV)" if price is not None else "No TCGplayer price",
            "product_id": p["id"], "tcgplayer_url": p["url"], "image": p["image"],
        }
        return ident, review, result["match_type"]

    def identify_sealed(self, raw, game_hint):
        product, score, review, top = self.sealed.match(raw, [game_hint] if game_hint else None)
        if product is None:
            return None, review, top
        price, basis = choose_price(next(iter(product["prices"].values()), None))
        ident = {
            "name": product["name"], "set": product["group_name"], "set_code": product["group_abbr"],
            "finish": "", "match_type": "SEALED", "confidence": min(1.0, score), "price": price,
            "price_source": basis, "price_note": "Sealed price from TCGplayer (TCGCSV)" if price is not None
            else "No TCGplayer price", "product_id": product["id"], "tcgplayer_url": product["url"],
            "image": product["image"], "sealed": True, "game": product["game"],
        }
        return ident, review, top

    # ---- whole file
    def process_file(self, path, condition, buy_tiers, log, progress, special_rules=None, default_game="magic",
                     sealed_tiers=None):
        self._special_rules = special_rules
        items, layout = read_list(path, known_name=self.known_name, known_set=self.known_set)
        if not items:
            raise RuntimeError(f"No card rows were found in the input file ({layout}).")
        condition = normalize_condition(condition) or condition
        log(f"Found {len(items)} valid card rows.")
        log(f"Detected layout: {layout}")
        progress(0, len(items))
        totals = {"input": len(items), "exact": 0, "other": 0, "review": 0, "nomatch": 0,
                  "graded": 0, "with_price": 0, "value": 0.0}

        # Rows whose game is clear decide the file's main game; rows that
        # could be several games (or none) lean toward it.
        clear = {}
        sealed_keys = set()
        for item in items:
            key = _item_key(item)
            if key in clear or key in sealed_keys:
                continue
            if self.sealed and self.is_sealed(item["raw"]):
                sealed_keys.add(key)
            else:
                clear[key] = self.clear_game(item)
        votes = Counter(g for g, _hits in clear.values() if g)
        file_game = votes.most_common(1)[0][0] if votes else None
        if file_game:
            log(f"Main game of this list: {GAMES[file_game]['label']} "
                f"({votes[file_game]} of {sum(votes.values())} identifiable rows)")

        # Decide game and parse each distinct row once.
        plans = {}
        for item in items:
            key = _item_key(item)
            if key in plans:
                continue
            raw = item["raw"]
            if key in sealed_keys:
                plans[key] = {"game": self.explicit_game(item), "sealed": True, "note": ""}
                continue
            game, note = self.detect_game(item, default_game, file_game, clear[key])
            guessed = note == GUESS
            plans[key] = {"game": game, "sealed": False, "note": "" if guessed else note, "guessed": guessed,
                          "parsed": self.parse_for(game, item)}

        if self.magic_db:
            prewarm_fuzzy_multiprocess(self.magic_db, [p["parsed"] for p in plans.values()
                                                       if p.get("game") == "magic" and not p["sealed"]], log)

        output = []
        for i, item in enumerate(items, 1):
            raw = item["raw"]
            qty = int(item.get("quantity") or 1)
            plan = plans[_item_key(item)]
            log(f"[{i}/{len(items)}] {raw}  x{qty}")

            if plan["sealed"]:
                parsed = _apply_common_columns({"raw": raw, "variant_terms": []}, item)
                ident, review, top = self.identify_sealed(raw, plan["game"])
                game = (ident or {}).get("game") or plan["game"] or ""
                if ident is None:
                    parsed["sealed_unmatched"] = True
                    ident = {"match_type": "SEALED", "price_note": ("Closest: " + "; ".join(top)) if top else ""}
                elif ident.get("price") is None:
                    parsed["sealed_unpriced"] = True
                row = make_row(game, raw, qty, parsed, ident, review, "", buy_tiers, "", special_rules, sealed_tiers)
            else:
                game, parsed = plan["game"], plan["parsed"]
                row_condition = parsed.get("row_condition") or condition
                condition_source = parsed.get("condition_source") or "Default"
                if parsed.get("graded"):
                    totals["graded"] += 1
                ident, review, mtype = self.identify(game, item, parsed)
                if ident is None and plan.get("guessed"):
                    # No catalog had this exact name (usually a typo): try
                    # the other games before calling it unknown.
                    for other in [g for g in self.guess_order(item, game) if g != game]:
                        other_parsed = self.parse_for(other, item)
                        o_ident, o_review, o_mtype = self.identify(other, item, other_parsed)
                        if o_ident is not None:
                            game, parsed, ident, mtype = other, other_parsed, o_ident, o_mtype
                            review = "; ".join(x for x in (f"GAME GUESSED ({GAMES[other]['label']})", o_review) if x)
                            row_condition = parsed.get("row_condition") or condition
                            condition_source = parsed.get("condition_source") or "Default"
                            break
                extra = list(parsed.get("parse_warnings") or [])
                if plan["note"]:
                    extra.append(plan["note"])
                if parsed.get("signed"):
                    extra.append("SIGNED")
                review = "; ".join(unique(extra + ([review] if review else [])))
                if ident is None:
                    totals["nomatch"] += 1
                elif mtype == "EXACT":
                    totals["exact"] += 1
                else:
                    totals["other"] += 1
                row = make_row(game, raw, qty, parsed, ident, review, row_condition, buy_tiers, condition_source,
                               special_rules, sealed_tiers)
            if row["Review Flag"]:
                totals["review"] += 1
            output.append(row)
            progress(i, len(items))
            if row["Price Used"]:
                totals["with_price"] += 1
                numeric = money(row["Extended Value"])
                if numeric is not None:
                    totals["value"] = round_cents(totals["value"] + numeric)

        for row in output:
            row["Status"] = STATUS_LABELS[_bucket(row)]
        # Confirmed rows on top, unknowns at the bottom; most valuable first
        # within each status.
        output.sort(key=lambda r: (_bucket(r), -(money(r["Price Used"]) or money(r["Market Price"]) or 0)))
        counts = {b: sum(1 for r in output if r["Status"] == STATUS_LABELS[b]) for b in STATUS_LABELS}
        log("Final audit: " + " | ".join(f"{STATUS_LABELS[b]}: {counts[b]}" for b in STATUS_LABELS))

        output.append({k: "" for k in OUTPUT_COLUMNS})
        summary = {k: "" for k in OUTPUT_COLUMNS}
        summary["Status"] = "TOTAL"
        summary["Input"] = "TOTAL"
        summary["Quantity"] = str(sum(int(x.get("quantity") or 1) for x in items))
        summary["Matched Name"] = f"{totals['with_price']} priced / {len(items)} rows"
        summary["Review Flag"] = f"{totals['review']} review"
        summary["Extended Value"] = f"${totals['value']:,.2f}"
        output.append(summary)
        return output, totals


def _bucket(row):
    mt = str(row.get("Match Type") or "").upper()
    matched = str(row.get("Matched Name") or "").strip()
    price = str(row.get("Price Used") or "").strip()
    review = str(row.get("Review Flag") or "").strip()
    if review.startswith(MANUAL_CHECK_PREFIX):
        return 3
    if mt == "SEALED" and price:
        return 2
    if not matched or mt == "NO MATCH":
        return 5
    if not price:
        return 4
    if review or mt not in {"EXACT", "NORMALIZED"}:
        return 1
    return 0


def process_file(path, db, condition, buy_tiers, log, progress, special_rules=None, tcgcsv=None,
                 default_game="magic", sealed_tiers=None, engine=None):
    """Price one list. Builds an Engine unless one is passed in."""
    engine = engine or Engine(db, tcgcsv, log)
    return engine.process_file(path, condition, buy_tiers, log, progress, special_rules, default_game, sealed_tiers)
