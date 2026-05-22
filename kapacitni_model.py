#!/usr/bin/env python3
"""
Kapacitní model: kolik farností lze obsloužit při klesajícím počtu kněží?

Předpoklady:
- 2024: 192 kněží, 278 farností
- Pokles kněží: -50 % za 10 let (2034 → 96 kněží), exponenciální
- Max. farností na kněze: aktuální průměr je 1,45; praktický strop ~4
  (nad 4 farnosti/kněz je služba fyzicky neudržitelná při zachování nedělních mší)
- Přidělování prioritou: nejdříve jsou obsluhovány největší farnosti
- Věřící: predikce exp. modelu z predikce_farnost
"""

import math
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

DB_FILE = Path(__file__).parent / "scitani.db"
OUT_DIR = Path(__file__).parent / "grafy"
OUT_DIR.mkdir(exist_ok=True)

KNEZI_2024    = 192
POKLES_B      = math.log(0.5) / 10   # -50 % za 10 let
MAX_FAR_KNEZ  = 2                     # každou neděli mše ve 2 farnostech (různé časy)
ROKY_MODELU   = [2024, 2027, 2029, 2031, 2034, 2037, 2039]


def knezi_v_roce(rok: int) -> int:
    t = rok - 2024
    return max(1, round(KNEZI_2024 * math.exp(POKLES_B * t)))


