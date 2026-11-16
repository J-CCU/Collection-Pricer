"""Regression tests for the collection pricer.

Run from the CardPricer folder:   py tests/run_tests.py [section ...]
Sections: layouts, filegame, magic, pokemon, yugioh, onepiece, riftbound, sealed, mixed
(default: all). Needs the Scryfall index built by
the app ("1. Load Card Data"); TCGCSV-backed sections skip games not synced.
"""

import csv
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.stdout.reconfigure(encoding="utf-8")

from cardpricer import engine, pricing  # noqa: E402
from cardpricer.conditions import normalize_condition  # noqa: E402
from cardpricer.games.magic import ScryfallDB  # noqa: E402
from cardpricer.sources.tcgcsv import TCGCSV  # noqa: E402
from cardpricer.listread import read_list  # noqa: E402
from cardpricer.text import compact, norm, split_leading_quantity  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
RESULTS = {"pass": 0, "fail": 0}


def check(ok, label, detail=""):
    RESULTS["pass" if ok else "fail"] += 1
    if not ok:
        print(f"  FAIL {label} {detail}")


_DB = None
_ENGINE = None


def engine_for_tests():
    """One Engine over the Scryfall index and whatever TCGCSV data is synced."""
    global _ENGINE
    if _ENGINE is None:
        t = time.time()
        _ENGINE = engine.Engine(magic_db(), TCGCSV(lambda s: None), lambda s: None)
        print(f"(engine ready in {time.time() - t:.0f}s; games: {', '.join(_ENGINE.games)})")
    return _ENGINE


