#!/usr/bin/env python3
"""
Kapacitní model: kolik farností lze obsloužit při klesajícím počtu kněží?

VYLEPŠENÍ oproti původní verzi (po validačním reportu):

#3.1 KNEZI z DB — počet kněží se odvozuje dynamicky z tabulky `knezi`
     podle definice AKTIVNI_ROLE (zachycuje kněze schopné celebrovat mši).
     Konstantu lze přepsat přes --knezi.

#3.2 Citlivostní analýza POKLES_B — kromě hlavního scénáře (-50%/10 let)
     se ukládá i 'mild' (-30%/10 let) a 'severe' (-65%/10 let).

#3.3 Scénáře MAX_FAR_KNEZ — model počítá 3 varianty: 2, 3, 4 farnosti/kněz.

#3.4 Geografické přidělování — kapacita kněží se rozdělí proporčně po
     děkanátech (podle dnešního stavu) a greedy se aplikuje pouze v rámci
     daného děkanátu. Realističtější než globální greedy.

#3.5 Pokrytí všech 277 farností — i farnosti s NULL/0 v poslední iteraci
     scitani jsou zahrnuty s hodnotou 0 (nebo posledním známým údajem).

#3.6 Exp eval přímo — pro mezi-roky (2027, 2031, …) se vyhodnocuje
     fitnutý exp model přímo, ne se interpolují koncové body.
"""

import argparse
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

# Definice "aktivní" kněz (může celebrovat nedělní mši ve farnosti)
AKTIVNI_ROLE = (
    "Farář",
    "Administrátor",
    "Administrátor excurrendo",
    "Administrátor excurrendo in materialibus",
    "Administrátor excurrendo in spiritualibus",
    "Administrátor in spiritualibus",
    "Farní vikář",
    "Výpomocný duchovní",
    "Rektor kostela ve farnosti",
    "Rektor klášterního kostela",
    "Rektor kostela duchovní správy",
)

REFERENCNI_ROK = 2024
POKLES_SCENARE = {
    "mild":   math.log(0.7) / 10,   # -30 % za 10 let
    "base":   math.log(0.5) / 10,   # -50 % za 10 let (hlavní scénář)
    "severe": math.log(0.35) / 10,  # -65 % za 10 let
}
MAX_FAR_SCENARE = (2, 3, 4)
ROKY_MODELU = [2024, 2027, 2029, 2031, 2034, 2037, 2039]


# ── pomocné funkce ────────────────────────────────────────────────────────────

def aktivni_knezi(conn: sqlite3.Connection) -> int:
    """Vrátí počet jedinečných aktivních kněží v DB."""
    placeholders = ",".join("?" for _ in AKTIVNI_ROLE)
    n = conn.execute(
        f"SELECT COUNT(DISTINCT jmeno) FROM knezi "
        f"WHERE jmeno IS NOT NULL AND role IN ({placeholders})",
        AKTIVNI_ROLE,
    ).fetchone()[0]
    return n


def knezi_v_roce(knezi_2024: int, pokles_b: float, rok: int) -> int:
    """Exponenciální projekce počtu kněží."""
    t = rok - REFERENCNI_ROK
    return max(1, round(knezi_2024 * math.exp(pokles_b * t)))


