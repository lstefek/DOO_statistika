#!/usr/bin/env python3
"""
Predikce počtu věřících na základě sčítání 1999–2024.
Modely: exponenciální pokles + lineární regrese.
Úrovně: diecéze, děkanát, farnost.
Výstup: tabulky predikce_dieceze, predikce_dekanat, predikce_farnost v scitani.db.
"""

import math
import sqlite3
from pathlib import Path

import numpy as np

DB_FILE = Path(__file__).parent / "scitani.db"
ROKY_HISTORICKE = [1999, 2004, 2009, 2014, 2019, 2024]
ROKY_PREDIKCE   = [2029, 2034, 2039]
VSECHNY_ROKY    = ROKY_HISTORICKE + ROKY_PREDIKCE


def fit_exp(roky: list[int], hodnoty: list[float]) -> tuple[float, float] | None:
    """Fituje y = a * exp(b * (rok - 1999)) metodou OLS na log(y)."""
    t = np.array([r - 1999 for r in roky], dtype=float)
    y = np.array(hodnoty, dtype=float)
    mask = y > 0
    if mask.sum() < 2:
        return None
    log_y = np.log(y[mask])
    t_m = t[mask]
    b, log_a = np.polyfit(t_m, log_y, 1)
    a = math.exp(log_a)
    return a, b


def fit_lin(roky: list[int], hodnoty: list[float]) -> tuple[float, float]:
    """Fituje y = a + b * (rok - 1999)."""
    t = np.array([r - 1999 for r in roky], dtype=float)
    y = np.array(hodnoty, dtype=float)
    b, a = np.polyfit(t, y, 1)
    return a, b


def predikuj(a_exp, b_exp, a_lin, b_lin, rok: int) -> tuple[float | None, float]:
    t = rok - 1999
    exp_val = max(0.0, a_exp * math.exp(b_exp * t)) if a_exp is not None else None
    lin_val = max(0.0, a_lin + b_lin * t)
    return exp_val, lin_val


def r2(roky, hodnoty, a, b, model="exp") -> float:
    y = np.array(hodnoty, dtype=float)
    t = np.array([r - 1999 for r in roky], dtype=float)
    if model == "exp":
        y_hat = np.array([max(0.0, a * math.exp(b * ti)) for ti in t])
    else:
        y_hat = a + b * t
    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0


def zpracuj_skupinu(roky: list[int], hodnoty: list[float]) -> dict:
    """Vrátí dict s parametry modelu a predikcemi."""
    exp_params = fit_exp(roky, hodnoty)
    a_e, b_e = exp_params if exp_params else (None, None)
    a_l, b_l = fit_lin(roky, hodnoty)

    r2_exp = r2(roky, hodnoty, a_e, b_e, "exp") if a_e is not None else None
    r2_lin = r2(roky, hodnoty, a_l, b_l, "lin")

    result = {
        "exp_a": a_e, "exp_b": b_e, "r2_exp": r2_exp,
        "lin_a": a_l, "lin_b": b_l, "r2_lin": r2_lin,
    }
    for rok in ROKY_PREDIKCE:
        e_val, l_val = predikuj(a_e, b_e, a_l, b_l, rok)
        result[f"exp_{rok}"] = round(e_val) if e_val is not None else None
        result[f"lin_{rok}"] = round(l_val)
    return result


