"""Pokémon, Yu-Gi-Oh!, One Piece, Riftbound, sealed and mixed-game cases.

Each case: (title, extra columns, expected status group, expected matched
name, expected set (substring) or None, expected finish or None).
Extra columns: {"Game": ..., "Condition": ..., "Printing": ..., "Set": ..., "Number": ...}
Expected answers were looked up in the TCGplayer catalog (TCGCSV).
"""

OK = {"GUARANTEED", "NEEDS CHECKING"}
MANUAL = {"MANUAL CHECK"}
UNKNOWN = {"UNKNOWN"}
SEALED = {"SEALED"}

POKEMON = [
    # number identifies the printing
    ("Charizard ex 006/165", {}, OK, "Charizard ex - 006/165", "151", "Holofoil"),
    ("Charizard ex - 199/165 SIR", {}, OK, "Charizard ex - 199/165", "151", None),
    ("Pikachu 173/165", {}, OK, "Pikachu - 173/165", "151", None),
    ("Pikachu 151 025/165", {}, OK, "Pikachu - 025/165", "151", "Normal"),
    ("Pikachu MEW 25 Reverse Holo", {}, OK, "Pikachu - 025/165", "151", "Reverse Holofoil"),
    ("3x Pikachu 025/165 NM", {}, OK, "Pikachu - 025/165", "151", "Normal"),
    ("Pikachu 025/165 Rev Holo LP", {}, OK, "Pikachu - 025/165", "151", "Reverse Holofoil"),
    ("Umbreon VMAX 215/203", {}, OK, "Umbreon VMAX (Alternate Art Secret)", "Evolving Skies", None),
    ("Umbreon VMAX Alt Art Evolving Skies", {}, OK, "Umbreon VMAX (Alternate Art Secret)", "Evolving Skies", None),
    ("Lugia V Alt Art 186/195", {}, OK, "Lugia V (Alternate Full Art)", "Silver Tempest", None),
    ("Charizard SM158", {}, OK, "Charizard - SM158", "SM Promos", None),
    ("Gengar TG06/TG30", {}, OK, "Gengar", "Lost Origin Trainer Gallery", None),
    # set identifies it
    ("Charizard Base Set", {}, OK, "Charizard", "Base Set", "Holofoil"),
    ("Charizard Base Set Holo 1st Edition", {}, OK, "Charizard", "Base Set (Shadowless)", "1st Edition Holofoil"),
    ("Blastoise Base Set Shadowless", {}, OK, "Blastoise", "Base Set (Shadowless)", None),
    # columns instead of title words
    ("Pikachu", {"Set": "SV: Scarlet & Violet 151", "Number": "025/165", "Printing": "Reverse Holofoil"},
     OK, "Pikachu - 025/165", "151", "Reverse Holofoil"),
    ("Charizard", {"Set": "Base Set", "Condition": "Heavily Played"}, OK, "Charizard", "Base Set", "Holofoil"),
    # typos
    ("Charizrd ex 006/165", {}, OK, "Charizard ex - 006/165", "151", None),
    ("Pikachuu 173/165", {}, OK, "Pikachu - 173/165", "151", None),
    # name only -> manual check (can't tell the printing without the card)
    ("Pikachu", {}, MANUAL, "Pikachu", None, None),
    ("Charizard", {}, MANUAL, "Charizard", None, None),
    ("Radiant Charizard", {}, MANUAL, "Radiant Charizard", None, None),
    ("Mew ex 151", {}, MANUAL, "Mew ex", None, None),
    ("Eevee", {}, MANUAL, "Eevee", None, None),
    # graded / foreign -> manual check
    ("Charizard ex 006/165 PSA 10", {}, MANUAL, "Charizard ex - 006/165", "151", None),
    ("Charizard Base Set CGC 9.5", {}, MANUAL, "Charizard", "Base Set", None),
    ("Pikachu 025/165 Japanese", {}, MANUAL, "Pikachu - 025/165", None, None),
    ("Pikachu 173/165", {"Condition": "NM", "Game": "Pokemon"}, OK, "Pikachu - 173/165", "151", None),
    # not real
    ("Flurbleglorp ex", {"Game": "Pokemon"}, UNKNOWN, None, None, None),
    ("Pkchu Mgxzt 999", {"Game": "Pokemon"}, UNKNOWN, None, None, None),
]

YUGIOH = [
    ("Dark Magician LOB-005", {}, OK, "Dark Magician", "The Legend of Blue Eyes White Dragon", "Unlimited"),
    ("Dark Magician LOB-005 1st Edition", {}, OK, "Dark Magician", "The Legend of Blue Eyes White Dragon", "1st Edition"),
    # LOB-EN005 is both the Worldwide English print and the 25th Anniversary reprint
    ("Dark Magician LOB-EN005", {}, MANUAL, "Dark Magician", None, None),
    ("Dark Magician LOB-EN005 Legend of Blue Eyes White Dragon (Worldwide English)", {}, OK, "Dark Magician",
     "Worldwide English", "Unlimited"),
    ("Pot of Greed LOB-119 Unlimited", {}, OK, "Pot of Greed", "The Legend of Blue Eyes White Dragon", "Unlimited"),
    ("Mirror Force MRD-138 1st Ed", {}, OK, "Mirror Force", "Metal Raiders", "1st Edition"),
    ("Ash Blossom RA01-EN008", {}, OK, "Ash Blossom & Joyous Spring", "25th Anniversary Rarity Collection", None),
    ("Ash Blossom & Joyous Spring RA01-EN008 Secret Rare", {}, OK, "Ash Blossom & Joyous Spring (Secret Rare)",
     "25th Anniversary Rarity Collection", None),
    ("Ash Blossom & Joyous Spring MAGO-EN011 Alt Art", {}, OK, "Ash Blossom & Joyous Spring (Alternate Art)",
     "Maximum Gold", None),
    ("Pot of Greed DPKB-EN029", {}, OK, "Pot of Greed (UTR)", "Duelist Pack: Kaiba", None),
    ("Mirror Force DL15-EN018 Blue", {}, OK, "Mirror Force (Blue)", "Duelist League", None),
    ("Dark Magician", {"Set": "Starter Deck: Yugi", "Printing": "1st Edition"}, OK, "Dark Magician",
     "Starter Deck: Yugi", "1st Edition"),
    ("Dark Magican LOB-005", {}, OK, "Dark Magician", "The Legend of Blue Eyes White Dragon", None),
    ("Ash Blossom & Joyous Spring", {}, MANUAL, "Ash Blossom & Joyous Spring", None, None),
    ("Mirror Force DL15-EN018", {}, MANUAL, "Mirror Force", None, None),
    ("Dark Magician LOB-005 PSA 9", {}, MANUAL, "Dark Magician", None, None),
    ("Dark Magician SDY-006 German", {}, MANUAL, "Dark Magician", None, None),
    ("Super Ultra Dragon of Doom", {"Game": "Yu-Gi-Oh"}, UNKNOWN, None, None, None),
]

