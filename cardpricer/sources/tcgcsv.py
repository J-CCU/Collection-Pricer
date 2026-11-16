"""TCGplayer catalog and prices from TCGCSV (tcgcsv.com), cached locally.

TCGCSV mirrors TCGplayer's catalog once a day. Its usage guidelines: sync at
most once a day, check last-updated.txt first, send a custom User-Agent, and
pause between requests. A sync downloads every set ("group") of the chosen
games; product lists are only re-fetched for groups whose modifiedOn changed,
prices are re-fetched every sync. An interrupted sync resumes where it
stopped.
"""

import gzip
import json
import pickle
import re
import time

import requests

from ..paths import DATA_DIR
from ..text import norm

BASE_URL = "https://tcgcsv.com"
TCGCSV_UA = {"User-Agent": "MTGCollectionBuyer/3.0 (collection pricing; daily sync)"}
REQUEST_DELAY = 0.15
TCGCSV_DIR = DATA_DIR / "tcgcsv"
INDEX_VERSION = 1

GAMES = {
    "magic": {"category": 1, "label": "Magic: The Gathering"},
    "pokemon": {"category": 3, "label": "Pokémon"},
    "yugioh": {"category": 2, "label": "Yu-Gi-Oh!"},
    "onepiece": {"category": 68, "label": "One Piece"},
    "riftbound": {"category": 89, "label": "Riftbound"},
}


def _get_json(session, url):
    time.sleep(REQUEST_DELAY)
    r = session.get(url, headers=TCGCSV_UA, timeout=60)
    if r.status_code == 404:
        return {"results": []}  # TCGplayer returns 404 for empty groups
    r.raise_for_status()
    return r.json()


def choose_price(price_row):
    """Return (price, basis) for one TCGCSV price row.

    Market price first. Very expensive cards often have no market price
    (Alpha Black Lotus); then the lowest listing is used and marked so the
    row can be flagged for review.
    """
    if not price_row:
        return None, ""
    if price_row.get("marketPrice") is not None:
        return float(price_row["marketPrice"]), "TCGplayer Market"
    if price_row.get("lowPrice") is not None:
        return float(price_row["lowPrice"]), "TCGplayer Low (no market price)"
    return None, ""


class Catalog:
    """One game's products with prices, plus lookup indexes."""

    def __init__(self, game, products, groups):
        self.game = game
        self.products = products          # productId -> product dict
        self.groups = groups              # groupId -> group dict
        self.by_name = {}                 # norm(base name) -> [product]
        self.by_number = {}               # norm(number) -> [product]
        for p in products.values():
            self.by_name.setdefault(norm(p["base_name"]), []).append(p)
            if p["number"]:
                self.by_number.setdefault(norm(p["number"]), []).append(p)

    def get(self, product_id):
        return self.products.get(int(product_id)) if product_id else None


def _ext(product, key):
    for e in product.get("extendedData") or []:
        if e.get("name") == key:
            return (e.get("value") or "").strip()
    return ""


def base_product_name(name):
    """Card name without the trailing number TCGplayer adds to some games
    ("Pikachu - 173/165" -> "Pikachu")."""
    return re.sub(r"\s+-\s+[A-Za-z0-9]*\d[A-Za-z0-9/\-]*\s*$", "", name or "").strip()


def build_catalog(game, raw):
    """Turn cached raw TCGCSV JSON into a Catalog."""
    groups = {g["groupId"]: g for g in raw["groups"]}
    prices = {}
    for gid, rows in raw["prices"].items():
        for row in rows:
            prices.setdefault(row["productId"], {})[row.get("subTypeName") or "Normal"] = row
    products = {}
    for gid, rows in raw["products"].items():
        group = groups.get(int(gid), {})
        for p in rows:
            number = _ext(p, "Number")
            rarity = _ext(p, "Rarity")
            products[p["productId"]] = {
                "id": p["productId"],
                "game": game,
                "name": p.get("name", ""),
                "base_name": base_product_name(p.get("name", "")),
                "clean_name": p.get("cleanName", ""),
                "group_id": int(gid),
                "group_name": group.get("name", ""),
                "group_abbr": group.get("abbreviation") or "",
                "released": (group.get("publishedOn") or "")[:10],
                "number": number,
                "rarity": rarity,
                # Sealed product has neither a card number nor a rarity.
                "sealed": not number and not rarity,
                "url": p.get("url", ""),
                "image": p.get("imageUrl", ""),
                "ext": {e.get("name"): (e.get("value") or "") for e in p.get("extendedData") or []
                        if e.get("name") in ("Number", "Rarity", "Card Type", "Attribute", "Color", "Monster Type",
                                             "SubType", "Description")},
                "prices": prices.get(p["productId"], {}),
            }
    return Catalog(game, products, groups)


