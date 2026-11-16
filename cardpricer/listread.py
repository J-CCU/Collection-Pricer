"""Reading collection lists into rows (name, quantity, condition, ...).

Handles every layout people send:
  * name only, one card per line;
  * everything in one column ("2x Charizard ex 006/165 Holo NM");
  * deck-list lines ("4 Lightning Bolt (LEB) 161 *F*", "Lightning Bolt x4");
  * structured files with headers, including ManaBox, Moxfield, Deckbox,
    TCGplayer app, Dragon Shield and Collectr exports;
  * files whose columns are shuffled or headed misleadingly.

Each column's role is decided once per file from its contents; header
words are only a hint. A numeric-only cell never becomes a card name.
"""

import csv
import io
import re
from pathlib import Path

from .clues import language_code
from .conditions import normalize_condition
from .text import _is_number_only, norm, split_leading_quantity

ROLES = ("name", "quantity", "condition", "finish", "set", "number", "language", "game", "grade",
         "product_id", "rarity", "price", "ignore")

# Header words per role. Checked longest first so "set code" wins over "set".
HEADER_ALIASES = {
    "name": {"name", "card", "card name", "card names", "title", "titles", "input", "card list", "cards",
             "cards list", "product name", "product", "item", "item name", "description"},
    "quantity": {"quantity", "quantities", "qty", "count", "counts", "amount", "number owned", "copies",
                 "have", "owned", "total"},
    "condition": {"condition", "card condition", "cond"},
    "finish": {"foil", "foil?", "finish", "finishes", "foil status", "printing", "variance", "variant",
               "treatment", "holo", "edition type"},
    "set": {"set", "set name", "edition", "expansion", "set code", "edition code", "series", "release"},
    "number": {"collector number", "collector no", "collector #", "number", "card number", "cn", "card #",
               "card no", "no.", "#", "card id", "code"},
    "language": {"language", "lang", "card language"},
    "game": {"game", "category", "tcg", "product line"},
    "grade": {"grade", "graded", "grading", "slab"},
    "product_id": {"product id", "tcgplayer id", "tcgplayer product id", "tcg product id", "productid"},
    "rarity": {"rarity"},
    "price": {"price", "market price", "purchase price", "price each", "price bought", "my price", "low",
              "mid", "market", "average cost paid", "cost", "value", "total value", "price override"},
    "ignore": {"tradelist count", "trade quantity", "tags", "notes", "date added", "date bought", "last modified",
               "folder name", "portfolio name", "manabox id", "scryfall id", "sku", "simple name", "signed",
               "altered", "altered art", "misprint", "proxy", "alter", "promo", "textless", "artist proof",
               "printing id", "printing note", "watchlist", "purchase price currency", "binder name",
               "binder type", "location"},
}
# Roles that may appear in more than one column (set name + set code).
MULTI_ROLES = {"set", "price", "ignore"}

FINISH_WORDS = {"foil", "f", "yes", "y", "true", "etched", "etched foil", "nonfoil", "non-foil", "normal",
                "no", "n", "false", "holo", "holofoil", "reverse holo", "reverse holofoil", "reverse",
                "1st edition", "1st edition holofoil", "1st edition normal", "unlimited", "unlimited holofoil",
                "limited", "regular", "standard"}
GAME_WORDS = {"magic", "mtg", "magic: the gathering", "magic the gathering", "pokemon", "pokémon",
              "yugioh", "yu-gi-oh", "yu-gi-oh!", "ygo", "one piece", "one piece card game", "optcg",
              "riftbound", "riftbound league of legends trading card game"}
NUMBER_RE = re.compile(
    r"^(?:#?\d{1,4}[a-z]?(?:/\d{1,4})?"                  # 161, 025/165, #25, 12a
    r"|[a-z]{1,4}\d{1,4}(?:/[a-z]{0,4}\d{1,4})?"         # TG05/TG30, SWSH050, GG35, SVP044
    r"|[a-z0-9]{2,5}-[a-z]{0,2}\d{2,4}[a-z]?)$",         # LOB-EN001, OP01-120, OGN-001
    re.I)
PRICE_RE = re.compile(r"^\$?\s*\d{1,6}(?:,\d{3})*\.\d{2}$")

# "4 Lightning Bolt (LEB) 161 *F*"  (Moxfield / Arena / MTGO deck lists)
DECK_LINE_RE = re.compile(
    r"^(?P<qty>\d{1,3})x?\s+(?P<name>.+?)\s+\((?P<set>[A-Za-z0-9]{2,6})\)\s+(?P<num>[A-Za-z0-9\-]+)"
    r"(?P<foil>\s+\*[FE]\*)?\s*$")
# "Lightning Bolt x4"
TRAILING_QTY_RE = re.compile(r"^(?P<name>.+?)\s+[xX]\s?(?P<qty>\d{1,3})$")


