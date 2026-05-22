#!/usr/bin/env python3
"""
Predikce počtu věřících na základě sčítání 1999–2024.

Modely:
- Exponenciální pokles: y = a·exp(b·t), fit OLS na log(y) (pouze body y>0)
- Lineární regrese:    y = a + b·t
- Recent trend (exp):  fit jen z posledních 2 bodů (lokální tempo)

Úrovně: diecéze, děkanát, farnost.

Výstup: tabulky predikce_dieceze, predikce_dekanat, predikce_farnost v scitani.db,
plus tabulka predikce_farnost_model s parametry modelu a R² (v log prostoru pro exp).

Klíčové vlastnosti:
- NULL hodnoty v scitani jsou zachovány jako NULL (nikoli mapovány na 0).
- Predikce má sloupec validni (1/0) — 0 znamená méně než MIN_BODY validních pozorování
  nebo R²_exp < R2_PRAH. Klient by neměl validni=0 predikce používat pro plánování.
- 90% predikční interval (pred_lo, pred_hi) pro exp model je odvozen ze
  standardní chyby reziduí v log prostoru.
"""

import math
import sqlite3
from pathlib import Path

import numpy as np
from statsmodels.tsa.holtwinters import ExponentialSmoothing as HW

DB_FILE = Path(__file__).parent / "scitani.db"
ROKY_HISTORICKE = [1999, 2004, 2009, 2014, 2019, 2024]
ROKY_PREDIKCE   = [2029, 2034, 2039]
VSECHNY_ROKY    = ROKY_HISTORICKE + ROKY_PREDIKCE

MIN_BODY = 4        # minimální počet nenulových bodů pro důvěryhodný fit
R2_PRAH  = 0.5      # exp R² (log space) pod tímto prahem → predikce není validní
CI_Z     = 1.645    # 90% z-skóre pro predikční interval


# ── fit funkce ────────────────────────────────────────────────────────────────

def fit_exp(roky: list[int], hodnoty: list[float]) -> dict | None:
    """Fituje y = a·exp(b·t) metodou OLS na log(y), pouze body y > 0.
    Vrací dict s a, b, sigma_log (rozptyl reziduí log y), r2_log nebo None."""
    t = np.array([r - 1999 for r in roky], dtype=float)
    y = np.array(hodnoty, dtype=float)
    mask = y > 0
    if mask.sum() < 2:
        return None
    log_y = np.log(y[mask])
    t_m = t[mask]
    b, log_a = np.polyfit(t_m, log_y, 1)
    a = math.exp(log_a)

    # R² v log prostoru (konzistentně s OLS minimalizovanou funkcí)
    log_yhat = log_a + b * t_m
    ss_res = float(np.sum((log_y - log_yhat) ** 2))
    ss_tot = float(np.sum((log_y - log_y.mean()) ** 2))
    r2_log = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Reziduální směrodatná odchylka v log prostoru (pro CI)
    n = len(t_m)
    sigma_log = math.sqrt(ss_res / max(n - 2, 1)) if n > 2 else 0.0

    return {"a": a, "b": b, "n": n, "r2_log": r2_log, "sigma_log": sigma_log}


def fit_lin(roky: list[int], hodnoty: list[float]) -> dict | None:
    """Fituje y = a + b·t (ignoruje pouze NULL, ne nuly)."""
    t = np.array([r - 1999 for r in roky], dtype=float)
    y = np.array(hodnoty, dtype=float)
    if len(y) < 2:
        return None
    b, a = np.polyfit(t, y, 1)
    yhat = a + b * t
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"a": a, "b": b, "n": len(y), "r2": r2}


def fit_recent(roky: list[int], hodnoty: list[float], n_last: int = 2) -> dict | None:
    """Fituje exp model z posledních n_last bodů (lokální tempo)."""
    pairs = [(r, h) for r, h in zip(roky, hodnoty) if h is not None and h > 0]
    if len(pairs) < n_last:
        return None
    pairs = pairs[-n_last:]
    r2, h2 = pairs[-1]
    r1, h1 = pairs[0]
    if r2 == r1:
        return None
    b = (math.log(h2) - math.log(h1)) / (r2 - r1)
    # a tak, aby model šel přesně přes poslední bod
    a = h2 / math.exp(b * (r2 - 1999))
    return {"a": a, "b": b, "n": n_last}


# ── predikce + CI ─────────────────────────────────────────────────────────────

def predikuj_exp(params: dict, rok: int) -> tuple[float, float, float] | None:
    """Vrátí (point, lo, hi) pro 90% predikční interval v exp modelu."""
    if params is None:
        return None
    t = rok - 1999
    log_yhat = math.log(params["a"]) + params["b"] * t
    sigma = params.get("sigma_log", 0.0)
    point = math.exp(log_yhat)
    lo = math.exp(log_yhat - CI_Z * sigma)
    hi = math.exp(log_yhat + CI_Z * sigma)
    return max(0.0, point), max(0.0, lo), max(0.0, hi)


