# Statistická analýza bohoslužeb — Diecéze ostravsko-opavská

## Přehled projektu

Analýza návštěvnosti nedělních bohoslužeb v Diecézi ostravsko-opavské na základě sčítání ČBK 1999–2024. Zahrnuje historický trend, predikci do roku 2039, personální obsazení farností a kapacitní model pokrytí při poklesu kněží.

---

## Soubory projektu

| Soubor | Popis |
|--------|-------|
| `scitani.db` | Hlavní SQLite databáze — všechna data |
| `scitani-srovnani-1999-2024-web.csv` | Zdrojová data sčítání (vstup) |
| `import_csv_to_sqlite.py` | Import CSV → tabulka `scitani` + volitelné corrigenda |
| `scrape_knezi.py` | Scraping kněží z doo.cz/katalog/farnosti/ (BS4, retry, dedup) |
| `scrape_souradnice.py` | Scraping GPS souřadnic farností (s manuálním override) |
| `predikce.py` | 3 modely predikce (exp + lin + recent), 90% CI, validita |
| `validace_predikce.py` | Leave-2024-out validace, MAPE/RMSE/bias |
| `kapacitni_model.py` | Geografický kapacitní model + citlivostní analýza |
| `grafy.py` | Generování PNG grafů |
| `mapa_ohrozenych.py` | Interaktivní HTML mapy (Folium) |
| `report.html` | Závěrečný HTML report |
| `requirements.txt` | Python závislosti |
| `statistika_web.zip` | Balíček pro nasazení na web |
| `validace_predikce.txt` | Textový výstup leave-2024-out validace |
| `grafy/` | Adresář s grafy a mapami (PNG + Folium HTML) |
| `CLAUDE.md` | Instrukce pro Claude Code (AI asistent) |

---

## Databázové tabulky

| Tabulka | Obsah | Klíčové sloupce |
|---------|-------|-----------------|
| `scitani` | 1 662 záznamů (277 farností × 6 let, NULL kde data nepořízena) | dekanat, farnost, rok, osob_celkem, prumerny_vek, muz, zena |
| `dieceze_statistiky` | Celodiecézní statistiky z Wikipedie (1999–2019) | rok, obyvatele, katolici, knezi, jahni, krty |
| `knezi` | Kněží přiřazení k farnostem (scraping 2025) | farnost, guid, role, jmeno |
| `farnosti_souradnice` | GPS souřadnice 277/277 farností (zdroj: 'web' / 'manual') | farnost, guid, lat, lon, zdroj |
| `predikce_dieceze` | Predikce diecéze + 90% CI | rok, hodnota, exp_val, exp_lo, exp_hi, lin_val, recent_val |
| `predikce_dekanat` | Predikce 11 děkanátů | dekanat, rok, hodnota, exp_val, exp_lo, exp_hi, lin_val, recent_val, r2_exp_log, r2_lin, validni |
| `predikce_farnost` | Predikce 277 farností | farnost, rok, hodnota, exp_val, exp_lo, exp_hi, lin_val, recent_val, r2_exp_log, r2_lin, validni |
| `predikce_farnost_model` | Parametry modelu (1 řádek/farnost) | exp_a, exp_b, sigma_log, lin_a, lin_b, recent_a, recent_b, validni, duvod_invaliditn |
| `kapacitni_model` | Hlavní scénář pokrytí | rok, farnost, vericich, pocet_knezi, stav, scenar, max_far_knez |
| `citlivost_scenare` | 9 scénářů (3 poklesy × 3 limity) | scenar, max_far_knez, rok, knezi, kapacita, pokryte, ohrozene |

---

## Klíčové parametry a předpoklady

