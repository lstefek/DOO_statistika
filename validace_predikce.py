#!/usr/bin/env python3
"""
Validace predikčního modelu pomocí leave-one-out na posledním sčítání.

Princip:
- Vyřaď z dat poslední rok (2024).
- Fitnout exp + lin + recent modely jen na 1999–2019 (5 bodů).
- Předpovědět rok 2024.
- Porovnat se skutečností: MAPE, RMSE, vážená MAPE.

Tento test odhaluje, jak dobře by predikce predikovaly skutečnost po pětileté
extrapolaci. Pokud je MAPE pro 2024 podobné MAPE, které očekáváme pro 2029 atd.,
máme alespoň empirický důvod věřit širším predikcím.

Výstup: validace_predikce.txt (přehled), volá `predikce.py` funkce.
"""

import math
import sqlite3
from pathlib import Path

import numpy as np

from predikce import (
    ROKY_HISTORICKE, MIN_BODY, R2_PRAH,
    fit_exp, fit_lin, fit_recent,
    predikuj_exp, predikuj_lin,
)

DB_FILE = Path(__file__).parent / "scitani.db"
OUT_FILE = Path(__file__).parent / "validace_predikce.txt"
HOLDOUT_ROK = 2024  # poslední rok, který chceme predikovat


def metrics(skutecnost: list[float], predikce: list[float]) -> dict:
    """MAPE, RMSE, vážená MAPE (vah = velikost skutečnosti)."""
    pairs = [(s, p) for s, p in zip(skutecnost, predikce)
             if s is not None and p is not None and s > 0]
    if not pairs:
        return {"n": 0, "mape": None, "rmse": None, "wmape": None, "bias": None}
    s_arr = np.array([s for s, _ in pairs])
    p_arr = np.array([p for _, p in pairs])

    ape = np.abs(s_arr - p_arr) / s_arr
    mape = float(ape.mean()) * 100

    rmse = float(np.sqrt(((s_arr - p_arr) ** 2).mean()))

    wmape = float(np.abs(s_arr - p_arr).sum() / s_arr.sum()) * 100

    bias = float((p_arr - s_arr).mean())  # >0 = model nadhodnocuje

    return {"n": len(pairs), "mape": mape, "rmse": rmse, "wmape": wmape, "bias": bias}


def validace_farnost(conn) -> tuple[dict, dict, dict]:
    """Pro každou farnost: fituj na 1999-2019, predikuj 2024.
    Vrať tři dict (exp, lin, recent) s {farnost: predikce_2024}."""
    cur = conn.cursor()
    cur.execute("""
        SELECT farnost, rok, osob_celkem
        FROM scitani
        WHERE rok != ?
        ORDER BY farnost, rok
    """, (HOLDOUT_ROK,))

    by_far: dict[str, dict[int, float | None]] = {}
    for far, rok, val in cur.fetchall():
        by_far.setdefault(far, {})[rok] = val

    train_roky = [r for r in ROKY_HISTORICKE if r != HOLDOUT_ROK]
    pred_exp, pred_lin, pred_rec = {}, {}, {}

    for far, rd in by_far.items():
        hod = [rd.get(r) for r in train_roky]
        roky_valid = [r for r, h in zip(train_roky, hod) if h is not None]
        hod_valid  = [h for h in hod if h is not None]
        if len(hod_valid) < 2:
            continue

        ex = fit_exp(roky_valid, hod_valid)
        if ex:
            r = predikuj_exp(ex, HOLDOUT_ROK)
            if r:
                pred_exp[far] = r[0]
        ln = fit_lin(roky_valid, hod_valid)
        if ln:
            pred_lin[far] = predikuj_lin(ln, HOLDOUT_ROK)
        rc = fit_recent(roky_valid, hod_valid, n_last=2)
        if rc:
            r = predikuj_exp(rc, HOLDOUT_ROK)
            if r:
                pred_rec[far] = r[0]

    return pred_exp, pred_lin, pred_rec


def skutecnost_farnost(conn) -> dict[str, float]:
    cur = conn.cursor()
    cur.execute(
        "SELECT farnost, osob_celkem FROM scitani WHERE rok=? AND osob_celkem IS NOT NULL",
        (HOLDOUT_ROK,)
    )
    return {f: v for f, v in cur.fetchall()}


def validace_dieceze(conn) -> dict:
    cur = conn.cursor()
    train_roky = [r for r in ROKY_HISTORICKE if r != HOLDOUT_ROK]
    train_hod = []
    for r in train_roky:
        v = cur.execute(
            "SELECT SUM(osob_celkem) FROM scitani WHERE rok=?", (r,)
        ).fetchone()[0]
        train_hod.append(v)

    sk = cur.execute(
        "SELECT SUM(osob_celkem) FROM scitani WHERE rok=?", (HOLDOUT_ROK,)
    ).fetchone()[0]

    ex = fit_exp(train_roky, train_hod)
    ln = fit_lin(train_roky, train_hod)
    rc = fit_recent(train_roky, train_hod, n_last=2)

    out = {"skutecnost": sk, "train_roky": train_roky, "train_hod": train_hod}
    if ex:
        r = predikuj_exp(ex, HOLDOUT_ROK)
        out["exp"]    = r[0]
        out["exp_ci"] = (r[1], r[2])
        out["exp_chyba_pct"] = (r[0] - sk) / sk * 100
    if ln:
        out["lin"] = predikuj_lin(ln, HOLDOUT_ROK)
        out["lin_chyba_pct"] = (out["lin"] - sk) / sk * 100
    if rc:
        r = predikuj_exp(rc, HOLDOUT_ROK)
        out["recent"] = r[0]
        out["recent_chyba_pct"] = (r[0] - sk) / sk * 100

    return out


