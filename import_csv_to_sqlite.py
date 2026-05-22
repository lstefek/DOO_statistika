#!/usr/bin/env python3
"""Import scitani-srovnani CSV do SQLite databáze."""

import csv
import sqlite3
import sys
from pathlib import Path

CSV_FILE = Path(__file__).parent / "scitani-srovnani-1999-2024-web.csv"
DB_FILE = Path(__file__).parent / "scitani.db"


def parse_float(value: str) -> float | None:
    if not value or value.strip() == "":
        return None
    return float(value.strip().replace(",", "."))


def parse_int(value: str) -> int | None:
    if not value or value.strip() == "":
        return None
    return int(value.strip())


def main() -> None:
    if DB_FILE.exists():
        DB_FILE.unlink()
        print(f"Odstraněna existující databáze: {DB_FILE}")

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE scitani (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            dekanat      TEXT    NOT NULL,
            farnost      TEXT    NOT NULL,
            rok          INTEGER NOT NULL,
            osob_celkem  INTEGER,
            prumerny_vek REAL,
            muz          INTEGER,
            zena         INTEGER,
            neuvedeno    INTEGER
        )
    """)

    cur.execute("""
        CREATE INDEX idx_dekanat_farnost ON scitani (dekanat, farnost)
    """)
    cur.execute("CREATE INDEX idx_rok ON scitani (rok)")

    rows_inserted = 0
    with open(CSV_FILE, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        next(reader)  # přeskočit hlavičku
        for line_no, row in enumerate(reader, start=2):
            if len(row) < 5:
                continue
            # sloupce: [seq_id, dekanat, farnost, rok, osob_celkem, prumerny_vek, muz, zena, neuvedeno, ...]
            dekanat = row[1].strip()
            farnost = row[2].strip()
            rok     = parse_int(row[3])
            osob    = parse_int(row[4])
            vek     = parse_float(row[5]) if len(row) > 5 else None
            muz     = parse_int(row[6])   if len(row) > 6 else None
            zena    = parse_int(row[7])   if len(row) > 7 else None
            neuvd   = parse_int(row[8])   if len(row) > 8 else None

            if not dekanat or not farnost or rok is None:
                print(f"  Přeskočen řádek {line_no}: {row}", file=sys.stderr)
                continue

            cur.execute(
                "INSERT INTO scitani (dekanat, farnost, rok, osob_celkem, prumerny_vek, muz, zena, neuvedeno) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (dekanat, farnost, rok, osob, vek, muz, zena, neuvd),
            )
            rows_inserted += 1

    conn.commit()
    conn.close()
    print(f"Hotovo: {rows_inserted} záznamů vloženo do {DB_FILE}")


if __name__ == "__main__":
    main()