```python
# predikce.py
ROKY_HISTORICKE = [1999, 2004, 2009, 2014, 2019, 2024]
ROKY_PREDIKCE   = [2029, 2034, 2039]
MIN_BODY = 4         # min. počet nenulových pozorování pro validní fit
R2_PRAH  = 0.5       # min. R² v log prostoru pro validni=1
CI_Z     = 1.645     # 90% predikční interval

# kapacitni_model.py
AKTIVNI_ROLE = (Farář, Administrátor*, Farní vikář, Výpomocný duchovní, Rektor*)
REFERENCNI_ROK = 2024
# Počet kněží v REFERENCNI_ROK se odvodí z tabulky knezi automaticky
# (aktivni_knezi() — momentálně 186). Lze přepsat přes `--knezi N`.
POKLES_SCENARE = {mild: -30%/10 let, base: -50%/10 let, severe: -65%/10 let}
MAX_FAR_SCENARE = (2, 3, 4)
# Hlavní scénář se ukládá s key (base, 2); ostatní jen do citlivost_scenare
```

**Klíčové zjištění:** Periferní děkanáty (Bruntál, Krnov, Jeseník) překračují limit
2 farnosti/kněz **už dnes**. „Kritický rok 2031" z první analýzy podhodnocoval
geografickou nerovnoměrnost rozdělení kněží.

---

## Validace predikčních modelů (Leave-2024-out)

Modely fitnuté pouze na 1999–2019, předpovídající rok 2024:

| Model | Skutečnost 2024 | Predikce | Chyba |
|-------|----------------|----------|-------|
| Exp | 36 188 | 42 220 | **+16,7 %** (90% CI nepojme skutečnost) |
| Lin | 36 188 | 40 022 | +10,6 % |
| Recent (2b) | 36 188 | 41 068 | +13,5 % |

Pozorovaný pokles 2019→2024 je rychlejší, než modely fitnuté na 1999–2019 očekávaly.
**Důsledek:** bodové predikce 2039 mohou být příliš optimistické. Skutečný pokles bude
pravděpodobně blíže lin/recent než exp modelu.

---

## Spuštění pipeline

```bash
pip install -r requirements.txt --break-system-packages

# Plná obnova (po novém sčítání):
python3 import_csv_to_sqlite.py   # CSV → tabulka scitani (+ volitelná corrigenda)
python3 scrape_knezi.py           # doo.cz → tabulka knezi
python3 scrape_souradnice.py      # doo.cz → tabulka farnosti_souradnice
python3 predikce.py               # → tabulky predikce_*
python3 validace_predikce.py      # leave-2024-out přesnost
python3 kapacitni_model.py        # → tabulka kapacitni_model + citlivost_scenare
python3 grafy.py                  # → grafy/*.png
python3 mapa_ohrozenych.py        # → grafy/mapa_*.html

# Jen přepočet predikcí a výstupů (bez scrapingu):
python3 predikce.py && python3 validace_predikce.py && \
python3 kapacitni_model.py && python3 grafy.py && python3 mapa_ohrozenych.py
```

---

## Aktualizace po sčítání 2029

1. Nový CSV nahradí `scitani-srovnani-1999-2024-web.csv` (nebo přejmenovat — pak upravit `CSV_FILE` v `import_csv_to_sqlite.py`).
2. V `predikce.py` rozšířit `ROKY_HISTORICKE` o 2029, `ROKY_PREDIKCE` posunout o 5 let (2034, 2039, 2044).
3. V `validace_predikce.py` nastavit `HOLDOUT_ROK = 2029` — leave-out test se posune.
4. V `kapacitni_model.py` aktualizovat `REFERENCNI_ROK = 2029` (po novém scrapingu kněží). Konstanta `KNEZI_2024` neexistuje — počet se odvozuje z DB.
5. Aktualizovat `dieceze_statistiky` o roky 2024+ (počet kněží z diecézní ročenky); pak lze fitnout skutečný pokles a opustit hypotézu −50 %/10 let.
6. Pokud po novém scrapingu vzniknou farnosti bez GPS, doplnit je do `MANUAL_GPS` v `scrape_souradnice.py`.
7. Spustit celý pipeline (viz výše).

---

## Corrigenda — manuální korekce dat

