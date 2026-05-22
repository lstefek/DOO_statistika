#!/usr/bin/env python3
"""
Interaktivní mapa ohrožených farností podle kapacitního modelu.
Generuje HTML soubory pro roky 2034, 2037, 2039.
"""

import sqlite3
from pathlib import Path
import folium
from folium.plugins import MarkerCluster

DB_FILE = Path(__file__).parent / "scitani.db"
OUT_DIR = Path(__file__).parent / "grafy"
OUT_DIR.mkdir(exist_ok=True)

BARVY = {
    "ohrozena": "#dc2626",   # červená
    "pokryta":  "#2563eb",   # modrá
}
ROKY = [2034, 2037, 2039]


def generuj_mapu(conn, rok: int) -> Path:
    rows = conn.execute("""
        SELECT
            km.farnost,
            km.dekanat,
            ROUND(km.vericich) AS vericich,
            km.stav,
            fs.lat,
            fs.lon,
            k.jmeno AS knez,
            k.role
        FROM kapacitni_model km
        JOIN farnosti_souradnice fs ON fs.farnost = km.farnost
        LEFT JOIN knezi k ON k.farnost = km.farnost
            AND k.role IN ('Farář','Administrátor excurrendo','Administrátor')
            AND (k.jmeno LIKE 'P. %' OR k.jmeno LIKE 'Mons.%')
        WHERE km.rok = ?
          AND fs.lat IS NOT NULL
        GROUP BY km.farnost
        ORDER BY km.stav, km.vericich DESC
    """, (rok,)).fetchall()

    knezi_v_roce = conn.execute(
        "SELECT pocet_knezi FROM kapacitni_model WHERE rok=? LIMIT 1", (rok,)
    ).fetchone()[0]
    ohrozenych = sum(1 for r in rows if r[3] == "ohrozena")

    # Střed diecéze (Ostrava)
    mapa = folium.Map(location=[49.75, 17.8], zoom_start=9,
                      tiles="CartoDB positron")

    # Nadpis
    title_html = f"""
    <div style="position:fixed;top:10px;left:50%;transform:translateX(-50%);
                background:white;padding:8px 16px;border-radius:6px;
                box-shadow:0 2px 6px rgba(0,0,0,.3);z-index:1000;font-family:sans-serif">
        <b>Kapacitní model {rok}</b> — {knezi_v_roce} kněží,
        <span style="color:#dc2626"><b>{ohrozenych} ohrožených farností</b></span>
        z {len(rows)} celkem
    </div>"""
    mapa.get_root().html.add_child(folium.Element(title_html))

    # Legenda
    legend_html = """
    <div style="position:fixed;bottom:30px;left:20px;background:white;
                padding:8px 12px;border-radius:6px;box-shadow:0 2px 6px rgba(0,0,0,.3);
                font-family:sans-serif;font-size:13px;z-index:1000">
        <div><span style="color:#2563eb;font-size:18px">●</span> Pokrytá farnost</div>
        <div><span style="color:#dc2626;font-size:18px">●</span> Ohrožená farnost</div>
    </div>"""
    mapa.get_root().html.add_child(folium.Element(legend_html))

    for farnost, dekanat, vericich, stav, lat, lon, knez, role in rows:
        barva = BARVY[stav]
        radius = max(5, min(20, int((vericich or 1) ** 0.5)))
        popup_text = f"""
            <b>{farnost}</b><br>
            Děkanát: {dekanat}<br>
            Věřících (predikce {rok}): <b>{int(vericich or 0)}</b><br>
            Stav: <span style="color:{barva}"><b>{stav.upper()}</b></span><br>
            Kněz: {knez or '—'}<br>
            Role: {role or '—'}
        """
        folium.CircleMarker(
            location=[lat, lon],
            radius=radius,
            color=barva,
            fill=True,
            fill_color=barva,
            fill_opacity=0.7,
            popup=folium.Popup(popup_text, max_width=260),
            tooltip=f"{farnost} ({int(vericich or 0)} věř.) — {stav}",
        ).add_to(mapa)

    path = OUT_DIR / f"mapa_ohrozenych_{rok}.html"
    mapa.save(str(path))
    return path


def main():
    conn = sqlite3.connect(DB_FILE)
    for rok in ROKY:
        path = generuj_mapu(conn, rok)
        print(f"  {path}")
    conn.close()
    print("Hotovo.")


if __name__ == "__main__":
    main()
