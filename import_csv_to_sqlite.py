#!/usr/bin/env python3
"""
Import scitani-srovnani CSV do SQLite databáze.

Místo mazání celé DB se pouze přepíše tabulka `scitani` — zachovají se tedy
ostatní tabulky (knezi, farnosti_souradnice, dieceze_statistiky, predikce_*).

Po importu se aplikují manuální korekce dat (CORRIGENDA) — viz statistika.md.
"""

import csv
import sqlite3
import sys
from pathlib import Path

CSV_FILE = Path(__file__).parent / "scitani-srovnani-1999-2024-web.csv"
DB_FILE  = Path(__file__).parent / "scitani.db"

# Manuální korekce v datech (osob_celkem, muz, zena se opraví proporčně).
# Pole: (farnost, rok, osob_celkem_nový, poznámka)
CORRIGENDA: list[tuple[str, int, int, str]] = [
    ("Lubina", 2014, 210, "Outlier — hodnota 238 neodpovídá trendu, opraveno na 210; "
                          "muz/zena přeškálovány proporčně (97/113)."),
]


def parse_float(value: str) -> float | None:
    if not value or value.strip() == "":
        return None
    return float(value.strip().replace(",", "."))


def parse_int(value: str) -> int | None:
    if not value or value.strip() == "":
        return None
    return int(value.strip())


def apply_corrigenda(cur: sqlite3.Cursor) -> None:
    """Aplikuje korekce z CORRIGENDA na čerstvě naimportovanou tabulku scitani."""
    for farnost, rok, target, poznamka in CORRIGENDA:
        row = cur.execute(
            "SELECT osob_celkem, muz, zena FROM scitani WHERE farnost=? AND rok=?",
            (farnost, rok),
        ).fetchone()
        if not row:
            print(f"  ⚠ corrigenda: {farnost} {rok} — řádek nenalezen, přeskočeno", file=sys.stderr)
            continue
        osob_old, muz_old, zena_old = row
        if osob_old == target:
            continue  # už opraveno
        suma_pohlavi = (muz_old or 0) + (zena_old or 0)
        if suma_pohlavi > 0 and muz_old is not None and zena_old is not None:
            ratio = target / suma_pohlavi
            muz_new  = round(muz_old  * ratio)
            zena_new = round(zena_old * ratio)
            # Doladit zaokrouhlovací chybu, aby muz+zena = target
            if muz_new + zena_new != target:
                zena_new = target - muz_new
            cur.execute(
                "UPDATE scitani SET osob_celkem=?, muz=?, zena=? WHERE farnost=? AND rok=?",
                (target, muz_new, zena_new, farnost, rok),
            )
            print(f"  ✓ corrigenda: {farnost} {rok}: osob_celkem {osob_old}→{target}, "
                  f"muz {muz_old}→{muz_new}, zena {zena_old}→{zena_new}")
        else:
            cur.execute(
                "UPDATE scitani SET osob_celkem=? WHERE farnost=? AND rok=?",
                (target, farnost, rok),
            )
            print(f"  ✓ corrigenda: {farnost} {rok}: osob_celkem {osob_old}→{target}")


def main() -> None:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    # Jen scitani — zachovej ostatní tabulky (knezi, souradnice, ...)
    cur.execute("DROP TABLE IF EXISTS scitani")
    cur.execute("DROP INDEX IF EXISTS idx_dekanat_farnost")
    cur.execute("DROP INDEX IF EXISTS idx_rok")

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
    cur.execute("CREATE INDEX idx_dekanat_farnost ON scitani (dekanat, farnost)")
    cur.execute("CREATE INDEX idx_rok ON scitani (rok)")

    rows_inserted = 0
    with open(CSV_FILE, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        next(reader)  # přeskočit hlavičku
        for line_no, row in enumerate(reader, start=2):
            if len(row) < 5:
                continue
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

    print(f"Vloženo {rows_inserted} záznamů.")
    print("\nAplikuji corrigenda:")
    apply_corrigenda(cur)

    conn.commit()
    conn.close()
    print(f"\nHotovo: data v {DB_FILE}")


if __name__ == "__main__":
    main()
