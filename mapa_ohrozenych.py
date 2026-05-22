#!/usr/bin/env python3
"""
Interaktivní mapa ohrožených farností podle kapacitního modelu.
Generuje HTML soubory pro roky 2034, 2037, 2039.

Oprava #4.3: deterministický JOIN — pro každou farnost se sestaví seznam
všech aktivních kněží (Farář, Administrátor*, Farní vikář, Výpomocný duchovní)
přes GROUP_CONCAT v poddotazu. Žádné nedeterministické GROUP BY.
"""

import sqlite3
from pathlib import Path
import folium

DB_FILE = Path(__file__).parent / "scitani.db"
OUT_DIR = Path(__file__).parent / "grafy"
OUT_DIR.mkdir(exist_ok=True)

BARVY = {
    "ohrozena": "#dc2626",
    "pokryta":  "#2563eb",
}
ROKY = [2034, 2037, 2039]

# Hierarchie priorit pro "hlavního" kněze (zobrazí se jako první v popupu)
ROLE_PRIORITY = (
    "Farář",
    "Administrátor",
    "Administrátor excurrendo",
    "Administrátor excurrendo in materialibus",
    "Administrátor excurrendo in spiritualibus",
    "Farní vikář",
    "Výpomocný duchovní",
)


def pripocti_knezi(conn) -> dict[str, list[tuple[str, str]]]:
    """{farnost: [(role, jmeno), …]} — uspořádané podle ROLE_PRIORITY."""
    out: dict[str, list[tuple[str, str]]] = {}
    rows = conn.execute(
        "SELECT farnost, role, jmeno FROM knezi "
        "WHERE jmeno IS NOT NULL AND role IS NOT NULL"
    ).fetchall()
    for f, r, j in rows:
        out.setdefault(f, []).append((r, j))

    def order_key(rj):
        r, _ = rj
        return ROLE_PRIORITY.index(r) if r in ROLE_PRIORITY else len(ROLE_PRIORITY)

    for f in out:
        out[f].sort(key=order_key)
    return out


def generuj_mapu(conn, rok: int, knezi_map: dict) -> Path:
    rows = conn.execute("""
        SELECT
            km.farnost,
            km.dekanat,
            ROUND(km.vericich) AS vericich,
            km.stav,
            fs.lat,
            fs.lon
        FROM kapacitni_model km
        JOIN farnosti_souradnice fs ON fs.farnost = km.farnost
        WHERE km.rok = ?
          AND fs.lat IS NOT NULL
        ORDER BY km.stav, km.vericich DESC
    """, (rok,)).fetchall()

    knezi_v_roce = conn.execute(
        "SELECT pocet_knezi FROM kapacitni_model WHERE rok=? LIMIT 1", (rok,)
    ).fetchone()[0]
    ohrozenych = sum(1 for r in rows if r[3] == "ohrozena")

    # Spočítej i ty bez GPS
    bez_gps = conn.execute("""
        SELECT km.farnost FROM kapacitni_model km
        LEFT JOIN farnosti_souradnice fs ON fs.farnost = km.farnost
        WHERE km.rok = ? AND (fs.lat IS NULL OR fs.lat IS NULL)
    """, (rok,)).fetchall()
    if bez_gps:
        print(f"  ⚠ {len(bez_gps)} farností bez GPS v mapě {rok}: "
              + ", ".join(b[0] for b in bez_gps[:5])
              + ("…" if len(bez_gps) > 5 else ""))

    mapa = folium.Map(location=[49.75, 17.8], zoom_start=9, tiles="CartoDB positron")

    title_html = f"""
    <div style="position:fixed;top:10px;left:50%;transform:translateX(-50%);
                background:white;padding:8px 16px;border-radius:6px;
                box-shadow:0 2px 6px rgba(0,0,0,.3);z-index:1000;font-family:sans-serif">
        <b>Kapacitní model {rok}</b> — {knezi_v_roce} kněží,
        <span style="color:#dc2626"><b>{ohrozenych} ohrožených farností</b></span>
        z {len(rows)} celkem
    </div>"""
    mapa.get_root().html.add_child(folium.Element(title_html))

    legend_html = """
    <div style="position:fixed;bottom:30px;left:20px;background:white;
                padding:8px 12px;border-radius:6px;box-shadow:0 2px 6px rgba(0,0,0,.3);
                font-family:sans-serif;font-size:13px;z-index:1000">
        <div><span style="color:#2563eb;font-size:18px">●</span> Pokrytá farnost</div>
        <div><span style="color:#dc2626;font-size:18px">●</span> Ohrožená farnost</div>
    </div>"""
    mapa.get_root().html.add_child(folium.Element(legend_html))

    for farnost, dekanat, vericich, stav, lat, lon in rows:
        barva = BARVY[stav]
        radius = max(5, min(20, int((vericich or 1) ** 0.5)))

        knezi_list = knezi_map.get(farnost, [])
        if knezi_list:
            knezi_html = "<br>".join(f"<i>{r}:</i> {j}" for r, j in knezi_list)
        else:
            knezi_html = "<i>—</i>"

        popup_text = f"""
            <b>{farnost}</b><br>
            Děkanát: {dekanat}<br>
            Věřících (predikce {rok}): <b>{int(vericich or 0)}</b><br>
            Stav: <span style="color:{barva}"><b>{stav.upper()}</b></span><br>
            <hr style="margin:4px 0">
            <b>Kněží:</b><br>
            {knezi_html}
        """
        folium.CircleMarker(
            location=[lat, lon],
            radius=radius,
            color=barva,
            fill=True,
            fill_color=barva,
            fill_opacity=0.7,
            popup=folium.Popup(popup_text, max_width=320),
            tooltip=f"{farnost} ({int(vericich or 0)} věř.) — {stav}",
        ).add_to(mapa)

    path = OUT_DIR / f"mapa_ohrozenych_{rok}.html"
    mapa.save(str(path))
    return path


def main():
    conn = sqlite3.connect(DB_FILE)
    knezi_map = pripocti_knezi(conn)
    for rok in ROKY:
        path = generuj_mapu(conn, rok, knezi_map)
        print(f"  {path}")
    conn.close()
    print("Hotovo.")


if __name__ == "__main__":
    main()
