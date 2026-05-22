#!/usr/bin/env python3
"""
Vizualizace predikce návštěvnosti bohoslužeb — diecéze, děkanáty, farnosti NJ.

Vylepšení:
- Skutečnost = NULL je vykreslena jako mezera (NaN), ne jako 0.
- Pás 90% CI exp modelu je vyplněn (s legendou „90 % CI exp").
- Pás mezi exp a lin model je vyplněn s jasným popiskem („Rozdíl exp/lin").
- Predikce s validni=0 v predikce_farnost se nevykreslují.
"""

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

HIST_ROKY = [1999, 2004, 2009, 2014, 2019, 2024]
PRED_ROKY = [2029, 2034, 2039]
VSECHNY   = HIST_ROKY + PRED_ROKY

BARVA_HIST = "#2563eb"
BARVA_EXP  = "#dc2626"
BARVA_LIN  = "#16a34a"
BARVA_REC  = "#f59e0b"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "figure.dpi": 120,
})


def nacti(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def kresli_predikci(ax, hist_roky, hist_hod, pred_roky, exp_hod, exp_lo, exp_hi,
                    lin_hod, recent_hod, nazev, show_recent=True):
    """Vykreslí historii + obě/tři predikce. Skutečnost s NaN pro NULL roky."""
    # Historie (NaN namísto None pro správný matplotlib render)
    hist_y = [h if h is not None else np.nan for h in hist_hod]
    ax.plot(hist_roky, hist_y, "o-", color=BARVA_HIST, lw=2, ms=5, label="Skutečnost")

    # Najdi poslední platný historický bod (pro spojnici k predikci)
    last_valid = None
    for r, h in zip(hist_roky, hist_hod):
        if h is not None:
            last_valid = (r, h)
    if last_valid is None or not pred_roky:
        ax.set_title(nazev, fontsize=11, fontweight="bold")
        return

    posl_rok, posl_hod = last_valid
    all_pred = [posl_rok] + pred_roky

    # Exp + CI
    if any(v is not None for v in exp_hod):
        exp_full = [posl_hod] + list(exp_hod)
        ax.plot(all_pred, exp_full, "s--", color=BARVA_EXP, lw=1.8, ms=5,
                label="Exp. model")
        if exp_lo and exp_hi and all(v is not None for v in exp_lo):
            lo_full = [posl_hod] + list(exp_lo)
            hi_full = [posl_hod] + list(exp_hi)
            ax.fill_between(all_pred, lo_full, hi_full, alpha=0.10,
                            color=BARVA_EXP, label="90 % CI exp")

    # Lin
    if any(v is not None for v in lin_hod):
        lin_full = [posl_hod] + list(lin_hod)
        ax.plot(all_pred, lin_full, "^--", color=BARVA_LIN, lw=1.5, ms=4,
                label="Lin. model")

    # Recent (lokální tempo) — jen pro diecéze a děkanáty
    if show_recent and recent_hod is not None and any(v is not None for v in recent_hod):
        rec_full = [posl_hod] + list(recent_hod)
        ax.plot(all_pred, rec_full, "v:", color=BARVA_REC, lw=1.5, ms=4,
                label="Recent (lokální)")

    ax.axvline(2024.5, color="gray", lw=0.8, ls=":")
    ax.set_title(nazev, fontsize=11, fontweight="bold")
    ax.set_xticks(VSECHNY)
    ax.set_xticklabels([str(r) for r in VSECHNY], rotation=45, ha="right", fontsize=8)
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: f"{int(x):,}".replace(",", " ")))


# ── 1. DIECÉZE ────────────────────────────────────────────────────────────────
def graf_dieceze(conn):
    rows = nacti(conn,
        "SELECT rok, hodnota, exp_val, exp_lo, exp_hi, lin_val, recent_val "
        "FROM predikce_dieceze ORDER BY rok")
    hist_r = [r[0] for r in rows if r[1] is not None]
    hist_h = [r[1] for r in rows if r[1] is not None]
    pred_r = [r[0] for r in rows if r[2] is not None]
    exp_h  = [r[2] for r in rows if r[2] is not None]
    exp_lo = [r[3] for r in rows if r[2] is not None]
    exp_hi = [r[4] for r in rows if r[2] is not None]
    lin_h  = [r[5] for r in rows if r[5] is not None]
    rec_h  = [r[6] for r in rows if r[6] is not None]
    # Doplň lin a rec na stejnou délku jako pred_r (pokud jeden chybí, je vše None)
    while len(lin_h) < len(pred_r): lin_h.append(None)
    while len(rec_h) < len(pred_r): rec_h.append(None)

    fig, ax = plt.subplots(figsize=(9, 5))
    kresli_predikci(ax, hist_r, hist_h, pred_r,
                    exp_h, exp_lo, exp_hi, lin_h, rec_h,
                    "Diecéze ostravsko-opavská — návštěvnost nedělních bohoslužeb")
    ax.set_ylabel("Počet účastníků")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    path = OUT_DIR / "dieceze.png"
    fig.savefig(path)
    plt.close(fig)
    print(f"  {path}")


