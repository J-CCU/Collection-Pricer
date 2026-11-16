"""Tk settings screen and main window.

Long jobs (loading the card databases, syncing TCGplayer prices, pricing a
list) run on a worker thread; the window stays responsive and receives log
lines and progress through a queue.
"""

import json
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from .conditions import CONDITION_ORDER
from .engine import OUTPUT_COLUMNS, Engine
from .games.magic import ScryfallDB
from .paths import SETTINGS
from .pricing import (DEFAULT_BUY_TIERS, DEFAULT_SEALED_TIERS, DEFAULT_SPECIAL_RULES, SETTINGS_VERSION,
                      SPECIAL_RULE_LABELS, migrate_settings, normalize_buy_tiers, normalize_special_rules)
from .report import write_csv, write_xlsx
from .sources.tcgcsv import GAMES, TCGCSV

GAME_CHOICES = [(key, GAMES[key]["label"]) for key in ("magic", "pokemon", "yugioh", "onepiece", "riftbound")]


class TierTable:
    """Editable Min / Max / Buy % rows."""

    def __init__(self, parent, tiers):
        self.frame = ttk.Frame(parent)
        for col, text in enumerate(("Min price", "Max price", "Buy %")):
            ttk.Label(self.frame, text=text).grid(row=0, column=col, sticky="w", padx=(0, 8), pady=(0, 2))
        self.rows = []
        self._next_row = 1
        for tier in tiers:
            self.add(*tier[:3])

    def add(self, low="", high="", pct=""):
        r = self._next_row
        self._next_row += 1
        low_var = tk.StringVar(value="" if low is None else str(low))
        high_var = tk.StringVar(value="" if high is None else str(high))
        pct_var = tk.StringVar(value="" if pct is None else str(pct))
        widgets = [ttk.Entry(self.frame, textvariable=low_var, width=10),
                   ttk.Entry(self.frame, textvariable=high_var, width=10),
                   ttk.Entry(self.frame, textvariable=pct_var, width=8)]
        for col, w in enumerate(widgets):
            w.grid(row=r, column=col, sticky="w", padx=(0, 8), pady=1)
        row = (widgets, low_var, high_var, pct_var)
        remove = ttk.Button(self.frame, text="Remove", command=lambda: self.remove(row))
        remove.grid(row=r, column=len(widgets), sticky="w", pady=1)
        widgets.append(remove)
        self.rows.append(row)

    def remove(self, row):
        self.rows = [x for x in self.rows if x is not row]
        for w in row[0]:
            w.destroy()

    def reset(self, tiers):
        for row in list(self.rows):
            self.remove(row)
        for tier in tiers:
            self.add(*tier[:3])

    def values(self):
        return [[v.get().strip() for v in row[1:]] for row in self.rows]

    def tiers(self, label):
        """Validated tiers, or ValueError naming the table."""
        raw = [tuple(v) for v in self.values() if any(v)]
        clean = normalize_buy_tiers(raw)
        if len(clean) != len(raw):
            raise ValueError(f"{label}: every range needs a valid Min price, Buy %, and a Max above Min (or blank).")
        if not clean:
            raise ValueError(f"{label}: at least one price range is required.")
        for a, b in zip(clean, clean[1:]):
            if a[1] is None or a[1] > b[0]:
                raise ValueError(f"{label}: price ranges overlap. Make each range non-overlapping.")
        return clean


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Collection Pricer — Magic, Pokémon, Yu-Gi-Oh!, One Piece, Riftbound")
        self.geometry("1320x900")
        self.minsize(1000, 650)
        self.resizable(True, True)
        self.db = None
        self.tcgcsv = None
        self.engine = None
        self.busy = False
        self.events = queue.Queue()
        self.make_ui()
        self.after(100, self._drain_events)

    # ------------------------------------------------------------------ UI
    def make_ui(self):
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Collection Pricer", font=("TkDefaultFont", 18, "bold")).pack(anchor="w")

        opts = ttk.LabelFrame(frame, text="Pricing assumptions", padding=10)
        opts.pack(fill="x")
        settings = self.load_settings()

        top = ttk.Frame(opts)
        top.grid(row=0, column=0, sticky="w")
        ttk.Label(top, text="Condition assumption:").pack(side="left")
        self.condition = tk.StringVar(value=settings.get("condition") or "LP/MP")
        ttk.Combobox(top, textvariable=self.condition, values=["LP/MP", "NM", "LP", "MP", "HP", "DMG"],
                     state="readonly", width=8).pack(side="left", padx=(8, 4))
        ttk.Label(top, text="for rows with no condition (LP/MP averages LP and MP).").pack(side="left", padx=(0, 24))
        ttk.Label(top, text="Default game:").pack(side="left")
        labels = [label for _k, label in GAME_CHOICES]
        saved_game = dict(GAME_CHOICES).get(settings.get("default_game", "magic"), labels[0])
        self.default_game = tk.StringVar(value=saved_game)
        ttk.Combobox(top, textvariable=self.default_game, values=labels, state="readonly", width=20).pack(
            side="left", padx=(8, 4))
        ttk.Label(top, text="used when a name exists in several games or none.").pack(side="left")

        steps = ttk.Frame(opts)
        steps.grid(row=1, column=0, sticky="w", pady=(10, 0))

        step1 = ttk.LabelFrame(steps, text="Step 1 - Condition value (% of NM price)", padding=8)
        step1.grid(row=0, column=0, sticky="nw")
        for col, cond in enumerate(CONDITION_ORDER, start=1):
            ttk.Label(step1, text=cond).grid(row=0, column=col, sticky="w", padx=(0, 8))
        saved_special = settings.get("special_rules") or {}
        self.special_vars = {}
        for r, (key, label) in enumerate(SPECIAL_RULE_LABELS.items(), start=1):
            ttk.Label(step1, text=label).grid(row=r, column=0, sticky="w", padx=(0, 12), pady=1)
            values = saved_special.get(key) or DEFAULT_SPECIAL_RULES[key]
            self.special_vars[key] = {}
            for col, cond in enumerate(CONDITION_ORDER, start=1):
                var = tk.StringVar(value=str(values.get(cond, "")))
                ttk.Entry(step1, textvariable=var, width=6).grid(row=r, column=col, sticky="w", padx=(0, 8), pady=1)
                self.special_vars[key][cond] = var
        ttk.Label(step1, text="Alpha/Beta/Unlimited and foil Magic cards use\ntheir row or All cards, whichever is lower.").grid(
            row=len(SPECIAL_RULE_LABELS) + 1, column=0, columnspan=len(CONDITION_ORDER) + 1, sticky="w", pady=(4, 0))

        ttk.Label(steps, text="→", font=("TkDefaultFont", 18)).grid(row=0, column=1, padx=10)

        step2 = ttk.LabelFrame(steps, text="Step 2 - Buy % (by condition value)", padding=8)
        step2.grid(row=0, column=2, sticky="nw")
        self.card_tiers = TierTable(step2, settings.get("tiers") or DEFAULT_BUY_TIERS)
        self.card_tiers.frame.pack(anchor="w")
        ttk.Button(step2, text="+ Add Price Range", command=lambda: self.card_tiers.add()).pack(anchor="w", pady=(6, 0))

        step3 = ttk.LabelFrame(steps, text="Sealed product - Buy % (no condition step)", padding=8)
        step3.grid(row=0, column=3, sticky="nw", padx=(24, 0))
        self.sealed_tiers = TierTable(step3, settings.get("sealed_tiers") or DEFAULT_SEALED_TIERS)
        self.sealed_tiers.frame.pack(anchor="w")
        ttk.Button(step3, text="+ Add Price Range", command=lambda: self.sealed_tiers.add()).pack(anchor="w", pady=(6, 0))

        reset_row = ttk.Frame(opts)
        reset_row.grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Button(reset_row, text="Reset Defaults", command=self.reset_defaults).pack(side="left")
        ttk.Label(reset_row, text="Example: $100 NM card in MP -> 70% = $70 condition value -> $70's Buy % applies. "
                                  "Leave Max blank for no upper limit. Settings are remembered between runs.").pack(
            side="left", padx=8)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=12)
        self.load_btn = ttk.Button(buttons, text="1. Load Card Data", command=self.load_data)
        self.load_btn.pack(side="left")
        self.file_btn = ttk.Button(buttons, text="2. Select List", command=self.select_file, state="disabled")
        self.file_btn.pack(side="left", padx=10)
        self.sync_btn = ttk.Button(buttons, text="Update TCGplayer Prices", command=self.update_prices)
        self.sync_btn.pack(side="left", padx=(30, 0))
        ttk.Label(buttons, text="TCGCSV refreshes once a day; a full update takes about 15 minutes.").pack(
            side="left", padx=8)

        self.progress_bar = ttk.Progressbar(frame, orient="horizontal", length=960, mode="determinate")
        self.progress_bar.pack(pady=(0, 10))
        self.status = ttk.Label(frame, text="Waiting. Click 1. Load Card Data to start.")
        self.status.pack(anchor="w")
        self.log_box = tk.Text(frame, height=30, width=120, state="disabled")
        self.log_box.pack(fill="both", expand=True, pady=(8, 0))

    # ------------------------------------------------------------ settings
    def load_settings(self):
        """Saved settings, upgraded to the current format; user values kept."""
        try:
            settings = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
        except Exception:
            return {}
        return migrate_settings(settings)

    def save_settings(self):
        try:
            SETTINGS.write_text(json.dumps({
                "version": SETTINGS_VERSION,
                "condition": self.condition.get(),
                "default_game": self.game_key(),
                "special_rules": {k: {c: v.get().strip() for c, v in conds.items()}
                                  for k, conds in self.special_vars.items()},
                "tiers": self.card_tiers.values(),
                "sealed_tiers": self.sealed_tiers.values(),
            }, indent=2), encoding="utf-8")
        except Exception as e:
            self.log(f"Could not save settings: {e}")

    def reset_defaults(self):
        self.card_tiers.reset(DEFAULT_BUY_TIERS)
        self.sealed_tiers.reset(DEFAULT_SEALED_TIERS)
        for key, conds in self.special_vars.items():
            for cond, var in conds.items():
                var.set(str(DEFAULT_SPECIAL_RULES[key].get(cond, "")))

    def game_key(self):
        return {label: key for key, label in GAME_CHOICES}.get(self.default_game.get(), "magic")

    def get_special_rules(self):
        raw = {k: {c: v.get().strip() for c, v in conds.items()} for k, conds in self.special_vars.items()}
        for key, conds in raw.items():
            for cond, value in conds.items():
                try:
                    if value and float(value) < 0:
                        raise ValueError
                except ValueError:
                    raise ValueError(f"{SPECIAL_RULE_LABELS[key]} {cond} value '{value}' must be a non-negative number or blank.")
        return normalize_special_rules(raw)

    # ------------------------------------------------- thread-safe updates
    def log(self, msg):
        self.events.put(("log", msg))

    def update_progress(self, value, total):
        self.events.put(("progress", (value, total)))

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.log_box.config(state="normal")
                    self.log_box.insert("end", payload + "\n")
                    self.log_box.see("end")
                    self.log_box.config(state="disabled")
                elif kind == "progress":
                    value, total = payload
                    self.progress_bar["maximum"] = max(1, total)
                    self.progress_bar["value"] = value
                    self.status.config(text=f"Working… {value:,} / {total:,}")
                elif kind == "status":
                    self.status.config(text=payload)
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def run_in_background(self, label, work, done=None):
        """Run work() on a worker thread; done(result) runs on the UI thread."""
        if self.busy:
            messagebox.showinfo("Busy", "Please wait for the current job to finish.")
            return
        self.busy = True
        for b in (self.load_btn, self.file_btn, self.sync_btn):
            b.config(state="disabled")
        self.events.put(("status", label))

        def runner():
            try:
                result, error = work(), None
            except Exception as e:  # reported on the UI thread
                result, error = None, e

            def finish():
                self.busy = False
                self.load_btn.config(state="normal")
                self.sync_btn.config(state="normal")
                self.file_btn.config(state="normal" if self.engine else "disabled")
                if error is not None:
                    self.log(f"ERROR: {error}")
                    self.status.config(text="Stopped with an error; see the log.")
                    messagebox.showerror("Error", str(error))
                elif done:
                    done(result)
            self.events.put(("call", finish))

        threading.Thread(target=runner, daemon=True).start()

    # ---------------------------------------------------------------- jobs
    def load_data(self):
        def work():
            db = ScryfallDB(self.log)
            db.ensure_bulk()
            db.build()
            tcg = TCGCSV(self.log)
            missing = [g for g in GAMES if not tcg.has_data(g)]
            if missing:
                self.log("TCGplayer data missing for: " + ", ".join(GAMES[g]["label"] for g in missing)
                         + ". Downloading now (one time, about 15 minutes for all games)...")
                tcg.sync(missing, self.update_progress)
            self.log("Indexing TCGplayer catalogs...")
            engine = Engine(db, tcg, self.log)
            return db, tcg, engine

        def done(result):
            self.db, self.tcgcsv, self.engine = result
            self.file_btn.config(state="normal")
            self.log("========================================")
            self.log("Card data ready: " + ", ".join(GAMES[g]["label"] for g in self.engine.games))
            self.status.config(text="Ready. Click 2. Select List.")

        self.run_in_background("Loading card data…", work, done)

    def update_prices(self):
        def work():
            tcg = self.tcgcsv or TCGCSV(self.log)
            changed = tcg.sync(list(GAMES), self.update_progress)
            engine = Engine(self.db, tcg, self.log) if (self.db and (changed or not self.engine)) else self.engine
            return tcg, engine, changed

        def done(result):
            self.tcgcsv, self.engine, changed = result
            self.log("TCGplayer prices updated." if changed else "TCGplayer prices were already current.")
            self.status.config(text="Ready." if self.engine else "Prices updated. Click 1. Load Card Data.")

        self.run_in_background("Updating TCGplayer prices…", work, done)

    def select_file(self):
        path = filedialog.askopenfilename(
            title="Select a card list",
            filetypes=[("Card lists", "*.csv *.tsv *.txt *.xlsx"), ("All files", "*.*")])
        if path:
            self.process(path)

    def process(self, path):
        if not self.engine:
            messagebox.showerror("Card data not loaded", "Click 1. Load Card Data first.")
            return
        try:
            buy_tiers = self.card_tiers.tiers("Step 2")
            sealed_tiers = self.sealed_tiers.tiers("Sealed product")
            special_rules = self.get_special_rules()
        except ValueError as e:
            messagebox.showerror("Invalid settings", str(e))
            return
        if buy_tiers[0][0] > 0:
            self.log("WARNING: No buy percentage is defined below $" + f"{buy_tiers[0][0]:,.2f}")
        self.save_settings()
        condition, default_game = self.condition.get(), self.game_key()

        def work():
            self.db.self_test()
            rows, totals = self.engine.process_file(path, condition, buy_tiers, self.log, self.update_progress,
                                                    special_rules, default_game, sealed_tiers)
            base = f"{os.path.splitext(path)[0]}_PRICED_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            write_csv(rows, OUTPUT_COLUMNS, base + ".csv")
            write_xlsx(rows, OUTPUT_COLUMNS, base + ".xlsx")
            return base + ".xlsx", totals

        def done(result):
            out, totals = result
            self.log("\n========================================")
            self.log("PROCESSING COMPLETE")
            self.log("========================================")
            self.log(f"Input rows:       {totals['input']}")
            self.log(f"Exact matches:    {totals['exact']}")
            self.log(f"Other matches:    {totals['other']}")
            self.log(f"Needs review:     {totals['review']}")
            self.log(f"No match:         {totals['nomatch']}")
            self.log(f"Graded:           {totals['graded']}")
            self.log(f"With price:       {totals['with_price']}")
            self.log(f"Extended value:   ${totals['value']:,.2f}")
            self.log(f"Output: {out}  (filterable, sorted by status; same rows in the .csv beside it)")
            self.status.config(text="Done.")
            messagebox.showinfo("Complete", f"Finished.\n\nOutput:\n{out}\n\nRows: {totals['input']}\n"
                                            f"Priced: {totals['with_price']}\nReview flagged: {totals['review']}\n"
                                            f"No match: {totals['nomatch']}")

        self.run_in_background("Pricing list…", work, done)