# ---------------------------------------------------------------- file input
def _read_table(path):
    """Return the file as a list of rows (lists of strings)."""
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        return [["" if v is None else str(v) for v in row] for row in ws.iter_rows(values_only=True)]
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    lines = [ln for ln in text.splitlines() if ln.strip()][:200]
    delimiter = None
    # The delimiter is the one most lines split into the same number of
    # fields with; title lines above a header may have none.
    best = 0
    for d in ("\t", ",", ";", "|"):
        counts = [len(next(csv.reader([ln], delimiter=d))) for ln in lines]
        multi = [c for c in counts if c >= 2]
        if not multi:
            continue
        mode = max(set(multi), key=multi.count)
        share = multi.count(mode) / len(lines)
        if share >= 0.5 and share > best:
            best, delimiter = share, d
    if delimiter is None:
        return [[line] for line in text.splitlines()]
    return list(csv.reader(io.StringIO(text), delimiter=delimiter))


def _header_role(cell):
    n = norm(cell).strip(" :")
    for role in ("product_id", "ignore", "number", "set", "finish", "quantity", "condition", "language",
                 "game", "grade", "rarity", "price", "name"):
        if n in HEADER_ALIASES[role]:
            return role
    return None


def _find_header(rows):
    """Index of the header row within the first 10 rows, or None."""
    for i, row in enumerate(rows[:10]):
        cells = [c for c in row if c.strip()]
        hits = [c for c in cells if _header_role(c)]
        if len(hits) >= 2 or (len(hits) == 1 and len(cells) == 1 and _header_role(hits[0]) == "name"):
            return i
    return None


# ------------------------------------------------------------ role scoring
def _share(values, test):
    return sum(1 for v in values if test(v)) / len(values) if values else 0.0


def _is_quantity(v):
    v = v.strip().lower().rstrip("x").lstrip("x")
    return v.isdigit() and 0 < int(v) <= 999 and not (len(v) > 1 and v.startswith("0"))