def main() -> None:
    conn = sqlite3.connect(DB_FILE)

    print(f"=== Leave-{HOLDOUT_ROK}-out validace ===\n")

    # ── 1. Diecéze ───────────────────────────────────────────────────────────
    diec = validace_dieceze(conn)
    lines = [f"=== Leave-{HOLDOUT_ROK}-out validace predikčního modelu ===", ""]
    lines.append("## DIECÉZE")
    lines.append(f"Trénink: roky {diec['train_roky']}")
    lines.append(f"Trénink hodnoty: {diec['train_hod']}")
    lines.append(f"Skutečnost {HOLDOUT_ROK}: {diec['skutecnost']:,}".replace(",", " "))
    lines.append("")
    if "exp" in diec:
        lo, hi = diec["exp_ci"]
        chk = "✓" if lo <= diec["skutecnost"] <= hi else "✗"
        lines.append(f"  Exp model     : {diec['exp']:,.0f}  CI=[{lo:,.0f}; {hi:,.0f}]  "
                     f"chyba={diec['exp_chyba_pct']:+.1f}%  v CI={chk}")
    if "lin" in diec:
        lines.append(f"  Lin model     : {diec['lin']:,.0f}  chyba={diec['lin_chyba_pct']:+.1f}%")
    if "recent" in diec:
        lines.append(f"  Recent (2b)   : {diec['recent']:,.0f}  chyba={diec['recent_chyba_pct']:+.1f}%")
    lines.append("")

    # ── 2. Farnosti ──────────────────────────────────────────────────────────
    pred_exp, pred_lin, pred_rec = validace_farnost(conn)
    skut = skutecnost_farnost(conn)

    common_far = set(pred_exp) & set(skut)
    farnosti = sorted(common_far)
    skut_arr = [skut[f] for f in farnosti]
    exp_arr  = [pred_exp[f] for f in farnosti]
    lin_arr  = [pred_lin.get(f) for f in farnosti]
    rec_arr  = [pred_rec.get(f) for f in farnosti]

    lines.append(f"## FARNOSTI (n={len(farnosti)})")
    for name, arr in (("Exp", exp_arr), ("Lin", lin_arr), ("Recent", rec_arr)):
        m = metrics(skut_arr, arr)
        if m["n"] == 0:
            continue
        lines.append(f"  {name:<8} n={m['n']:>3}  MAPE={m['mape']:6.1f}%  "
                     f"wMAPE={m['wmape']:6.1f}%  RMSE={m['rmse']:6.1f}  "
                     f"bias={m['bias']:+.1f}")
    lines.append("")

    # ── 3. Děkanáty ──────────────────────────────────────────────────────────
    lines.append("## DĚKANÁTY")
    cur = conn.cursor()
    dek_data: dict[str, dict[int, float | None]] = {}
    cur.execute("""
        SELECT dekanat, rok, SUM(osob_celkem)
        FROM scitani WHERE rok != ?
        GROUP BY dekanat, rok
    """, (HOLDOUT_ROK,))
    for d, r, v in cur.fetchall():
        dek_data.setdefault(d, {})[r] = v

    cur.execute("SELECT dekanat, SUM(osob_celkem) FROM scitani WHERE rok=? GROUP BY dekanat",
                (HOLDOUT_ROK,))
    dek_skut = {d: v for d, v in cur.fetchall()}

    train_roky = [r for r in ROKY_HISTORICKE if r != HOLDOUT_ROK]
    lines.append(f"{'Děkanát':<14} {'Skut':>7} {'Exp':>7} {'Δ%':>7} {'Lin':>7} {'Δ%':>7} {'Rec':>7} {'Δ%':>7}")
    lines.append("-" * 70)
    for d in sorted(dek_data):
        hod = [dek_data[d].get(r) for r in train_roky]
        roky_v = [r for r, h in zip(train_roky, hod) if h is not None]
        hod_v  = [h for h in hod if h is not None]
        if len(hod_v) < 2:
            continue
        sk = dek_skut.get(d, 0)
        ex = fit_exp(roky_v, hod_v)
        ln = fit_lin(roky_v, hod_v)
        rc = fit_recent(roky_v, hod_v, n_last=2)
        ex_v = predikuj_exp(ex, HOLDOUT_ROK)[0] if ex else None
        ln_v = predikuj_lin(ln, HOLDOUT_ROK) if ln else None
        rc_v = predikuj_exp(rc, HOLDOUT_ROK)[0] if rc else None
        def fmt(v):
            return f"{v:>7.0f}" if v is not None else "      —"
        def err(v):
            return f"{(v-sk)/sk*100:+6.1f}%" if v is not None and sk else "      —"
        lines.append(f"{d:<14} {sk:>7.0f} {fmt(ex_v)} {err(ex_v)} {fmt(ln_v)} {err(ln_v)} {fmt(rc_v)} {err(rc_v)}")
    lines.append("")

    # ── 4. Závěr ─────────────────────────────────────────────────────────────
    lines.append("## Interpretace")
    lines.append(f"- MAPE napříč farnostmi pro exp model říká: typicky se 5-letá predikce")
    lines.append(f"  liší o tuto hodnotu %. Pro horizont 2039 (15 let) může chyba lineárně růst.")
    lines.append(f"- Pokud je 'v CI' = ✓ na diecézní úrovni, predikční interval funguje.")
    lines.append(f"- bias > 0 = model nadhodnocuje skutečnost (predikce ≥ skutečnost).")

    output = "\n".join(lines)
    OUT_FILE.write_text(output, encoding="utf-8")
    print(output)
    print(f"\nUloženo: {OUT_FILE}")

    conn.close()


if __name__ == "__main__":
    main()