def predikni_verice(conn, rok: int) -> dict[str, float]:
    """Vrátí {farnost: predikovaný počet věřících} pro daný rok.
    Pro roky bez dat interpoluje lineárně mezi nejbližšími dostupnými body."""
    if rok <= 2024:
        rows = conn.execute(
            "SELECT farnost, osob_celkem FROM scitani WHERE rok=? AND osob_celkem IS NOT NULL",
            (rok,)
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    # Dostupné predikční roky
    pred_roky = [2029, 2034, 2039]
    if rok in pred_roky:
        rows = conn.execute(
            "SELECT farnost, exp_val FROM predikce_farnost WHERE rok=? AND exp_val IS NOT NULL",
            (rok,)
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    # Interpolace: najdi okolní roky
    vsechny = [2024] + pred_roky
    r_low  = max(r for r in vsechny if r <= rok)
    r_high = min(r for r in vsechny if r >= rok)
    if r_low == r_high:
        return predikni_verice(conn, r_low)

    d_low  = predikni_verice(conn, r_low)
    d_high = predikni_verice(conn, r_high)
    t = (rok - r_low) / (r_high - r_low)
    result = {}
    for far in set(d_low) | set(d_high):
        v_low  = d_low.get(far, 0)
        v_high = d_high.get(far, 0)
        result[far] = v_low + t * (v_high - v_low)
    return result


def dekanaty_far(conn) -> dict[str, str]:
    rows = conn.execute("SELECT DISTINCT farnost, dekanat FROM scitani").fetchall()
    return {r[0]: r[1] for r in rows}


def simuluj_pokryti(vericich: dict[str, float], pocet_knezi: int) -> dict[str, str]:
    """
    Seřadí farnosti od největší, přiděluje kněze dokud není vyčerpána kapacita.
    Vrátí {farnost: stav} kde stav je 'pokryta' nebo 'ohrozena'.
    """
    kapacita = pocet_knezi * MAX_FAR_KNEZ
    serazene = sorted(vericich.items(), key=lambda x: -x[1])
    stav = {}
    for i, (far, _) in enumerate(serazene):
        stav[far] = "pokryta" if i < kapacita else "ohrozena"
    return stav


def main():
    conn = sqlite3.connect(DB_FILE)
    dek_map = dekanaty_far(conn)

    # ── 1. Uložit do databáze ─────────────────────────────────────────────────
    conn.execute("DROP TABLE IF EXISTS kapacitni_model")
    conn.execute("""
        CREATE TABLE kapacitni_model (
            rok          INTEGER NOT NULL,
            farnost      TEXT    NOT NULL,
            dekanat      TEXT,
            vericich     REAL,
            pocet_knezi  INTEGER,
            kapacita     INTEGER,
            stav         TEXT,
            PRIMARY KEY (rok, farnost)
        )
    """)

    scenare = []   # (rok, knezi, pokryte, ohrozene, ver_pokryte, ver_ohrozene)

    for rok in ROKY_MODELU:
        pocet_k = knezi_v_roce(rok)
        ver     = predikni_verice(conn, rok)
        stav    = simuluj_pokryti(ver, pocet_k)
        kapacita = pocet_k * MAX_FAR_KNEZ

        pokryte   = [(f, v) for f, v in ver.items() if stav.get(f) == "pokryta"]
        ohrozene  = [(f, v) for f, v in ver.items() if stav.get(f) == "ohrozena"]

        ver_p = sum(v for _, v in pokryte)
        ver_o = sum(v for _, v in ohrozene)

        scenare.append((rok, pocet_k, len(pokryte), len(ohrozene), ver_p, ver_o))

        for far, ver_f in ver.items():
            conn.execute(
                "INSERT OR REPLACE INTO kapacitni_model VALUES (?,?,?,?,?,?,?)",
                (rok, far, dek_map.get(far), ver_f, pocet_k, kapacita, stav.get(far, "neznáma"))
            )

    conn.commit()

    # ── 2. Přehled do konzole ─────────────────────────────────────────────────
    print(f"\n{'Rok':>6}  {'Kněží':>6}  {'Kapac.':>7}  {'Pokryt.':>8}  {'Ohrož.':>8}  "
          f"{'Věř.pokr.':>10}  {'Věř.ohr.':>9}  {'% ohr.':>7}")
    print("-" * 75)
    for rok, k, p, o, vp, vo in scenare:
        pct = vo / (vp + vo) * 100 if (vp + vo) > 0 else 0
        print(f"{rok:>6}  {k:>6}  {k*MAX_FAR_KNEZ:>7}  {p:>8}  {o:>8}  "
              f"{int(vp):>10,}  {int(vo):>9,}  {pct:>6.1f} %")

    # Ohrožené farnosti v roce 2034
    print("\n=== Ohrožené farnosti 2034 (řazeno sestupně dle věřících) ===")
    rows = conn.execute("""
        SELECT farnost, dekanat, ROUND(vericich) as ver
        FROM kapacitni_model
        WHERE rok=2034 AND stav='ohrozena'
        ORDER BY vericich DESC
    """).fetchall()
    print(f"Celkem: {len(rows)} farností")
    for far, dek, ver in rows[:20]:
        print(f"  {far:<35} {dek:<15} {int(ver):>4} věř.")
    if len(rows) > 20:
        print(f"  … a dalších {len(rows)-20} farností")

    conn.close()

    # ── 3. Grafy ──────────────────────────────────────────────────────────────
    roky   = [s[0] for s in scenare]
    knezi  = [s[1] for s in scenare]
    pokr   = [s[2] for s in scenare]
    ohroz  = [s[3] for s in scenare]
    ver_p  = [s[4] for s in scenare]
    ver_o  = [s[5] for s in scenare]

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "figure.dpi": 120,
    })

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    fig.suptitle("Kapacitní model: kněží vs. farnosti (max. 2 farnosti/kněz)",
                 fontsize=13, fontweight="bold")

    # Graf 1: počet kněží v čase
    ax = axes[0, 0]
    ax.plot(roky, knezi, "o-", color="#7c3aed", lw=2, ms=6)
    ax.axhline(96, color="red", lw=1, ls="--", label="50 % (96)")
    ax.set_title("Počet kněží")
    ax.set_ylabel("Kněží")
    ax.legend(fontsize=9)
    for r, k in zip(roky, knezi):
        ax.annotate(str(k), (r, k), textcoords="offset points", xytext=(0, 7),
                    ha="center", fontsize=8)

    # Graf 2: pokryté vs. ohrožené farnosti
    ax = axes[0, 1]
    ax.stackplot(roky, pokr, ohroz,
                 labels=["Pokryté farnosti", "Ohrožené farnosti"],
                 colors=["#2563eb", "#dc2626"], alpha=0.8)
    ax.axhline(278, color="gray", lw=0.8, ls=":", label="Celkem 278 farností")
    ax.set_title("Pokrytí farností")
    ax.set_ylabel("Počet farností")
    ax.legend(fontsize=9, loc="lower left")

    # Graf 3: věřící v pokrytých vs. ohrožených farnostech
    ax = axes[1, 0]
    ax.stackplot(roky, ver_p, ver_o,
                 labels=["Věřící v pokrytých", "Věřící v ohrožených"],
                 colors=["#2563eb", "#dc2626"], alpha=0.8)
    ax.set_title("Věřící podle pokrytí")
    ax.set_ylabel("Počet věřících")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f"{int(x):,}".replace(",", " ")))
    ax.legend(fontsize=9, loc="upper right")

    # Graf 4: % ohrožených věřících
    ax = axes[1, 1]
    pct_ohr = [vo / (vp + vo) * 100 if (vp + vo) > 0 else 0
               for vp, vo in zip(ver_p, ver_o)]
    bars = ax.bar(roky, pct_ohr, color=["#2563eb" if p < 10 else "#f59e0b" if p < 30 else "#dc2626"
                                         for p in pct_ohr], width=2)
    ax.set_title("% věřících v ohrožených farnostech")
    ax.set_ylabel("Podíl (%)")
    ax.set_ylim(0, 100)
    for bar, pct in zip(bars, pct_ohr):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"{pct:.1f} %", ha="center", fontsize=8)

    for ax_row in axes:
        for ax in ax_row:
            ax.set_xticks(roky)
            ax.set_xticklabels([str(r) for r in roky], rotation=45, ha="right", fontsize=8)

    fig.tight_layout()
    path = OUT_DIR / "kapacitni_model.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"\nGraf: {path}")

    # ── Graf 5: ohrožené farnosti podle děkanátů (2034) ──────────────────────
    conn2 = sqlite3.connect(DB_FILE)
    rows_dek = conn2.execute("""
        SELECT dekanat,
               SUM(CASE WHEN stav='pokryta'  THEN 1 ELSE 0 END) AS pokr,
               SUM(CASE WHEN stav='ohrozena' THEN 1 ELSE 0 END) AS ohr
        FROM kapacitni_model
        WHERE rok=2034
        GROUP BY dekanat
        ORDER BY ohr DESC
    """).fetchall()
    conn2.close()

    dekanaty = [r[0] for r in rows_dek]
    pokr_d   = [r[1] for r in rows_dek]
    ohr_d    = [r[2] for r in rows_dek]

    fig2, ax2 = plt.subplots(figsize=(11, 5))
    x = np.arange(len(dekanaty))
    w = 0.4
    ax2.bar(x - w/2, pokr_d, width=w, label="Pokryté",  color="#2563eb", alpha=0.85)
    ax2.bar(x + w/2, ohr_d,  width=w, label="Ohrožené", color="#dc2626", alpha=0.85)
    ax2.set_xticks(x)
    ax2.set_xticklabels(dekanaty, rotation=30, ha="right")
    ax2.set_title("Pokrytí farností podle děkanátu — scénář 2034 (96 kněží)", fontweight="bold")
    ax2.set_ylabel("Počet farností")
    ax2.legend()
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    fig2.tight_layout()
    path2 = OUT_DIR / "kapacita_dekanaty_2034.png"
    fig2.savefig(path2)
    plt.close(fig2)
    print(f"Graf: {path2}")


if __name__ == "__main__":
    main()