def _score_column(values, known_name, known_set):
    """Score how well a column's values fit each role (0..1+)."""
    vals = [v.strip() for v in values if v and v.strip()]
    if not vals:
        return {"ignore": 1.0}
    fill = len(vals) / len(values)
    distinct = len({v.lower() for v in vals})
    s = {}
    s["quantity"] = _share(vals, _is_quantity)
    ints = [int(v.strip().lower().strip("x")) for v in vals if _is_quantity(v)]
    if ints and sorted(ints)[len(ints) // 2] > 20:
        s["quantity"] *= 0.4  # big numbers are more likely collector numbers
    s["number"] = _share(vals, lambda v: bool(NUMBER_RE.match(v)) and not PRICE_RE.match(v))
    if s["number"] and any(re.search(r"[/\-]|^0\d|^[a-z]", v, re.I) for v in vals):
        s["number"] += 0.2
    s["price"] = _share(vals, lambda v: bool(PRICE_RE.match(v)))
    s["condition"] = _share(vals, lambda v: normalize_condition(v) is not None)
    s["finish"] = _share(vals, lambda v: norm(v) in FINISH_WORDS)
    s["language"] = _share(vals, lambda v: language_code(v) is not None and len(v) > 1)
    s["game"] = _share(vals, lambda v: norm(v) in GAME_WORDS)
    s["grade"] = _share(vals, lambda v: bool(re.match(r"^(?:psa|bgs|cgc|sgc|tag|beckett)\s*\d|^ungraded$|^raw$", v, re.I)))
    s["product_id"] = _share(vals, lambda v: v.isdigit() and len(v) >= 4) * 0.5
    alpha = _share(vals, lambda v: bool(re.search(r"[A-Za-z]{2}", v)) and not _is_number_only(v))
    avg_len = sum(len(v) for v in vals) / len(vals)
    s["set"] = _share(vals, known_set) if known_set else 0.0
    name_hits = _share(vals, known_name) if known_name else 0.0
    s["name"] = alpha * (0.5 + min(avg_len, 30) / 60) + name_hits
    # The name column is filled on (nearly) every row and varies: a mostly
    # empty "Foil?" column of the word "Foil" (also a card name) is not it.
    s["name"] *= fill
    if len(vals) >= 10 and distinct <= 3:
        s["name"] *= 0.3
    # A column of set names is not a name column even though it is text.
    if s["set"] > 0.6 and s["set"] > name_hits:
        s["name"] *= 0.3
    return s


def detect_roles(header, columns, known_name=None, known_set=None):
    """Assign one role to each column. Content decides; the header breaks ties
    and identifies roles content can't (price, ignore, product id)."""
    scores = []
    for idx, values in enumerate(columns):
        s = _score_column(values, known_name, known_set)
        hint = _header_role(header[idx]) if header and idx < len(header) else None
        if hint:
            s[hint] = s.get(hint, 0.0) + 0.45
        scores.append(s)

    roles = ["ignore"] * len(columns)
    taken = set()
    # Strongest fits first, so a clear quantity column can't be stolen by name.
    pairs = sorted(((sc, i, r) for i, s in enumerate(scores) for r, sc in s.items()), reverse=True)
    assigned = set()
    for sc, i, r in pairs:
        if i in assigned or sc < 0.5:
            continue
        if r in taken and r not in MULTI_ROLES:
            continue
        roles[i] = r
        assigned.add(i)
        taken.add(r)
    if "name" not in taken:
        # Fall back to the most text-like column that isn't numeric.
        best = max((i for i in range(len(columns)) if i not in assigned or roles[i] in MULTI_ROLES),
                   key=lambda i: scores[i].get("name", 0), default=None)
        if best is not None and scores[best].get("name", 0) > 0:
            roles[best] = "name"
    return roles


# --------------------------------------------------------------- one cell
def parse_list_line(text):
    """Pull structure out of a single free-text list line."""
    line = text.strip()
    m = DECK_LINE_RE.match(line)
    if m:
        return {"raw": m.group("name").strip(), "quantity": int(m.group("qty")), "set": m.group("set"),
                "collector": m.group("num"), "foil": "foil" if m.group("foil") else ""}
    m = TRAILING_QTY_RE.match(line)
    if m and not re.search(r"\b(?:psa|bgs|cgc|sgc)$", m.group("name"), re.I):
        return {"raw": m.group("name").strip(), "quantity": int(m.group("qty"))}
    name, qty = split_leading_quantity(line)
    return {"raw": name, "quantity": qty or 1}


def _quantity(value):
    v = (value or "").strip().lower().strip("x")
    try:
        return max(1, int(float(v)))
    except ValueError:
        return 1


def _blank_item(row_number):
    return {"condition": "", "foil": "", "set": "", "collector": "", "language": "", "game": "",
            "grade": "", "product_id": "", "rarity": "", "row_number": row_number}


def _free_text_items(lines, first_row_number):
    items = []
    for n, cell in enumerate(lines, start=first_row_number):
        if not cell or _is_number_only(cell):
            continue
        item = _blank_item(n)
        item.update(parse_list_line(cell))
        items.append(item)
    return items


# ------------------------------------------------------------------ public
def read_list(path, known_name=None, known_set=None):
    """Read a collection list. Returns (items, layout description).

    known_name / known_set are optional callables (text -> bool) used to
    recognize card-name and set-name columns by content.
    """
    rows = [[c.strip() for c in r] for r in _read_table(path)]
    rows = [r for r in rows if any(r)]
    if not rows:
        return [], "empty file"

    header_idx = _find_header(rows)
    header = rows[header_idx] if header_idx is not None else None
    body = rows[header_idx + 1:] if header_idx is not None else rows
    first_row_number = (header_idx + 2) if header_idx is not None else 1
    width = max(len(r) for r in body) if body else 0

    if width <= 1:
        return _free_text_items([r[0] if r else "" for r in body], first_row_number), \
            "one column: each line read as free text"

    columns = [[r[i] if i < len(r) else "" for r in body[:1000]] for i in range(width)]
    roles = detect_roles(header, columns, known_name, known_set)
    if "name" not in roles:
        return [], "no card-name column found"
    if header is None and set(roles) <= {"name", "ignore"}:
        # Nothing but text: commas inside names ("Ragavan, Nimble Pilferer")
        # split the lines, not real columns. Read each line whole.
        return _free_text_items([", ".join(c for c in r if c) for r in body], first_row_number), \
            "one column: each line read as free text"

    def col_label(i):
        letter = chr(ord("A") + i) if i < 26 else str(i + 1)
        return f"col {letter}" + (f" ({header[i]})" if header and i < len(header) and header[i] else "")

    layout = ", ".join(f"{r}={col_label(i)}" for i, r in enumerate(roles) if r not in ("ignore",))

    items = []
    for n, r in enumerate(body, start=first_row_number):
        get = {role: [] for role in ROLES}
        for i, role in enumerate(roles):
            if i < len(r) and r[i]:
                get[role].append(r[i])
        name = " ".join(get["name"]).strip()
        if not name or _is_number_only(name):
            continue
        if get["quantity"]:
            # A quantity column exists, so a leading number in the name
            # ("151 Booster Bundle") belongs to the name.
            item = {"raw": name, "quantity": _quantity(get["quantity"][0])}
        else:
            item = parse_list_line(name)
        finish = get["finish"][0] if get["finish"] else ""
        item.update({
            "condition": get["condition"][0] if get["condition"] else "",
            "foil": finish or item.get("foil", ""),
            "set": " | ".join(get["set"]) or item.get("set", ""),
            "collector": get["number"][0] if get["number"] else item.get("collector", ""),
            "language": get["language"][0] if get["language"] else "",
            "game": get["game"][0] if get["game"] else "",
            "grade": get["grade"][0] if get["grade"] else "",
            "product_id": get["product_id"][0] if get["product_id"] else "",
            "rarity": get["rarity"][0] if get["rarity"] else "",
            "row_number": n,
        })
        items.append(item)
    return items, layout


def extract_csv_rows(path, known_name=None, known_set=None):
    return read_list(path, known_name, known_set)[0]