def create_table(cur, nazev: str, klice: list[tuple[str, str]]) -> None:
    cols = "\n".join(f"    {k} {t}," for k, t in klice)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {nazev} (
        {cols}
        PRIMARY KEY ({klice[0][0]})
        )
    """)


def main() -> None:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    # ── 1. Agregace historických dat ─────────────────────────────────────────
    def nacti(group_by: str) -> dict:
        cur.execute(f"""
            SELECT {group_by}, rok, SUM(osob_celkem)
            FROM scitani
            GROUP BY {group_by}, rok
            ORDER BY {group_by}, rok
        """)
        data: dict = {}
        for skupina, rok, celkem in cur.fetchall():
            data.setdefault(skupina, {})[rok] = celkem or 0
        return data

    diec_data: dict[int, float] = {}
    cur.execute("SELECT rok, SUM(osob_celkem) FROM scitani GROUP BY rok ORDER BY rok")
    for rok, celkem in cur.fetchall():
        diec_data[rok] = celkem or 0

    dek_data  = nacti("dekanat")
    far_data  = nacti("farnost")

    # ── 2. Tabulky predikce ───────────────────────────────────────────────────
    pred_cols = [
        ("rok",     "INTEGER NOT NULL"),
        ("exp_val", "REAL"),
        ("lin_val", "REAL"),
    ]

    for tbl in ("predikce_dieceze", "predikce_dekanat", "predikce_farnost"):
        cur.execute(f"DROP TABLE IF EXISTS {tbl}")

    cur.execute("""
        CREATE TABLE predikce_dieceze (
            rok      INTEGER PRIMARY KEY,
            hodnota  INTEGER,
            exp_val  REAL,
            lin_val  REAL
        )
    """)
    cur.execute("""
        CREATE TABLE predikce_dekanat (
            dekanat  TEXT    NOT NULL,
            rok      INTEGER NOT NULL,
            hodnota  INTEGER,
            exp_val  REAL,
            lin_val  REAL,
            r2_exp   REAL,
            r2_lin   REAL,
            PRIMARY KEY (dekanat, rok)
        )
    """)
    cur.execute("""
        CREATE TABLE predikce_farnost (
            farnost  TEXT    NOT NULL,
            rok      INTEGER NOT NULL,
            hodnota  INTEGER,
            exp_val  REAL,
            lin_val  REAL,
            r2_exp   REAL,
            r2_lin   REAL,
            PRIMARY KEY (farnost, rok)
        )
    """)

    # ── 3. Diecéze ────────────────────────────────────────────────────────────
    d_roky = [r for r in ROKY_HISTORICKE if r in diec_data]
    d_hod  = [diec_data[r] for r in d_roky]
    d_res  = zpracuj_skupinu(d_roky, d_hod)

    for rok in ROKY_HISTORICKE:
        cur.execute("INSERT INTO predikce_dieceze VALUES (?,?,?,?)",
                    (rok, diec_data.get(rok), None, None))
    for rok in ROKY_PREDIKCE:
        cur.execute("INSERT INTO predikce_dieceze VALUES (?,?,?,?)",
                    (rok, None, d_res[f"exp_{rok}"], d_res[f"lin_{rok}"]))

    print("=== DIECÉZE ===")
    print(f"  Exp model: a={d_res['exp_a']:.1f}, b={d_res['exp_b']:.4f}, R²={d_res['r2_exp']:.3f}")
    print(f"  Lin model: R²={d_res['r2_lin']:.3f}")
    for rok in ROKY_PREDIKCE:
        print(f"  {rok}: exp={d_res[f'exp_{rok}']:,}  lin={d_res[f'lin_{rok}']:,}")

    # ── 4. Děkanáty ───────────────────────────────────────────────────────────
    print("\n=== DĚKANÁTY ===")
    for dek, rok_data in sorted(dek_data.items()):
        roky = [r for r in ROKY_HISTORICKE if r in rok_data]
        hod  = [rok_data[r] for r in roky]
        res  = zpracuj_skupinu(roky, hod)
        for rok in ROKY_HISTORICKE:
            cur.execute("INSERT INTO predikce_dekanat VALUES (?,?,?,?,?,?,?)",
                        (dek, rok, rok_data.get(rok), None, None, None, None))
        for rok in ROKY_PREDIKCE:
            cur.execute("INSERT INTO predikce_dekanat VALUES (?,?,?,?,?,?,?)",
                        (dek, rok, None,
                         res[f"exp_{rok}"], res[f"lin_{rok}"],
                         res["r2_exp"], res["r2_lin"]))
        print(f"  {dek}: 2029 exp={res['exp_2029']:,} lin={res['lin_2029']:,}  (R²_exp={res['r2_exp']:.3f})")

    # ── 5. Farnosti ───────────────────────────────────────────────────────────
    print("\n=== FARNOSTI (ukázka Nový Jičín) ===")
    nj_farnosti = set()
    cur.execute("SELECT DISTINCT farnost FROM scitani WHERE dekanat='Nový Jičín'")
    nj_farnosti = {r[0] for r in cur.fetchall()}

    for farnost, rok_data in sorted(far_data.items()):
        roky = [r for r in ROKY_HISTORICKE if r in rok_data]
        hod  = [rok_data[r] for r in roky]
        res  = zpracuj_skupinu(roky, hod)
        for rok in ROKY_HISTORICKE:
            cur.execute("INSERT INTO predikce_farnost VALUES (?,?,?,?,?,?,?)",
                        (farnost, rok, rok_data.get(rok), None, None, None, None))
        for rok in ROKY_PREDIKCE:
            cur.execute("INSERT INTO predikce_farnost VALUES (?,?,?,?,?,?,?)",
                        (farnost, rok, None,
                         res[f"exp_{rok}"], res[f"lin_{rok}"],
                         res["r2_exp"], res["r2_lin"]))
        if farnost in nj_farnosti:
            print(f"  {farnost}: 2029 exp={res['exp_2029']} lin={res['lin_2029']}")

    conn.commit()
    conn.close()
    print("\nHotovo — tabulky predikce_dieceze, predikce_dekanat, predikce_farnost uloženy.")


if __name__ == "__main__":
    main()
