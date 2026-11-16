"""Write priced rows as CSV and as a filterable, color-coded Excel sheet."""

import csv

from .text import money

# Status -> fill color, top of the sheet to bottom.
STATUS_FILLS = {
    "GUARANTEED": "C6EFCE",      # green
    "NEEDS CHECKING": "FFEB9C",  # yellow
    "SEALED": "DDEBF7",          # blue
    "MANUAL CHECK": "F8CBAD",    # orange
    "UNPRICED": "E7E6E6",        # grey
    "UNKNOWN": "FFC7CE",         # red
}
MONEY_COLUMNS = {"Market Price", "Condition Value", "Price Used", "Extended Value"}
WIDTHS = {"Status": 15, "Game": 12, "Input": 40, "Matched Name": 36, "Set": 30, "Review Flag": 50,
          "Price Notes": 60, "TCGplayer URL": 30, "Scryfall URL": 30, "Image URL": 30}


def write_csv(rows, columns, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def write_xlsx(rows, columns, path):
    """Same rows as the CSV, with a filter on every column, the header frozen,
    one color per status and prices stored as numbers so they sort."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Priced"
    ws.append(columns)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        values = []
        for col in columns:
            v = row.get(col, "")
            if col in MONEY_COLUMNS and v and money(v) is not None:
                v = money(v)
            elif col == "Quantity" and str(v).isdigit():
                v = int(v)
            values.append(v)
        ws.append(values)
        fill = STATUS_FILLS.get(row.get("Status", ""))
        if fill:
            for cell in ws[ws.max_row]:
                cell.fill = PatternFill("solid", fgColor=fill)
        if row.get("Status") == "TOTAL":
            for cell in ws[ws.max_row]:
                cell.font = Font(bold=True)
    for i, col in enumerate(columns, 1):
        letter = get_column_letter(i)
        ws.column_dimensions[letter].width = WIDTHS.get(col, max(10, min(18, len(col) + 2)))
        if col in MONEY_COLUMNS:
            for cell in ws[letter][1:]:
                cell.number_format = '"$"#,##0.00'
    last_data_row = 1 + sum(1 for r in rows if r.get("Status") not in ("", "TOTAL"))
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(2, last_data_row)}"
    ws.freeze_panes = "A2"
    wb.save(path)
