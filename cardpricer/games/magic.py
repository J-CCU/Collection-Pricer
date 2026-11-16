"""Magic: The Gathering identification against Scryfall bulk data."""


# ============================================================
# MTG COLLECTION BUYER
# Dirty collection list -> Scryfall identification -> pricing
# ============================================================
# Important design rules:
#   * Parse the input into card-name + constraints BEFORE matching.
#   * Exact card name always outranks fuzzy matching.
#   * Finish, set, variant, and collector-number clues FILTER candidates.
#   * Multiple printings are NOT automatically ambiguous.
#   * A foil request such as "Intuition Foil" searches all Intuition
#     printings and selects the applicable foil printing.  If there is
#     exactly one foil printing, it is resolved automatically.
#   * Unknown/alias names may be resolved through Scryfall search.
#   * Fuzzy matching is a last resort, and is never allowed to override
#     strong set/finish/collector-number evidence.
#   * Graded cards are identified but are NOT assigned an ungraded price.
#   * Scryfall supplies TCGplayer price fields, but not TCGplayer
#     the program uses only Scryfall price fields and does not attempt to reproduce a separate marketplace low price.
# ============================================================

import gzip
import heapq
import json
import multiprocessing as mp
import pickle
import re
import requests
import sys
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from difflib import SequenceMatcher
from pathlib import Path

from ..clues import GRADED_RE, GRADED_WORD_RE, LANGUAGE_ALIASES, NON_LATIN_RE, SEALED_RE
from ..conditions import CONDITION_ALIASES, extract_title_condition
from ..paths import BUNDLE_DIR, DATA_DIR, UA
from ..pricing import normalize_special_rules
from ..sources.tcgcsv import choose_price
from ..text import _bigrams, _name_words, collector_number_equal, compact, money, norm, unique

BULK_GZ = DATA_DIR / "scryfall_all_cards.jsonl.gz"

BULK_META = DATA_DIR / "bulk_metadata.json"

# Separate from the original collection_pricer.py index so the two programs
# never rebuild over each other.
INDEX = DATA_DIR / "cardpricer_scryfall_index.pkl"

SEARCH_CACHE = DATA_DIR / "scryfall_name_cache.json"

# Legacy cache migration / discovery. PyInstaller bundles are read-only and
# one-file builds unpack to temporary locations, so mutable Scryfall data must
# live in DATA_DIR. We also actively look for an existing bulk file in the
# source/app folder and copy it once instead of downloading it again.
def _legacy_candidate_dirs():
    dirs = []
    for d in (BUNDLE_DIR, Path.cwd()):
        try:
            d = d.resolve()
        except Exception:
            continue
        if d not in dirs:
            dirs.append(d)
    # For a .app, also check the directory containing the executable and its
    # parent locations where a user may have kept the database beside the app.
    try:
        exe = Path(sys.executable).resolve()
        for d in (exe.parent, exe.parent.parent, exe.parent.parent.parent):
            if d not in dirs:
                dirs.append(d)
    except Exception:
        pass
    return dirs

def migrate_legacy_cache(log=None):
    candidates = _legacy_candidate_dirs()
    bulk_names = (
        "scryfall_all_cards.jsonl.gz",
        "scryfall_all_cards.jsonl.tmp",
    )
    meta_names = ("bulk_metadata.json",)
    index_names = ("scryfall_index.pkl", "scryfall_index_v15.pkl", "scryfall_index_v14.pkl")
    search_names = ("scryfall_name_cache.json", "scryfall_name_cache_v8.json", "scryfall_name_cache_v5.json")

    def copy_first(names, dest):
        if dest.exists():
            return False
        for directory in candidates:
            for name in names:
                src = directory / name
                if src.exists() and src.is_file():
                    try:
                        import shutil
                        shutil.copy2(src, dest)
                        if log:
                            log(f"Migrated existing Scryfall cache: {src} -> {dest}")
                        return True
                    except Exception as e:
                        if log:
                            log(f"Could not migrate {src}: {e}")
        return False

    copy_first(bulk_names, BULK_GZ)
    copy_first(meta_names, BULK_META)
    copy_first(index_names, INDEX)
    copy_first(search_names, SEARCH_CACHE)

migrate_legacy_cache()

BULK_API = "https://api.scryfall.com/bulk-data"

INDEX_VERSION = 18  # 18: TCGplayer product ids for TCGCSV prices

SELF_TEST_NAMES = (
    "Mishra's Workshop",
    "Grim Monolith",
    "Black Lotus",
    "Primeval Titan",
)

# Condition values: what a copy in each condition is worth as a % of the NM
# price. "All cards" applies to everything (LP/MP/HP from Card Kingdom's
# buylist: EX 80-90, VG 70-80, G 50-70; DMG about half of HP). Old-set and
# foil cards lose more value to wear (Card Kingdom: Alpha/Beta/Unlimited
# 80/60/40, foils 75/50/30); for those, the lower value is used.
ABU_SET_CODES = {"lea", "leb", "2ed"}

# User-facing set aliases.  The matcher also accepts the real Scryfall set name.
SET_ALIASES = {
    "unlim": ["unlimited edition"],
    "unlimited": ["unlimited edition"],
    "7th ed": ["seventh edition"],
    "7th edition": ["seventh edition"],
    "tempest": ["tempest"],
    "onslaught": ["onslaught"],
    "revised": ["revised edition"],
    "mm": ["modern masters"],
    "lorwyn": ["lorwyn"],
    "eventide": ["eventide"],
    "shadowmoor": ["shadowmoor"],
    "morningtide": ["morningtide"],
    "urza's destiny": ["urza's destiny"],
    "urza's saga": ["urza's saga"],
    "urza's legacy": ["urza's legacy"],
    "urza's legacy0": ["urza's legacy"],
    "urea's legacy0": ["urza's legacy"],
    "urea's legacy": ["urza's legacy"],
    "arabian nights": ["arabian nights"],
    "antiquities": ["antiquities"],
    "the dark": ["the dark"],
    "fallen empires": ["fallen empires"],
    "homelands": ["homelands"],
    "mirage": ["mirage"],
    "visions": ["visions"],
    "weatherlight": ["weatherlight"],
    "stronghold": ["stronghold"],
    "exodus": ["exodus"],
    "mercadian masques": ["mercadian masques"],
    "nemesis": ["nemesis"],
    "prophecy": ["prophecy"],
    "legends": ["legends"],
    "battle royale": ["battle royale"],
    "lorwyn eclipsed": ["lorwyn eclipsed"],
    "wpn promo": ["magic premier shop", "world championship decks", "magic player rewards"],
    "promo": ["promo"],
    "from the vault": ["from the vault"],
    "mm1": ["modern masters"],
    "utm": ["ultimate masters"],
    "lor": ["lorwyn"],
    "btb": ["battlebond"],
    "legi": ["legends"],
    "cok": ["champions of kamigawa"],
    "cml": ["commander legends"],
    "apo": ["apocalypse"],
    "evt": ["eventide"],
    "shd": ["shadowmoor"],
    "pst": ["planeshift"],
    "cld": ["kaladesh"],
    "des": ["dissension"],
    "mcm": ["commander masters"],
    "icm": ["iconic masters"],
    "thr": ["theros"],
    "wlw": ["worldwake"],
    "pro": ["prophecy"],
    "tbd": ["theros beyond death"],
    "jug": ["judgment"],
    "sco": ["scourge"],
    "ali": ["alliances"],
    "p3k": ["portal three kingdoms"],
    "wea": ["weatherlight"],
    "mm2": ["modern masters 2015"],
    "m25": ["masters 25"],
    "2xm": ["double masters"],
    "zrn": ["zendikar rising"],
    "ixa": ["ixalan"],
    "ori": ["magic origins"],
    "emn": ["eldritch moon"],
    "kal": ["kaladesh"],
    "kld": ["kaladesh"],
    "str": ["stronghold"],
}

KNOWN_SET_PHRASES = sorted(SET_ALIASES.keys(), key=len, reverse=True)

# Phrases that are also common card-title words. These require stronger context
# than a bare substring match so a card name is not damaged during parsing.
AMBIGUOUS_SET_ALIASES = {"the dark", "promo"}

