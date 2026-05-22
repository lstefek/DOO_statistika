# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Přehled

Statistická analýza návštěvnosti bohoslužeb v Diecézi ostravsko-opavské. Projekt transformuje data sčítání ČBK (CSV) do SQLite databáze, počítá predikce a kapacitní model pokrytí farností při poklesu kněží, generuje grafy a HTML report.

Podrobný popis projektu, postup aktualizace a diferenciální analýza jsou v `statistika.md`.

## Spuštění pipeline

Pořadí skriptů závisí na tom, co se aktualizuje:

```bash
# Plná obnova (po novém sčítání):
python3 import_csv_to_sqlite.py   # CSV → tabulka scitani
python3 scrape_knezi.py           # doo.cz → tabulka knezi
python3 scrape_souradnice.py      # doo.cz → tabulka farnosti_souradnice
python3 predikce.py               # → tabulky predikce_*
python3 kapacitni_model.py        # → tabulka kapacitni_model
python3 grafy.py                  # → grafy/*.png
python3 mapa_ohrozenych.py        # → grafy/mapa_*.html

# Jen přepočet predikcí a výstupů (bez scrapingu):
python3 predikce.py && python3 kapacitni_model.py && python3 grafy.py && python3 mapa_ohrozenych.py
```

Závislosti: `pip install numpy scipy matplotlib folium --break-system-packages`

## Databáze `scitani.db`

Jediný zdroj pravdy. Klíčové tabulky:

- **`scitani`** — historická data sčítání (dekanat, farnost, rok, osob_celkem, prumerny_vek, muz, zena, neuvedeno)
- **`knezi`** — personální obsazení farností z doo.cz (farnost, guid, role, jmeno)
- **`farnosti_souradnice`** — GPS souřadnice (lat, lon) pro mapové výstupy
- **`predikce_farnost / predikce_dekanat / predikce_dieceze`** — exp_val, lin_val pro roky 2029/2034/2039; historické roky mají hodnota, predikční exp_val/lin_val
- **`kapacitni_model`** — stav farnosti ('pokryta'/'ohrozena') pro roky 2024–2039 při daném počtu kněží
- **`dieceze_statistiky`** — celodiecézní data z Wikipedie (knezi, jahni, krty…)

## Klíčové parametry ke změně při aktualizaci

V `kapacitni_model.py`:
```python
KNEZI_2024   = 192       # aktualizovat po novém scrapingu
POKLES_B     = log(0.5)/10  # −50 % za 10 let — přezkoumat dle nových dat
MAX_FAR_KNEZ = 2         # max. farností na kněze (nedělní mše)
```

V `predikce.py`:
```python
ROKY_HISTORICKE = [1999, 2004, 2009, 2014, 2019, 2024]  # přidat 2029 po sčítání
ROKY_PREDIKCE   = [2029, 2034, 2039]                     # posunout o 5 let
```

## Corrigenda

Manuální korekce dat jsou zdokumentovány v `statistika.md` (sekce Corrigenda).
Aktuálně nejsou aplikovány žádné korekce. Hodnota Lubina 2014 je převzata ze
zdrojového CSV jako `osob_celkem=238`, `muz=110`, `zena=128`.

## Výstupy

- `report.html` + `grafy/` — nasadit na web jako `statistika_web.zip` (rozbalit do `public_html/statistika/`)
- Report dostupný na `farnost.lubina.cz/statistika/report.html`