def vericich_v_roce(conn: sqlite3.Connection, rok: int) -> dict[str, float]:
    """
    Vrátí {farnost: počet věřících} pro libovolný rok.
    - rok ≤ 2024: skutečnost z scitani (NULL → 0)
    - rok > 2024: vyhodnocení exp modelu z predikce_farnost_model přímo
      (a·exp(b·t)). Pokud farnost nemá platný model, použije se poslední
      známá hodnota (0 pokud žádná).
    Zaručuje pokrytí všech 277 farností.
    """
    cur = conn.cursor()
    # Vždy začneme se seznamem všech farností
    all_far = [r[0] for r in cur.execute("SELECT DISTINCT farnost FROM scitani").fetchall()]
    out: dict[str, float] = {f: 0.0 for f in all_far}

    if rok <= REFERENCNI_ROK:
        # Nejbližší rok, kde jsou data
        roky_data = [r[0] for r in cur.execute(
            "SELECT DISTINCT rok FROM scitani WHERE rok<=? ORDER BY rok DESC", (rok,)
        ).fetchall()]
        if roky_data:
            zk_rok = roky_data[0]
            rows = cur.execute(
                "SELECT farnost, COALESCE(osob_celkem, 0) FROM scitani WHERE rok=?",
                (zk_rok,),
            ).fetchall()
            for f, v in rows:
                out[f] = v
        return out

    # Pro budoucí rok: vyhodnotit exp model přímo
    t = rok - 1999  # předikce model fituje proti (rok-1999)
    rows = cur.execute(
        "SELECT farnost, exp_a, exp_b, validni FROM predikce_farnost_model"
    ).fetchall()
    for f, a, b, validni in rows:
        if a is not None and b is not None:
            val = max(0.0, a * math.exp(b * t))
            out[f] = val
        else:
            # Fallback: poslední známá hodnota
            row = cur.execute(
                "SELECT osob_celkem FROM scitani "
                "WHERE farnost=? AND osob_celkem IS NOT NULL "
                "ORDER BY rok DESC LIMIT 1",
                (f,),
            ).fetchone()
            out[f] = (row[0] or 0) if row else 0
    return out


