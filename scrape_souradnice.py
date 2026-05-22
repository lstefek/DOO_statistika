#!/usr/bin/env python3
"""Stáhne GPS souřadnice farností z doo.cz a uloží do tabulky farnosti_souradnice."""

import re
import sqlite3
import time
import urllib.request
from pathlib import Path

DB_FILE  = Path(__file__).parent / "scitani.db"
BASE_URL = "https://doo.cz/katalog/farnosti/"
DELAY    = 0.3


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")


def main() -> None:
    conn = sqlite3.connect(DB_FILE)
    cur  = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS farnosti_souradnice")
    cur.execute("""
        CREATE TABLE farnosti_souradnice (
            farnost TEXT PRIMARY KEY,
            guid    TEXT,
            lat     REAL,
            lon     REAL
        )
    """)
    conn.commit()

    # Načti seznam farností z knezi (guid + farnost)
    parishes = cur.execute(
        "SELECT DISTINCT farnost, guid FROM knezi WHERE guid IS NOT NULL"
    ).fetchall()
    print(f"Farností k zpracování: {len(parishes)}")

    ok = 0
    for i, (farnost, guid) in enumerate(parishes, 1):
        url  = f"{BASE_URL}?guid={guid}"
        try:
            html = fetch(url)
            m = re.search(r'query=([\d.]+),([\d.]+)', html)
            if m:
                lat, lon = float(m.group(1)), float(m.group(2))
                cur.execute(
                    "INSERT OR REPLACE INTO farnosti_souradnice VALUES (?,?,?,?)",
                    (farnost, guid, lat, lon)
                )
                ok += 1
                if i % 50 == 0:
                    conn.commit()
                    print(f"  [{i}/{len(parishes)}] {farnost}: {lat}, {lon}")
            else:
                cur.execute(
                    "INSERT OR REPLACE INTO farnosti_souradnice VALUES (?,?,NULL,NULL)",
                    (farnost, guid)
                )
        except Exception as e:
            print(f"  CHYBA [{i}] {farnost}: {e}")

        time.sleep(DELAY)

    conn.commit()
    conn.close()
    print(f"\nHotovo: {ok}/{len(parishes)} farností se souřadnicemi.")


if __name__ == "__main__":
    main()
