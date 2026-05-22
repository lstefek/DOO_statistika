#!/usr/bin/env python3
"""
Hierarchický negativně binomický model predikce návštěvnosti bohoslužeb.

Tříúrovňová hierarchie:  diecéze → děkanáty → farnosti
Partial pooling: intercept a slope sdíleny přes děkanát, přes farnosti.

Model:
    log(μ_it) = a_i + b_i · t          t = rok − 1999
    Y_it ~ NegBinomial(μ_it, α)
    a_i ~ Normal(a_d[i], σ_a_par)
    b_i ~ Normal(b_d[i], σ_b_par)
    a_d[j] ~ Normal(μ_a, σ_a_dek)
    b_d[j] ~ Normal(μ_b, σ_b_dek)

Klíčové vlastnosti oproti OLS modelům:
- Nuly v historii jsou v NB přirozené (žádný fallback).
- Malé/extrémní farnosti se smrskují ke skupinovému průměru (regularizace).
- Posterior HDI plně zachycuje parametrickou nejistotu.
- Výstup je konzistentní: součet farnostních predikcí = prognóza diecéze.

Výstup: sloupce hnb_val, hnb_lo, hnb_hi v tabulkách predikce_*.
        Tyto sloupce přidá/přepíše (ALTER TABLE nebo UPDATE).

Spuštění: python3 predikce_hnb.py
Požadavky: pip install pymc arviz
Čas běhu: ~8 min (NUTS, 2 chains × 1 000 tune + 500 draws, CPU)
"""

import sqlite3
import warnings
from pathlib import Path

import numpy as np
import arviz as az

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

DB_FILE = Path(__file__).parent / "scitani.db"

ROKY_PREDIKCE = [2029, 2034, 2039]

NUTS_TUNE    = 1000
NUTS_DRAWS   = 500
NUTS_CHAINS  = 2
TARGET_ACCEPT = 0.90
RANDOM_SEED  = 42


# ── 1. Načtení dat ────────────────────────────────────────────────────────────

def nacti_data(conn):
    rows = conn.execute("""
        SELECT farnost, dekanat, rok, osob_celkem
        FROM scitani
        WHERE rok IN (1999,2004,2009,2014,2019,2024)
        ORDER BY farnost, rok
    """).fetchall()

    farnosti = sorted(set(r[0] for r in rows))
    dekanaty = sorted(set(r[1] for r in rows))
    far_idx  = {f: i for i, f in enumerate(farnosti)}
    dek_idx  = {d: i for i, d in enumerate(dekanaty)}
    far_to_dek = {}
    for f, d, r, v in rows:
        far_to_dek[f] = d

    obs_far, obs_t, obs_y = [], [], []
    for f, d, rok, val in rows:
        if val is not None:
            obs_far.append(far_idx[f])
            obs_t.append(float(rok - 1999))
            obs_y.append(int(val))

    obs_far = np.array(obs_far, dtype=int)
    obs_t   = np.array(obs_t,   dtype=float)
    obs_y   = np.array(obs_y,   dtype=int)
    far_dek = np.array([dek_idx[far_to_dek[f]] for f in farnosti], dtype=int)

    return dict(
        farnosti=farnosti, dekanaty=dekanaty,
        far_idx=far_idx, dek_idx=dek_idx, far_to_dek=far_to_dek,
        obs_far=obs_far, obs_t=obs_t, obs_y=obs_y,
        far_dek=far_dek,
    )


# ── 2. Model + sampling ───────────────────────────────────────────────────────