Korekce jsou aplikovány automaticky z `CORRIGENDA` v `import_csv_to_sqlite.py`.
Aktuálně nejsou aplikovány žádné korekce.

| Datum | Farnost | Rok | Hodnota | Důvod |
|-------|---------|-----|---------|-------|
| 2026-05-22 | Lubina | 2014 | ponecháno osob_celkem 238, muz 110, zena 128 | Původní dočasná korekce na 210 byla zrušena; pravdivá hodnota je zdrojových 238. |

---

## Validační report (z 2026-05-22)

Kompletní review pipeline z 2026-05-22 odhalil tyto bloky problémů (všechny opraveny ve verzi 2):

**Kritické:**
- ~~NULL → 0 v predikcích — historie farností bez dat se zobrazovala jako nula.~~
- ~~Predikce z 1–2 nenulových bodů produkovala nesmyslné výsledky.~~
- ~~Lubina 2014 oprava neaktualizovala muz/zena.~~

**Závažné (metodika predikce):**
- ~~Exp model výrazně podhodnocuje akceleraci poklesu po 2019.~~
- ~~R² počítáno v originálním prostoru u exp modelu (inkonzistentní s OLS na log).~~
- ~~Žádná out-of-sample validace.~~

**Závažné (kapacitní model):**
- ~~KNEZI_2024 = 192 hardcoded, neodvozeno z DB.~~
- ~~POKLES_B bez datové opory, bez citlivostní analýzy.~~
- ~~MAX_FAR_KNEZ = 2 neodpovídá realitě (kněží spravují 4–7 farností).~~
- ~~Greedy přidělování ignorovalo geografii.~~

**Závažné (scraping):**
- ~~Křehký regex parsing (přechod na BS4).~~
- ~~Duplicity v knezi neodstraňovány.~~
- ~~Nedeterministický JOIN v mapě.~~

**Drobné:**
- ~~GPS pro Maria Hilf, Býkov, Zálesí doplněny manuálně.~~
- ~~Věk komunity v reportu uváděl ~44/47, správně je 45/49 vážený.~~
- ~~Počet farností 278 sjednocen na 277.~~

Detail validace: viz git historie repozitáře `lstefek/DOO_statistika` (commit b94f606 a předchozí).

### Otevřené body do další iterace

Nedořešené nebo nutné zopakovat:

- **Aktualizace `dieceze_statistiky` o 2020–2024** — nutné pro odvození skutečného tempa poklesu kněží z dat místo hypotézy.
- **Geografický model** — proporční alokace kněží předpokládá, že děkanáty si dnes drží relativní podíl kněží. Realita po přesunech může být jiná; pro přesnější model by bylo vhodné zahrnout omezení vzdálenosti (kněz z farnosti X může obsluhovat farnosti v okruhu Y km), což vyžaduje algoritmus typu k-Median nebo Set Cover.
- **Akcelerace poklesu** — exp model přestřeluje. Alternativa: segmented model se zlomem 2014 nebo 2019, případně weighted regression s vyšší vahou na poslední body.
- **CI bias** — predikční interval ze σ log-reziduí je úzký, protože nezohledňuje akceleraci a má malý počet stupňů volnosti (4). Zvážit bootstrap CI z prediktorů.
- **Out-of-sample test** je dnes jen na úrovni jednoho holdoutu (2024). Při novém sčítání 2029 ho zopakovat (HOLDOUT_ROK=2029) a sledovat vývoj MAPE.

---

## Závislosti (Python balíčky)

Viz `requirements.txt`:
```
numpy>=2.0
scipy>=1.10
matplotlib>=3.7
folium>=0.15
beautifulsoup4>=4.12
```

Instalace:
```bash
pip install -r requirements.txt --break-system-packages
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
| 2026-05-22 | Validační report a verze 2 — opravy kritických a závažných nedostatků |
| 2026-05-22 | Repo `lstefek/DOO_statistika` na GitHubu, veřejně |