def dekanat_farnosti(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT DISTINCT farnost, dekanat FROM scitani").fetchall()
    return {f: d for f, d in rows}


def prideleni_knezi_dekanaty(
    conn: sqlite3.Connection,
    pocet_knezi: int,
) -> dict[str, int]:
    """
    Rozdělí celkový počet kněží mezi děkanáty podle DNEŠNÍHO podílu
    kněží v daném děkanátu (z tabulky knezi). Předpoklad: poměry mezi
    děkanáty zůstávají stabilní (pokles je rovnoměrný).

    Tento přístup je realističtější než rovnoměrné rozdělení podle počtu
    farností — některé děkanáty mají 1,3 farnosti/kněz (Frýdek), jiné
    3,7 farnosti/kněz (Bruntál).
    """
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT s.dekanat, COUNT(DISTINCT k.jmeno) AS aktivnich
        FROM scitani s
        LEFT JOIN knezi k ON k.farnost = s.farnost
            AND k.role IN ('Farář','Administrátor','Administrátor excurrendo',
                           'Administrátor excurrendo in materialibus',
                           'Administrátor excurrendo in spiritualibus',
                           'Administrátor in spiritualibus',
                           'Farní vikář','Výpomocný duchovní',
                           'Rektor kostela ve farnosti','Rektor klášterního kostela',
                           'Rektor kostela duchovní správy')
        GROUP BY s.dekanat
    """).fetchall()
    total = sum(c or 0 for _, c in rows)
    if total == 0:
        # Fallback: rovnoměrné rozdělení podle farností
        rows2 = cur.execute(
            "SELECT dekanat, COUNT(DISTINCT farnost) FROM scitani GROUP BY dekanat"
        ).fetchall()
        total = sum(c for _, c in rows2)
        rows = rows2

    out: dict[str, int] = {}
    rem = pocet_knezi
    sorted_rows = sorted(rows, key=lambda x: -(x[1] or 0))
    for i, (dek, count) in enumerate(sorted_rows):
        if i == len(sorted_rows) - 1:
            out[dek] = max(1, rem)
        else:
            n = max(1, round(pocet_knezi * (count or 0) / total))
            out[dek] = n
            rem -= n
    return out


def simuluj_pokryti_geo(
    vericich: dict[str, float],
    dek_far: dict[str, str],
    knezi_po_dekanatu: dict[str, int],
    max_far_knez: int,
) -> dict[str, str]:
    """
    Simuluje pokrytí v rámci děkanátu.
    Vrátí {farnost: stav}.
    """
    stav: dict[str, str] = {}
    by_dek: dict[str, list[tuple[str, float]]] = {}
    for far, v in vericich.items():
        dek = dek_far.get(far, "?")
        by_dek.setdefault(dek, []).append((far, v))

    for dek, far_list in by_dek.items():
        far_list.sort(key=lambda x: -x[1])
        kapacita = knezi_po_dekanatu.get(dek, 0) * max_far_knez
        for i, (f, _) in enumerate(far_list):
            stav[f] = "pokryta" if i < kapacita else "ohrozena"
    return stav


def simuluj_pokryti_globalni(
    vericich: dict[str, float],
    pocet_knezi: int,
    max_far_knez: int,
) -> dict[str, str]:
    """Původní globální greedy — pro srovnání s geo verzí."""
    kapacita = pocet_knezi * max_far_knez
    serazene = sorted(vericich.items(), key=lambda x: -x[1])
    return {f: ("pokryta" if i < kapacita else "ohrozena")
            for i, (f, _) in enumerate(serazene)}


# ── hlavní výpočet ────────────────────────────────────────────────────────────

def vypocti_scenare(conn, knezi_2024: int) -> dict:
    """
    Pro každou kombinaci (POKLES_SCENARE × MAX_FAR_SCENARE × ROKY_MODELU)
    spočítá pokrytí. Vrací dict s detaily.
    """
    dek_far = dekanat_farnosti(conn)

    results = {}
    for sc_nazev, b in POKLES_SCENARE.items():
        for mfk in MAX_FAR_SCENARE:
            key = (sc_nazev, mfk)
            results[key] = []
            for rok in ROKY_MODELU:
                pocet_k = knezi_v_roce(knezi_2024, b, rok)
                ver = vericich_v_roce(conn, rok)
                knezi_po_dek = prideleni_knezi_dekanaty(conn, pocet_k)
                stav = simuluj_pokryti_geo(ver, dek_far, knezi_po_dek, mfk)

                pokryte  = sum(1 for s in stav.values() if s == "pokryta")
                ohrozene = sum(1 for s in stav.values() if s == "ohrozena")
                ver_p = sum(v for f, v in ver.items() if stav.get(f) == "pokryta")
                ver_o = sum(v for f, v in ver.items() if stav.get(f) == "ohrozena")

                results[key].append({
                    "rok": rok, "knezi": pocet_k, "kapacita": pocet_k * mfk,
                    "pokryte": pokryte, "ohrozene": ohrozene,
                    "ver_p": ver_p, "ver_o": ver_o,
                    "stav": stav, "ver": ver, "knezi_po_dek": knezi_po_dek,
                })
    return results


def uloz_main_scenar(conn, results, scenar_nazev=("base", 2)) -> None:
    """Uloží hlavní scénář (base, 2 far/kněz) do tabulky kapacitni_model."""
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
            scenar       TEXT,
            max_far_knez INTEGER,
            PRIMARY KEY (rok, farnost)
        )
    """)
    dek_far = dekanat_farnosti(conn)
    pokles_label, mfk = scenar_nazev
    for entry in results[(pokles_label, mfk)]:
        for far, v in entry["ver"].items():
            conn.execute(
                "INSERT INTO kapacitni_model VALUES (?,?,?,?,?,?,?,?,?)",
                (entry["rok"], far, dek_far.get(far),
                 v, entry["knezi"], entry["kapacita"],
                 entry["stav"].get(far, "neznámá"),
                 pokles_label, mfk),
            )
    conn.commit()