def fituj_model(d):
    import pymc as pm

    farnosti = d["farnosti"]
    dekanaty = d["dekanaty"]
    n_far    = len(farnosti)
    n_dek    = len(dekanaty)
    obs_far  = d["obs_far"]
    obs_t    = d["obs_t"]
    obs_y    = d["obs_y"]
    far_dek  = d["far_dek"]

    # Prior na průměrný intercept z dat
    nonzero = d["obs_y"][d["obs_y"] > 0]
    global_log_mean = float(np.log(nonzero.mean())) if len(nonzero) else 4.0

    print(f"Data: {n_far} farností, {n_dek} děkanátů, {len(obs_y)} pozorování "
          f"({(obs_y==0).sum()} nul, {6*n_far - len(obs_y)} NULL)")

    coords = {"farnost": farnosti, "dekanat": dekanaty}

    with pm.Model(coords=coords) as model:
        # Diecézní hyperpriors
        mu_a        = pm.Normal("mu_a",        mu=global_log_mean, sigma=1.0)
        sigma_a_dek = pm.HalfNormal("sigma_a_dek", sigma=0.5)
        mu_b        = pm.Normal("mu_b",        mu=-0.028, sigma=0.02)
        sigma_b_dek = pm.HalfNormal("sigma_b_dek", sigma=0.01)

        # Děkanátová úroveň (non-centered)
        a_dek_z = pm.Normal("a_dek_z", 0.0, 1.0, dims="dekanat")
        b_dek_z = pm.Normal("b_dek_z", 0.0, 1.0, dims="dekanat")
        a_dek   = pm.Deterministic("a_dek", mu_a + sigma_a_dek * a_dek_z, dims="dekanat")
        b_dek   = pm.Deterministic("b_dek", mu_b + sigma_b_dek * b_dek_z, dims="dekanat")

        # Farnostní úroveň (non-centered)
        sigma_a_par = pm.HalfNormal("sigma_a_par", sigma=0.5)
        sigma_b_par = pm.HalfNormal("sigma_b_par", sigma=0.01)
        a_par_z     = pm.Normal("a_par_z", 0.0, 1.0, dims="farnost")
        b_par_z     = pm.Normal("b_par_z", 0.0, 1.0, dims="farnost")
        a_par = pm.Deterministic(
            "a_par", a_dek[far_dek] + sigma_a_par * a_par_z, dims="farnost")
        b_par = pm.Deterministic(
            "b_par", b_dek[far_dek] + sigma_b_par * b_par_z, dims="farnost")

        # NB overdispersion (globální)
        alpha_nb = pm.HalfNormal("alpha_nb", sigma=10)

        # Likelihood
        log_mu = a_par[obs_far] + b_par[obs_far] * obs_t
        pm.NegativeBinomial("y_obs",
                            mu=pm.math.exp(log_mu),
                            alpha=alpha_nb,
                            observed=obs_y)

        print(f"\nSampling NUTS: {NUTS_CHAINS} chains × {NUTS_TUNE} tune + {NUTS_DRAWS} draws …")
        trace = pm.sample(
            draws=NUTS_DRAWS,
            tune=NUTS_TUNE,
            chains=NUTS_CHAINS,
            target_accept=TARGET_ACCEPT,
            random_seed=RANDOM_SEED,
            progressbar=True,
            return_inferencedata=True,
        )

    return trace


# ── 3. Diagnostika ─────────────────────────────────────────────────────────────

def diagnostika(trace):
    divs = int(trace.sample_stats["diverging"].values.sum())
    # R-hat jen pro skalární/vektorové parametry (ne Deterministic s n_far dimenzí)
    scalar_vars = ["mu_a", "sigma_a_dek", "mu_b", "sigma_b_dek",
                   "sigma_a_par", "sigma_b_par", "alpha_nb"]
    rhat_vals = []
    for v in scalar_vars:
        try:
            rhat_vals.append(float(az.rhat(trace, var_names=[v]).to_array().max()))
        except Exception:
            pass
    rhat_max = max(rhat_vals) if rhat_vals else float("nan")

    print(f"\n── Diagnostika ──")
    print(f"  Divergence: {divs}")
    print(f"  R̂ max (hyperparametry): {rhat_max:.3f}")
    if divs > 20:
        print("  ⚠  Mnoho divergencí — zvažte vyšší target_accept.")
    if rhat_max > 1.05:
        print("  ⚠  R̂ > 1,05 — model nekonvergoval spolehlivě.")

    # Klíčové hyperparametry
    post = trace.posterior
    for v in ["mu_b", "sigma_b_dek", "sigma_b_par", "alpha_nb"]:
        if v in post:
            vals = post[v].values.reshape(-1)
            print(f"  {v:<16}: mean={vals.mean():.4f}  std={vals.std():.4f}  "
                  f"HDI90=[{np.percentile(vals,5):.4f}, {np.percentile(vals,95):.4f}]")


# ── 4. Predikce ───────────────────────────────────────────────────────────────