def predikuj_lin(params: dict, rok: int) -> float | None:
    if params is None:
        return None
    t = rok - 1999
    return max(0.0, params["a"] + params["b"] * t)


def fit_holt(roky: list[int], hodnoty: list[float | None]) -> dict | None:
    """Holt's damped ExponentialSmoothing (trend='add', damped_trend=True).
    Série je ošetřena jako rovnoměrně rozestupová (každý bod = 1 perioda = 5 let)."""
    pairs = [(r, h) for r, h in zip(roky, hodnoty) if h is not None]
    if len(pairs) < 3:
        return None
    y = np.array([p[1] for p in pairs], dtype=float)
    try:
        fit = HW(y, trend="add", damped_trend=True,
                 initialization_method="estimated").fit(optimized=True, remove_bias=False)
        return {
            "alpha":    float(fit.params["smoothing_level"]),
            "beta":     float(fit.params["smoothing_trend"]),
            "phi":      float(fit.params.get("damping_trend", 1.0)),
            "l_T":      float(np.asarray(fit.level)[-1]),
            "b_T":      float(np.asarray(fit.trend)[-1]),
            "n":        len(y),
            "last_rok": pairs[-1][0],
        }
    except Exception:
        return None


def predikuj_holt(params: dict, rok: int) -> float | None:
    """h-kroková predikce Holtova modelu; h = (rok − last_rok) / 5."""
    if params is None:
        return None
    h = (rok - params["last_rok"]) // 5
    if h <= 0:
        return None
    phi = params["phi"]
    if abs(phi - 1.0) < 1e-6:
        val = params["l_T"] + h * params["b_T"]
    else:
        phi_sum = phi * (1 - phi ** h) / (1 - phi)
        val = params["l_T"] + phi_sum * params["b_T"]
    return max(0, round(val))


# ── orchestrace ───────────────────────────────────────────────────────────────

def zpracuj_skupinu(roky: list[int], hodnoty: list[float | None]) -> dict:
    """
    Vrátí dict s parametry modelů a predikcemi pro ROKY_PREDIKCE.
    Pole hodnoty může obsahovat None (NULL); takové body se ignorují.
    """
    pairs = [(r, h) for r, h in zip(roky, hodnoty) if h is not None]
    if len(pairs) < 2:
        return {
            "validni": 0, "duvod": "méně než 2 pozorování",
            "exp": None, "lin": None, "recent": None, "holt": None,
        }
    r_v = [p[0] for p in pairs]
    h_v = [p[1] for p in pairs]

    exp_p = fit_exp(r_v, h_v)
    lin_p = fit_lin(r_v, h_v)
    rec_p = fit_recent(r_v, h_v, n_last=2)
    hlt_p = fit_holt(r_v, h_v)

    # Validita
    n_pos = sum(1 for h in h_v if h > 0)
    if n_pos < MIN_BODY:
        validni = 0
        duvod = f"jen {n_pos} kladných pozorování (< {MIN_BODY})"
    elif exp_p is None or exp_p["r2_log"] < R2_PRAH:
        validni = 0
        duvod = f"R²_exp (log space) = {exp_p['r2_log']:.2f} < {R2_PRAH}" if exp_p else "exp fit selhal"
    else:
        validni = 1
        duvod = None

    pred = {}
    for rok in ROKY_PREDIKCE:
        exp_t = predikuj_exp(exp_p, rok) if exp_p else None
        lin_v = predikuj_lin(lin_p, rok) if lin_p else None
        rec_t = predikuj_exp(rec_p, rok) if rec_p else None
        hlt_v = predikuj_holt(hlt_p, rok) if hlt_p else None
        pred[rok] = {
            "exp":     round(exp_t[0]) if exp_t else None,
            "exp_lo":  round(exp_t[1]) if exp_t else None,
            "exp_hi":  round(exp_t[2]) if exp_t else None,
            "lin":     round(lin_v) if lin_v is not None else None,
            "recent":  round(rec_t[0]) if rec_t else None,
            "holt":    hlt_v,
        }
    return {
        "validni": validni, "duvod": duvod,
        "exp": exp_p, "lin": lin_p, "recent": rec_p, "holt": hlt_p, "pred": pred,
    }


# ── DB inicializace ───────────────────────────────────────────────────────────

