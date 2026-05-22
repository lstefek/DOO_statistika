#!/usr/bin/env python3
"""
Stáhne seznam kněží z doo.cz/katalog/farnosti/ a uloží do SQLite.

Vylepšení oproti původní verzi:
- BeautifulSoup místo regulárů (odolné vůči změnám HTML formátování)
- Retry s exponenciálním back-offem při HTTP chybách
- Deduplikace tuple (farnost, role, jmeno) — zdrojový web občas
  duplikuje stejnou osobu, čistíme to ihned
"""

import sqlite3
import time
import urllib.request
import urllib.error
from pathlib import Path

from bs4 import BeautifulSoup

BASE_URL = "https://doo.cz"
LIST_URL = f"{BASE_URL}/katalog/farnosti/"
DB_FILE = Path(__file__).parent / "scitani.db"
DELAY = 0.3       # sekundy mezi požadavky
MAX_RETRIES = 3
RETRY_BACKOFF = 1.5  # sekundy, násobí se 2× při každém retry


def fetch(url: str) -> str:
    """HTTP GET s retry. Vyhazuje výjimku až po vyčerpání pokusů."""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * (2 ** (attempt - 1))
                print(f"    retry {attempt}/{MAX_RETRIES} po {wait:.1f}s ({e})")
                time.sleep(wait)
    raise RuntimeError(f"fetch selhal po {MAX_RETRIES} pokusech: {last_err}")


def get_parish_list(html: str) -> list[tuple[str, str]]:
    """Vrátí seznam (guid, nazev) pro všechny farnosti ze seznamu /katalog/farnosti/."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("/katalog/farnosti/?guid="):
            continue
        guid = href.split("guid=", 1)[1]
        strong = a.find("strong")
        if strong:
            out.append((guid, strong.get_text(strip=True)))
    # Deduplikuj při zachování pořadí
    seen = set()
    uniq = []
    for guid, nazev in out:
        if guid in seen:
            continue
        seen.add(guid)
        uniq.append((guid, nazev))
    return uniq


def get_osoby(html: str) -> list[tuple[str, str]]:
    """Vrátí seznam (role, jmeno) na stránce konkrétní farnosti.
    Hledáme blok 'Osoby ve farnosti' (sekce <h2>) a v něm <p> s rolí a jménem."""
    soup = BeautifulSoup(html, "html.parser")

    block = None
    # Varianta 1: div.wrapp.farnost.osoby
    block = soup.find("div", class_="wrapp farnost osoby")
    if not block:
        # Varianta 2: vyhledáme h2 'Osoby ve farnosti' a vezmeme následující sourozence
        for h2 in soup.find_all("h2"):
            if "osoby" in h2.get_text(strip=True).lower() and "farnost" in h2.get_text(strip=True).lower():
                block = h2.parent
                break

    if not block:
        return []

    osoby = []
    for p in block.find_all("p"):
        strong = p.find("strong")
        span = p.find("span")
        if strong and span:
            role = strong.get_text(strip=True)
            jmeno = span.get_text(strip=True)
            if role and jmeno:
                osoby.append((role, jmeno))
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

    total_osoby = 0
    total_dedup_skipped = 0

    for i, (guid, nazev) in enumerate(parishes, 1):
        url = f"{BASE_URL}/katalog/farnosti/?guid={guid}"
        try:
            html = fetch(url)
            osoby_raw = get_osoby(html)

            # Deduplikace tuple (role, jmeno) v rámci jedné farnosti
            seen_tuples = set()
            osoby = []
            for role, jmeno in osoby_raw:
                key = (role, jmeno)
                if key in seen_tuples:
                    total_dedup_skipped += 1
                    continue
                seen_tuples.add(key)
                osoby.append((role, jmeno))

            if osoby:
                cur.executemany(
                    "INSERT INTO knezi (farnost, guid, role, jmeno) VALUES (?, ?, ?, ?)",
                    [(nazev, guid, role, jmeno) for role, jmeno in osoby],
                )
                total_osoby += len(osoby)
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
    n_unikatnich = conn2.execute(
        "SELECT COUNT(DISTINCT jmeno) FROM knezi WHERE jmeno IS NOT NULL"
    ).fetchone()[0]
    conn2.close()

    print(f"\nCelkem: {total_osoby} přiřazení, {n_unikatnich} unikátních osob")
    print(f"Deduplikováno během importu: {total_dedup_skipped} duplicit")
    print("\n=== Přehled rolí ===")
    for role, pocet in rows:
        print(f"  {pocet:3}x  {role}")


if __name__ == "__main__":
    main()
