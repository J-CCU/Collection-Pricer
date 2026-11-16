"""Buy pricing: condition value first, then the buy % range."""

from .conditions import CONDITION_ORDER

SPECIAL_RULE_LABELS = {"all": "All cards", "abu": "Alpha/Beta/Unlimited", "foil": "Foil / etched"}

DEFAULT_SPECIAL_RULES = {
    "all": {"NM": 100, "LP": 85, "MP": 70, "HP": 50, "DMG": 25},
    "abu": {"NM": 100, "LP": 80, "MP": 60, "HP": 40, "DMG": 20},
    "foil": {"NM": 100, "LP": 75, "MP": 50, "HP": 30, "DMG": 15},
}

def condition_value_percent(condition_pcts, condition, special_ratios=()):
    """What a copy in this condition is worth, as a % of the NM price.

    A blank condition cell counts as 100%. A range such as LP/MP uses the
    average of its two ends. Each special ratio set (old set, foil) caps the
    value; the lowest wins.
    """
    parts = [p for p in (condition or "").split("/") if p in CONDITION_ORDER]
    if not parts:
        return 100.0

    def rate(cond):
        value = condition_pcts.get(cond) if condition_pcts.get(cond) is not None else 100.0
        for ratios in special_ratios:
            if ratios.get(cond) is not None:
                value = min(value, ratios[cond])
        return value

    vals = [rate(p) for p in parts]
    return sum(vals) / len(vals)

def normalize_special_rules(rules):
    """Parse {"abu": {"LP": "80", ...}, ...}; blank or invalid cells are skipped."""
    clean = {}
    for key in SPECIAL_RULE_LABELS:
        ratios = {}
        for cond, value in ((rules or {}).get(key) or {}).items():
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if cond in CONDITION_ORDER and value >= 0:
                ratios[cond] = value
        if ratios:
            clean[key] = ratios
    return clean

def normalize_buy_tiers(tiers):
    """Normalize editable price bands.

    Each tier is (low, high, percent) or (low, high, percent, condition_pcts),
    where condition_pcts maps NM/LP/MP/HP/DMG to the % of NM value a copy in
    that condition is worth (blank = 100%). high=None means no upper limit.
    Percentages are written as 50 for 50%.
    """
    clean = []
    for tier in tiers:
        low, high, pct = tier[:3]
        raw_conds = tier[3] if len(tier) > 3 else {}
        try:
            low = float(low)
            high = None if high in (None, "", "inf", "infinity") else float(high)
            pct = float(pct)
        except Exception:
            continue
        if low < 0 or (high is not None and high <= low) or pct < 0:
            continue
        cond_pcts = {}
        for cond in CONDITION_ORDER:
            value = (raw_conds or {}).get(cond)
            if value in (None, ""):
                continue
            try:
                value = float(value)
            except Exception:
                continue
            if value >= 0:
                cond_pcts[cond] = value
        clean.append((low, high, pct, cond_pcts))
    clean.sort(key=lambda x: x[0])
    return clean

def tier_for_price(price, tiers):
    """Return the (low, high, buy %, condition %) tier containing price."""
    if price is None:
        return None
    for tier in normalize_buy_tiers(tiers):
        low, high = tier[0], tier[1]
        if price >= low and (high is None or price < high):
            return tier
    return None

def price_offer(nm_price, tiers, condition=None, special_ratios=(), condition_pcts=None):
    """Condition first, then the buy % range.

    1. NM price x condition % (NM 100, MP 70, ...) = condition value.
    2. The condition value's range sets the Buy %.
    E.g. $100 NM in MP at 70% -> $70 -> the $25-100 range's 55% -> $38.50.
    condition_pcts is the flat "All cards" row; without it, the condition
    columns of the NM price's range are used. Returns (condition %,
    condition value, buy %, offer); None parts when no range covers a price.
    """
    if nm_price is None:
        return None, None, None, None
    if condition_pcts is None:
        nm_tier = tier_for_price(nm_price, tiers)
        if nm_tier is None:
            return None, None, None, None
        condition_pcts = nm_tier[3]
    cond_pct = condition_value_percent(condition_pcts, condition, special_ratios)
    value = nm_price * cond_pct / 100.0
    value_tier = tier_for_price(value, tiers)
    if value_tier is None:
        return cond_pct, value, None, None
    return cond_pct, value, value_tier[2], value * value_tier[2] / 100.0