def uloz_citlivost(conn, results) -> None:
    """Tabulka citlivost: pro každou kombinaci sumární výsledek."""
    conn.execute("DROP TABLE IF EXISTS citlivost_scenare")
    conn.execute("""
        CREATE TABLE citlivost_scenare (
            scenar       TEXT,
            max_far_knez INTEGER,
            rok          INTEGER,
            knezi        INTEGER,
            kapacita     INTEGER,
            pokryte      INTEGER,
            ohrozene     INTEGER,
            vericich_pokryti  REAL,
            vericich_ohrozeni REAL,
            PRIMARY KEY (scenar, max_far_knez, rok)
        )
    """)
    for (sc, mfk), entries in results.items():
        for e in entries:
            conn.execute(
                "INSERT INTO citlivost_scenare VALUES (?,?,?,?,?,?,?,?,?)",
                (sc, mfk, e["rok"], e["knezi"], e["kapacita"],
                 e["pokryte"], e["ohrozene"], e["ver_p"], e["ver_o"])
            )
    conn.commit()


def kriticky_rok(entries: list[dict]) -> int | None:
    """Vrací první rok, kdy kapacita < počet farností."""
    for e in entries:
        if e["ohrozene"] > 0:
            return e["rok"]
    return None


# ── grafy ─────────────────────────────────────────────────────────────────────

def grafy_hlavni(results, scenar=("base", 2)):
    pokles_label, mfk = scenar
    entries = results[scenar]
    roky   = [e["rok"]      for e in entries]
    knezi  = [e["knezi"]    for e in entries]
    pokr   = [e["pokryte"]  for e in entries]
    ohroz  = [e["ohrozene"] for e in entries]
    ver_p  = [e["ver_p"]    for e in entries]
    ver_o  = [e["ver_o"]    for e in entries]
    total_far = pokr[0] + ohroz[0]

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "figure.dpi": 120,
    })

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    fig.suptitle(f"Kapacitní model — scénář '{pokles_label}', max {mfk} farností/kněz",
                 fontsize=13, fontweight="bold")

    ax = axes[0, 0]
    ax.plot(roky, knezi, "o-", color="#7c3aed", lw=2, ms=6)
    ax.set_title("Počet kněží (projekce)")
    ax.set_ylabel("Kněží")
    for r, k in zip(roky, knezi):
        ax.annotate(str(k), (r, k), textcoords="offset points", xytext=(0, 7),
                    ha="center", fontsize=8)

    ax = axes[0, 1]
    ax.stackplot(roky, pokr, ohroz,
                 labels=["Pokryté farnosti", "Ohrožené farnosti"],
                 colors=["#2563eb", "#dc2626"], alpha=0.8)
    ax.axhline(total_far, color="gray", lw=0.8, ls=":", label=f"Celkem {total_far} farností")
    ax.set_title("Pokrytí farností")
    ax.set_ylabel("Počet farností")
    ax.legend(fontsize=9, loc="lower left")

    ax = axes[1, 0]
    ax.stackplot(roky, ver_p, ver_o,
                 labels=["Věřící v pokrytých", "Věřící v ohrožených"],
                 colors=["#2563eb", "#dc2626"], alpha=0.8)
    ax.set_title("Věřící podle pokrytí")
    ax.set_ylabel("Počet věřících")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f"{int(x):,}".replace(",", " ")))
    ax.legend(fontsize=9, loc="upper right")

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
    print(f"  {path}")