ONEPIECE = [
    ("Nami OP01-016", {}, OK, "Nami", "Romance Dawn", None),
    ("Shanks OP01-120", {}, OK, "Shanks", "Romance Dawn", None),
    ("Nami OP01-016 Alt Art", {}, OK, "Nami (Parallel)", "Romance Dawn", None),
    ("Roronoa Zoro OP01-001", {}, OK, "Roronoa Zoro (001)", "Romance Dawn", None),
    ("Monkey D Luffy ST01-001", {}, OK, "Monkey.D.Luffy (001)", "Starter Deck 1", None),
    ("Shanks", {}, MANUAL, "Shanks", None, None),
    ("Nami OP01-016 PSA 10", {}, MANUAL, "Nami", None, None),
    ("Captain Nonexistent OP99-999", {"Game": "One Piece"}, UNKNOWN, None, None, None),
]

RIFTBOUND = [
    ("Jinx, Loose Cannon 251/298", {}, OK, "Jinx, Loose Cannon", "Origins", "Foil"),
    ("Jinx, Loose Cannon Overnumbered", {}, OK, "Jinx, Loose Cannon (Overnumbered)", "Origins", None),
    ("Ahri, Alluring 066/298", {}, OK, "Ahri, Alluring", "Origins", None),
    ("Ahri, Alluring Alt Art", {}, OK, "Ahri, Alluring (Alternate Art)", "Origins", None),
    ("Jinx, Loose Cannon", {}, MANUAL, "Jinx, Loose Cannon", None, None),
    ("Calm Rune", {}, MANUAL, "Calm Rune", None, None),
]

SEALED_CASES = [
    ("Delta Reign Elite Trainer Box", {}, SEALED, "Delta Reign Elite Trainer Box", None, None),
    ("151 Booster Bundle", {}, SEALED, "151 Booster Bundle", None, None),
    ("Evolving Skies Booster Box", {}, SEALED, "Evolving Skies Booster Box", None, None),
    ("Surging Sparks Booster Box Case", {}, SEALED, "Surging Sparks Booster Box Case", None, None),
    ("Delta Reign Booster Pack", {}, SEALED, "Delta Reign Booster Pack", None, None),
    ("Modern Horizons 3 Collector Booster Box", {}, SEALED, "Modern Horizons 3 - Collector Booster Display", None, None),
    ("MH3 Play Booster Box", {}, SEALED, "Modern Horizons 3 - Play Booster Display", None, None),
    ("Duskmourn Bundle", {}, SEALED, "Duskmourn: House of Horror - Bundle", None, None),
    ("Bloomburrow Collector Booster Box", {}, SEALED, "Bloomburrow - Collector Booster Display", None, None),
    ("Phantom Nightmare Booster Box", {}, SEALED, "Phantom Nightmare Booster Box [1st Edition]", None, None),
    ("Romance Dawn Booster Box Wave 1", {}, SEALED, "Romance Dawn - Booster Box (Wave 1 - Blue)", None, None),
    ("Origins Booster Display", {}, SEALED, "Origins - Booster Display", None, None),
    ("Evolving Skies ETB", {}, MANUAL, None, None, None),         # several different ETBs
    ("Ice Age Theme Deck Sealed", {}, MANUAL, None, None, None),  # not on TCGplayer
    ("Alpha Booster Box sealed", {}, MANUAL, None, None, None),   # no TCGplayer price
    ("Booster Box of Nothing Real", {}, MANUAL, None, None, None),
    # card names that only look like sealed product
    ("Pack Rat", {}, OK, "Pack Rat", None, None),
    ("Booster Tutor", {}, OK, "Booster Tutor", None, None),
]

MIXED = [
    # one list, five games; no Game column
    ("Lightning Bolt (LEB)", {}, OK, "Lightning Bolt", None, None),
    ("Charizard ex 006/165", {}, OK, "Charizard ex - 006/165", None, None),
    ("Dark Magician LOB-005", {}, OK, "Dark Magician", None, None),
    ("Nami OP01-016", {}, OK, "Nami", None, None),
    ("Jinx, Loose Cannon 251/298", {}, OK, "Jinx, Loose Cannon", None, None),
    ("Sol Ring Unlimited", {}, OK, "Sol Ring", None, None),
    # game column overrides detection
    ("Dark Magician", {"Game": "Yu-Gi-Oh!", "Set": "Starter Deck: Yugi"}, OK, "Dark Magician", "Starter Deck: Yugi", None),
]
