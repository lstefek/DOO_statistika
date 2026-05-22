#!/usr/bin/env python3
"""
Validace predikčního modelu — verze 3.

Rozšíření oproti v2:
- Segmentované metriky: validní/nevalidní, nuly v historii, velikostní pásma.
- Coverage: kolik skutečných hodnot spadlo do 90 % CI exp modelu.
- Rolling holdout: trénink 1999–2014, holdout 2019.
- Původní leave-2024-out zůstává zachováno.

Výstup: validace_predikce.txt
"""

import math
import sqlite3
from pathlib import Path

import numpy as np

from predikce import (
    ROKY_HISTORICKE, MIN_BODY, R2_PRAH, CI_Z,
    fit_exp, fit_lin, fit_recent,
    predikuj_exp, predikuj_lin,
)

DB_FILE  = Path(__file__).parent / "scitani.db"
OUT_FILE = Path(__file__).parent / "validace_predikce.txt"


# ── metriky ───────────────────────────────────────────────────────────────────

def metrics(skutecnost: list, predikce: list) -> dict:
    """MAPE, wMAPE, RMSE, bias, medAPE, podíl nadhodnocení."""
    pairs = [(s, p) for s, p in zip(skutecnost, predikce)
             if s is not None and p is not None and s > 0]
    if not pairs:
        return {"n": 0, "mape": None, "rmse": None, "wmape": None,
                "bias": None, "med_ape": None, "pct_over": None}
    s_arr = np.array([s for s, _ in pairs])
    p_arr = np.array([p for _, p in pairs])

    ape     = np.abs(s_arr - p_arr) / s_arr
    mape    = float(ape.mean()) * 100
    med_ape = float(np.median(ape)) * 100
    rmse    = float(np.sqrt(((s_arr - p_arr) ** 2).mean()))
    wmape   = float(np.abs(s_arr - p_arr).sum() / s_arr.sum()) * 100
    bias    = float((p_arr - s_arr).mean())
    pct_over = float((p_arr > s_arr).sum() / len(pairs)) * 100

    return {"n": len(pairs), "mape": mape, "rmse": rmse, "wmape": wmape,
            "bias": bias, "med_ape": med_ape, "pct_over": pct_over}


def fmt_metrics(m: dict) -> str:
    if m["n"] == 0:
        return "  (žádná data)"
    return (f"  n={m['n']:>3}  MAPE={m['mape']:6.1f}%  wMAPE={m['wmape']:6.1f}%  "
            f"RMSE={m['rmse']:6.1f}  bias={m['bias']:+.1f}  "
            f"medAPE={m['med_ape']:6.1f}%  nadhodnoceno={m['pct_over']:5.1f}%")


def coverage(skutecnost: list, pred_lo: list, pred_hi: list) -> str:
    pairs = [(s, lo, hi) for s, lo, hi in zip(skutecnost, pred_lo, pred_hi)
             if s is not None and lo is not None and hi is not None]
    if not pairs:
        return "N/A"
    inside = sum(1 for s, lo, hi in pairs if lo <= s <= hi)
    return f"{inside}/{len(pairs)} ({inside/len(pairs)*100:.1f} %)"


# ── fit + predikce farností ────────────────────────────────────────────────────

def fit_farnosti(
    conn, train_roky: list[int], holdout_rok: int
) -> tuple[dict, dict, dict, dict, dict]:
    """
    Fituje modely na train_roky a predikuje holdout_rok.
    Vrátí (pred_exp, pred_exp_lo, pred_exp_hi, pred_lin, pred_rec).
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT farnost, rok, osob_celkem FROM scitani
        WHERE rok != ? ORDER BY farnost, rok
    """, (holdout_rok,))
    by_far: dict = {}
    for far, rok, val in cur.fetchall():
        by_far.setdefault(far, {})[rok] = val

    p_exp, p_exp_lo, p_exp_hi, p_lin, p_rec = {}, {}, {}, {}, {}
    for far, rd in by_far.items():
        hod = [rd.get(r) for r in train_roky]
        rv = [r for r, h in zip(train_roky, hod) if h is not None]
        hv = [h for h in hod if h is not None]
        if len(hv) < 2:
            continue
        ex = fit_exp(rv, hv)
        if ex:
            r = predikuj_exp(ex, holdout_rok)
            if r:
                p_exp[far], p_exp_lo[far], p_exp_hi[far] = r
        ln = fit_lin(rv, hv)
        if ln:
            p_lin[far] = predikuj_lin(ln, holdout_rok)
        rc = fit_recent(rv, hv, n_last=2)
        if rc:
            r = predikuj_exp(rc, holdout_rok)
            if r:
                p_rec[far] = r[0]
    return p_exp, p_exp_lo, p_exp_hi, p_lin, p_rec