def price_rows(rows, header, default_game="magic"):
    """Write rows to a temporary CSV, price it, return {input: output row}."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cases.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        out, _totals = engine_for_tests().process_file(
            path, "LP/MP", pricing.DEFAULT_BUY_TIERS, lambda s: None, lambda a, b: None,
            pricing.DEFAULT_SPECIAL_RULES, default_game)
    return {r["Input"]: r for r in out if r["Input"] not in ("", "TOTAL")}


def magic_db():
    global _DB
    if _DB is None:
        t = time.time()
        _DB = ScryfallDB(lambda s: None)
        _DB.build()
        print(f"(Scryfall index loaded in {time.time() - t:.0f}s)")
    return _DB


# --------------------------------------------------------------- layouts
# file -> expected rows: (name, quantity, condition, set contains, number, finish, language)
LAYOUTS = {
    "name_only.txt": [("Lightning Bolt", 1, "", "", "", "", ""), ("Brainstorm", 1, "", "", "", "", "")],
    "one_column_mixed.csv": [("Lightning Bolt Beta NM", 2, "", "", "", "", ""),
                             ("Counterspell (ITA)", 3, "", "", "", "", "")],
    "deck_list.txt": [("Lightning Bolt", 4, "", "LEB", "162", "", ""),
                      ("Sheoldred, the Apocalypse", 1, "", "DMU", "107", "foil", ""),
                      ("Counterspell", 3, "", "", "", "", ""), ("Brainstorm", 2, "", "", "", "", "")],
    "shuffled_misleading.csv": [("Lightning Bolt", 2, "NM", "Beta", "", "", ""),
                                ("Dark Ritual", 1, "HP", "Alpha", "", "", "")],
    "shuffled_no_header.csv": [("Lightning Bolt", 4, "NM", "", "", "Foil", ""), ("Sol Ring", 1, "LP", "", "", "", "")],
    "structured.csv": [("Lightning Bolt", 2, "NM", "LEB", "162", "", ""),
                       ("Sheoldred, the Apocalypse", 1, "LP", "DMU", "107", "foil", "")],
    "header_not_row1.csv": [("Lightning Bolt", 2, "NM", "", "", "", ""), ("Counterspell", 3, "MP", "", "", "", "")],
    "tab_separated.tsv": [("Lightning Bolt", 2, "NM", "LEB", "", "", ""), ("Sol Ring", 1, "LP", "2ED", "", "", "")],
    "manabox.csv": [("Lightning Bolt", 2, "NM", "leb", "162", "normal", "en"),
                    ("Sheoldred, the Apocalypse", 1, "LP", "dmu", "107", "foil", "en"),
                    ("Counterspell", 3, "MP", "ice", "64", "normal", "it")],
    "moxfield.csv": [("Lightning Bolt", 2, "NM", "leb", "162", "", "English"),
                     ("Counterspell", 3, "MP", "ice", "64", "", "Japanese")],
    "tcgplayer_app.csv": [("Lightning Bolt", 2, "NM", "LEB", "162", "Normal", "English"),
                          ("Sheoldred, the Apocalypse", 1, "LP", "DMU", "107", "Foil", "English")],
    "deckbox.csv": [("Lightning Bolt", 2, "NM", "LEB", "162", "", "English"),
                    ("Sol Ring", 1, "LP", "2ED", "270", "", "English")],
    "legends_with_commas.txt": [("Ragavan, Nimble Pilferer", 1, "", "", "", "", ""),
                                ("Jace, the Mind Sculptor", 1, "", "", "", "", "")],
    "excel.xlsx": [("Lightning Bolt", 2, "NM", "", "", "", ""), ("Counterspell", 3, "MP", "", "", "", "")],
}


def test_layouts():
    print("== list layouts")
    db = magic_db()
    known_name = lambda v: bool(db.names.get(norm(v)) or db._compact_name_map.get(compact(v)))  # noqa: E731
    known_set = lambda v: norm(v) in db._set_lookup or compact(v) in db._set_lookup  # noqa: E731
    for fname, expected in LAYOUTS.items():
        items, layout = read_list(FIXTURES / fname, known_name, known_set)
        print(f"  {fname}: {len(items)} rows | {layout}")
        by_name = {i["raw"]: i for i in items}
        for name, qty, cond, set_part, number, finish, lang in expected:
            it = by_name.get(name)
            if it is None:
                check(False, fname, f"missing row {name!r}; got {sorted(by_name)}")
                continue
            got_cond = normalize_condition(it.get("condition", "")) or it.get("condition", "")
            problems = []
            if it["quantity"] != qty:
                problems.append(f"qty {it['quantity']} != {qty}")
            if cond and got_cond != cond:
                problems.append(f"condition {got_cond!r} != {cond!r}")
            if set_part and set_part.lower() not in it.get("set", "").lower():
                problems.append(f"set {it.get('set')!r} lacks {set_part!r}")
            if number and it.get("collector") != number:
                problems.append(f"number {it.get('collector')!r} != {number!r}")
            if finish and it.get("foil", "").lower() != finish.lower():
                problems.append(f"finish {it.get('foil')!r} != {finish!r}")
            if lang and it.get("language") != lang:
                problems.append(f"language {it.get('language')!r} != {lang!r}")
            check(not problems, f"{fname} / {name}", "; ".join(problems))


# ----------------------------------------------------------------- magic
def test_magic():
    print("== magic cases")
    from magic_cases import CASES
    rows = price_rows([c[:4] for c in CASES], ["Title", "Condition", "Foil?", "Language"])
    for title, _cond, _foil, _lang, want_status, want_name in CASES:
        r = rows.get(split_leading_quantity(title)[0])
        ok = (r is not None and (want_status is None or r["Status"] in want_status)
              and (want_name is None or r["Matched Name"] == want_name)
              and not (want_status == {"UNKNOWN"} and r["Matched Name"]))
        check(ok, title, r and f"-> {r['Status']} / {r['Matched Name']!r} / {r['Review Flag']}")


# ------------------------------------------------- other games and sealed
TCG_HEADER = ["Title", "Game", "Condition", "Printing", "Set", "Number"]


def run_tcg_cases(label, cases, default_game="magic"):
    print(f"== {label}")
    for title, cols, want_status, want_name, want_set, want_finish in cases:
        row = [title, cols.get("Game", ""), cols.get("Condition", ""), cols.get("Printing", ""),
               cols.get("Set", ""), cols.get("Number", "")]
        rows = price_rows([row], TCG_HEADER, default_game)
        r = next(iter(rows.values()), None)
        problems = []
        if r is None:
            problems.append("no output row")
        else:
            if r["Status"] not in want_status:
                problems.append(f"status {r['Status']}")
            if want_name and r["Matched Name"] != want_name:
                problems.append(f"name {r['Matched Name']!r}")
            if want_status == UNKNOWN_STATUS and r["Matched Name"]:
                problems.append(f"matched {r['Matched Name']!r}")
            if want_set and want_set.lower() not in r["Set"].lower():
                problems.append(f"set {r['Set']!r}")
            if want_finish and r["Finish"] != want_finish:
                problems.append(f"finish {r['Finish']!r}")
        detail = r and f"[{r['Game']} | {r['Matched Name']} | {r['Set']} | {r['Finish']} | {r['Price Used']} | {r['Review Flag']}]"
        check(not problems, f"{title} {cols or ''}", "; ".join(problems) + " " + str(detail))


UNKNOWN_STATUS = {"UNKNOWN"}


def test_pokemon():
    from tcg_cases import POKEMON
    run_tcg_cases("pokemon", POKEMON, "pokemon")


def test_yugioh():
    from tcg_cases import YUGIOH
    run_tcg_cases("yu-gi-oh", YUGIOH, "yugioh")


def test_onepiece():
    from tcg_cases import ONEPIECE
    run_tcg_cases("one piece", ONEPIECE, "onepiece")


def test_riftbound():
    from tcg_cases import RIFTBOUND
    run_tcg_cases("riftbound", RIFTBOUND, "riftbound")


def test_sealed():
    from tcg_cases import SEALED_CASES
    run_tcg_cases("sealed", SEALED_CASES)


def test_mixed():
    """No default game help: the default stays Magic, rows must find their own game."""
    from tcg_cases import MIXED
    run_tcg_cases("mixed games", MIXED, "magic")


def test_filegame():
    """A name that exists in several games follows the game most of the file is in."""
    print("== main game of the file")
    magic_list = [["Lightning Bolt"], ["Counterspell"], ["Sol Ring"], ["Dark Ritual"], ["Brainstorm"],
                  ["Ancient Tomb"], ["Earthquake"], ["Cataclysm"]]
    rows = price_rows(magic_list, ["Card"], default_game="pokemon")
    for name in ("Ancient Tomb", "Earthquake", "Cataclysm"):
        r = rows[name]
        check(r["Game"].startswith("Magic"), f"magic list / {name}", f"-> {r['Game']} {r['Review Flag']}")
    pokemon_list = [["Charizard ex 006/165"], ["Pikachu 173/165"], ["Umbreon VMAX 215/203"], ["Mew ex 151/165"],
                    ["Gust of Wind"], ["Recycle"]]
    rows = price_rows(pokemon_list, ["Card"], default_game="magic")
    for name in ("Gust of Wind", "Recycle"):
        r = rows[name]
        check(r["Game"] == "Pokémon", f"pokemon list / {name}", f"-> {r['Game']} {r['Review Flag']}")


SECTIONS = {"layouts": test_layouts, "filegame": test_filegame, "magic": test_magic, "pokemon": test_pokemon, "yugioh": test_yugioh,
            "onepiece": test_onepiece, "riftbound": test_riftbound, "sealed": test_sealed, "mixed": test_mixed}

if __name__ == "__main__":
    for name in sys.argv[1:] or SECTIONS:
        SECTIONS[name]()
    print(f"\n{RESULTS['pass']} passed, {RESULTS['fail']} failed")
    sys.exit(1 if RESULTS["fail"] else 0)
