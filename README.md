# Collection Pricer

A desktop app (Tkinter) that prices messy card lists for buying collections.
It identifies each line, looks up a TCGplayer price, and works out a buy
offer from your condition and buy-percentage tables.

## Supported games

- Magic: The Gathering (cards identified with Scryfall bulk data)
- Pokémon
- Yu-Gi-Oh!
- One Piece
- Riftbound
- Sealed product for all of the above

A list can mix games. The game for each row comes from a Game column, game
words in the title, a game-specific card number (for example `LOB-EN001`,
`OP01-120`), or which game's catalog knows the name. When a name exists in
several games or none, the **Default game** setting decides.

## Supported list formats

Files: `.csv`, `.tsv`, `.txt`, `.xlsx`.

Layouts the reader handles:

- Name only, one card per line
- Everything in one column, e.g. `2x Charizard ex 006/165 Holo NM`
- Deck-list lines, e.g. `4 Lightning Bolt (LEB) 161 *F*` or `Lightning Bolt x4`
- Structured files with headers, including ManaBox, Moxfield, Deckbox,
  TCGplayer app, Dragon Shield and Collectr exports
- Files with no header, a header that is not on row 1, or shuffled or
  misleadingly named columns (each column's role is decided from its
  contents; header words are only a hint)

Conditions can come from a condition column or the title, in TCGplayer,
Card Kingdom, Cardmarket or older US grading terms. They are all mapped to
NM / LP / MP / HP / DMG. Rows with no condition use the **Condition
assumption** setting (default `LP/MP`, the average of LP and MP).

## Running

### Prebuilt app

- Windows: `CardPricer.exe`
- Mac: unzip `CardPricer-mac.zip` to get `CardPricer.app`

The apps are not signed. On Windows, at "Windows protected your PC" click
**More info**, then **Run anyway**. On a Mac, right-click the app, choose
**Open**, then **Open** again. If macOS says the app "is damaged", run
`xattr -cr /path/to/CardPricer.app` once.

### From source

Needs Python 3 with Tkinter, plus:

```
pip install requests openpyxl
```

Then, from the repo folder:

```
py run_pricer.py          # Windows
python3 run_pricer.py     # Mac / Linux
```

### One-file script

`card_pricer.py` is the whole package in one file, for sharing a single
script. It has the same requirements and is run the same way:

```
py card_pricer.py
```

It is generated from `cardpricer/`; do not edit it by hand.

### Using the app

1. **1. Load Card Data** loads Scryfall and TCGplayer data. The first run
   downloads it: about 400 MB from Scryfall and about 15 minutes of TCGCSV
   requests for all games. Later loads use the local cache.
2. **2. Select List** prices a list. Two files are written next to it:
   `<name>_PRICED_<YYYYMMDD_HHMMSS>.xlsx` (filter on every column, frozen
   header, rows colored by status, prices stored as numbers) and a `.csv`
   with the same rows. A TOTAL row at the end gives the priced count and
   total extended value.

**Update TCGplayer Prices** refreshes prices from TCGCSV, which updates once a
day. A full update takes about 15 minutes; an interrupted update resumes where
it stopped.

## Pricing

Settings are edited in the **Pricing assumptions** panel and saved to
`pricer_settings.json` in the data folder (see below). **Reset Defaults**
restores the values below. The defaults are defined in
`cardpricer/pricing.py`.

**Step 1 - Condition value.** NM price x condition % = condition value.

| Row | NM | LP | MP | HP | DMG |
|---|---|---|---|---|---|
| All cards | 100 | 85 | 70 | 50 | 25 |
| Alpha/Beta/Unlimited | 100 | 80 | 60 | 40 | 20 |
| Foil / etched | 100 | 75 | 50 | 30 | 15 |

Alpha/Beta/Unlimited and foil or etched Magic cards use their row or All
cards, whichever is lower. A blank condition counts as 100%; a range such as
LP/MP uses the average of the two.

**Step 2 - Buy %.** The price range the condition value falls in sets the
Buy %. Offer = condition value x Buy %.

| Min | Max | Buy % |
|---|---|---|
| $0 | $25 | 50 |
| $25 | $100 | 55 |
| $100 | $500 | 60 |
| $500 | $1,000 | 65 |
| $1,000 | (none) | 70 |

Example: a $100 NM card in MP is worth 70% = $70, which falls in the
$25-$100 range, so the offer is 55% of $70 = $38.50.

**Sealed product** has no condition step: market price x the Buy % of its
range.

| Min | Max | Buy % |
|---|---|---|
| $0 | $50 | 55 |
| $50 | $200 | 65 |
| $200 | (none) | 70 |

Ranges must not overlap; leave Max blank for no upper limit. Older saved
settings files are upgraded automatically, keeping the values you entered.

## Status column

Output rows are sorted by status:

