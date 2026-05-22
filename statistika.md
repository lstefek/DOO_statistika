# Statistická analýza bohoslužeb — Diecéze ostravsko-opavská

## Přehled projektu

Analýza návštěvnosti nedělních bohoslužeb v Diecézi ostravsko-opavské na základě sčítání ČBK 1999–2024. Zahrnuje historický trend, predikci do roku 2039, personální obsazení farností a kapacitní model pokrytí při poklesu kněží.

---

## Soubory projektu

| Soubor | Popis |
|--------|-------|
| `scitani.db` | Hlavní SQLite databáze — všechna data |
| `scitani-srovnani-1999-2024-web.csv` | Zdrojová data sčítání (vstup) |
| `import_csv_to_sqlite.py` | Import CSV do tabulky `scitani` |
| `scrape_knezi.py` | Scraping kněží z doo.cz/katalog/farnosti/ |
| `scrape_souradnice.py` | Scraping GPS souřadnic farností |
| `predikce.py` | Výpočet predikcí (exp + lineární model) |
| `kapacitni_model.py` | Kapacitní model pokrytí farností |
| `grafy.py` | Generování PNG grafů |
| `mapa_ohrozenych.py` | Generování interaktivních HTML map (Folium) |
| `report.html` | Závěrečný HTML report |
| `statistika_web.zip` | Balíček pro nasazení na web |
| `grafy/` | Adresář s grafy a mapami |

---

## Databázové tabulky

| Tabulka | Obsah | Klíčové sloupce |
|---------|-------|-----------------|
| `scitani` | 1 662 záznamů návštěvnosti (277 farností, 1999–2024) | dekanat, farnost, rok, osob_celkem, prumerny_vek, muz, zena |
| `dieceze_statistiky` | Celodiecézní statistiky z Wikipedie (1999–2019) | rok, obyvatele, katolici, knezi, jahni, krty |
| `knezi` | Kněží přiřazení k farnostem (scraping 2025) | farnost, guid, role, jmeno |
| `farnosti_souradnice` | GPS souřadnice 274/278 farností | farnost, guid, lat, lon |
| `predikce_dieceze` | Predikce pro celou diecézi | rok, hodnota, exp_val, lin_val |
| `predikce_dekanat` | Predikce pro 11 děkanátů | dekanat, rok, hodnota, exp_val, lin_val, r2_exp, r2_lin |
| `predikce_farnost` | Predikce pro každou farnost | farnost, rok, hodnota, exp_val, lin_val, r2_exp, r2_lin |
| `kapacitni_model` | Simulace pokrytí farností | rok, farnost, vericich, pocet_knezi, stav |

---

## Klíčové parametry a předpoklady

```python
# predikce.py
ROKY_HISTORICKE = [1999, 2004, 2009, 2014, 2019, 2024]
ROKY_PREDIKCE   = [2029, 2034, 2039]

# kapacitni_model.py
KNEZI_2024    = 192          # aktuální počet kněží (scraping 2025)
POKLES_B      = log(0.5)/10  # -50 % za 10 let (předpoklad)
MAX_FAR_KNEZ  = 2            # max. farností na kněze (nedělní mše)
```

**Klíčové zjištění:** Kritický práh kapacity nastane kolem roku **2031** — tehdy 118 kněží × 2 = 236 míst < 278 farností.

---

## Aktualizace po sčítání 2029

### 1. Aktualizace CSV dat
Nový soubor sčítání 2029 nahrát jako `scitani-srovnani-1999-2029-web.csv` a upravit konstantu:
```python
# import_csv_to_sqlite.py — žádná změna kódu není nutná, CSV má stejnou strukturu
```

Pak spustit celý pipeline:
```bash
python3 import_csv_to_sqlite.py     # přepíše tabulku scitani
python3 predikce.py                 # přepočítá predikce (nově 1999–2029 → 2034, 2039, 2044)
python3 kapacitni_model.py          # přepočítá kapacitní model
python3 grafy.py                    # obnoví grafy
python3 mapa_ohrozenych.py          # obnoví mapy
```

### 2. Aktualizace personálních dat
```bash
python3 scrape_knezi.py             # nový scraping kněží z doo.cz
python3 scrape_souradnice.py        # souřadnice se nemění, ale spustit pro nové farnosti
python3 kapacitni_model.py          # přepočítat s aktuálním počtem kněží
```
**Před spuštěním:** Aktualizovat `KNEZI_2024` (a rok) v `kapacitni_model.py`.

---

## Diferenciální analýza (srovnání dvou období)

Dotaz pro srovnání sčítání 2024 vs. 2029:

```sql
SELECT
    a.dekanat,
    a.farnost,
    a.osob_celkem AS ver_2024,
    b.osob_celkem AS ver_2029,
    b.osob_celkem - a.osob_celkem AS zmena,
    ROUND((b.osob_celkem * 1.0 / a.osob_celkem - 1) * 100, 1) AS zmena_pct
FROM scitani a
JOIN scitani b ON a.farnost = b.farnost
WHERE a.rok = 2024 AND b.rok = 2029
ORDER BY zmena_pct;
```

Srovnání predikce vs. skutečnost:
```sql
SELECT
    p.farnost,
    p.exp_val AS predikce_exp,
    s.osob_celkem AS skutecnost,
    s.osob_celkem - p.exp_val AS odchylka,
    ROUND((s.osob_celkem / p.exp_val - 1) * 100, 1) AS odchylka_pct
FROM predikce_farnost p
JOIN scitani s ON s.farnost = p.farnost AND s.rok = 2029
WHERE p.rok = 2029
ORDER BY odchylka_pct;
```

---

## Zajímavé farnosti k sledování

| Farnost | Jev | Poznámka |
|---------|-----|----------|
| Lubina | Nejstabilnější v děkanátu NJ | −28 % (1999–2024), průměr věku 38,9 let |
| Bartošovice | Jediná s nárůstem v NJ | +9 % (1999–2024) — sledovat, zda trend přetrvá |
| Veřovice | Nejrychlejší pokles v NJ | −76 % (1999–2024) |
| Trnávka | První ohrožená v NJ | Model: ohrožena od 2034 (19 věřících) |
| Bruntál, Krnov | Systémové ohrožení | 26+22 ohrožených farností ve scénáři 2034 |

---

## Corrigenda — manuální korekce dat

| Datum | Farnost | Rok | Původní hodnota | Opravená hodnota | Důvod |
|-------|---------|-----|-----------------|------------------|-------|
| 2026-05-21 | Lubina | 2014 | 238 | 210 | Outlier — hodnota neodpovídá trendu |

Korekce v databázi:
```sql
UPDATE scitani SET osob_celkem = 210 WHERE farnost = 'Lubina' AND rok = 2014;
```

---

## Závislosti (Python balíčky)

```
numpy>=2.0
scipy>=1.17
matplotlib>=3.10
folium>=0.20
```

Instalace:
```bash
pip install numpy scipy matplotlib folium --break-system-packages
```

---

## Zdroje dat

| Zdroj | URL | Frekvence aktualizace |
|-------|-----|-----------------------|
| Sčítání ČBK | doo.cz (ke stažení) | Každých 5 let (říjen) |
| Katalog farností | doo.cz/katalog/farnosti/ | Průběžně |
| Diecézní statistiky | cs.wikipedia.org/wiki/Diecéze_ostravsko-opavská | Po vydání ročenky |

---

## Historie analýz

| Datum | Popis |
|-------|-------|
| 2026-05-21 | Prvotní analýza — data 1999–2024, predikce 2029–2039, kapacitní model, report |