def spocitej_predikce(trace, d):
    """
    Vrátí pred_far, pred_dek, pred_diec.
    Každý záznam: (hnb_val, hnb_lo, hnb_hi)
    hnb_val = round(posterior mean of μ)
    hnb_lo/hi = 5./95. percentil posterior μ  (parametrická nejistota)
    """
    farnosti = d["farnosti"]
    dekanaty = d["dekanaty"]
    far_to_dek = d["far_to_dek"]
    n_far = len(farnosti)

    post  = trace.posterior
    a_smp = post["a_par"].values.reshape(-1, n_far)   # (S, n_far)
    b_smp = post["b_par"].values.reshape(-1, n_far)

    pred_far  = {f: {} for f in farnosti}
    pred_dek  = {d: {} for d in dekanaty}
    pred_diec = {}

    for rok in ROKY_PREDIKCE:
        t = float(rok - 1999)
        mu_smp = np.exp(a_smp + b_smp * t)          # (S, n_far)

        # Farnosti
        val = np.round(mu_smp.mean(axis=0)).astype(int)
        lo  = np.maximum(0, np.percentile(mu_smp, 5,  axis=0)).astype(int)
        hi  = np.percentile(mu_smp, 95, axis=0).astype(int)
        for i, f in enumerate(farnosti):
            pred_far[f][rok] = (int(val[i]), int(lo[i]), int(hi[i]))

        # Děkanáty (součet přes farnosti skupiny)
        for dk in dekanaty:
            idx = [i for i, f in enumerate(farnosti) if far_to_dek[f] == dk]
            mu_dk = mu_smp[:, idx].sum(axis=1)
            pred_dek[dk][rok] = (
                int(round(mu_dk.mean())),
                int(max(0, np.percentile(mu_dk, 5))),
                int(np.percentile(mu_dk, 95)),
            )

        # Diecéze
        mu_di = mu_smp.sum(axis=1)
        pred_diec[rok] = (
            int(round(mu_di.mean())),
            int(max(0, np.percentile(mu_di, 5))),
            int(np.percentile(mu_di, 95)),
        )

    return pred_far, pred_dek, pred_diec


# ── 5. Zápis do DB ────────────────────────────────────────────────────────────

def uloz_do_db(conn, pred_far, pred_dek, pred_diec):
    cur = conn.cursor()

    # Přidej sloupce (ignoruj chybu, pokud už existují)
    for tbl in ("predikce_farnost", "predikce_dekanat", "predikce_dieceze"):
        for col in ("hnb_val", "hnb_lo", "hnb_hi"):
            try:
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} REAL")
            except Exception:
                pass

    # Farnosti
    for f, rok_pred in pred_far.items():
        for rok, (val, lo, hi) in rok_pred.items():
            cur.execute(
                "UPDATE predikce_farnost SET hnb_val=?, hnb_lo=?, hnb_hi=?"
                " WHERE farnost=? AND rok=?",
                (val, lo, hi, f, rok),
            )

    # Děkanáty
    for dk, rok_pred in pred_dek.items():
        for rok, (val, lo, hi) in rok_pred.items():
            cur.execute(
                "UPDATE predikce_dekanat SET hnb_val=?, hnb_lo=?, hnb_hi=?"
                " WHERE dekanat=? AND rok=?",
                (val, lo, hi, dk, rok),
            )

    # Diecéze
    for rok, (val, lo, hi) in pred_diec.items():
        cur.execute(
            "UPDATE predikce_dieceze SET hnb_val=?, hnb_lo=?, hnb_hi=? WHERE rok=?",
            (val, lo, hi, rok),
        )

    conn.commit()


# ── 6. Výstup / shrnutí ───────────────────────────────────────────────────────

def tiskni_srovnani(conn, pred_diec):
    print("\n── Srovnání modelů (diecéze) ──")
    print(f"  {'Rok':>4}  {'Exp':>7}  {'Lin':>7}  {'Recent':>7}  "
          f"{'Holt':>7}  {'HNB':>7}  {'HNB 90% HDI'}")
    for rok in ROKY_PREDIKCE:
        row = conn.execute(
            "SELECT exp_val, lin_val, recent_val, holt_val FROM predikce_dieceze WHERE rok=?",
            (rok,)
        ).fetchone()
        if not row:
            continue
        exp_v, lin_v, rec_v, hlt_v = row
        val, lo, hi = pred_diec[rok]
        def fmt(v): return f"{int(v):>7,}".replace(",", " ") if v else "      —"
        print(f"  {rok}  {fmt(exp_v)}  {fmt(lin_v)}  {fmt(rec_v)}  "
              f"{fmt(hlt_v)}  {val:>7,}  [{lo:,} – {hi:,}]"
              .replace(",", " "))


def main():
    conn = sqlite3.connect(DB_FILE)

    d = nacti_data(conn)
    trace = fituj_model(d)
    diagnostika(trace)

    print("\nPočítám predikce z posterior …")
    pred_far, pred_dek, pred_diec = spocitej_predikce(trace, d)
    uloz_do_db(conn, pred_far, pred_dek, pred_diec)
    tiskni_srovnani(conn, pred_diec)

    conn.close()
    print("\nHotovo — hnb_val/hnb_lo/hnb_hi uloženy do predikce_*.")


if __name__ == "__main__":
    main()
