#!/usr/bin/env python3
"""
Stáhne GPS souřadnice farností z doo.cz a uloží do tabulky farnosti_souradnice.

Stránka farnosti obsahuje odkaz na mapu typu:
   https://maps.google.com/?q=...&query=LAT,LON
Z toho parsujeme lat/lon.

Pro farnosti, které nelze najít (Maria Hilf, Býkov, Zálesí), nabízíme
manuální override v MANUAL_GPS.
"""

import re
import sqlite3
import time
import urllib.request
import urllib.error
from pathlib import Path

DB_FILE  = Path(__file__).parent / "scitani.db"
BASE_URL = "https://doo.cz/katalog/farnosti/"
DELAY    = 0.3
MAX_RETRIES = 3
RETRY_BACKOFF = 1.5

# Ruční dohledané GPS pro farnosti, jejichž stránka neobsahuje query=lat,lon
# Zdroj: mapy.cz (zaokrouhleno na 4 desetinná místa)
MANUAL_GPS: dict[str, tuple[float, float]] = {
    "Maria Hilf":  (50.2536, 17.4119),  # poutní místo u Zlatých Hor
    "Býkov":       (49.9700, 17.6133),  # u Krnova (Býkov–Láryšov)
    "Zálesí":      (50.3050, 17.0539),  # Javorník-Zálesí
}


def fetch(url: str) -> str:
    """HTTP GET s retry."""
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


# Regex tolerantní k zápornému znaménku (např. když by byla farnost na druhé polokouli)
GPS_RE = re.compile(r"query=(-?[\d.]+),(-?[\d.]+)")


def in_dioceze(lat: float, lon: float) -> bool:
    """Hrubá kontrola: spadá souřadnice do oblasti DOO (přibližně)?"""
    return 49.3 <= lat <= 50.5 and 17.0 <= lon <= 18.9


def main() -> None:
    conn = sqlite3.connect(DB_FILE)
    cur  = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS farnosti_souradnice")
    cur.execute("""
        CREATE TABLE farnosti_souradnice (
            farnost TEXT PRIMARY KEY,
            guid    TEXT,
            lat     REAL,
            lon     REAL,
            zdroj   TEXT  -- 'web', 'manual'
        )
    """)
    conn.commit()

    # Načti seznam farností z knezi (guid + farnost)
    parishes = cur.execute(
        "SELECT DISTINCT farnost, guid FROM knezi WHERE guid IS NOT NULL"
    ).fetchall()
    print(f"Farností k zpracování: {len(parishes)}")

    ok = 0
    bez_souradnic: list[str] = []
    mimo_dieceze: list[str] = []

    for i, (farnost, guid) in enumerate(parishes, 1):
        url  = f"{BASE_URL}?guid={guid}"
        lat = lon = None
        zdroj = None

        try:
            html = fetch(url)
            m = GPS_RE.search(html)
            if m:
                lat = float(m.group(1))
                lon = float(m.group(2))
                zdroj = "web"
        except Exception as e:
            print(f"  CHYBA [{i}] {farnost}: {e}")

        # Manual override
        if (lat is None or lon is None) and farnost in MANUAL_GPS:
            lat, lon = MANUAL_GPS[farnost]
            zdroj = "manual"
            print(f"  [manual] {farnost}: {lat}, {lon}")

        if lat is not None and lon is not None:
            if not in_dioceze(lat, lon):
                mimo_dieceze.append(f"{farnost} ({lat},{lon})")
            cur.execute(
                "INSERT OR REPLACE INTO farnosti_souradnice VALUES (?,?,?,?,?)",
                (farnost, guid, lat, lon, zdroj),
            )
            ok += 1
            if i % 50 == 0:
                conn.commit()
                print(f"  [{i}/{len(parishes)}] {farnost}: {lat}, {lon}")
        else:
            cur.execute(
                "INSERT OR REPLACE INTO farnosti_souradnice VALUES (?,?,?,?,?)",
                (farnost, guid, None, None, None),
            )
            bez_souradnic.append(farnost)

        time.sleep(DELAY)

    conn.commit()
    conn.close()

    print(f"\nHotovo: {ok}/{len(parishes)} farností se souřadnicemi.")
    if bez_souradnic:
        print(f"\n⚠ Bez souřadnic ({len(bez_souradnic)}):")
        for f in bez_souradnic:
            print(f"   - {f}")
        print("   Doplňte MANUAL_GPS v scrape_souradnice.py a znovu spusťte.")
    if mimo_dieceze:
        print(f"\n⚠ Mimo DOO (kontrola):")
        for f in mimo_dieceze:
            print(f"   - {f}")


if __name__ == "__main__":
    main()