class TCGCSV:
    def __init__(self, log, session=None):
        self.log = log
        self.session = session or requests.Session()
        TCGCSV_DIR.mkdir(parents=True, exist_ok=True)
        self.catalogs = {}

    # ---- sync -----------------------------------------------------------
    def remote_stamp(self):
        time.sleep(REQUEST_DELAY)
        r = self.session.get(f"{BASE_URL}/last-updated.txt", headers=TCGCSV_UA, timeout=30)
        r.raise_for_status()
        return r.text.strip()

    def _raw_path(self, game):
        return TCGCSV_DIR / f"{game}.json.gz"

    def _load_raw(self, game):
        path = self._raw_path(game)
        if not path.exists():
            return None
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _save_raw(self, game, raw):
        tmp = self._raw_path(game).with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(raw, f)
        tmp.replace(self._raw_path(game))

    def sync(self, games, progress=None):
        """Download the chosen games if TCGCSV has newer data. Returns True
        if anything changed."""
        stamp = self.remote_stamp()
        changed = False
        for game in games:
            category = GAMES[game]["category"]
            raw = self._load_raw(game) or {}
            if raw.get("stamp") == stamp and raw.get("complete"):
                self.log(f"TCGCSV {GAMES[game]['label']}: already current ({stamp}).")
                continue
            self.log(f"TCGCSV {GAMES[game]['label']}: syncing data from {stamp}...")
            groups = _get_json(self.session, f"{BASE_URL}/tcgplayer/{category}/groups")["results"]
            old_groups = {g["groupId"]: g for g in raw.get("groups", [])}
            products = raw.get("products", {})
            prices = raw.get("prices", {}) if raw.get("stamp") == stamp else {}
            done_prices = set(raw.get("done_prices", [])) if raw.get("stamp") == stamp else set()
            raw = {"stamp": stamp, "complete": False, "groups": groups, "products": products,
                   "prices": prices, "done_prices": sorted(done_prices)}
            for i, g in enumerate(groups, 1):
                gid = str(g["groupId"])
                old = old_groups.get(g["groupId"])
                if gid not in products or not old or old.get("modifiedOn") != g.get("modifiedOn"):
                    products[gid] = _get_json(self.session, f"{BASE_URL}/tcgplayer/{category}/{gid}/products")["results"]
                if gid not in done_prices:
                    prices[gid] = _get_json(self.session, f"{BASE_URL}/tcgplayer/{category}/{gid}/prices")["results"]
                    done_prices.add(gid)
                if i % 25 == 0 or i == len(groups):
                    raw["done_prices"] = sorted(done_prices)
                    self._save_raw(game, raw)  # checkpoint so an interrupted sync resumes
                    self.log(f"  {i}/{len(groups)} sets")
                if progress:
                    progress(i, len(groups))
            live = {str(g["groupId"]) for g in groups}
            raw["products"] = {k: v for k, v in products.items() if k in live}
            raw["prices"] = {k: v for k, v in prices.items() if k in live}
            raw["complete"] = True
            self._save_raw(game, raw)
            self._index_path(game).unlink(missing_ok=True)
            self.catalogs.pop(game, None)
            changed = True
        return changed

    # ---- catalogs -------------------------------------------------------
    def _index_path(self, game):
        return TCGCSV_DIR / f"{game}_index.pkl"

    def has_data(self, game):
        raw = self._load_raw(game)
        return bool(raw and raw.get("complete"))

    def catalog(self, game):
        """Load (or build and cache) one game's Catalog; None if not synced."""
        if game in self.catalogs:
            return self.catalogs[game]
        path = self._index_path(game)
        if path.exists():
            try:
                data = pickle.loads(path.read_bytes())
                if data.get("version") == INDEX_VERSION:
                    cat = Catalog(game, data["products"], data["groups"])
                    self.catalogs[game] = cat
                    return cat
            except Exception:
                pass
        raw = self._load_raw(game)
        if not raw or not raw.get("complete"):
            return None
        cat = build_catalog(game, raw)
        path.write_bytes(pickle.dumps({"version": INDEX_VERSION, "products": cat.products, "groups": cat.groups},
                                      pickle.HIGHEST_PROTOCOL))
        self.catalogs[game] = cat
        self.log(f"TCGCSV {GAMES[game]['label']}: {len(cat.products):,} products indexed.")
        return cat