def main() -> None:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    # ── 1. Agregace historických dat (NULL je zachováno) ─────────────────────
    def nacti(group_by: str) -> dict:
        cur.execute(f"""
            SELECT {group_by}, rok,
                   SUM(CASE WHEN osob_celkem IS NULL THEN 0 ELSE 1 END) AS pocet,
                   SUM(osob_celkem) AS celkem
            FROM scitani
            GROUP BY {group_by}, rok
            ORDER BY {group_by}, rok
        """)
        data: dict = {}
        for skupina, rok, pocet, celkem in cur.fetchall():
            # Pokud žádná farnost ve skupině neměla pro tento rok hodnotu, je NULL
            data.setdefault(skupina, {})[rok] = celkem if pocet > 0 else None
        return data

    diec_data: dict[int, float | None] = {}
    cur.execute("""
        SELECT rok,
               SUM(CASE WHEN osob_celkem IS NULL THEN 0 ELSE 1 END) AS pocet,
               SUM(osob_celkem) AS celkem
        FROM scitani GROUP BY rok ORDER BY rok
    """)
    for rok, pocet, celkem in cur.fetchall():
        diec_data[rok] = celkem if pocet > 0 else None

    dek_data = nacti("dekanat")
    far_data = nacti("farnost")

    # ── 2. Drop & recreate tabulky ────────────────────────────────────────────
    for tbl in ("predikce_dieceze", "predikce_dekanat",
                "predikce_farnost", "predikce_farnost_model"):
        cur.execute(f"DROP TABLE IF EXISTS {tbl}")

    cur.execute("""
        CREATE TABLE predikce_dieceze (
            rok      INTEGER PRIMARY KEY,
            hodnota  INTEGER,
            exp_val  REAL,
            exp_lo   REAL,
            exp_hi   REAL,
            lin_val  REAL,
            recent_val REAL,
            holt_val REAL
        )
    """)
    cur.execute("""
        CREATE TABLE predikce_dekanat (
            dekanat  TEXT    NOT NULL,
            rok      INTEGER NOT NULL,
            hodnota  INTEGER,
            exp_val  REAL,
            exp_lo   REAL,
            exp_hi   REAL,
            lin_val  REAL,
            recent_val REAL,
            holt_val REAL,
            r2_exp_log REAL,
            r2_lin   REAL,
            validni  INTEGER,
            PRIMARY KEY (dekanat, rok)
        )
    """)
    cur.execute("""
        CREATE TABLE predikce_farnost (
            farnost  TEXT    NOT NULL,
            rok      INTEGER NOT NULL,
            hodnota  INTEGER,
            exp_val  REAL,
            exp_lo   REAL,
            exp_hi   REAL,
            lin_val  REAL,
            recent_val REAL,
            holt_val REAL,
            r2_exp_log REAL,
            r2_lin   REAL,
            validni  INTEGER,
            PRIMARY KEY (farnost, rok)
        )
    """)
    cur.execute("""
        CREATE TABLE predikce_farnost_model (
            farnost          TEXT PRIMARY KEY,
            exp_a            REAL,
            exp_b            REAL,
            exp_n            INTEGER,
            r2_exp_log       REAL,
            sigma_log        REAL,
            lin_a            REAL,
            lin_b            REAL,
            r2_lin           REAL,
            recent_a         REAL,
            recent_b         REAL,
            holt_alpha       REAL,
            holt_beta        REAL,
            holt_phi         REAL,
            validni          INTEGER,
            duvod_invaliditn TEXT,
            zero_count       INTEGER,
            last_value       REAL,
            model_type       TEXT
        )
    """)

    # ── 3. Diecéze ────────────────────────────────────────────────────────────
    d_roky = ROKY_HISTORICKE
    d_hod  = [diec_data.get(r) for r in d_roky]
    d_res  = zpracuj_skupinu(d_roky, d_hod)

    for rok in ROKY_HISTORICKE:
        cur.execute("INSERT INTO predikce_dieceze VALUES (?,?,?,?,?,?,?,?)",
                    (rok, diec_data.get(rok), None, None, None, None, None, None))
    for rok in ROKY_PREDIKCE:
        p = d_res["pred"][rok]
        cur.execute("INSERT INTO predikce_dieceze VALUES (?,?,?,?,?,?,?,?)",
                    (rok, None, p["exp"], p["exp_lo"], p["exp_hi"], p["lin"], p["recent"], p["holt"]))

    print("=== DIECÉZE ===")
    if d_res["exp"]:
        print(f"  Exp model: a={d_res['exp']['a']:.1f}, b={d_res['exp']['b']:.4f}, "
              f"R²_log={d_res['exp']['r2_log']:.3f}, σ_log={d_res['exp']['sigma_log']:.3f}")
    if d_res["recent"]:
        annual = (math.exp(d_res['recent']['b']) - 1) * 100
        print(f"  Recent (poslední 2 body): {annual:.2f} %/rok")
    for rok in ROKY_PREDIKCE:
        p = d_res["pred"][rok]
        print(f"  {rok}: exp={p['exp']:,} (90% CI {p['exp_lo']:,}–{p['exp_hi']:,})  "
              f"lin={p['lin']:,}  recent={p['recent']:,}  holt={p['holt']}")

    # ── 4. Děkanáty ───────────────────────────────────────────────────────────
    print("\n=== DĚKANÁTY ===")
    for dek, rok_data in sorted(dek_data.items()):
        hod = [rok_data.get(r) for r in ROKY_HISTORICKE]
        res = zpracuj_skupinu(ROKY_HISTORICKE, hod)
        for rok in ROKY_HISTORICKE:
            cur.execute("INSERT INTO predikce_dekanat VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (dek, rok, rok_data.get(rok),
                         None, None, None, None, None, None, None, None, None))
        for rok in ROKY_PREDIKCE:
            p = res["pred"][rok] if "pred" in res else {"exp": None, "exp_lo": None, "exp_hi": None, "lin": None, "recent": None, "holt": None}
            cur.execute("INSERT INTO predikce_dekanat VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (dek, rok, None,
                         p["exp"], p["exp_lo"], p["exp_hi"], p["lin"], p["recent"], p.get("holt"),
                         res["exp"]["r2_log"] if res.get("exp") else None,
                         res["lin"]["r2"] if res.get("lin") else None,
                         res["validni"]))
        if res.get("exp"):
            p = res["pred"][2029]
            print(f"  {dek:<12}: 2029 exp={p['exp']:>5} ({p['exp_lo']:>5}–{p['exp_hi']:>5})  "
                  f"R²_log={res['exp']['r2_log']:.3f}  validni={res['validni']}")

    # ── 5. Farnosti ───────────────────────────────────────────────────────────
    print("\n=== FARNOSTI ===")
    n_validni = 0
    n_invalidni = 0
    for farnost, rok_data in sorted(far_data.items()):
        hod = [rok_data.get(r) for r in ROKY_HISTORICKE]
        res = zpracuj_skupinu(ROKY_HISTORICKE, hod)

        # Metadata o nulách (nula = skutečná nulová účast, ne chybějící hodnota)
        zero_count = sum(1 for h in hod if h is not None and h == 0)
        nn = [h for h in hod if h is not None]
        last_value = nn[-1] if nn else None
        if res["validni"] == 1:
            model_type = "exp_log_positive"
        elif last_value is not None and last_value == 0:
            model_type = "fallback_zero"
        elif last_value is not None and last_value > 0:
            model_type = "fallback_last_known"
        else:
            model_type = "fallback_no_data"

        for rok in ROKY_HISTORICKE:
            cur.execute("INSERT INTO predikce_farnost VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (farnost, rok, rok_data.get(rok),
                         None, None, None, None, None, None, None, None, None))
        for rok in ROKY_PREDIKCE:
            p = res["pred"][rok] if "pred" in res else {"exp": None, "exp_lo": None, "exp_hi": None, "lin": None, "recent": None, "holt": None}
            cur.execute("INSERT INTO predikce_farnost VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (farnost, rok, None,
                         p["exp"], p["exp_lo"], p["exp_hi"], p["lin"], p["recent"], p.get("holt"),
                         res["exp"]["r2_log"] if res.get("exp") else None,
                         res["lin"]["r2"] if res.get("lin") else None,
                         res["validni"]))

        # Tabulka modelů (1 řádek na farnost)
        cur.execute("INSERT INTO predikce_farnost_model VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (farnost,
                     res["exp"]["a"]        if res.get("exp")    else None,
                     res["exp"]["b"]        if res.get("exp")    else None,
                     res["exp"]["n"]        if res.get("exp")    else None,
                     res["exp"]["r2_log"]   if res.get("exp")    else None,
                     res["exp"]["sigma_log"] if res.get("exp")   else None,
                     res["lin"]["a"]        if res.get("lin")    else None,
                     res["lin"]["b"]        if res.get("lin")    else None,
                     res["lin"]["r2"]       if res.get("lin")    else None,
                     res["recent"]["a"]     if res.get("recent") else None,
                     res["recent"]["b"]     if res.get("recent") else None,
                     res["holt"]["alpha"]   if res.get("holt")   else None,
                     res["holt"]["beta"]    if res.get("holt")   else None,
                     res["holt"]["phi"]     if res.get("holt")   else None,
                     res["validni"],
                     res.get("duvod"),
                     zero_count, last_value, model_type))

        n_validni += res["validni"]
        n_invalidni += 1 - res["validni"]

    print(f"  Validních predikcí (R²_log ≥ {R2_PRAH} a ≥ {MIN_BODY} bodů): {n_validni}")
    print(f"  Neplatných: {n_invalidni}")

    conn.commit()
    conn.close()
    print("\nHotovo — tabulky predikce_dieceze, predikce_dekanat, predikce_farnost, "
          "predikce_farnost_model uloženy.")


if __name__ == "__main__":
    main()