CARD_NAME_SHORTHAND = {
    "cop black": "Circle of Protection: Black",
    "cop blue": "Circle of Protection: Blue",
    "cop green": "Circle of Protection: Green",
    "cop red": "Circle of Protection: Red",
    "cop white": "Circle of Protection: White",
}

def expand_card_name_shorthand(text):
    original=text or ""
    n=norm(original)
    for short, full in CARD_NAME_SHORTHAND.items():
        if n == short:
            return full
        if n.startswith(short + " "):
            suffix=original[len(short):].strip()
            return full + (" " + suffix if suffix else "")
    return original

def special_rules_for(card, parsed, special_rules):
    """Return [(key, ratios)] for the special rules that apply to this printing."""
    keys = []
    if norm(card.get("set", "")) in ABU_SET_CODES:
        keys.append("abu")
    if effective_finish(card, parsed) in {"foil", "etched"}:
        keys.append("foil")
    rules = normalize_special_rules(special_rules)
    return [(k, rules[k]) for k in keys if k in rules]

def parse_dirty_title(raw):
    """Parse dirty collection text while preserving generic treatment clues.

    Variant/treatment names are deliberately metadata-driven. We keep explicit
    parenthetical annotations and generic "X foil" phrases as clues, then let
    the Scryfall database decide whether those clues actually describe a
    printing. This avoids a hard-coded list that becomes stale when Scryfall
    adds new treatments.
    """
    s = (raw or "").strip()
    work = expand_card_name_shorthand(s).replace("\u2019", "'").replace("\u2018", "'")

    sealed = bool(SEALED_RE.search(work))
    set_product = bool(re.search(r"^\s*(?:complete\s+)?set\b|\bfactory\s+set\b", work, re.I))
    signed = bool(re.search(r"(?:^|[\s,*])signed\b", work, re.I))
    # Condition words are recorded and then removed so they never reach the
    # card-name matcher or become treatment clues.
    row_condition, work = extract_title_condition(work)

    language = ""
    language_tokens = []
    for token, lang in LANGUAGE_ALIASES.items():
        if not re.search(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])", work, re.I):
            continue
        # In seller language, "JP Alternate Art" is a printing/treatment
        # descriptor, not a request to price a Japanese-language card.
        if token in {"JP", "JPN", "JAP"} and re.search(r"\bJP\s+(?:alternate|alt)\s+art\b", work, re.I):
            continue
        if any(token in longer for longer in language_tokens):
            continue  # "CHINESE" inside an already-found "SIMPLIFIED CHINESE"
        language = lang
        language_tokens.append(token)
    # Card names are Latin script; a title in another script is a
    # foreign-language printing even without a language word.
    if not language and NON_LATIN_RE.search(work):
        language = "non-latin"

    grader_m = GRADED_RE.search(work)
    graded = bool(grader_m) or bool(GRADED_WORD_RE.search(work))
    grader = grader_m.group(1).upper() if grader_m else ""
    grade = grader_m.group(2) if grader_m else ""
    if grader == "BECKETT":
        grader = "BGS"
    serialized = bool(re.search(r"\bserial(?:ized)?\b|\bserial\s+numbered\b", work, re.I))

    # Repair a common dirty-list/OCR case where a trailing parenthetical is
    # missing its closing parenthesis. Keep the contents as an annotation clue.
    unmatched_annotation = ""
    open_pos = work.rfind("(")
    close_pos = work.rfind(")")
    if open_pos >= 0 and open_pos > close_pos:
        unmatched_annotation = work[open_pos + 1:].strip()
        work = work[:open_pos].rstrip() + (" " if work[:open_pos].strip() else "")

    # Pull parenthetical annotations before stripping them. These are often the
    # most useful printing clues: Galaxy Foil, Scrolls Silver Foil, Retro Frame,
    # Borderless Poster Foil, etc. Numeric-only annotations are handled separately.
    annotations = re.findall(r"\(([^()]*)\)", work)
    annotation_clues = []
    for a in annotations + ([unmatched_annotation] if unmatched_annotation else []):
        a = re.sub(r"\s+", " ", a.strip())
        if a and not re.fullmatch(r"\d{1,4}[A-Za-z]?", a):
            annotation_clues.append(a)

    finish = "nonfoil"
    finish_explicit = False
    if re.search(r"\b(?:etched(?:\s+foil)?|etched)\b", work, re.I):
        finish = "etched"
        finish_explicit = True
    elif re.search(r"\b(?:[A-Za-z0-9'’.-]+\s+){0,4}foil\b", work, re.I):
        finish = "foil"
        finish_explicit = True

    # Parenthetical annotations are treatment clues. Plain-text special
    # treatments are discovered later from Scryfall's own metadata vocabulary.
    treatment_phrases = list(annotation_clues)

    set_cues = []
    set_patterns = []
    for alias in KNOWN_SET_PHRASES:
        pattern = r"(?<![\w'])" + re.escape(alias) + r"(?![\w'])"
        if not re.search(pattern, work, re.I):
            continue
        # "The Dark" inside a card such as Sauron, the Dark Lord is not a set
        # clue. Ambiguous aliases are accepted when they occur at the end, after
        # a separator, or in parentheses; ordinary set aliases remain flexible.
        if alias in AMBIGUOUS_SET_ALIASES:
            strong = re.search(r"(?:[-–—,]|\(|^)\s*" + re.escape(alias) + r"\s*(?:\)|$)", work, re.I)
            if not strong:
                continue
        set_cues.append(alias)
        set_patterns.append(alias)

    collector_number = ""
    # Collector numbers are often written as "- 360" or "(7031)" even when
    # the input is not explicitly marked serialized. Preserve those numbers as
    # cross-set clues. Parenthetical text is only accepted when it is numeric.
    m = re.search(r"(?:#|[-–—]\s*)(\d{1,4}[A-Za-z]?)(?=\s*(?:\([^()]*\)\s*)*$)", work)
    if m:
        collector_number = m.group(1)
    if not collector_number:
        nums = re.findall(r"\((\d{1,4}[A-Za-z]?)\)", work)
        if nums:
            collector_number = nums[-1]

    name = work
    name = GRADED_RE.sub("", name)
    name = GRADED_WORD_RE.sub("", name)
    name = re.sub(r"\bserial(?:ized)?\b|\bserial\s+numbered\b", "", name, flags=re.I)
    name = re.sub(r"\betched(?:\s+foil)?\b", "", name, flags=re.I)
    # Remove only generic finish words here. Metadata-specific treatment words
    # are removed later after the Scryfall vocabulary is available.
    for sp in set_patterns:
        name = re.sub(r"(?<![\w'])" + re.escape(sp) + r"(?![\w'])", "", name, flags=re.I)
    if collector_number:
        # Remove a collector number even when a treatment annotation follows it.
        name = re.sub(r"(?:#|[-–—]\s*)" + re.escape(collector_number) + r"(?=\s*(?:\([^()]*\)\s*)*$)", "", name)
        name = re.sub(r"\(" + re.escape(collector_number) + r"\)", "", name)
    name = re.sub(r"\([^()]*\)", " ", name)
    for token in language_tokens:
        name = re.sub(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])", " ", name, flags=re.I)
    # Remove a bare generic foil word if it survived, but keep all other words.
    name = re.sub(r"\bfoil\b", "", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip(" -")

    name_variants = [name]
    parts = name.split()
    if len(parts) > 2:
        name_variants.extend([" ".join(parts[:n]) for n in range(len(parts) - 1, 1, -1)])
    for piece in re.split(r"\s+[-:]\s+", name):
        piece = piece.strip()
        if len(piece.split()) >= 2:
            name_variants.append(piece)
    name_variants = unique(name_variants)

    return {
        "raw": raw,
        "name": name,
        "name_variants": name_variants,
        "name_norm": norm(name),
        "compact": compact(name),
        "finish": finish,
        "finish_explicit": finish_explicit,
        "variant_terms": unique(annotation_clues),
        "treatment_phrases": unique(treatment_phrases),
        "set_cues": set_cues,
        "collector_number": collector_number,
        "serialized": serialized,
        "graded": graded,
        "grade": grade,
        "grader": grader,
        "language": language,
        "language_tokens": language_tokens,
        "signed": signed,
        "sealed": sealed,
        "set_product": set_product,
        "row_condition": row_condition,
    }

class ScryfallDB:
    def __init__(self, log):
        self.log = log
        self.cards = []
        self.names = {}
        self.unique_names = []
        self.metadata_terms = set()
        self.set_terms = set()
        self.cache = self.load_search_cache()

        # Runtime-only acceleration structures. These are rebuilt from the
        # persistent index after loading; they are deliberately NOT sent to
        # worker processes.
        self._fuzzy_cache = {}
        self._name_hits_cache = {}
        self._embedded_cache = {}
        self._compact_name_map = {}
        self._compact_base_name_map = {}
        self._token_name_index = {}
        self._length_name_index = {}
        self._set_vocab = {}
        self._set_lookup = {}
        self._metadata_lookup = {}
        self._known_set_codes = set()

    def _build_runtime_indexes(self):
        """Build fast in-memory indexes from the persistent Scryfall index.

        This is intentionally done once per application launch, not once per
        input row. In particular, set vocabulary is cached here so metadata
        enrichment never scans 542k cards for every card in the CSV.
        """
        self._fuzzy_cache.clear()
        self._name_hits_cache.clear()
        self._embedded_cache.clear()
        self._compact_name_map = {}
        self._compact_base_name_map = {}
        self._token_name_index = {}
        self._length_name_index = {}
        self._set_vocab = {}
        self._set_lookup = {}
        self._metadata_lookup = {}
        self._known_set_codes = set()

        for c in self.cards:
            sn = norm(c.get("set_name", ""))
            sc = norm(c.get("set", ""))
            if sn:
                self._set_vocab[sn] = sn
                self._set_lookup.setdefault(sn, sn)
                self._set_lookup.setdefault(compact(sn), sn)
            if sc:
                self._set_vocab[sc] = sn
                self._set_lookup.setdefault(sc, sn)
                self._set_lookup.setdefault(compact(sc), sn)
                self._known_set_codes.add(sc)

        # Sellers write "Alpha"/"Beta" for Limited Edition Alpha/Beta. These are
        # only set lookups (not SET_ALIASES), so "Alpha Kavu" keeps its name.
        for short, full in (("alpha", "limited edition alpha"), ("beta", "limited edition beta")):
            if full in self._set_vocab:
                self._set_lookup.setdefault(short, full)

        for term in self.metadata_terms:
            self._metadata_lookup.setdefault(compact(term), term)

        self._compact_of = {}
        for name in self.unique_names:
            cn = compact(name)
            if not cn:
                continue
            self._compact_of[name] = cn
            self._compact_name_map.setdefault(cn, []).append(name)
            # Parenthetical Scryfall names can be matched without scanning all
            # 500k+ names on every unresolved row.
            base = norm(re.sub(r"\s*\([^()]*\)\s*$", "", name))
            if base and base != norm(name):
                bcn = compact(base)
                if bcn:
                    self._compact_base_name_map.setdefault(bcn, []).append(name)
            self._length_name_index.setdefault(len(cn), []).append(name)
            for tok in set(re.findall(r"[a-z0-9]+", norm(name))) | set(_name_words(name)):
                if len(tok) >= 3:
                    self._token_name_index.setdefault(tok, []).append(name)

    def load_search_cache(self):
        try:
            return json.loads(SEARCH_CACHE.read_text(encoding="utf-8")) if SEARCH_CACHE.exists() else {}
        except Exception:
            return {}

    def save_search_cache(self):
        try:
            SEARCH_CACHE.write_text(json.dumps(self.cache, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def ensure_bulk(self):
        self.log(f"Data folder: {DATA_DIR}")
        self.log("Magic card list (identifies Magic cards; prices come from TCGplayer): checking for updates...")
        r = requests.get(BULK_API, headers=UA, timeout=30)
        r.raise_for_status()
        data = r.json()
        meta = next((x for x in data.get("data", []) if x.get("type") == "all_cards"), None)
        if not meta:
            raise RuntimeError("Scryfall All Cards bulk-data entry was not found.")
        download_uri = meta.get("download_uri") or meta.get("jsonl_download_uri")
        if not download_uri:
            raise RuntimeError("Scryfall did not provide a bulk-data download URI.")

        old = {}
        if BULK_META.exists():
            try:
                old = json.loads(BULK_META.read_text(encoding="utf-8"))
            except Exception:
                pass
        current = {"id": meta.get("id"), "updated_at": meta.get("updated_at"), "download_uri": download_uri}

        # Fast path: the persistent cache and its metadata agree with Scryfall.
        if BULK_GZ.exists() and old.get("id") == current["id"] and old.get("updated_at") == current["updated_at"]:
            self.log("Magic card list is up to date.")
            return

        # If a user supplied an existing bulk file but no usable metadata, use it
        # rather than blindly downloading hundreds of MB. We record that the file
        # was locally adopted; the next launch will perform only the small metadata
        # request above and, if Scryfall has a newer updated_at, download once.
        if BULK_GZ.exists() and not old:
            self.log("Using the Magic card list already on this computer.")
            BULK_META.write_text(json.dumps({
                **current,
                "source": "existing-local-bulk",
                "adopted_without_download": True,
            }, indent=2), encoding="utf-8")
            if INDEX.exists():
                try:
                    INDEX.unlink()
                except OSError:
                    pass
            return

        self.log("Downloading the latest Magic card list from Scryfall (about 400 MB)...")
        tmp = DATA_DIR / "scryfall_all_cards.jsonl.download.tmp"
        try:
            with requests.get(download_uri, headers=UA, stream=True, timeout=180) as rr:
                rr.raise_for_status()
                total = int(rr.headers.get("content-length", "0") or 0)
                got = 0
                with open(tmp, "wb") as f:
                    for chunk in rr.iter_content(1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            got += len(chunk)
                            if total and (got % (50 * 1024 * 1024) < 1024 * 1024):
                                self.log(f"  Downloaded {got/1024/1024:.1f} / {total/1024/1024:.1f} MB")
            tmp.replace(BULK_GZ)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        BULK_META.write_text(json.dumps(current, indent=2), encoding="utf-8")
        if INDEX.exists():
            INDEX.unlink()
        self.log("Magic card list downloaded.")

    def build(self):
        if INDEX.exists():
            try:
                d = pickle.loads(INDEX.read_bytes())
                if d.get("version") != INDEX_VERSION:
                    raise ValueError("old index version")
                self.cards = d["cards"]
                self.names = d["names"]
                self.unique_names = d["unique_names"]
                self.metadata_terms = set(d.get("metadata_terms", []))
                self.set_terms = set(d.get("set_terms", []))
                if not self.metadata_terms or not self.set_terms:
                    self._build_metadata_terms()
                self._build_runtime_indexes()
                self.log(f"Magic card list loaded: {len(self.cards):,} printings.")
                self.self_test()
                return
            except Exception as e:
                self.log(f"Cached index rejected ({e}); rebuilding from bulk data...")

        self.log("Indexing the Magic card list (after each Scryfall update, about 2 minutes)...")
        self.cards = []
        self.names = {}
        with gzip.open(BULK_GZ, "rt", encoding="utf-8") as f:
            for line in f:
                c = json.loads(line)
                card = {
                    "id": c.get("id"),
                    "name": c.get("name", ""),
                    "set": c.get("set", ""),
                    "set_name": c.get("set_name", ""),
                    "set_type": c.get("set_type", ""),
                    "released_at": c.get("released_at", ""),
                    "collector_number": c.get("collector_number", ""),
                    "lang": c.get("lang", ""),
                    "oracle_id": c.get("oracle_id", ""),
                    "printed_name": c.get("printed_name", ""),
                    "finishes": c.get("finishes") or [],
                    "frame_effects": c.get("frame_effects") or [],
                    "promo_types": c.get("promo_types") or [],
                    "frame": c.get("frame", ""),
                    "security_stamp": c.get("security_stamp", ""),
                    "watermark": c.get("watermark", ""),
                    "flavor_name": c.get("flavor_name", ""),
                    "flavor_text": c.get("flavor_text", ""),
                    "artist": c.get("artist", ""),
                    "card_faces_names": [f.get("name", "") for f in (c.get("card_faces") or []) if f.get("name")],
                    "full_art": bool(c.get("full_art")),
                    "oversized": bool(c.get("oversized")),
                    "booster": c.get("booster"),
                    "story_spotlight": bool(c.get("story_spotlight")),
                    "border": c.get("border", ""),
                    "border_color": c.get("border_color", ""),
                    "promo": bool(c.get("promo")),
                    "digital": bool(c.get("digital")),
                    "variation": bool(c.get("variation")),
                    "prices": c.get("prices") or {},
                    "tcgplayer_id": c.get("tcgplayer_id"),
                    "tcgplayer_etched_id": c.get("tcgplayer_etched_id"),
                    "image": (c.get("image_uris") or {}).get("normal", ""),
                    "scryfall_uri": c.get("scryfall_uri", ""),
                }
                self.cards.append(card)
                for nm in {card["name"], card.get("printed_name", "")}:
                    if nm:
                        self.names.setdefault(norm(nm), []).append(card)
                for face in c.get("card_faces") or []:
                    fn = face.get("name", "")
                    if fn:
                        self.names.setdefault(norm(fn), []).append(card)

        self.unique_names = sorted(self.names.keys())
        self._build_metadata_terms()
        self._build_runtime_indexes()
        self.self_test()
        INDEX.write_bytes(pickle.dumps({
            "version": INDEX_VERSION,
            "cards": self.cards,
            "names": self.names,
            "unique_names": self.unique_names,
            "metadata_terms": sorted(self.metadata_terms),
            "set_terms": sorted(self.set_terms),
        }, pickle.HIGHEST_PROTOCOL))
        self.log(f"Magic card list indexed: {len(self.cards):,} printings.")
        
    def _build_metadata_terms(self):
        """Learn treatment vocabulary directly from the current Scryfall bulk data."""
        terms = set()
        set_terms = set()
        for c in self.cards:
            sn = norm(c.get("set_name", ""))
            if sn:
                set_terms.add(sn)
            for key in ("frame_effects", "promo_types"):
                for value in c.get(key) or []:
                    n = norm(value)
                    if n:
                        terms.add(n)
            for key in ("frame", "border", "security_stamp", "watermark"):
                value = norm(c.get(key, ""))
                if value:
                    terms.add(value)
        # Compound metadata labels are useful too, but keep only reasonably
        # descriptive terms so ordinary card names aren't swallowed.
        self.metadata_terms = {x for x in terms if len(_clue_tokens(x)) <= 4}
        self.set_terms = set_terms

    def enrich_parsed_with_metadata(self, parsed):
        """Discover set/treatment clues using bounded lookups, not full scans.

        IMPORTANT PERFORMANCE RULE:
        Never iterate over every Scryfall set or metadata term for every input
        row.  A 2,400-row dirty CSV would otherwise perform millions of regex
        searches before processing even begins.  Instead we generate only the
        small number of phrases that can actually occur in this row and look
        them up in O(1) dictionaries built once from Scryfall.
        """
        source = expand_card_name_shorthand(parsed.get("raw", parsed.get("name", "")))
        _condition, source = extract_title_condition(source)
        source = re.sub(r"\([^()]*\)", " ", source)
        source = GRADED_RE.sub("", source)
        source = GRADED_WORD_RE.sub("", source)
        for token in parsed.get("language_tokens") or []:
            source = re.sub(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])", " ", source, flags=re.I)
        source = re.sub(r"\bserial(?:ized)?\b|\bserial\s+numbered\b", "", source, flags=re.I)
        for sp in parsed.get("set_cues") or []:
            source = re.sub(r"(?<![\w'])" + re.escape(sp) + r"(?![\w'])", " ", source, flags=re.I)
        if parsed.get("collector_number"):
            source = re.sub(r"(?:#|[-–—]\s*)" + re.escape(parsed["collector_number"]) + r"\s*$", "", source)
        source = re.sub(r"\betched(?:\s+foil)?\b|\bfoil\b", "", source, flags=re.I)
        source = re.sub(r"\s+", " ", source).strip(" -")

        # ---- Fast set lookup -------------------------------------------------
        set_found = list(parsed.get("set_cues") or [])
        set_found_norm = {norm(x) for x in set_found}

        # Generate only 1..6 word phrases from the current row.  This catches
        # ordinary set names ("Aetherdrift"), multi-word names, and set codes
        # such as "DFT" without scanning the entire Scryfall set vocabulary.
        src_words = re.findall(r"[A-Za-z0-9'’.-]+", source)
        max_set_words = 6
        # Longest phrase first, so "ice age" wins over the set code "ice".
        i = 0
        while i < len(src_words):
            step = 1
            for j in range(min(len(src_words), i + max_set_words), i, -1):
                phrase = " ".join(src_words[i:j])
                pn = norm(phrase)
                if len(pn) < 3:
                    continue
                canonical = self._set_lookup.get(pn) or self._set_lookup.get(compact(pn))
                if not canonical:
                    continue
                # Never consume the entire input when it is itself an exact
                # card name (e.g. a card named after a set).
                if norm(parsed.get("raw", "")) == pn and self.names.get(pn):
                    continue
                if canonical not in set_found_norm:
                    set_found.append(canonical)
                    set_found_norm.add(norm(canonical))
                    source = re.sub(r"(?<![\w'])" + re.escape(phrase) + r"(?![\w'])", " ", source, count=1, flags=re.I)
                step = j - i
                break
            i += step

        # Parenthetical annotations are especially useful for set names.
        alias_to_canonical = {}
        for alias, targets in SET_ALIASES.items():
            for target in targets:
                alias_to_canonical[norm(alias)] = norm(target)
        for clue in parsed.get("treatment_phrases") or []:
            cn = norm(clue)
            canonical = alias_to_canonical.get(cn)
            if not canonical:
                canonical = self._set_lookup.get(cn) or self._set_lookup.get(compact(cn))
            if canonical:
                set_found.append(canonical)
                set_found_norm.add(norm(canonical))

        parsed["set_cues"] = unique(set_found)

        # ---- Fast treatment lookup ------------------------------------------
        # Only examine suffix phrases from the actual input.  Scryfall metadata
        # terms are limited to the vocabulary learned from the current bulk
        # data, but we never loop over that vocabulary for every card.
        name = source
        found = list(parsed.get("treatment_phrases") or [])
        found_norm = {norm(x) for x in found}
        words = name.split()
        max_meta_words = 4
        consumed = 0
        # Treatments in collection exports overwhelmingly occur at the end of
        # the title ("Borderless Poster", "Galaxy Foil", etc.). Check suffixes
        # from longest to shortest so a specific treatment wins over a generic
        # shorter phrase.
        for length in range(min(max_meta_words, len(words)), 0, -1):
            tail = " ".join(words[-length:])
            key = compact(tail)
            term = self._metadata_lookup.get(key)
            if not term:
                continue
            if norm(term) in {"foil", "nonfoil", "etched", "showcase", "borderless"}:
                continue
            if norm(term) not in found_norm:
                found.append(term)
                found_norm.add(norm(term))
            words = words[:-length]
            break

        parsed["name"] = " ".join(words).strip(" -")
        parsed["name_norm"] = norm(parsed["name"])
        parsed["compact"] = compact(parsed["name"])
        parsed["name_variants"] = unique([parsed["name"]])
        parsed["treatment_phrases"] = unique(found)
        parsed["variant_terms"] = unique(found)
        return parsed

    def self_test(self):
        missing = [x for x in SELF_TEST_NAMES if not self.names.get(norm(x))]
        if missing:
            raise RuntimeError("Scryfall index self-test FAILED. Missing exact names: " + ", ".join(missing))
        self.log("Magic card list self-test passed.")
        self.log("  Exact-name checks: " + ", ".join(SELF_TEST_NAMES))

    def _name_hits(self, name):
        cache_key = norm(name)
        if cache_key in self._name_hits_cache:
            return self._name_hits_cache[cache_key]

        hits = self.names.get(cache_key, [])
        if hits:
            result = unique_cards(hits)
            self._name_hits_cache[cache_key] = result
            return result

        comp = compact(name)
        if not comp:
            self._name_hits_cache[cache_key] = []
            return []

        out = []
        for key in self._compact_name_map.get(comp, []):
            out.extend(self.names.get(key, []))

        # Parenthetical Scryfall names use a prebuilt O(1) base-name index.
        if not out:
            for key in self._compact_base_name_map.get(comp, []):
                out.extend(self.names.get(key, []))

        result = unique_cards(out)
        self._name_hits_cache[cache_key] = result
        return result

    def _explains_leftover(self, words):
        """True when every leftover word is a set, treatment, condition,
        language, grading or finish clue rather than part of a card name."""
        i = 0
        while i < len(words):
            for j in range(min(len(words), i + 6), i, -1):
                phrase = " ".join(words[i:j])
                joined = phrase.replace(" ", "")
                if (phrase in _SET_ALIAS_WORDS or phrase in self._set_lookup or joined in self._set_lookup
                        or joined in self._metadata_lookup
                        or (j - i == 1 and (phrase in LEFTOVER_NOISE_WORDS or re.fullmatch(r"\d+[a-z]?", phrase)))):
                    i = j
                    break
            else:
                return False
        return True

    def _embedded_exact_name(self, raw):
        """Find a canonical card name inside dirty text.

        The name must appear as whole words, and every other word in the text
        must be a recognizable clue (set, condition, foil, grade, ...).
        Otherwise "Mox Diamondback" would become Mox Diamond and "Lotus of
        the Abyss" would become The Abyss.
        """
        cache_key = norm(raw)
        if cache_key in self._embedded_cache:
            return self._embedded_cache[cache_key]
        raw_words = _name_words(raw)
        if not raw_words:
            self._embedded_cache[cache_key] = None
            return None

        lookup_tokens = {t for t in raw_words + re.findall(r"[a-z0-9]+", cache_key) if len(t) >= 3}
        candidate_names = set()
        pools = []
        for tok in lookup_tokens:
            hits = self._token_name_index.get(tok)
            if hits:
                pools.append((len(hits), hits))
        pools.sort(key=lambda x: x[0])
        for _, hits in pools[:4]:
            candidate_names.update(hits)

        best = None
        for name in sorted(candidate_names, key=lambda n: len(compact(n)), reverse=True):
            name_words = _name_words(name)
            n = len(name_words)
            if not n or len(compact(name)) < 3:
                continue
            for start in range(len(raw_words) - n + 1):
                if raw_words[start:start + n] == name_words:
                    if self._explains_leftover(raw_words[:start]) and self._explains_leftover(raw_words[start + n:]):
                        best = name
                    break
            if best:
                break
        self._embedded_cache[cache_key] = best
        return best

    def _strict_fuzzy_name(self, name):
        q = norm(name)
        if q in self._fuzzy_cache:
            return self._fuzzy_cache[q]
        qc = compact(q)
        if not qc:
            result = (None, 0.0, 0.0)
            self._fuzzy_cache[q] = result
            return result

        pool = set()
        qtokens = [t for t in re.findall(r"[a-z0-9]+", q) if len(t) >= 3]
        for tok in qtokens:
            pool.update(self._token_name_index.get(tok, ()))
        # Always include names of similar length: a misspelled single word
        # ("Tarmagoyf") shares no token with the real name.
        qlen = len(qc)
        radius = max(2, min(6, qlen // 5))
        for ln in range(max(1, qlen-radius), qlen+radius+1):
            pool.update(self._length_name_index.get(ln, ()))

        # Keep the names that share the most letter pairs with the query, so
        # the real name is never cut by an arbitrary pool limit.
        if len(pool) > 600:
            qgrams = _bigrams(qc)
            compact_of = getattr(self, "_compact_of", {})

            def gram_score(k):
                kg = _bigrams(compact_of.get(k) or compact(k))
                return len(qgrams & kg) / len(qgrams | kg)
            pool = heapq.nlargest(600, pool, key=gram_score)

        # Score on spelling similarity alone; a single-word typo shares no
        # whole word with the real name, so word overlap must not count.
        scored = []
        for key in pool:
            kc = compact(key)
            if kc:
                scored.append((SequenceMatcher(None, qc, kc).ratio(), key))
        if not scored:
            result = (None, 0.0, 0.0)
            self._fuzzy_cache[q] = result
            return result
        scored.sort(reverse=True)
        best_ratio, best_key = scored[0]

        # The runner-up must be a different card: a foreign printed name of
        # the same card ("Llanowarelfen") is not a competing guess.
        def card_identity(key):
            hits = self.names.get(key) or []
            return norm(hits[0].get("name", "")) if hits else key
        best_identity = card_identity(best_key)
        # On a near tie, resolve to the English name rather than a foreign
        # printed name of the same card, so English printings are priced.
        if best_key != best_identity:
            english = next((r for r, k in scored if k == best_identity), None)
            if english is not None and english >= best_ratio - 0.02:
                best_key = best_identity
        second_ratio =next((r for r, k in scored[1:] if card_identity(k) != best_identity), 0.0)
        margin = best_ratio - second_ratio
        min_ratio = 0.86 if len(qc) >= 8 else 0.9
        if best_ratio >= min_ratio and (margin >= 0.05 or best_ratio >= 0.95):
            result = (best_key, best_ratio, margin)
        else:
            result = (None, best_ratio, margin)
        self._fuzzy_cache[q] = result
        return result


    def _descriptor_hits(self, words, parsed):
        """Descriptor-prefix lookup ("Green Chaos Emerald" -> "Chaos Emerald").

        The prefix is only accepted when Scryfall metadata for the hit
        actually mentions it; otherwise "Lotus of the Abyss" would become
        The Abyss and "Blue-Eyes White Dragon" would become White Dragon.
        """
        for start in range(1, min(3, len(words) - 1) + 1):
            tail = " ".join(words[start:]).strip()
            if not tail:
                continue
            hits = self._name_hits(tail)
            if not hits:
                continue
            probe = {"descriptor_terms": [" ".join(words[:start])]}
            described = [c for c in hits
                         if descriptor_match_score(c, probe) and norm(probe["descriptor_terms"][0]) not in norm(c.get("name", ""))]
            if described:
                parsed.setdefault("descriptor_terms", []).append(probe["descriptor_terms"][0])
                return unique_cards(hits)
        return None

    def candidates(self, parsed):
        embedded = self._embedded_exact_name(expand_card_name_shorthand(parsed.get("raw", "")))
        if embedded:
            parsed["name"] = embedded
            parsed["name_norm"] = norm(embedded)
            parsed["compact"] = compact(embedded)
            parsed["name_variants"] = [embedded]
            parsed["exact_embedded_name"] = True
        else:
            parsed["exact_embedded_name"] = False
        self.enrich_parsed_with_metadata(parsed)
        # Re-assert the embedded canonical name after metadata enrichment.
        # Metadata vocabulary must never be allowed to consume part of a known
        # card title (for example the word "Tawnos" in Candelabra of Tawnos).
        if embedded:
            parsed["name"] = embedded
            parsed["name_norm"] = norm(embedded)
            parsed["compact"] = compact(embedded)
            parsed["name_variants"] = [embedded]
        # Some modern Secret Lair variants are commonly entered with a
        # descriptor before the card name (e.g. "Green Chaos Emerald") even
        # though Scryfall's canonical card name is "Chaos Emerald (Lotus Petal)".
        # Preserve the descriptor as a clue, but search the trailing phrase as
        # a possible canonical card name before falling back to fuzzy matching.
        # 1. Exact canonical name is authoritative. Never let a Scryfall
        # search alias or fuzzy result replace an exact canonical card name.
        exact_hits = self.names.get(parsed["name_norm"], [])
        if exact_hits:
            return unique_cards(exact_hits), "EXACT"
        if not embedded:
            raw_words = re.findall(r"[A-Za-z0-9'’.-]+", parsed.get("name", ""))
            if len(raw_words) >= 3:
                hits = self._descriptor_hits(raw_words, parsed)
                if hits:
                    return hits, "NORMALIZED"

        # 2. Normalized/base-name matches are allowed when Scryfall has a
        # parenthetical printing name (e.g. Chaos Emerald (Lotus Petal)).
        for name in parsed["name_variants"]:
            hits = self._name_hits(name)
            if hits:
                return unique_cards(hits), "NORMALIZED"

        # 3. Descriptor-prefix fallback. Collection lists often say things like
        # "Green Chaos Emerald" while the canonical Scryfall name is different.
        words = parsed["name"].split()
        hits = self._descriptor_hits(words, parsed) if len(words) >= 3 else None
        if hits:
            return hits, "NORMALIZED"

        # 4. CPU-heavy fuzzy matching, local only. No network request is made
        # here; unresolved names remain visible for manual review.
        fuzzy_name, fuzzy_score, fuzzy_margin = self._strict_fuzzy_name(parsed["name"])
        # A typo followed by words that aren't part of the name (a misspelled
        # set, a note): try the leading words, at a stricter 0.9 ratio.
        lead = parsed["name"].split()
        for n in range(len(lead) - 1, 1, -1):
            if fuzzy_name:
                break
            guess, score, margin = self._strict_fuzzy_name(" ".join(lead[:n]))
            if guess and score >= 0.9:
                fuzzy_name, fuzzy_score, fuzzy_margin = guess, score, margin
                parsed.setdefault("parse_warnings", []).append(
                    "IGNORED WORDS: " + " ".join(lead[n:]))
        if fuzzy_name:
            hits=self._name_hits(fuzzy_name)
            if hits:
                parsed["resolved_name"]=fuzzy_name
                parsed["fuzzy_name_score"]=fuzzy_score
                parsed["fuzzy_name_margin"]=fuzzy_margin
                return unique_cards(hits), "FUZZY"
        return [], "NO MATCH"

_SET_ALIAS_WORDS = {" ".join(_name_words(k)) for k in SET_ALIASES}

# Words that can sit next to a card name in a dirty title without being part
# of it: finish, grading, language, condition, treatment and filler words.
LEFTOVER_NOISE_WORDS = (
    {"foil", "foils", "etched", "nonfoil", "non", "normal", "signed", "autographed", "graded", "slab", "slabbed",
     "holo", "x", "edition", "ed", "mtg", "magic", "condition", "psa", "bgs", "cgc", "sgc", "tag", "beckett",
     "gem", "pristine", "showcase", "borderless", "extended", "art", "alternate", "alt", "retro", "frame",
     "full", "promo", "prerelease", "stamped", "textless", "misprint", "serialized", "serial", "numbered",
     "alpha", "beta", "unlimited", "revised", "copy", "copies", "card"}
    | {w for k in CONDITION_ALIASES for w in _name_words(k)}
    | {w for k in LANGUAGE_ALIASES for w in _name_words(k)}
)

def unique_cards(cards):
    out = []
    seen = set()
    for c in cards:
        cid = c.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            out.append(c)
    return out

def set_matches(card, cue):
    sn = norm(card.get("set_name", ""))
    aliases = SET_ALIASES.get(norm(cue), [cue])
    if norm(cue) == "promo":
        return bool(card.get("promo")) or "promo" in sn
    return any(a in sn or sn == a for a in map(norm, aliases))

def finish_matches(card, finish):
    finishes = set(card.get("finishes") or [])
    if finish == "foil":
        return "foil" in finishes
    if finish == "etched":
        return "etched" in finishes
    return "nonfoil" in finishes

def _metadata_values(card):
    """Return normalized Scryfall metadata values usable as treatment evidence."""
    vals = []
    for key in ("frame_effects", "promo_types"):
        vals.extend(card.get(key) or [])
    for key in ("frame", "border", "security_stamp", "watermark", "flavor_name", "artist"):
        if card.get(key):
            vals.append(card.get(key))
    if card.get("full_art"):
        vals.append("full art")
    if card.get("oversized"):
        vals.append("oversized")
    if card.get("story_spotlight"):
        vals.append("story spotlight")
    if card.get("booster") is False:
        vals.append("not booster")
    return [norm(v) for v in vals if v]

def _clue_tokens(text):
    # Treat spaces, hyphens and punctuation as equivalent for metadata matching.
    return set(re.findall(r"[a-z0-9]+", norm(text)))

def _metadata_match_score(clue, metadata):
    """Score a free-form input clue against Scryfall metadata without a fixed list."""
    clue_n = norm(clue)
    clue_tokens = _clue_tokens(clue_n)
    if not clue_tokens:
        return 0
    best = 0
    for value in metadata:
        vt = _clue_tokens(value)
        if not vt:
            continue
        if clue_n == value or compact(clue_n) == compact(value):
            best = max(best, 3)
            continue
        if compact(value) and compact(value) in compact(clue_n):
            best = max(best, 2)
            continue
        if clue_tokens <= vt or vt <= clue_tokens:
            best = max(best, 2)
            continue
        overlap = len(clue_tokens & vt)
        if overlap and overlap / max(len(clue_tokens), len(vt)) >= 0.5:
            best = max(best, 1)

    # A user phrase can combine multiple Scryfall metadata fields. For example,
    # "Borderless Poster Foil" is finish=foil plus border=borderless plus
    # promo_type=poster. Treat the phrase as confirmed when each meaningful
    # token is represented somewhere in the metadata, even if Scryfall stores
    # those tokens in separate fields.
    metadata_tokens = set()
    for value in metadata:
        metadata_tokens.update(_clue_tokens(value))
    if clue_tokens and clue_tokens <= metadata_tokens:
        best = max(best, 3)
    return best

def variant_matches(card, parsed):
    clues = parsed.get("treatment_phrases") or parsed.get("variant_terms") or []
    if not clues:
        return 0
    metadata = _metadata_values(card)
    if not metadata:
        return 0
    return sum(1 for clue in clues if _metadata_match_score(clue, metadata) >= 2)

def variant_evidence(card, parsed):
    """Return (matched_clues, requested_clues) for precise review decisions."""
    clues = parsed.get("treatment_phrases") or parsed.get("variant_terms") or []
    metadata = _metadata_values(card)
    matched = [clue for clue in clues if _metadata_match_score(clue, metadata) >= 2]
    return matched, clues

def descriptor_values(card):
    """Human-facing descriptors that may distinguish otherwise identical cards."""
    vals = []
    for key in ("flavor_name", "printed_name", "name", "set_name", "collector_number", "artist"):
        value = card.get(key)
        if value:
            vals.append(norm(value))
    vals.extend(norm(x) for x in (card.get("card_faces_names") or []) if x)
    return vals

def descriptor_match_score(card, parsed):
    clues = parsed.get("descriptor_terms") or []
    if not clues:
        return 0
    values = descriptor_values(card)
    score = 0
    for clue in clues:
        cn = norm(clue)
        if any(cn == v or cn in v for v in values):
            score += 1
    return score

def score_candidate(c, parsed):
    q = parsed["name_norm"]
    cname = norm(c.get("name", ""))
    score = 0.0

    if cname == q:
        score += 1000
    elif compact(cname) == parsed["compact"]:
        score += 950
    else:
        score += 500 * SequenceMatcher(None, cname, q).ratio()

    # Strong explicit constraints.
    if parsed["set_cues"]:
        matched_sets = sum(1 for cue in parsed["set_cues"] if set_matches(c, cue))
        if matched_sets:
            score += 450 * matched_sets
        else:
            score -= 800

    if parsed["collector_number"]:
        if collector_number_equal(c.get("collector_number"), parsed["collector_number"]):
            score += 700
        else:
            score -= 900

    if parsed["finish"] in {"foil", "etched"}:
        if finish_matches(c, parsed["finish"]):
            score += 500
        else:
            score -= 900
    elif not parsed.get("finish_explicit") and finish_matches(c, "nonfoil"):
        score += 40

    clues = parsed.get("treatment_phrases") or parsed.get("variant_terms") or []
    dm = descriptor_match_score(c, parsed)
    if parsed.get("descriptor_terms"):
        score += 350 * dm
        if dm == 0:
            score -= 350
    vm = variant_matches(c, parsed)
    if clues:
        score += 220 * vm
        if vm == 0:
            # Metadata-driven clues are meaningful, but not every marketplace
            # phrase has a one-to-one Scryfall field. Penalize rather than reject.
            score -= 250

    if c.get("lang") == "en":
        score += 25
    if c.get("digital"):
        score -= 200
    if is_unlikely_unspecified_printing(c) and not explicitly_requests_special_printing(parsed):
        score -= 700
    # A serialized printing is a materially different product. Do not select
    # one merely because the input says "poster foil"; require an explicit
    # serialized clue. Scryfall exposes this in promo_types.
    if "serialized" in {norm(x) for x in (c.get("promo_types") or [])}:
        if parsed.get("serialized"):
            score += 250
        else:
            score -= 900

    if c.get("promo") and "promo" not in {norm(x) for x in parsed["variant_terms"]} and not parsed["set_cues"]:
        score -= 80

    return score

def filter_candidates(cands, parsed):
    """Apply hard constraints when doing so leaves a viable candidate set."""
    out = unique_cards(cands)

    if parsed["set_cues"]:
        for cue in parsed["set_cues"]:
            filtered = [c for c in out if set_matches(c, cue)]
            if filtered:
                out = filtered

    if parsed["collector_number"]:
        filtered = [c for c in out if collector_number_equal(c.get("collector_number"), parsed["collector_number"])]
        if filtered:
            out = filtered

    if parsed["finish"] in {"foil", "etched"}:
        filtered = [c for c in out if finish_matches(c, parsed["finish"])]
        if filtered:
            out = filtered

    # Never silently turn an ordinary card request into a serialized printing.
    # If the user explicitly asks for serialized, keep only serialized records.
    serialized_cards = [c for c in out if "serialized" in {norm(x) for x in (c.get("promo_types") or [])}]
    if parsed.get("serialized") and serialized_cards:
        out = serialized_cards
    elif not parsed.get("serialized") and serialized_cards:
        ordinary_cards = [c for c in out if "serialized" not in {norm(x) for x in (c.get("promo_types") or [])}]
        if ordinary_cards:
            out = ordinary_cards

    # Human-facing descriptors (e.g. Green/Blue/Purple) are treated as strong
    # clues when Scryfall exposes them in flavor/printed metadata. Do not guess
    # when Scryfall has no evidence.
    descriptor_clues = parsed.get("descriptor_terms") or []
    if descriptor_clues:
        described = [c for c in out if descriptor_match_score(c, parsed) == len(descriptor_clues)]
        if described:
            out = described

    # Explicit treatment cues are a filter only when Scryfall metadata confirms
    # at least one candidate. A fully matched clue is preferred over generic foil.
    clues = parsed.get("treatment_phrases") or parsed.get("variant_terms") or []
    if clues:
        treated = [c for c in out if all(_metadata_match_score(clue, _metadata_values(c)) >= 2 for clue in clues)]
        if treated:
            out = treated
        else:
            partial = [c for c in out if variant_matches(c, parsed) > 0]
            if partial:
                out = partial

    return out

def is_unlikely_unspecified_printing(card):
    """Printings we should not select by default unless the input asks for them."""
    if card.get("oversized"):
        return True
    sn = norm(card.get("set_name", ""))
    # World Championship Deck products are legitimate Scryfall records, but
    # are unusual collection-trade inputs unless explicitly identified.
    if "world championship" in sn:
        return True
    if "championship deck" in sn:
        return True
    # Collector's Edition products are legitimate Scryfall printings, but
    # should not be selected for an ordinary card-list entry unless explicitly
    # identified. This covers both CE and International Collector's Edition.
    # 30th Anniversary Edition is a non-tournament-legal reprint product.
    if "30th anniversary edition" in sn:
        return True
    sn = sn.replace("'", "")  # Scryfall spells it "Collectors' Edition"
    if "collectors edition" in sn:
        return True
    if "international collector" in sn or "intl. collectors" in sn or "intl collectors" in sn:
        return True
    return False

def explicitly_requests_special_printing(parsed):
    text = norm(parsed.get("raw", "")).replace("collectors'", "collectors")
    return (
        "oversized" in text
        or "world championship" in text
        or "championship deck" in text
        or "collector's edition" in text
        or "collectors edition" in text
        or "international collector" in text
        or "intl. collectors" in text
        or "intl collectors" in text
        or bool(re.search(r"\bcei\b", text))
        or bool(re.search(r"\bced\b", text))
        or "serialized" in text
        or "30th anniversary" in text
        or bool(re.search(r"\b30a\b", text))
    )

def default_rank(c, parsed):
    """Deterministic default printing: oldest real-world paper printing first."""
    release = c.get("released_at") or "9999-99-99"
    promo_penalty = 1 if c.get("promo") else 0
    digital_penalty = 1 if c.get("digital") else 0
    variation_penalty = 1 if c.get("variation") else 0
    # Lower tuple is better.
    return (digital_penalty, promo_penalty, variation_penalty, release, norm(c.get("set_name", "")), norm(c.get("collector_number", "")))

def _card_has_requested_finish(card, parsed):
    finish = parsed.get("finish", "nonfoil")
    return finish_matches(card, finish)

def _has_scryfall_price(card, parsed):
    return price_card(card, parsed)[0] is not None

def _identity_is_specific(filtered, parsed, ranked):
    """Return True only when the available evidence identifies one printing."""
    if len(filtered) == 1:
        return True

    # A set + collector number is a printing-level identity.
    if parsed.get("set_cues") and parsed.get("collector_number"):
        matches = [c for c in filtered if any(set_matches(c, cue) for cue in parsed["set_cues"]) and collector_number_equal(c.get("collector_number"), parsed["collector_number"]) ]
        if len(matches) == 1:
            return True

    # Collector number plus an explicit finish/treatment can identify a printing
    # even when the set was not written by the collector.
    if parsed.get("collector_number"):
        matches = [c for c in filtered if collector_number_equal(c.get("collector_number"), parsed["collector_number"]) ]
        if parsed.get("finish") in {"foil", "etched"}:
            matches = [c for c in matches if finish_matches(c, parsed["finish"])]
        clues = parsed.get("treatment_phrases") or []
        if clues:
            matches = [c for c in matches if all(_metadata_match_score(x, _metadata_values(c)) >= 2 for x in clues)]
        if len(matches) == 1:
            return True

    # An explicit treatment that uniquely identifies one surviving printing is
    # enough even when the card has many historical printings.
    clues = parsed.get("treatment_phrases") or []
    if clues:
        matches = [c for c in filtered if all(_metadata_match_score(x, _metadata_values(c)) >= 2 for x in clues)]
        if len(matches) == 1:
            return True

    return False

def _reorder_underdetermined_candidates(filtered, parsed):
    """Put priced applicable candidates ahead when identity remains underdetermined."""
    priced = [c for c in filtered if _has_scryfall_price(c, parsed)]
    if priced:
        return sorted(priced, key=lambda c: (
            price_card(c, parsed)[0],
            score_candidate(c, parsed) * -1,
            default_rank(c, parsed),
        )) + [c for c in filtered if c not in priced]
    return sorted(filtered, key=lambda c: (-score_candidate(c, parsed), default_rank(c, parsed)))

def choose_candidate(cands, parsed, match_type):
    if not cands:
        return None, 0.0, "NO MATCH"

    # If the collector explicitly wrote "foil" but this card has literally
    # no foil printing anywhere in the available Scryfall records, treat the
    # foil word as an erroneous finish annotation. In that one situation only,
    # fall back to the ordinary nonfoil card. We intentionally check the full
    # candidate pool here rather than only the currently filtered set, because
    # a card may have a foil printing in another set.
    if parsed.get("finish_explicit") and parsed.get("finish") == "foil":
        has_any_foil_printing = any(finish_matches(c, "foil") for c in unique_cards(cands))
        if not has_any_foil_printing:
            parsed["finish"] = "nonfoil"
            parsed["finish_explicit"] = False

    filtered = filter_candidates(cands, parsed)
    if not explicitly_requests_special_printing(parsed):
        ordinary = [c for c in filtered if not is_unlikely_unspecified_printing(c)]
        if ordinary:
            filtered = ordinary
    if not filtered:
        return None, 0.0, "NO MATCH"

    ranked = sorted(((score_candidate(c, parsed), c) for c in filtered), key=lambda x: x[0], reverse=True)
    best_score, best = ranked[0]
    second_score, second = ranked[1] if len(ranked) > 1 else (None, None)
    specific = _identity_is_specific(filtered, parsed, ranked)
    review = ""

    # When the input does not uniquely identify a printing, choose among the
    # applicable priced candidates by price. Strongly identified printings are
    # never replaced just because another printing is cheaper.
    if not specific and len(filtered) > 1:
        ordered = _reorder_underdetermined_candidates(filtered, parsed)
        if ordered:
            best = ordered[0]
            best_score = score_candidate(best, parsed)
            if not _has_scryfall_price(best, parsed):
                review = "NO PRICE"
            else:
                review = "ASSUMED PRINTING"

    # If a specifically identified printing has no applicable Scryfall price,
    # preserve that exact printing. Do not silently substitute another set.
    if specific and not _has_scryfall_price(best, parsed):
        review = "NO PRICE FOR SPECIFIC PRINTING"

    if match_type == "EXACT":
        confidence = 1.0
    elif match_type == "NORMALIZED":
        confidence = 0.99
    elif match_type == "SCRYFALL SEARCH":
        confidence = 0.97
    else:
        confidence = max(0.0, min(0.99, best_score / 1200.0))

    if match_type == "FUZZY" and review == "":
        review = "FUZZY MATCH"

    # Treatment clues are decisive when Scryfall metadata confirms them.
    clues = parsed.get("treatment_phrases") or []
    if clues:
        matching_ids = []
        for _score, c in ranked:
            matched, _ = variant_evidence(c, parsed)
            if all(norm(x) in {norm(y) for y in matched} for x in clues):
                matching_ids.append(c.get("id"))
        if len(set(matching_ids)) == 1 and matching_ids[0] == best.get("id") and review == "AMBIGUOUS PRINTING":
            review = ""

    if parsed.get("descriptor_terms") and len(filtered) > 1 and descriptor_match_score(best, parsed) == 0:
        if review == "":
            review = "AMBIGUOUS PRINTING"

    if parsed.get("finish_explicit") and parsed["finish"] in {"foil", "etched"} and not finish_matches(best, parsed["finish"]):
        review = "REQUESTED FINISH NOT CONFIRMED"

    return best, confidence, review

def effective_finish(card, parsed):
    """Return the finish actually represented by the selected printing."""
    if parsed.get("finish_explicit"):
        return parsed.get("finish", "nonfoil")
    finishes = card.get("finishes") or []
    if "nonfoil" in finishes:
        return "nonfoil"
    if "foil" in finishes:
        return "foil"
    if "etched" in finishes:
        return "etched"
    return parsed.get("finish", "nonfoil")

# TCGplayer prices from TCGCSV, set by the engine when the Magic catalog has
# been synced. Scryfall's own price fields are the fallback.
_PRICE_CATALOG = None


def set_price_catalog(catalog):
    global _PRICE_CATALOG
    _PRICE_CATALOG = catalog


def tcgplayer_product(card, parsed):
    """(product, price row) for this printing and finish in the TCGCSV catalog."""
    if _PRICE_CATALOG is None:
        return None, None
    finish = effective_finish(card, parsed)
    product = None
    if finish == "etched" and card.get("tcgplayer_etched_id"):
        product = _PRICE_CATALOG.get(card["tcgplayer_etched_id"])
    if product is None:
        product = _PRICE_CATALOG.get(card.get("tcgplayer_id"))
    if product is None:
        return None, None
    prices = product.get("prices") or {}
    row = prices.get("Normal") if finish == "nonfoil" else prices.get("Foil")
    return product, row


def price_card(card, parsed):
    product, row = tcgplayer_product(card, parsed)
    if row:
        val, basis = choose_price(row)
        if val is not None:
            return val, basis, "Price from TCGplayer (TCGCSV)"
    prices = card.get("prices") or {}
    finish = effective_finish(card, parsed)
    if finish == "foil":
        val = money(prices.get("usd_foil"))
        if val is not None:
            return val, "Scryfall USD Foil", "Price supplied by Scryfall"
        return None, "", "No Scryfall foil price"
    if finish == "etched":
        val = money(prices.get("usd_etched"))
        if val is not None:
            return val, "Scryfall USD Etched", "Price supplied by Scryfall"
        return None, "", "No Scryfall etched price"
    val = money(prices.get("usd"))
    if val is not None:
        return val, "Scryfall USD", "Price supplied by Scryfall"
    return None, "", "No Scryfall price"

def image_url(card):
    return card.get("image", "")

def matched_display_name(card, parsed):
    """Return the face name the user actually matched, not the front-face
    composite name of a double-faced card.

    Scryfall stores a transforming/double-faced card as one printing whose
    top-level ``name`` can be something like ``Eiganjo Dynastorian //
    Replenish``.  The index also maps each face name to that printing.  When
    the input is exactly a face name (for example ``Replenish``), the output
    should report that face name rather than the composite card name.
    """
    wanted = norm(parsed.get("name", ""))
    if not wanted:
        return card.get("name", "")

    if wanted == norm(card.get("name", "")):
        return card.get("name", "")

    for face_name in card.get("card_faces_names") or []:
        if wanted == norm(face_name):
            return face_name

    # ``printed_name`` can also be the name the user matched on some
    # translated/special printings.
    printed = card.get("printed_name", "")
    if printed and wanted == norm(printed):
        return printed

    return card.get("name", "")

def prewarm_fuzzy_multiprocess(db, parsed_items, log):
    """Pre-resolve only genuinely fuzzy names using up to 8 local workers.

    IMPORTANT:
      The old macOS implementation spawned processes and built/serialized large
      fuzzy indexes for each worker. On a 542k-card Scryfall database that can
      take longer than the actual pricing job and can make the GUI appear frozen.

      We keep the user-visible "8 workers" behavior, but use threads against the
      already-built in-memory indexes. Exact/normalized matches never enter this
      pool. This avoids process spawning, giant pickles, duplicated indexes, and
      macOS AppTranslocation/process crashes.
    """
    queries = []
    seen = set()

    for parsed in parsed_items:
        q = norm(parsed.get("name", ""))
        if not q or q in seen or q in db._fuzzy_cache:
            continue
        # O(1) exact/compact lookup. Only names that truly need fuzzy matching
        # are sent to the worker pool.
        if db._name_hits(q):
            continue
        seen.add(q)
        queries.append(q)

    if not queries:
        log("Turbo pre-pass: no fuzzy names needed; using indexed matching.")
        return

    workers = min(8, max(1, (mp.cpu_count() or 2) - 1))
    log(f"Turbo pre-pass: {len(queries)} unique fuzzy names on {workers} workers...")

    def resolve(q):
        return q, db._strict_fuzzy_name(q)

    try:
        # Threads share the already-built Scryfall indexes. There is no database
        # copy and no spawn/import cost. SequenceMatcher releases enough time
        # between Python operations for this to provide useful parallelism while
        # preserving the same matching algorithm.
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="MTG-Fuzzy") as ex:
            completed = 0
            futures = [ex.submit(resolve, q) for q in queries]
            for fut in as_completed(futures):
                q, result = fut.result()
                db._fuzzy_cache[q] = result
                completed += 1
                if completed == len(futures) or completed % 50 == 0:
                    log(f"Turbo pre-pass: {completed}/{len(futures)} fuzzy names ready")
    except Exception as e:
        # Fuzzy prewarming is an optimization only. If a worker fails, clear
        # only the affected cache entries and let the normal local resolver run.
        log(f"Turbo worker pre-pass failed safely ({type(e).__name__}: {e}); continuing normally.")
        for q in queries:
            db._fuzzy_cache.pop(q, None)
