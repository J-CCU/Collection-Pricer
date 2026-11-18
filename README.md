# Collection Pricer

A desktop app (Tkinter) for stores and buyers pricing trading card
collections. Give it a messy card list; it identifies each line, looks up a
TCGplayer price, works out a buy offer from your condition and buy-percentage
tables, and writes a color-coded Excel sheet and a CSV.

## Quick start

A prebuilt Mac app is included: `CardPricer-mac.zip` (Apple Silicon Macs only;
built 2026-11-18). No Windows `.exe` is included yet; build one from source (see
[Building the .exe and .app](#building-the-exe-and-app)) or run
`card_pricer.py` with Python.

1. On an Apple Silicon Mac, download `CardPricer-mac.zip`, double-click it, and
   open `CardPricer.app`. The first time, right-click it > Open > Open (it is
   not signed by Apple). Otherwise run `card_pricer.py` from source (see
   [Running](#running)) or build an app (see
   [Building the .exe and .app](#building-the-exe-and-app)).
2. Click **1. Load Card Data**. The first time this downloads about 400 MB
   from Scryfall and takes about 15 minutes for TCGplayer data.
3. Click **2. Select List** and pick a `.csv`, `.tsv`, `.txt` or `.xlsx` list.
4. Open `<list name>_PRICED_<date>_<time>.xlsx`, written next to your list.

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

Files: `.csv`, `.tsv`, `.txt`, `.xlsx` (only the first worksheet is read).

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

### Built app

Build `CardPricer.exe` (Windows) or `CardPricer.app` (Mac) yourself; see
[Building the .exe and .app](#building-the-exe-and-app). A Mac build runs
on the chip it was built on (Apple Silicon or Intel).

The apps are not signed. On Windows, at "Windows protected your PC" click
**More info**, then **Run anyway**. On a Mac, right-click the app, choose
**Open**, then **Open** again. If macOS says the app "is damaged", run
`xattr -cr /path/to/CardPricer.app` once.

### From source

Needs Python 3 with Tkinter (3.10 or newer from python.org is recommended;
on a Mac, the Apple-supplied `/usr/bin/python3` has a Tk that is too old),
plus:

```
pip install requests openpyxl
```

Then, from the repo folder:

```
py card_pricer.py          # Windows
python3 card_pricer.py     # Mac / Linux
```

`card_pricer.py` is the whole app in one file; make changes there.

### Using the app

1. **1. Load Card Data** loads Scryfall and TCGplayer data. The first run
   downloads it: about 400 MB from Scryfall and about 15 minutes of TCGCSV
   requests for all games. Later loads reuse the local TCGplayer data, but
   every load asks Scryfall whether its card list has changed and downloads
   the full ~400 MB again when it has. Scryfall publishes a new list about
   once a day, so the first load each day usually includes this download.
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
the `cardpricer/pricing.py` section of `card_pricer.py`.

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

TCGCSV data is in its `tcgcsv` subfolder. The folder name comes from the older
MTGCollectionBuyer app this one replaced.

## Troubleshooting

| Message / symptom | Fix |
|---|---|
| "Card data not loaded" | Click **1. Load Card Data** and wait for "Ready. Click 2. Select List." |
| "Busy" | Wait for the current job to finish; progress is shown in the log. |
| "price ranges overlap" | Make each range's Min at least the previous range's Max. Only the last range may have a blank Max. |
| "every range needs a valid Min price, Buy %, and a Max above Min" | Fill in Min and Buy % with numbers, and a Max greater than Min (or blank), or remove the row. |
| "WARNING: No buy percentage is defined below $..." in the log | The first range does not start at $0, so cheaper cards get no offer. |
| "Stopped with an error; see the log." during loading | Usually a network problem reaching Scryfall or TCGCSV. Check the connection and click the button again; a TCGCSV download resumes where it stopped. |
| Prices look a day old | Click **Update TCGplayer Prices**; TCGCSV itself only updates once a day. |
| `ModuleNotFoundError: requests` or `openpyxl` | Run `pip install requests openpyxl` for the Python you start the app with. |
| Many rows are MANUAL CHECK or UNKNOWN | Add set names or card numbers to the list, or a Game column for mixed lists. Check the Review Flag column for the reason. |

To start over with fresh card data, close the app and delete the data folder
(see [Cache location](#cache-location)); this also resets your pricing
settings.

## Building the .exe and .app

PyInstaller cannot cross-build: build the `.exe` on Windows and the `.app` on
a Mac, each with Python 3.10+ from python.org. Card data and settings are never
put inside the app (they stay in the data folder above), so rebuilding keeps
them. In a terminal, in the folder with `card_pricer.py`:

Windows:

```
py -m venv build-env
build-env\Scripts\python -m pip install pyinstaller requests openpyxl
build-env\Scripts\python -m PyInstaller --noconfirm --onefile --windowed --name CardPricer --hidden-import openpyxl card_pricer.py
```

Mac:

```
python3 -m venv build-env
build-env/bin/python -m pip install pyinstaller requests openpyxl
build-env/bin/python -m PyInstaller --noconfirm --windowed --name CardPricer --hidden-import openpyxl card_pricer.py
ditto -c -k --keepParent dist/CardPricer.app dist/CardPricer-mac.zip
```

The result is `dist\CardPricer.exe` or `dist/CardPricer.app` (plus a `.zip`
to send to another Mac). A Mac app only runs on Macs with the same chip type
(Apple Silicon or Intel). Afterwards you can delete `build-env`, `build` and
`CardPricer.spec`.

## Repository files

| Path | What it is |
|---|---|
| `card_pricer.py` | The whole app: window, list reading, matching, pricing, reports. |
| `CardPricer-mac.zip` | Prebuilt Mac app (Apple Silicon), built from `card_pricer.py` on 2026-11-18. Rebuild it after changing the script. |
| `README.md` | This document. |
