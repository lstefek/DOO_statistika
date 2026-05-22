#!/usr/bin/env python3
"""Stáhne seznam kněží z doo.cz/katalog/farnosti/ a uloží do SQLite."""

import re
import sqlite3
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BASE_URL = "https://doo.cz"
LIST_URL = f"{BASE_URL}/katalog/farnosti/"
DB_FILE = Path(__file__).parent / "scitani.db"
DELAY = 0.3  # sekundy mezi požadavky


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")


def get_parish_list(html: str) -> list[tuple[str, str]]:
    """Vrátí seznam (guid, nazev) pro všechny farnosti."""
    return re.findall(
        r'href="/katalog/farnosti/\?guid=([^"]+)">\s*<strong>([^<]+)</strong>',
        html,
    )


def get_osoby(html: str) -> list[tuple[str, str]]:
    """Z HTML stránky farnosti vytáhne seznam (role, jmeno)."""
    # Najdi sekci "Osoby ve farnosti"
    m = re.search(r'class="wrapp farnost osoby">(.*?)</div>\s*\n\s*\n', html, re.DOTALL)
    if not m:
        m = re.search(r'Osoby ve farnosti</h2>(.*?)(?=<h2|<div class="blue-wrapp|</div></div>)', html, re.DOTALL)
    if not m:
        return []

    block = m.group(1)
    # Každá osoba je v <p>: <strong>ROLE</strong><br> <a ...><span>JMENO</span></a>
    osoby = []
    for p in re.findall(r'<p>(.*?)</p>', block, re.DOTALL):
        role_m = re.search(r'<strong>([^<]+)</strong>', p)
        name_m = re.search(r'<span>([^<]+)</span>', p)
        if role_m and name_m:
            role = role_m.group(1).strip()
            name = name_m.group(1).strip()
            osoby.append((role, name))
    return osoby


def main() -> None:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.executescript("""
        DROP TABLE IF EXISTS knezi;
        CREATE TABLE knezi (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            farnost  TEXT NOT NULL,
            guid     TEXT NOT NULL,
            role     TEXT,
            jmeno    TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_knezi_farnost ON knezi (farnost);
        CREATE INDEX IF NOT EXISTS idx_knezi_jmeno   ON knezi (jmeno);
    """)
    conn.commit()

    print("Stahuji seznam farností...")
    parishes = get_parish_list(fetch(LIST_URL))
    print(f"Nalezeno: {len(parishes)} farností")

    for i, (guid, nazev) in enumerate(parishes, 1):
        url = f"{BASE_URL}/katalog/farnosti/?guid={guid}"
        try:
            html = fetch(url)
            osoby = get_osoby(html)
            if osoby:
                cur.executemany(
                    "INSERT INTO knezi (farnost, guid, role, jmeno) VALUES (?, ?, ?, ?)",
                    [(nazev, guid, role, jmeno) for role, jmeno in osoby],
                )
            else:
                # farnost bez přiřazených osob — zapíšeme s NULL
                cur.execute(
                    "INSERT INTO knezi (farnost, guid, role, jmeno) VALUES (?, ?, NULL, NULL)",
                    (nazev, guid),
                )
            conn.commit()
            status = ", ".join(f"{r}: {j}" for r, j in osoby) if osoby else "—"
            print(f"[{i:3}/{len(parishes)}] {nazev}: {status}")
        except Exception as e:
            print(f"[{i:3}/{len(parishes)}] CHYBA {nazev}: {e}")

        time.sleep(DELAY)

    conn.close()

    # Shrnutí
    conn2 = sqlite3.connect(DB_FILE)
    rows = conn2.execute("""
        SELECT role, COUNT(*) as pocet
        FROM knezi
        WHERE role IS NOT NULL
        GROUP BY role
        ORDER BY pocet DESC
    """).fetchall()
    conn2.close()

    print("\n=== Přehled rolí ===")
    for role, pocet in rows:
        print(f"  {pocet:3}x  {role}")


if __name__ == "__main__":
    main()