| Status | Color | Meaning |
|---|---|---|
| GUARANTEED | green | exact match, priced |
| NEEDS CHECKING | yellow | priced, but with an assumption, a fuzzy match or a typo fix; see Review Flag |
| SEALED | blue | sealed product, priced |
| MANUAL CHECK | orange | graded, foreign-language, a printing that cannot be pinned down (for example a non-Magic card with no set or number), or sealed product that cannot be matched or priced |
| UNPRICED | grey | matched, but no price found |
| UNKNOWN | red | no match |

Other useful columns: Match Type, Confidence, Review Flag, Condition Source,
Market Price, Condition Value, Buy %, Price Used, Price Source, Price Notes,
Extended Value, and TCGplayer / Scryfall / image links.

## Data sources

- **Scryfall** (`api.scryfall.com`): the All Cards bulk file, used to
  identify Magic cards. Scryfall's USD prices are a fallback when TCGCSV has
  no price for a printing.
- **TCGCSV** (`tcgcsv.com`): a daily mirror of TCGplayer's catalog and prices
  for all five games. The TCGplayer market price is used; when there is no
  market price, the low price is used and the row is flagged.

### Cache location

Card data, indexes and settings are kept outside the app, so rebuilding or
updating the app keeps them:

| OS | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\MTGCollectionBuyer` |
| macOS | `~/Library/Application Support/MTGCollectionBuyer` |
| Linux | `$XDG_DATA_HOME/MTGCollectionBuyer` (default `~/.local/share/MTGCollectionBuyer`) |

TCGCSV data is in its `tcgcsv` subfolder. The folder name is shared with the
legacy MTGCollectionBuyer app.

## Tests

```
py tests/run_tests.py [section ...]
```

Sections: `layouts`, `filegame`, `magic`, `pokemon`, `yugioh`, `onepiece`,
`riftbound`, `sealed`, `mixed` (default: all). The tests use the cached data
from **Load Card Data**; TCGCSV-backed sections skip games that have not been
synced. Fixtures are in `tests/fixtures/`.

`py samples/grade_samples.py` prices the lists in `samples/` and grades the
results against a built-in answer key.

## Building the .exe and .app

Both builds use PyInstaller with `CardPricer.spec`. PyInstaller cannot
cross-build, so each must be built on its own system.

| Platform | Command | Output |
|---|---|---|
| Windows | `build_windows.bat` | `dist\CardPricer.exe` (one file, no console) |
| Mac | `./build_mac.sh` (needs Python 3.10+ from python.org) | `dist/CardPricer.app` and `dist/CardPricer-mac.zip` |

`build_mac.sh` builds for the Mac's own chip (Apple Silicon or Intel) in a
`.venv-build` virtual environment. Set `PYTHON` to use a different
interpreter.

### GitHub Actions

`.github/workflows/build.yml` builds on GitHub's machines with Python 3.12.
It runs when started from **Actions > build > Run workflow**, or when a tag
matching `v*` (for example `v3.0.0`) is pushed. Download the results from the
run's Artifacts:

- `CardPricer-windows` (`CardPricer.exe`)
- `CardPricer-mac-arm64` (Apple Silicon `CardPricer-mac.zip`)
- `CardPricer-mac-intel` (Intel `CardPricer-mac.zip`)

## Repository files

| Path | What it is |
|---|---|
| `cardpricer/` | The application package. **Source of truth**; make changes here. |
| `cardpricer/app.py` | Window and settings screen |
| `cardpricer/engine.py` | Per-row matching, pricing and status |
| `cardpricer/listread.py` | Reads and interprets list files |
| `cardpricer/pricing.py` | Pricing rules and default tables |
| `cardpricer/conditions.py` | Condition vocabulary |
| `cardpricer/report.py` | CSV and Excel output |
| `cardpricer/paths.py` | Data folder location |
| `cardpricer/games/` | Magic (Scryfall), other games (TCGplayer) and sealed matchers |
| `cardpricer/sources/tcgcsv.py` | TCGCSV download and cache |
| `run_pricer.py` | Starts the app; PyInstaller entry point |
| `tests/` | Regression tests and fixture lists |
| `samples/` | Sample lists, their priced output, and `grade_samples.py` |
| `CardPricer.spec`, `build_mac.sh`, `build_windows.bat` | Build scripts |
| `.github/workflows/build.yml` | GitHub Actions build |
| `CardPricer.exe`, `CardPricer-mac.zip` | Prebuilt current app |
| `card_pricer.py` | **Generated.** One-file build of `cardpricer/` made by `make_single_file.py`. Do not edit; regenerate after changing the package. |
| `collection_pricer.py` | **Legacy.** The older Magic-only "MTG Collection Buyer" pricer (Scryfall only). Superseded by `cardpricer/`. |
| `MTGCollectionBuyer`, `MTGCollectionBuyer.app.zip` | **Legacy.** Prebuilt binaries of `collection_pricer.py`. |
