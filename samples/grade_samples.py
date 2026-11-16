"""Price the four sample lists and grade them against a human answer key.

Run from the CardPricer folder:  py samples/grade_samples.py
Each row is graded on: outcome (priced / sealed / manual check / unknown),
the card matched, the set where the input names one, quantity and condition.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from cardpricer import pricing  # noqa: E402
from cardpricer.engine import Engine  # noqa: E402
from cardpricer.games.magic import ScryfallDB  # noqa: E402
from cardpricer.sources.tcgcsv import TCGCSV  # noqa: E402

PRICED, SEALED, MANUAL, UNKNOWN = "priced", "sealed", "manual", "unknown"
STATUS_OF = {"GUARANTEED": PRICED, "NEEDS CHECKING": PRICED, "SEALED": SEALED, "MANUAL CHECK": MANUAL,
             "UNPRICED": PRICED, "UNKNOWN": UNKNOWN}

# input text -> (outcome, matched name or None, set contains or None, quantity, condition or None)
KEYS = {
    "A_clean_export.csv": {
        "Lightning Bolt": (PRICED, "Lightning Bolt", "Beta", 2, "NM"),
        "Sheoldred, the Apocalypse": (PRICED, "Sheoldred, the Apocalypse", "Dominaria United", 1, "LP"),
        "Counterspell": (PRICED, "Counterspell", "Ice Age", 4, "MP"),
        "Sol Ring": (PRICED, "Sol Ring", "Unlimited", 1, "HP"),
        "Charizard ex": (PRICED, "Charizard ex - 006/165", "151", 1, "NM"),
        "Pikachu": (PRICED, "Pikachu - 025/165", "151", 3, "NM"),
        "Umbreon VMAX": (PRICED, "Umbreon VMAX (Alternate Art Secret)", "Evolving Skies", 1, "LP"),
        "Dark Magician": (PRICED, "Dark Magician", "Starter Deck: Yugi", 1, "MP"),
        "Pot of Greed": (PRICED, "Pot of Greed", "Legend of Blue Eyes", 2, "NM"),
        "Nami": (PRICED, "Nami", "Romance Dawn", 1, "NM"),
        "Shanks": (PRICED, "Shanks", "Romance Dawn", 1, "NM"),
        "Jinx, Loose Cannon": (PRICED, "Jinx, Loose Cannon", "Origins", 1, "NM"),
        "Ahri, Alluring": (PRICED, "Ahri, Alluring", "Origins", 1, "LP"),
        "Evolving Skies Booster Box": (SEALED, "Evolving Skies Booster Box", None, 1, None),
        "Modern Horizons 3 - Play Booster Display": (SEALED, "Modern Horizons 3 - Play Booster Display", None, 1, None),
        "Ragavan, Nimble Pilferer": (MANUAL, "Ragavan, Nimble Pilferer", None, 1, None),   # Japanese
        "Charizard": (PRICED, "Charizard", "Base Set", 1, "LP/MP"),                        # no condition given
    },
    "B_sloppy_headers.csv": {
        "Lightning Bolt": (PRICED, "Lightning Bolt", "Beta", 2, "NM"),
        "Sheoldred": (PRICED, "Sheoldred, the Apocalypse", "Dominaria United", 1, "LP"),   # DMU + foil
        "Counterspell": (PRICED, "Counterspell", "Ice Age", 4, "MP"),
        "sol ring": (PRICED, "Sol Ring", "Unlimited", 1, "HP"),
        "Force of Will": (PRICED, "Force of Will", "Alliances", 1, "LP"),
        "Wasteland": (PRICED, "Wasteland", "Tempest", 2, "MP"),
        "Charizard ex 006/165": (PRICED, "Charizard ex - 006/165", "151", 1, "NM"),
        "Pikachu 025/165": (PRICED, "Pikachu - 025/165", "151", 3, "NM"),
        "Dark Magician": (PRICED, "Dark Magician", "Starter Deck: Yugi", 1, "MP"),
        "Ash Blossom & Joyous Spring": (PRICED, "Ash Blossom & Joyous Spring", "Maximum Crisis", 3, "NM"),
        "Nami": (PRICED, "Nami", "Romance Dawn", 1, "NM"),
        # ST-01 has two Luffys (leader 001 and SR 012): no number, so manual check
        "Monkey.D.Luffy": (MANUAL, "Monkey.D.Luffy", None, 1, None),
        "Black Lotus": (PRICED, "Black Lotus", "Unlimited", 1, "LP"),
        "Mox Sapphire PSA 8": (MANUAL, "Mox Sapphire", None, 1, None),
        # Booster Tutor is from Unhinged; the list names the wrong set. Right answer:
        # the card, flagged (graded by outcome + name, not set).
        "Booster Tutor": (PRICED, "Booster Tutor", None, 1, "NM"),
        "Bloomburrow Collector Booster Box": (SEALED, "Bloomburrow - Collector Booster Display", None, 1, None),
        "Phantom Nightmare Booster Box": (SEALED, "Phantom Nightmare Booster Box [1st Edition]", None, 1, None),
        "Snapcaster Mage": (PRICED, "Snapcaster Mage", "Innistrad", 1, "LP"),
    },
    "C_messy_one_column.txt": {
        "Lightning Bolt 2X2 foil": (PRICED, "Lightning Bolt", "Double Masters 2022", 4, None),
        "Sheoldred the Apocalypse DMU foil NM": (PRICED, "Sheoldred, the Apocalypse", "Dominaria United", 1, "NM"),
        "counterspel - ice age - lp": (PRICED, "Counterspell", "Ice Age", 1, "LP"),
        "Brainstorm (Mercadian Masques) NM": (PRICED, "Brainstorm", "Mercadian Masques", 2, "NM"),
        "Snapcaster Mage ISD #78 LP": (PRICED, "Snapcaster Mage", "Innistrad", 1, "LP"),
        "Charizard ex 006/165 MEW NM": (PRICED, "Charizard ex - 006/165", "151", 1, "NM"),
        "pikachu 151 reverse holo": (PRICED, "Pikachu - 025/165", "151", 1, None),
        "Umbreon VMAX alt art Evolving Skies": (PRICED, "Umbreon VMAX (Alternate Art Secret)", "Evolving Skies", 1, None),
        "Blastoise base set unlimited holo LP": (PRICED, "Blastoise", "Base Set", 1, "LP"),
        "Dark Magician LOB-005 1st ed HP": (PRICED, "Dark Magician", "Legend of Blue Eyes", 1, "HP"),
        "Mirror Force MRD-138": (PRICED, "Mirror Force", "Metal Raiders", 1, None),
        "Ash Blossom RA01-EN008": (PRICED, "Ash Blossom & Joyous Spring", "Rarity Collection", 1, None),
        "Nami OP01-016 alt art": (PRICED, "Nami (Parallel)", "Romance Dawn", 1, None),
        "Shanks OP01-120 NM": (PRICED, "Shanks", "Romance Dawn", 1, "NM"),
        "Jinx Loose Cannon OGN 251/298": (PRICED, "Jinx, Loose Cannon", "Origins", 1, None),
        "Ragavan, Nimble Pilferer MH2 JPN": (MANUAL, "Ragavan, Nimble Pilferer", None, 1, None),
        "Black Lotus Unlimited PSA 7": (MANUAL, "Black Lotus", None, 1, None),
        "Pikachu": (MANUAL, "Pikachu", None, 3, None),
        "MH3 collector booster box sealed": (SEALED, "Modern Horizons 3 - Collector Booster Display", None, 1, None),
        "151 Booster Bundle": (SEALED, "151 Booster Bundle", None, 1, None),
    },
    "D_awful.csv": {
        "lightnig bolt beta": (PRICED, "Lightning Bolt", "Beta", 2, "NM"),
        "SHEOLDRED THE APOCALYPS dmu": (PRICED, "Sheoldred, the Apocalypse", "Dominaria United", 1, "LP"),
        "sol rng unlmited": (PRICED, "Sol Ring", None, 1, None),
        "Force of Wil alliances": (PRICED, "Force of Will", "Alliances", 1, "HP"),
        "Charizrd ex 006/165": (PRICED, "Charizard ex - 006/165", "151", 4, "NM"),
        "Pikachuu 173/165": (PRICED, "Pikachu - 173/165", "151", 1, None),
        "Dark Magican LOB-005": (PRICED, "Dark Magician", "Legend of Blue Eyes", 1, "MP"),
        "Nami OP01-016": (PRICED, "Nami", "Romance Dawn", 1, "NM"),
        "Blcak Ltous": (UNKNOWN, None, None, 1, None),
        "asdfgh": (UNKNOWN, None, None, 1, None),
        "Ash Blossom": (MANUAL, None, None, 2, None),              # real card, printing unknown
        "Charizard PSA 10": (MANUAL, None, None, 1, None),
        "jace the mind sculpter wwk": (PRICED, "Jace, the Mind Sculptor", "Worldwake", 1, None),
        "Evolving Skies Booster Box": (SEALED, "Evolving Skies Booster Box", None, 1, None),
        "Mox Diamondback": (UNKNOWN, None, None, 1, None),
        "Tarmagoyf FUT": (PRICED, "Tarmogoyf", "Future Sight", 1, "LP"),
        "Ragavan nimble pilferer": (PRICED, "Ragavan, Nimble Pilferer", None, 1, None),
        "Lotus of the Abyss": (UNKNOWN, None, None, 1, None),
        "Opt foil": (PRICED, "Opt", None, 3, None),
    },
}


def grade(engine, fname, key):
    out, _totals = engine.process_file(ROOT / "samples" / fname, "LP/MP", pricing.DEFAULT_BUY_TIERS,
                                       lambda s: None, lambda a, b: None, pricing.DEFAULT_SPECIAL_RULES, "magic")
    rows = {r["Input"]: r for r in out if r["Input"] not in ("", "TOTAL")}
    points = total = 0
    lines = []
    for text, (outcome, name, set_part, qty, cond) in key.items():
        r = rows.get(text)
        checks = []
        if r is None:
            checks.append(("row read", False, "row missing"))
        else:
            got = STATUS_OF[r["Status"]]
            checks.append(("outcome", got == outcome, f"{r['Status']}"))
            if name:
                checks.append(("card", r["Matched Name"] == name, r["Matched Name"] or "-"))
            elif outcome == UNKNOWN:
                checks.append(("no false match", not r["Matched Name"], r["Matched Name"] or "-"))
            if set_part and outcome == PRICED:
                checks.append(("set", set_part.lower() in r["Set"].lower(), r["Set"] or "-"))
            checks.append(("qty", str(r["Quantity"]) == str(qty), str(r["Quantity"])))
            if cond:
                checks.append(("condition", r["Condition Assumption"] == cond, r["Condition Assumption"] or "-"))
        ok = sum(c[1] for c in checks)
        points += ok
        total += len(checks)
        mark = "OK " if ok == len(checks) else "XX "
        fails = "; ".join(f"{c[0]}={c[2]}" for c in checks if not c[1])
        price = r["Price Used"] if r else ""
        lines.append(f"  {mark}{text[:40]:40} -> {(r or {}).get('Status', ''):14} {((r or {}).get('Matched Name') or '')[:38]:38} "
                     f"{((r or {}).get('Set') or '')[:26]:26} {price:>10}  {fails}")
    extra = [t for t in rows if t not in key]
    return points, total, lines, extra


def main():
    t = time.time()
    db = ScryfallDB(lambda s: None)
    db.build()
    engine = Engine(db, TCGCSV(lambda s: None), lambda s: None)
    print(f"(engine ready in {time.time() - t:.0f}s)\n")
    for fname, key in KEYS.items():
        points, total, lines, extra = grade(engine, fname, key)
        rows_ok = sum(1 for line in lines if line.startswith("  OK"))
        print(f"== {fname}: {rows_ok}/{len(key)} rows fully right, {points}/{total} checks ({100 * points / total:.0f}%)")
        print("\n".join(lines))
        if extra:
            print("  extra rows read:", extra)
        print()


if __name__ == "__main__":
    main()
