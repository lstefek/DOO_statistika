# Statistická analýza návštěvnosti bohoslužeb — Diecéze ostravsko-opavská

**Publikovaný report:** https://farnost.lubina.cz/static/doo_statistika/report.html

## Co analýza obsahuje

Analýza zpracovává výsledky celostátního sčítání ČBK z let 1999–2024 pro všech 277 farností Diecéze ostravsko-opavské. Zahrnuje:

- historický vývoj návštěvnosti bohoslužeb po farnostech a děkanátech (1999–2024),
- predikce do roku 2039 třemi modely (exponenciální, lineární, recent),
- leave-2024-out validaci přesnosti predikcí včetně segmentovaných metrik,
- kapacitní model — kolik farností ztratí pravidelnou pastorační péči při poklesu počtu kněží,
- citlivostní analýzu pro různá tempa poklesu a limity farností na kněze,
- interaktivní mapy ohrožených farností.

## Spuštění

```bash
# Plná obnova pipeline:
python3 import_csv_to_sqlite.py
python3 predikce.py
python3 predikce_hnb.py       # hierarchický NB model (~8 min)
python3 validace_predikce.py
python3 kapacitni_model.py
python3 grafy.py
python3 mapa_ohrozenych.py
python3 -m zipfile -c statistika_web.zip report.html report_changelog.html grafy
```

Závislosti: `pip install numpy scipy matplotlib folium --break-system-packages`

## Klíčové soubory

| Soubor | Popis |
|---|---|
| `scitani.db` | SQLite databáze — jediný zdroj pravdy |
| `report.html` | Hlavní report (verze 3) |
| `report_changelog.html` | Přehled změn mezi verzemi |
| `statistika_web.zip` | Balíček pro nasazení na web |
| `validace_predikce.txt` | Výstup validace predikcí |
| `validace3.md` | Plán a akceptační kritéria verze 3 |
| `statistika.md` | Podrobná dokumentace projektu |

## Verze

- **v1** — první analýza
- **v2** — oprava NULL hodnot, přidán CI a model Recent, validace, geografický kapacitní model
- **v3** — kapacitní model nepoužívá neplatné predikce, fallback strategie, segmentovaná validace, opravy nesouladů v reportu
