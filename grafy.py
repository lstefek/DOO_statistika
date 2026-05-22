#!/usr/bin/env python3
"""Vizualizace predikce návštěvnosti bohoslužeb — diecéze, děkanáty, farnosti NJ."""

import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

DB_FILE   = Path(__file__).parent / "scitani.db"
OUT_DIR   = Path(__file__).parent / "grafy"
OUT_DIR.mkdir(exist_ok=True)

HIST_ROKY = [1999, 2004, 2009, 2014, 2019, 2024]
PRED_ROKY = [2029, 2034, 2039]
VSECHNY   = HIST_ROKY + PRED_ROKY

BARVA_HIST = "#2563eb"   # modrá — naměřené hodnoty
BARVA_EXP  = "#dc2626"   # červená — exponenciální predikce
BARVA_LIN  = "#16a34a"   # zelená — lineární predikce
FILL_ALPHA = 0.10

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "figure.dpi": 120,
})


def nacti(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.fetchall()


def kresli_predikci(ax, hist_roky, hist_hod, pred_roky, exp_hod, lin_hod, nazev):
    """Vykreslí historii + obě predikce do axes."""
    # Historie
    ax.plot(hist_roky, hist_hod, "o-", color=BARVA_HIST, lw=2, ms=5, label="Skutečnost")
    # Spojnice poslední historický bod → predikce
    posl_rok = hist_roky[-1]
    posl_hod = hist_hod[-1]
    all_pred = [posl_rok] + pred_roky
    exp_full = [posl_hod] + list(exp_hod)
    lin_full = [posl_hod] + list(lin_hod)
    ax.plot(all_pred, exp_full, "s--", color=BARVA_EXP, lw=1.8, ms=5, label="Exp. model")
    ax.plot(all_pred, lin_full, "^--", color=BARVA_LIN, lw=1.8, ms=5, label="Lin. model")
    # Vyplnění pásma mezi modely
    ax.fill_between(all_pred, exp_full, lin_full, alpha=FILL_ALPHA, color="gray")
    # Svislá čára oddělující historii a predikci
    ax.axvline(2024.5, color="gray", lw=0.8, ls=":")
    ax.set_title(nazev, fontsize=11, fontweight="bold")
    ax.set_xticks(VSECHNY)
    ax.set_xticklabels([str(r) for r in VSECHNY], rotation=45, ha="right", fontsize=8)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}".replace(",", " ")))


# ── 1. DIECÉZE ────────────────────────────────────────────────────────────────
def graf_dieceze(conn):
    rows = nacti(conn, "SELECT rok, hodnota, exp_val, lin_val FROM predikce_dieceze ORDER BY rok")
    hist_r = [r[0] for r in rows if r[1] is not None]
    hist_h = [r[1] for r in rows if r[1] is not None]
    pred_r = [r[0] for r in rows if r[2] is not None]
    exp_h  = [r[2] for r in rows if r[2] is not None]
    lin_h  = [r[3] for r in rows if r[3] is not None]

    fig, ax = plt.subplots(figsize=(9, 5))
    kresli_predikci(ax, hist_r, hist_h, pred_r, exp_h, lin_h,
                    "Diecéze ostravsko-opavská — návštěvnost nedělních bohoslužeb")
    ax.set_ylabel("Počet účastníků")
    ax.legend(loc="upper right")
    fig.tight_layout()
    path = OUT_DIR / "dieceze.png"
    fig.savefig(path)
    plt.close(fig)
    print(f"  {path}")


# ── 2. DĚKANÁTY ───────────────────────────────────────────────────────────────
def graf_dekanaty(conn):
    dekanaty = [r[0] for r in nacti(conn, "SELECT DISTINCT dekanat FROM predikce_dekanat ORDER BY dekanat")]

    cols = 3
    rows_n = (len(dekanaty) + cols - 1) // cols
    fig, axes = plt.subplots(rows_n, cols, figsize=(cols * 5, rows_n * 4))
    axes_flat = axes.flatten()

    for i, dek in enumerate(dekanaty):
        rows = nacti(conn,
            "SELECT rok, hodnota, exp_val, lin_val FROM predikce_dekanat WHERE dekanat=? ORDER BY rok",
            (dek,))
        hist_r = [r[0] for r in rows if r[1] is not None]
        hist_h = [r[1] for r in rows if r[1] is not None]
        pred_r = [r[0] for r in rows if r[2] is not None]
        exp_h  = [r[2] for r in rows if r[2] is not None]
        lin_h  = [r[3] for r in rows if r[3] is not None]
        kresli_predikci(axes_flat[i], hist_r, hist_h, pred_r, exp_h, lin_h, dek)

    # Skryj prázdné panely
    for j in range(len(dekanaty), len(axes_flat)):
        axes_flat[j].set_visible(False)

    # Společná legenda
    handles, labels = axes_flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower right", fontsize=9)
    fig.suptitle("Děkanáty — návštěvnost bohoslužeb a predikce", fontsize=13, fontweight="bold", y=1.01)
    fig.tight_layout()
    path = OUT_DIR / "dekanaty.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  {path}")