def skutecnost_farnost(conn, rok: int) -> dict[str, float]:
    cur = conn.cursor()
    cur.execute(
        "SELECT farnost, osob_celkem FROM scitani WHERE rok=? AND osob_celkem IS NOT NULL",
        (rok,)
    )
    return {f: float(v) for f, v in cur.fetchall()}


# ── segmenty ──────────────────────────────────────────────────────────────────

def nacti_segmenty(conn) -> dict[str, set]:
    """Vrátí sety farností pro každý segment."""
    cur = conn.cursor()

    validni_set = set(r[0] for r in cur.execute(
        "SELECT farnost FROM predikce_farnost_model WHERE validni=1"
    ).fetchall())
    invalidni_set = set(r[0] for r in cur.execute(
        "SELECT farnost FROM predikce_farnost_model WHERE validni=0"
    ).fetchall())
    nuly_set = set(r[0] for r in cur.execute(
        "SELECT farnost FROM predikce_farnost_model WHERE zero_count > 0"
    ).fetchall())

    # Velikostní pásma podle skutečnosti v posledním roce
    cur.execute("""
        SELECT farnost, osob_celkem FROM scitani
        WHERE rok = (SELECT MAX(rok) FROM scitani)
          AND osob_celkem IS NOT NULL
    """)
    pas_0, pas_1_29, pas_30_99, pas_100 = set(), set(), set(), set()
    for f, v in cur.fetchall():
        if v == 0:      pas_0.add(f)
        elif v < 30:    pas_1_29.add(f)
        elif v < 100:   pas_30_99.add(f)
        else:           pas_100.add(f)

    return {
        "validni":    validni_set,
        "invalidni":  invalidni_set,
        "s_nulou":    nuly_set,
        "pas_0":      pas_0,
        "pas_1_29":   pas_1_29,
        "pas_30_99":  pas_30_99,
        "pas_100":    pas_100,
    }


# ── diecézní validace ──────────────────────────────────────────────────────────

def validace_dieceze(conn, train_roky: list[int], holdout_rok: int) -> dict:
    cur = conn.cursor()
    train_hod = []
    for r in train_roky:
        v = cur.execute(
            "SELECT SUM(osob_celkem) FROM scitani WHERE rok=?", (r,)
        ).fetchone()[0]
        train_hod.append(v)
    sk = cur.execute(
        "SELECT SUM(osob_celkem) FROM scitani WHERE rok=?", (holdout_rok,)
    ).fetchone()[0]

    ex = fit_exp(train_roky, train_hod)
    ln = fit_lin(train_roky, train_hod)
    rc = fit_recent(train_roky, train_hod, n_last=2)

    out = {"skutecnost": sk, "train_roky": train_roky, "train_hod": train_hod}
    if ex:
        r = predikuj_exp(ex, holdout_rok)
        out["exp"] = r[0]; out["exp_ci"] = (r[1], r[2])
        out["exp_chyba_pct"] = (r[0] - sk) / sk * 100
    if ln:
        out["lin"] = predikuj_lin(ln, holdout_rok)
        out["lin_chyba_pct"] = (out["lin"] - sk) / sk * 100
    if rc:
        r = predikuj_exp(rc, holdout_rok)
        out["recent"] = r[0]
        out["recent_chyba_pct"] = (r[0] - sk) / sk * 100
    return out


# ── hlavní výstup ─────────────────────────────────────────────────────────────