def graf_citlivost(results):
    """Heatmapa: rok ohroženosti × scénář × MAX_FAR."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)
    for i, mfk in enumerate(MAX_FAR_SCENARE):
        ax = axes[i]
        for sc_label, color in zip(POKLES_SCENARE.keys(),
                                   ("#16a34a", "#f59e0b", "#dc2626")):
            entries = results[(sc_label, mfk)]
            roky = [e["rok"] for e in entries]
            pct = [e["ohrozene"] / (e["pokryte"] + e["ohrozene"]) * 100
                   if (e["pokryte"] + e["ohrozene"]) > 0 else 0
                   for e in entries]
            ax.plot(roky, pct, "o-", lw=2, ms=5, label=sc_label, color=color)
        ax.set_title(f"Max {mfk} farností/kněz", fontweight="bold")
        ax.set_xlabel("Rok")
        if i == 0:
            ax.set_ylabel("% ohrožených farností")
        ax.set_ylim(0, 100)
        ax.set_xticks(roky)
        ax.set_xticklabels([str(r) for r in roky], rotation=45, ha="right", fontsize=8)
        ax.legend(fontsize=9, loc="upper left")
        ax.grid(alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.suptitle("Citlivostní analýza — % ohrožených farností pro různé scénáře",
                 fontweight="bold")
    fig.tight_layout()
    path = OUT_DIR / "citlivost.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  {path}")


def graf_dekanaty_2034(conn):
    rows = conn.execute("""
        SELECT dekanat,
               SUM(CASE WHEN stav='pokryta'  THEN 1 ELSE 0 END) AS pokr,
               SUM(CASE WHEN stav='ohrozena' THEN 1 ELSE 0 END) AS ohr
        FROM kapacitni_model
        WHERE rok=2034
        GROUP BY dekanat
        ORDER BY ohr DESC
    """).fetchall()
    dekanaty = [r[0] for r in rows]
    pokr_d   = [r[1] for r in rows]
    ohr_d    = [r[2] for r in rows]

    fig, ax = plt.subplots(figsize=(11, 5))
    x = np.arange(len(dekanaty))
    w = 0.4
    ax.bar(x - w/2, pokr_d, width=w, label="Pokryté",  color="#2563eb", alpha=0.85)
    ax.bar(x + w/2, ohr_d,  width=w, label="Ohrožené", color="#dc2626", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(dekanaty, rotation=30, ha="right")
    ax.set_title("Pokrytí farností podle děkanátu — scénář 2034 (base)",
                 fontweight="bold")
    ax.set_ylabel("Počet farností")
    ax.legend()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    path = OUT_DIR / "kapacita_dekanaty_2034.png"
    fig.savefig(path)
    plt.close(fig)
    print(f"  {path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Kapacitní model DOO")
    parser.add_argument("--knezi", type=int, default=None,
                        help="Explicitně specifikovat počet kněží v REFERENCNI_ROK "
                             "(jinak se odvodí z DB)")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_FILE)

    knezi_2024 = args.knezi if args.knezi else aktivni_knezi(conn)
    print(f"Počet aktivních kněží v {REFERENCNI_ROK}: {knezi_2024} "
          f"({'z DB' if args.knezi is None else 'CLI'})")

    results = vypocti_scenare(conn, knezi_2024)
    uloz_main_scenar(conn, results, scenar_nazev=("base", 2))
    uloz_citlivost(conn, results)

    # Konzolový přehled
    print(f"\nHlavní scénář (base: -50%/10 let, max 2 farnosti/kněz):")
    print(f"{'Rok':>6}  {'Kněží':>6}  {'Kapac.':>7}  {'Pokryt.':>8}  {'Ohrož.':>8}  "
          f"{'% ohr. far':>11}")
    print("-" * 60)
    base_main = results[("base", 2)]
    for e in base_main:
        pct = e["ohrozene"] / (e["pokryte"] + e["ohrozene"]) * 100 if (e["pokryte"] + e["ohrozene"]) > 0 else 0
        print(f"{e['rok']:>6}  {e['knezi']:>6}  {e['kapacita']:>7}  "
              f"{e['pokryte']:>8}  {e['ohrozene']:>8}  {pct:>9.1f} %")

    print(f"\nKritický rok (první rok s ohroženými farnostmi) podle scénářů:")
    for (sc, mfk), entries in sorted(results.items()):
        kr = kriticky_rok(entries)
        print(f"  scénář={sc:<6} max_far/kněz={mfk}: {kr if kr else 'nikdy v ROKY_MODELU'}")

    # Ohrožené farnosti v 2034 (hlavní scénář)
    print("\n=== Ohrožené farnosti 2034 (base, 2 far/kněz) ===")
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

    # Grafy
    print("\nGenerace grafů:")
    grafy_hlavni(results, scenar=("base", 2))
    graf_citlivost(results)

    conn2 = sqlite3.connect(DB_FILE)
    graf_dekanaty_2034(conn2)
    conn2.close()


if __name__ == "__main__":
    main()