# ── 2. DĚKANÁTY ───────────────────────────────────────────────────────────────
def graf_dekanaty(conn):
    dekanaty = [r[0] for r in nacti(conn,
        "SELECT DISTINCT dekanat FROM predikce_dekanat ORDER BY dekanat")]

    cols = 3
    rows_n = (len(dekanaty) + cols - 1) // cols
    fig, axes = plt.subplots(rows_n, cols, figsize=(cols * 5, rows_n * 4))
    axes_flat = axes.flatten()

    for i, dek in enumerate(dekanaty):
        rows = nacti(conn,
            "SELECT rok, hodnota, exp_val, exp_lo, exp_hi, lin_val, recent_val "
            "FROM predikce_dekanat WHERE dekanat=? ORDER BY rok", (dek,))
        hist_r = [r[0] for r in rows if r[1] is not None]
        hist_h = [r[1] for r in rows if r[1] is not None]
        pred_r = [r[0] for r in rows if r[2] is not None]
        exp_h  = [r[2] for r in rows if r[2] is not None]
        exp_lo = [r[3] for r in rows if r[2] is not None]
        exp_hi = [r[4] for r in rows if r[2] is not None]
        lin_h  = [r[5] for r in rows if r[5] is not None]
        rec_h  = [r[6] for r in rows if r[6] is not None]
        while len(lin_h) < len(pred_r): lin_h.append(None)
        while len(rec_h) < len(pred_r): rec_h.append(None)
        kresli_predikci(axes_flat[i], hist_r, hist_h, pred_r,
                        exp_h, exp_lo, exp_hi, lin_h, rec_h, dek)

    for j in range(len(dekanaty), len(axes_flat)):
        axes_flat[j].set_visible(False)

    handles, labels = axes_flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower right", fontsize=9)
    fig.suptitle("Děkanáty — návštěvnost bohoslužeb a predikce",
                 fontsize=13, fontweight="bold", y=1.01)
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
            "SELECT rok, hodnota, exp_val, exp_lo, exp_hi, lin_val, validni "
            "FROM predikce_farnost WHERE farnost=? ORDER BY rok", (far,))
        hist_r = [r[0] for r in rows if r[1] is not None]
        hist_h = [r[1] for r in rows if r[1] is not None]

        # Validní predikce? Pokud ne, kreslíme jen historii
        validni_flag = any(r[6] == 1 for r in rows if r[6] is not None)
        if validni_flag:
            pred_r = [r[0] for r in rows if r[2] is not None]
            exp_h  = [r[2] for r in rows if r[2] is not None]
            exp_lo = [r[3] for r in rows if r[2] is not None]
            exp_hi = [r[4] for r in rows if r[2] is not None]
            lin_h  = [r[5] for r in rows if r[5] is not None]
        else:
            pred_r, exp_h, exp_lo, exp_hi, lin_h = [], [], [], [], []
        while len(lin_h) < len(pred_r): lin_h.append(None)

        title = far if validni_flag else f"{far} (predikce neplatná)"
        kresli_predikci(axes_flat[i], hist_r, hist_h, pred_r,
                        exp_h, exp_lo, exp_hi, lin_h, None,
                        title, show_recent=False)

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
               MAX(CASE WHEN rok=2024 THEN hodnota END) AS h2024,
               MAX(CASE WHEN rok=2039 THEN exp_val  END) AS exp2039,
               MAX(CASE WHEN rok=2039 THEN lin_val  END) AS lin2039,
               MAX(CASE WHEN rok=2039 THEN recent_val END) AS rec2039
        FROM predikce_dekanat
        GROUP BY dekanat
        ORDER BY h2024 DESC
    """)
    dekanaty = [r[0] for r in rows]
    h2024    = [r[1] or 0 for r in rows]
    exp2039  = [r[2] or 0 for r in rows]
    lin2039  = [r[3] or 0 for r in rows]
    rec2039  = [r[4] or 0 for r in rows]

    x = np.arange(len(dekanaty))
    w = 0.21
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(x - 1.5*w, h2024,   width=w, label="2024 (skutečnost)", color=BARVA_HIST, alpha=0.85)
    ax.bar(x - 0.5*w, exp2039, width=w, label="2039 exp",     color=BARVA_EXP,  alpha=0.85)
    ax.bar(x + 0.5*w, lin2039, width=w, label="2039 lin",     color=BARVA_LIN,  alpha=0.85)
    ax.bar(x + 1.5*w, rec2039, width=w, label="2039 recent",  color=BARVA_REC,  alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(dekanaty, rotation=30, ha="right")
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"{int(v):,}".replace(",", " ")))
    ax.set_title("Srovnání děkanátů: skutečnost 2024 vs. predikce 2039",
                 fontweight="bold")
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