def main() -> None:
    conn = sqlite3.connect(DB_FILE)
    lines = []

    def h(txt):  lines.append(txt)
    def nl():    lines.append("")

    # ── A. Leave-2024-out (původní) ──────────────────────────────────────────
    HOLDOUT = 2024
    TRAIN   = [r for r in ROKY_HISTORICKE if r != HOLDOUT]

    h(f"=== Leave-{HOLDOUT}-out validace predikčního modelu — verze 3 ==="); nl()

    # Diecéze
    diec = validace_dieceze(conn, TRAIN, HOLDOUT)
    h("## 1. DIECÉZE — leave-2024-out")
    h(f"Trénink: {diec['train_roky']}  →  predikce {HOLDOUT}")
    h(f"Skutečnost {HOLDOUT}: {diec['skutecnost']:,.0f}".replace(",", " ")); nl()
    if "exp" in diec:
        lo, hi = diec["exp_ci"]
        chk = "✓ v CI" if lo <= diec["skutecnost"] <= hi else "✗ MIMO CI"
        h(f"  Exp    : {diec['exp']:>8,.0f}  CI=[{lo:,.0f}; {hi:,.0f}]  "
          f"chyba={diec['exp_chyba_pct']:+.1f}%  {chk}".replace(",", " "))
        h("  Poznámka: 90% CI exp modelu je empiricky podkalibrovaný — "
          "nezachycuje nejistotu parametrů ani strukturální zrychlení poklesu.")
    if "lin" in diec:
        h(f"  Lin    : {diec['lin']:>8,.0f}  chyba={diec['lin_chyba_pct']:+.1f}%".replace(",", " "))
    if "recent" in diec:
        h(f"  Recent : {diec['recent']:>8,.0f}  chyba={diec['recent_chyba_pct']:+.1f}%".replace(",", " "))
    nl()

    # Farnosti — leave-2024-out
    p_exp, p_lo, p_hi, p_lin, p_rec = fit_farnosti(conn, TRAIN, HOLDOUT)
    skut = skutecnost_farnost(conn, HOLDOUT)
    seg  = nacti_segmenty(conn)

    common = sorted(set(p_exp) & set(skut))
    s_arr  = [skut[f] for f in common]
    e_arr  = [p_exp.get(f) for f in common]
    l_arr  = [p_lin.get(f) for f in common]
    r_arr  = [p_rec.get(f) for f in common]
    lo_arr = [p_lo.get(f) for f in common]
    hi_arr = [p_hi.get(f) for f in common]

    h("## 2. FARNOSTI — leave-2024-out, celkové metriky")
    for name, arr in (("Exp", e_arr), ("Lin", l_arr), ("Recent", r_arr)):
        h(f"  {name:<8}:" + fmt_metrics(metrics(s_arr, arr)))
    h(f"  Coverage 90% CI exp: {coverage(s_arr, lo_arr, hi_arr)}")
    nl()

    # Segmentované metriky
    h("## 3. FARNOSTI — segmentované metriky (exp model, leave-2024-out)")
    segmenty = [
        ("validni",   "Validní predikce (validni=1)"),
        ("invalidni", "Nevalidní predikce (validni=0)"),
        ("s_nulou",   "Farnosti s alespoň jednou nulou v historii"),
        ("pas_0",     "Velikost 2024 = 0"),
        ("pas_1_29",  "Velikost 2024 = 1–29"),
        ("pas_30_99", "Velikost 2024 = 30–99"),
        ("pas_100",   "Velikost 2024 ≥ 100"),
    ]
    for seg_key, seg_label in segmenty:
        farnosti_seg = seg[seg_key]
        idx = [i for i, f in enumerate(common) if f in farnosti_seg]
        if not idx:
            h(f"  {seg_label}: (žádné farnosti)")
            continue
        ss = [s_arr[i] for i in idx]
        ee = [e_arr[i] for i in idx]
        lo_s = [lo_arr[i] for i in idx]
        hi_s = [hi_arr[i] for i in idx]
        m = metrics(ss, ee)
        cov = coverage(ss, lo_s, hi_s)
        h(f"  {seg_label}:")
        h(fmt_metrics(m) + f"  coverage={cov}")
    nl()

    # ── B. Rolling holdout: trénink 1999–2014, holdout 2019 ──────────────────
    HOLDOUT2 = 2019
    TRAIN2   = [r for r in ROKY_HISTORICKE if r not in (HOLDOUT, HOLDOUT2)]

    h("## 4. DIECÉZE — rolling holdout (trénink 1999–2014, holdout 2019)")
    diec2 = validace_dieceze(conn, TRAIN2, HOLDOUT2)
    h(f"Trénink: {diec2['train_roky']}  →  predikce {HOLDOUT2}")
    h(f"Skutečnost {HOLDOUT2}: {diec2['skutecnost']:,.0f}".replace(",", " ")); nl()
    if "exp" in diec2:
        lo, hi = diec2["exp_ci"]
        chk = "✓ v CI" if lo <= diec2["skutecnost"] <= hi else "✗ MIMO CI"
        h(f"  Exp    : {diec2['exp']:>8,.0f}  CI=[{lo:,.0f}; {hi:,.0f}]  "
          f"chyba={diec2['exp_chyba_pct']:+.1f}%  {chk}".replace(",", " "))
    if "lin" in diec2:
        h(f"  Lin    : {diec2['lin']:>8,.0f}  chyba={diec2['lin_chyba_pct']:+.1f}%".replace(",", " "))
    if "recent" in diec2:
        h(f"  Recent : {diec2['recent']:>8,.0f}  chyba={diec2['recent_chyba_pct']:+.1f}%".replace(",", " "))
    nl()

    p_exp2, p_lo2, p_hi2, p_lin2, p_rec2 = fit_farnosti(conn, TRAIN2, HOLDOUT2)
    skut2 = skutecnost_farnost(conn, HOLDOUT2)
    common2 = sorted(set(p_exp2) & set(skut2))
    s2 = [skut2[f] for f in common2]
    e2 = [p_exp2.get(f) for f in common2]
    l2 = [p_lin2.get(f) for f in common2]
    r2 = [p_rec2.get(f) for f in common2]
    lo2 = [p_lo2.get(f) for f in common2]
    hi2 = [p_hi2.get(f) for f in common2]

    h("## 5. FARNOSTI — rolling holdout (trénink 1999–2014, holdout 2019)")
    for name, arr in (("Exp", e2), ("Lin", l2), ("Recent", r2)):
        h(f"  {name:<8}:" + fmt_metrics(metrics(s2, arr)))
    h(f"  Coverage 90% CI exp: {coverage(s2, lo2, hi2)}")
    nl()

    # ── C. Děkanáty — leave-2024-out ─────────────────────────────────────────
    h("## 6. DĚKANÁTY — leave-2024-out")
    cur = conn.cursor()
    dek_data: dict = {}
    cur.execute("""
        SELECT dekanat, rok, SUM(osob_celkem) FROM scitani
        WHERE rok != ? GROUP BY dekanat, rok
    """, (HOLDOUT,))
    for d, r, v in cur.fetchall():
        dek_data.setdefault(d, {})[r] = v
    cur.execute("SELECT dekanat, SUM(osob_celkem) FROM scitani WHERE rok=? GROUP BY dekanat",
                (HOLDOUT,))
    dek_skut = {d: v for d, v in cur.fetchall()}

    h(f"{'Děkanát':<14} {'Skut':>7} {'Exp':>7} {'Δ%':>7} {'Lin':>7} {'Δ%':>7} {'Rec':>7} {'Δ%':>7}")
    h("-" * 70)
    for d in sorted(dek_data):
        hod = [dek_data[d].get(r) for r in TRAIN]
        rv = [r for r, h_ in zip(TRAIN, hod) if h_ is not None]
        hv = [h_ for h_ in hod if h_ is not None]
        if len(hv) < 2:
            continue
        sk = dek_skut.get(d, 0)
        ex = fit_exp(rv, hv)
        ln = fit_lin(rv, hv)
        rc = fit_recent(rv, hv, n_last=2)
        ex_v = predikuj_exp(ex, HOLDOUT)[0] if ex else None
        ln_v = predikuj_lin(ln, HOLDOUT) if ln else None
        rc_v = predikuj_exp(rc, HOLDOUT)[0] if rc else None

        def fmt(v): return f"{v:>7.0f}" if v is not None else "      —"
        def err(v): return f"{(v-sk)/sk*100:+6.1f}%" if v is not None and sk else "      —"
        h(f"{d:<14} {sk:>7.0f} {fmt(ex_v)} {err(ex_v)} {fmt(ln_v)} {err(ln_v)} {fmt(rc_v)} {err(rc_v)}")
    nl()

    # ── D. Kapacitní model — přehled zdrojů ──────────────────────────────────
    h("## 7. KAPACITNÍ MODEL — věřící podle zdroje (rok > 2024)")
    rows = cur.execute("""
        SELECT rok, vericich_zdroj, COUNT(*) AS farnosti, ROUND(SUM(vericich), 0) AS vericich_sum
        FROM kapacitni_model
        WHERE rok > 2024
        GROUP BY rok, vericich_zdroj
        ORDER BY rok, vericich_zdroj
    """).fetchall()
    if rows:
        h(f"  {'Rok':>4}  {'Zdroj':<25}  {'Farnosti':>8}  {'Věřících':>10}")
        h("  " + "-" * 55)
        for rok_k, zdroj, far_k, ver_k in rows:
            h(f"  {rok_k:>4}  {zdroj:<25}  {far_k:>8}  {ver_k:>10,.0f}".replace(",", " "))
    nl()

    # Akceptační kritérium: žádná neplatná predikce jako model_valid
    invalid_as_valid = cur.execute("""
        SELECT COUNT(*) FROM kapacitni_model
        WHERE rok > 2024 AND predikce_validni = 0 AND vericich_zdroj = 'model_valid'
    """).fetchone()[0]
    h(f"  Akceptační kritérium — invalid_used_as_valid = {invalid_as_valid} "
      f"({'OK' if invalid_as_valid == 0 else 'CHYBA — neplatné predikce v modelu!'})")
    nl()

    # ── E. Farnosti s nulou ───────────────────────────────────────────────────
    h("## 8. FARNOSTI S NULOVOU ÚČASTÍ V POSLEDNÍM ROCE (2024)")
    nuly = cur.execute("""
        SELECT s.farnost, s.dekanat, s.osob_celkem AS v2024,
               p.exp_val AS exp2039, m.validni, m.model_type
        FROM scitani s
        LEFT JOIN predikce_farnost p ON p.farnost = s.farnost AND p.rok = 2039
        LEFT JOIN predikce_farnost_model m ON m.farnost = s.farnost
        WHERE s.rok = 2024 AND s.osob_celkem = 0
        ORDER BY exp2039 DESC NULLS LAST
    """).fetchall()
    h(f"  {'Farnost':<30} {'Děk':>10} {'v2024':>6} {'exp2039':>8} {'validni':>8} {'model_type'}")
    h("  " + "-" * 80)
    for row in nuly:
        far, dek, v24, e39, val, mtype = row
        h(f"  {far:<30} {dek:>10} {v24 or 0:>6} "
          f"{e39 or 0:>8.0f} {val or 0:>8}  {mtype or '—'}")
    nl()

    # ── F. Interpretace ───────────────────────────────────────────────────────
    h("## 9. INTERPRETACE A OMEZENÍ")
    h("- MAPE a wMAPE jsou vypočítány pouze pro farnosti se skutečností > 0.")
    h("- Segmentace odhaluje výrazný rozdíl: nevalidní predikce mají výrazně vyšší chybu.")
    h("- Coverage 90% CI exp modelu ukazuje, zda interval byl kalibrovaný.")
    h("- Pokud coverage << 90 %, CI je podkalibrovaný (příliš úzký).")
    h("- Rolling holdout (1999–2014→2019) testuje 5-letou extrapolaci dříve v čase.")
    h("- bias > 0 = model nadhodnocuje skutečnost.")
    h("- Kapacitní model v3 používá POUZE validní predikce (validni=1); nevalidní")
    h("  farnosti dostanou fallback last_known nebo fallback_zero.")
    nl()

    output = "\n".join(lines)
    OUT_FILE.write_text(output, encoding="utf-8")
    print(output)
    print(f"\nUloženo: {OUT_FILE}")
    conn.close()


if __name__ == "__main__":
    main()