# ── 3. FARNOSTI — DĚKANÁT NOVÝ JIČÍN ─────────────────────────────────────────
def graf_farnosti_nj(conn):
    farnosti = [r[0] for r in nacti(conn, """
        SELECT DISTINCT farnost FROM predikce_farnost
        WHERE farnost IN (SELECT DISTINCT farnost FROM scitani WHERE dekanat='Nový Jičín')
        ORDER BY farnost
    """)]

    cols = 4
    rows_n = (len(farnosti) + cols - 1) // cols
    fig, axes = plt.subplots(rows_n, cols, figsize=(cols * 4.5, rows_n * 3.5))
    axes_flat = axes.flatten()

    for i, far in enumerate(farnosti):
        rows = nacti(conn,
            "SELECT rok, hodnota, exp_val, lin_val FROM predikce_farnost WHERE farnost=? ORDER BY rok",
            (far,))
        hist_r = [r[0] for r in rows if r[1] is not None]
        hist_h = [r[1] for r in rows if r[1] is not None]
        pred_r = [r[0] for r in rows if r[2] is not None]
        exp_h  = [r[2] for r in rows if r[2] is not None]
        lin_h  = [r[3] for r in rows if r[3] is not None]
        kresli_predikci(axes_flat[i], hist_r, hist_h, pred_r, exp_h, lin_h, far)

    for j in range(len(farnosti), len(axes_flat)):
        axes_flat[j].set_visible(False)

    handles, labels = axes_flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower right", fontsize=9)
    fig.suptitle("Děkanát Nový Jičín — farnosti, návštěvnost a predikce",
                 fontsize=13, fontweight="bold", y=1.005)
    fig.tight_layout()
    path = OUT_DIR / "farnosti_novy_jicin.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  {path}")


# ── 4. SROVNÁVACÍ PRUH — všechny děkanáty 2024 vs 2039 ───────────────────────
def graf_srovnani_dekanaty(conn):
    rows = nacti(conn, """
        SELECT dekanat,
               MAX(CASE WHEN rok=2024 THEN hodnota END) as h2024,
               MAX(CASE WHEN rok=2039 THEN exp_val  END) as exp2039,
               MAX(CASE WHEN rok=2039 THEN lin_val  END) as lin2039
        FROM predikce_dekanat
        GROUP BY dekanat
        ORDER BY h2024 DESC
    """)
    dekanaty = [r[0] for r in rows]
    h2024    = [r[1] or 0 for r in rows]
    exp2039  = [r[2] or 0 for r in rows]
    lin2039  = [r[3] or 0 for r in rows]

    x = np.arange(len(dekanaty))
    w = 0.28
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(x - w, h2024,   width=w, label="2024 (skutečnost)", color=BARVA_HIST, alpha=0.85)
    ax.bar(x,     exp2039, width=w, label="2039 exp. model",   color=BARVA_EXP,  alpha=0.85)
    ax.bar(x + w, lin2039, width=w, label="2039 lin. model",   color=BARVA_LIN,  alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(dekanaty, rotation=30, ha="right")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}".replace(",", " ")))
    ax.set_title("Srovnání děkanátů: skutečnost 2024 vs. predikce 2039", fontweight="bold")
    ax.set_ylabel("Počet účastníků")
    ax.legend()
    fig.tight_layout()
    path = OUT_DIR / "dekanaty_srovnani_2039.png"
    fig.savefig(path)
    plt.close(fig)
    print(f"  {path}")


def main():
    conn = sqlite3.connect(DB_FILE)
    print("Generuji grafy:")
    graf_dieceze(conn)
    graf_dekanaty(conn)
    graf_farnosti_nj(conn)
    graf_srovnani_dekanaty(conn)
    conn.close()
    print("Hotovo.")


if __name__ == "__main__":
    main()