# What a played copy is worth relative to NM, by NM price. LP/MP/HP follow
# Card Kingdom's published buylist schedule (EX/VG/G as a share of the NM
# buy price: <$25 80/70/50, $25-99.99 85/75/65, $100+ 90/80/70). Card
# Kingdom rejects below-Good cards, so DMG is set at roughly half of HP.
CONDITION_MARKET_RATIOS = [
    (0, {"NM": 1.00, "LP": 0.80, "MP": 0.70, "HP": 0.50, "DMG": 0.25}),
    (25, {"NM": 1.00, "LP": 0.85, "MP": 0.75, "HP": 0.65, "DMG": 0.30}),
    (100, {"NM": 1.00, "LP": 0.90, "MP": 0.80, "HP": 0.70, "DMG": 0.35}),
]

def market_condition_pcts(low):
    """Default condition values (% of NM) for a tier starting at NM price low."""
    try:
        low = float(low or 0)
    except (TypeError, ValueError):
        return {}
    ratios = [r for threshold, r in CONDITION_MARKET_RATIOS if low >= threshold][-1]
    return {c: f"{round(100 * ratios[c], 1):g}" for c in CONDITION_ORDER}

DEFAULT_BUY_TIERS = [(0, 25, 50), (25, 100, 55), (100, 500, 60), (500, 1000, 65), (1000, None, 70)]
# Sealed product has no condition step: market price x the range's Buy %.
DEFAULT_SEALED_TIERS = [(0, 50, 55), (50, 200, 65), (200, None, 70)]

# 3: per-range condition columns held % of NM value instead of a final buy %.
# 4: one flat "All cards" condition row; price ranges hold only Buy %.
SETTINGS_VERSION = 4

def migrate_settings(settings):
    """Bring saved settings up to version 4, keeping what the user entered."""
    version = settings.get("version", 1)
    tiers = settings.get("tiers") or []
    if version >= SETTINGS_VERSION or not tiers:
        return settings
    tiers = migrate_tier_conditions(tiers, version)
    rules = dict(settings.get("special_rules") or {})
    if "all" not in rules:
        # The lowest range holds most cards; its condition values become the
        # flat row unless they were never changed from the old defaults.
        first = tiers[0]
        conds = first[3] if len(first) > 3 else {}
        defaults = market_condition_pcts(first[0])
        changed = any(str(conds.get(c, "")).strip() != defaults.get(c) for c in CONDITION_ORDER)
        rules["all"] = ({c: conds.get(c, "") for c in CONDITION_ORDER} if changed
                        else dict(DEFAULT_SPECIAL_RULES["all"]))
    settings["special_rules"] = rules
    settings["tiers"] = [list(t[:3]) for t in tiers]
    settings["version"] = SETTINGS_VERSION
    return settings

def migrate_tier_conditions(tiers, version):
    """Bring saved price ranges up to the condition-value format.

    Never-filled condition cells get market defaults. Cells the user filled
    in under version 1-2 were final buy %s; they are converted to the same
    share of that range's NM rate, so the user's relative discounts survive.
    """
    out = []
    for t in tiers:
        if len(t) < 3:
            continue
        conds = dict(t[3]) if len(t) > 3 and t[3] else {}
        if version < 3:
            if not any(str(v).strip() for v in conds.values()):
                conds = market_condition_pcts(t[0])
            else:
                try:
                    nm = float(conds.get("NM") or t[2])
                except (TypeError, ValueError):
                    nm = 0
                conds = {c: (f"{round(float(v) / nm * 100, 1):g}" if str(v).strip() and nm else "")
                         for c, v in conds.items()}
        out.append(list(t[:3]) + [conds])
    return out
