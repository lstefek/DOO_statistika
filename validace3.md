# Validace 3 — plán úprav a instrukce pro opravy

Datum: 2026-05-22

Účel tohoto dokumentu je připravit verzi 3 analýzy bez okamžité implementace.
Navazuje na dodatečnou validaci projektu po verzi 2 a rozepisuje konkrétní
kroky, jak opravit zjištěné metodické chyby, nesoulady v reportu a jak začít
s doporučenými zlepšeními.

Tento dokument je plán. Neznamená, že níže uvedené úpravy už byly provedeny.

## Cíle verze 3

1. Zabránit tomu, aby kapacitní model používal farnostní predikce označené jako
   neplatné.
2. Oddělit skutečnou nulu ve sčítání od chybějící hodnoty a rozhodnout, jak se
   nuly mají promítat do exp/recent modelů.
3. Zpřesnit referenční alokaci kněží v roce 2024 a odstranit zkreslení
   způsobené poměrovým přerozdělením už v referenčním roce.
4. Rozšířit validaci tak, aby odděleně hodnotila platné a neplatné farnosti,
   kalibraci intervalů a citlivost kapacitního modelu.
5. Opravit ručně zapsané nesoulady v reportu a zavést postup, který podobné
   nesoulady příště odhalí automaticky.
6. Připravit verzi 3 reportu jako "dodatečnou validaci" s jasným rozlišením:
   historická data, modelové scénáře, nejisté předpoklady, a doporučené další
   kroky.

## Rozsah

Do verze 3 patří:

- úpravy `predikce.py`,
- úpravy `validace_predikce.py`,
- úpravy `kapacitni_model.py`,
- drobná oprava `mapa_ohrozenych.py`,
- aktualizace `report.html`, případně vytvoření pomocného generačního skriptu,
- aktualizace `statistika.md` a `CLAUDE.md`,
- přegenerování `scitani.db`, `validace_predikce.txt`, grafů, map a
  `statistika_web.zip`,
- doplnění kontrolních SQL dotazů nebo samostatného QA skriptu.

Mimo rozsah verze 3, pokud nebude dodán nový zdroj:

- nové scrapování kněží z internetu,
- přidání oficiálních diecézních statistik za roky 2020-2024 bez spolehlivého
  zdroje,
- optimalizační model typu k-median / set cover v plné podobě. Pro verzi 3 stačí
  připravit rozhraní a dokumentovat, co bude potřeba pro verzi 4.

## Výchozí zjištění, která se mají opravit

### 1. Kapacitní model používá neplatné farnostní predikce

Problém:

- `kapacitni_model.py` načítá `validni`, ale pro budoucí roky používá každý
  řádek s `exp_a` a `exp_b`.
- V DB je 100 neplatných farnostních predikcí; 97 z nich má exp parametry a tím
  vstupuje do modelu.
- Tím vzniká rozpor s reportem, který říká, že neplatné predikce nelze používat
  pro plánování.

Instrukce pro opravu:

1. V `kapacitni_model.py` upravit `vericich_v_roce()` tak, aby u budoucích let
   kontrolovala `validni`.
2. Přidat explicitní strategii pro farnosti s `validni = 0`. Doporučený návrh:
   `FALLBACK_NEVALIDNI = "last_known"` jako konzervativní výchozí varianta.
3. Podporované strategie:
   - `last_known`: poslední známá nenull hodnota, případně 0,
   - `dekanat_scale`: poslední známá hodnota farnosti škálovaná tempem poklesu
     příslušného děkanátu,
   - `zero_if_last_zero`: pokud poslední hodnota je 0, ponechat 0; jinak
     `last_known` nebo `dekanat_scale`,
   - `exclude_from_planning`: nepoužít pro plánovací součty, ale ponechat ve
     výstupu se stavem `nejista`.
4. Pro verzi 3 zvolit jednu hlavní strategii a uložit její název do výsledné
   tabulky, aby report věděl, jak byla hodnota určena.
5. Rozšířit `kapacitni_model` o sloupce:
   - `vericich_zdroj` (`actual`, `model_valid`, `fallback_last_known`,
     `fallback_dekanat_scale`, `fallback_zero`, ...),
   - `predikce_validni` (`0/1`),
   - volitelně `nejistota_flag`.
6. V reportu už neuvádět jedno číslo ohrožených farností bez poznámky, kolik z
   nich stojí na validních predikcích a kolik na fallbacku.

Akceptační kritéria:

- SQL dotaz níže vrátí 0:

```sql
SELECT COUNT(*) AS invalid_used_as_valid
FROM kapacitni_model
WHERE rok > 2024
  AND predikce_validni = 0
  AND vericich_zdroj = 'model_valid';
```

- Report obsahuje tabulku nebo poznámku s počty farností podle `vericich_zdroj`.
- `kapacitni_model.py` má explicitně otestovanou větev pro neplatné predikce.

### 2. Skutečné nuly jsou v exp/recent modelu ignorované

Problém:

- `fit_exp()` filtruje pouze `y > 0`, takže skutečné nuly nejsou součástí fitu.
- `fit_recent()` také bere jen kladné body.
- V roce 2024 existují farnosti s `osob_celkem = 0`; některé z nich přesto
  dostávají budoucí nenulovou exp predikci.

Instrukce pro opravu:

1. Nejdřív jasně rozhodnout, co `0` ve zdrojovém CSV znamená:
   - skutečná nulová účast,
   - nesčítaná farnost kódovaná jako nula,
   - administrativní záznam bez bohoslužby.
2. Pokud `0` znamená skutečnou nulu, nepovažovat ji za missing.
3. Doporučený model pro verzi 3:
   - pro exp model použít `log1p(y)` místo `log(y)`, tedy fitovat
     `log(1 + y) = a + b*t`,
   - predikci převést zpět jako `exp(pred) - 1`,
   - hodnoty pod např. 0.5 zaokrouhlovat na 0,
   - validitu pořád hodnotit samostatně, ne jen podle R2.
4. Alternativa, pokud nechceme měnit hlavní exp model:
   - ponechat exp model pro kladné řady,
   - ale pokud poslední hodnota je 0, defaultně použít fallback 0 nebo
     `zero_if_last_zero`,
   - v reportu označit, že exp model není vhodný pro farnosti s nulami.
5. Rozšířit `predikce_farnost_model` o informaci:
   - `zero_count`,
   - `last_value`,
   - `model_type` (`exp_log_positive`, `exp_log1p`, `fallback`, ...).

Akceptační kritéria:

- Farnost s poslední hodnotou 0 nesmí bez explicitního zdůvodnění dostat
  modelovou predikci vyšší než poslední kladná historická hodnota.
- V reportu je samostatná sekce "Farnosti s nulovou účastí" nebo poznámka k
  interpretaci nul.
- Validace ukazuje samostatné metriky pro farnosti s nulami v historii.

Kontrolní SQL:

```sql
SELECT s.farnost, s.dekanat, s.osob_celkem AS v2024, p.exp_val AS exp2039,
       m.validni, m.model_type
FROM scitani s
LEFT JOIN predikce_farnost p
  ON p.farnost = s.farnost AND p.rok = 2039
LEFT JOIN predikce_farnost_model m
  ON m.farnost = s.farnost
WHERE s.rok = 2024
  AND s.osob_celkem = 0
ORDER BY exp2039 DESC;
```

### 3. Kapacitní model používá poměrovou alokaci kněží i pro rok 2024

Problém:

- Funkce pro alokaci kněží dělí celkový počet kněží mezi děkanáty podle
  aktuálního podílu, ale tím už v referenčním roce mění skutečné obsazení.
- Někteří kněží působí ve více děkanátech, takže je potřeba jasně definovat,
  jestli počítáme unikátní osoby nebo kapacitní úvazky po děkanátech.

Instrukce pro opravu:

1. Zavést dvě samostatné veličiny:
   - `aktivni_knezi_unikat`: počet unikátních osob v celé diecézi,
   - `aktivni_knezi_dekanat_pairs`: počet dvojic kněz-děkanát, tedy kapacitní
     přítomnost v děkanátech.
2. Pro referenční rok 2024 nepoužívat zaokrouhlený poměr z celku, ale skutečné
   počty z DB po děkanátech.
3. Pro budoucí roky použít apportionment:
   - vzít skutečné referenční počty po děkanátech,
   - spočítat ideální budoucí kvóty podle poklesu,
   - rozdělit celočíselné kněze metodou largest remainder,
   - zachovat přesně celkový počet kněží pro daný rok,
   - umožnit nastavit minimální počet 0 nebo 1 podle scénáře; pro malé
     děkanáty není automatické `max(1, ...)` neutrální rozhodnutí.
4. Přidat do výsledků sloupce:
   - `knezi_dekanat`,
   - `alokace_metoda`,
   - `aktivni_role_definice`.
5. Report musí uvést, jestli periferní nedostatek je počítán podle unikátních
   osob nebo podle kněz-děkanát párů.

Akceptační kritéria:

- Pro rok 2024 sedí součet `knezi_dekanat` na definovaný referenční součet.
- Tabulka po děkanátech v reportu odpovídá SQL dotazu z DB.
- V kódu nejsou ručně zapsané počty typu "Bruntál 9, Krnov 7" mimo výsledky
  dotazu.

Kontrolní SQL:

```sql
SELECT s.dekanat,
       COUNT(DISTINCT s.farnost) AS farnosti,
       COUNT(DISTINCT k.jmeno) AS aktivnich,
       ROUND(COUNT(DISTINCT s.farnost) * 1.0 / NULLIF(COUNT(DISTINCT k.jmeno), 0), 2)
         AS farnosti_na_kneze
FROM scitani s
LEFT JOIN knezi k
  ON k.farnost = s.farnost
 AND k.role IN (
   'Farář', 'Administrátor', 'Administrátor excurrendo',
   'Administrátor excurrendo in materialibus',
   'Administrátor excurrendo in spiritualibus',
   'Administrátor in spiritualibus',
   'Farní vikář', 'Výpomocný duchovní',
   'Rektor kostela ve farnosti', 'Rektor klášterního kostela',
   'Rektor kostela duchovní správy'
 )
GROUP BY s.dekanat
ORDER BY farnosti_na_kneze DESC;
```

### 4. Predikční interval je příliš úzký

Problém:

- Interval z reziduální sigma v log prostoru neobsahuje nejistotu parametrů,
  strukturální zlom ani volbu modelu.
- Leave-2024-out ukazuje, že interval nepokryl skutečnost.

Instrukce pro opravu:

1. V reportu přejmenovat aktuální interval na "reziduální interval exp modelu",
   pokud zůstane zachován.
2. Pro verzi 3 přidat empirický validační interval:
   - použít chybu z leave-2024-out na úrovni diecéze a děkanátů,
   - vytvořit scénářové pásmo z exp/lin/recent nebo exp/log1p/fallback modelu,
   - reportovat rozsah modelů jako nejistotu, ne jen 90% CI.
3. Pro farnosti nepředstírat přesné CI, pokud je validace slabá.
4. Do `validace_predikce.py` přidat coverage metriky:
   - kolik skutečných hodnot spadlo do exp CI,
   - coverage po děkanátech,
   - coverage po farnostech, pokud bude CI dostupné.

Akceptační kritéria:

- Report explicitně říká, že původní 90% CI nebylo kalibrované.
- Validace obsahuje coverage a bias.
- Graf diecéze rozlišuje modelové pásmo od statistického CI.

### 5. Validace farností míchá platné a neplatné predikce

Problém:

- `validace_predikce.py` počítá celkové MAPE přes farnosti s exp predikcí, ale
  nerozděluje metriky podle `validni`.
- Výsledek tím maskuje, že neplatné farnosti mají výrazně horší chybu.

Instrukce pro opravu:

1. V `validace_predikce.py` doplnit metriky po segmentech:
   - všechny farnosti,
   - farnosti validní podle modelu fitnutého bez holdoutu,
   - farnosti nevalidní,
   - farnosti s nulou v historii,
   - farnosti s méně než 4 kladnými body,
   - farnosti podle velikostních pásem v roce 2024: 0, 1-29, 30-99, 100+.
2. Přidat validační soubor `validace_predikce_v3.txt` nebo rozšířit
   `validace_predikce.txt` se sekcí "Verze 3".
3. Přidat rolling holdout, pokud počet bodů dovolí:
   - trénink 1999-2014, holdout 2019,
   - trénink 1999-2019, holdout 2024.
4. U každého modelu reportovat:
   - `n`,
   - MAPE,
   - wMAPE,
   - RMSE,
   - bias,
   - median APE,
   - podíl nadhodnocení.

Akceptační kritéria:

- Report neuvádí jedinou farnostní MAPE bez segmentace.
- Kapacitní model používá jen segment, který je pro plánování povolený, nebo
  jasně označuje fallback.

### 6. Nesoulady v reportu

Nalezené nesoulady:

- Text "131 vlastního faráře, zbývajících 135" je aritmeticky i datově špatně:
  277 - 131 = 146; `Administrátor excurrendo` je v jiné metrice.
- Počty kněží po děkanátech v textu neodpovídaly aktuální DB při stejné
  definici aktivních rolí.
- Doporučení "farností s < 30 věřícími cca 40" neodpovídalo DB; v době kontroly
  šlo o 92 farností.
- Tvrzení "pokles po roce 2019 akceleruje ve všech děkanátech" bylo příliš
  silné; minimálně Bruntál a Místek měly menší relativní pokles 2019-2024 než
  2014-2019.

Instrukce pro opravu:

1. Nevkládat do `report.html` ručně opsaná čísla, pokud je lze získat z DB.
2. Vytvořit buď:
   - jednoduchý `generuj_report.py`, který načte DB a doplní HTML šablonu, nebo
   - samostatný `qa_report.py`, který kontroluje ručně zapsaná čísla proti DB.
3. Minimální QA kontroly:
   - počet farností,
   - počet farností s vlastním farářem,
   - počet farností bez vlastního faráře,
   - počet farností s `Administrátor excurrendo`,
   - počet aktivních kněží,
   - počty po děkanátech,
   - počet farností s `< 30` a `<= 30` věřícími,
   - diecézní predikce 2029/2034/2039,
   - validační hodnoty 2024.
4. Změnit formulace:
   - "pokles akceleruje ve všech děkanátech" nahradit "na diecézní úrovni a ve
     většině děkanátů pokles po roce 2019 zrychlil".
   - "cca 40 farností" nahradit hodnotou z DB nebo slovem "ověřit z DB".
5. Do `report_v1_v2.html` nebo nové verze přidat poznámku, že verze 3 opravuje
   validační nesoulady a metodiku použití neplatných predikcí.

Akceptační kritéria:

- QA kontrola reportu projde bez chyb.
- V reportu není žádné staré číslo, které se liší od DB o více než povolenou
  zaokrouhlovací toleranci.

### 7. Drobná chyba v mapě

Problém:

- V `mapa_ohrozenych.py` je kontrola bez GPS ve tvaru
  `fs.lat IS NULL OR fs.lat IS NULL`.

Instrukce pro opravu:

1. Opravit podmínku na `fs.lat IS NULL OR fs.lon IS NULL`.
2. Přidat kontrolní výpis počtu farností v mapě proti počtu farností v
   `kapacitni_model`.

Akceptační kritéria:

- Pokud existuje farnost s chybějícím `lon`, mapa ji nahlásí.
- Při kompletních GPS výstup hlásí 0 farností bez GPS.

## Doporučený implementační postup

### Fáze A — Před změnami

1. Zkontrolovat pracovní strom:

```bash
git status -sb
```

2. Pokud existují změny nesouvisející s verzí 3, rozhodnout, zda je commitnout,
   stashnout, nebo ponechat mimo scope.
3. Vytvořit pracovní větev:

```bash
git switch -c validace3
```

4. Spustit baseline kontroly a uložit výstup:

```bash
sqlite3 -readonly -header -column scitani.db "SELECT rok, SUM(osob_celkem) FROM scitani GROUP BY rok;"
python3 validace_predikce.py
python3 kapacitni_model.py
```

### Fáze B — Predikce a validace

1. Upravit `predikce.py`:
   - doplnit práci s nulami,
   - doplnit metadata modelu,
   - neukládat neplatné predikce jako běžné plánovací hodnoty bez zdroje
     fallbacku.
2. Upravit `validace_predikce.py`:
   - segmentované metriky,
   - coverage,
   - rolling holdout.
3. Přegenerovat:

```bash
python3 predikce.py
python3 validace_predikce.py
```

4. Ověřit:

```sql
SELECT validni, COUNT(*)
FROM predikce_farnost_model
GROUP BY validni;

SELECT model_type, COUNT(*)
FROM predikce_farnost_model
GROUP BY model_type;
```

### Fáze C — Kapacitní model

1. Upravit `kapacitni_model.py`:
   - použít skutečnou referenční alokaci,
   - zavést largest remainder pro budoucí roky,
   - přidat fallback strategii pro nevalidní farnosti,
   - rozšířit tabulku `kapacitni_model`.
2. Přegenerovat:

```bash
python3 kapacitni_model.py
```

3. Ověřit:

```sql
SELECT rok, COUNT(*) AS rows, SUM(stav='pokryta') AS pokryte,
       SUM(stav='ohrozena') AS ohrozene
FROM kapacitni_model
GROUP BY rok;

SELECT rok, vericich_zdroj, COUNT(*) AS farnosti,
       ROUND(SUM(vericich), 1) AS vericich
FROM kapacitni_model
GROUP BY rok, vericich_zdroj
ORDER BY rok, vericich_zdroj;
```

### Fáze D — Report a QA

1. Opravit `report.html` nebo zavést generování reportu.
2. Doplnit verzi 3:
   - "Verze 3 — dodatečná validace",
   - co se změnilo proti verzi 2,
   - jak se zachází s neplatnými predikcemi,
   - jak se zachází s nulami,
   - segmentovaná validace,
   - metodická omezení kapacitního modelu.
3. Opravit nesoulady:
   - farář / bez faráře / excurrendo,
   - počty po děkanátech,
   - farnosti `< 30`,
   - formulace o akceleraci.
4. Vytvořit nebo rozšířit `report_v1_v2.html` na přehled verzí:
   - v1,
   - v2,
   - v3.
5. Spustit QA:

```bash
python3 qa_report.py
```

Pokud `qa_report.py` nebude zaveden, spustit alespoň ruční SQL dotazy uvedené v
tomto dokumentu.

### Fáze E — Výstupy

1. Přegenerovat grafy a mapy:

```bash
python3 grafy.py
python3 mapa_ohrozenych.py
```

2. Obnovit ZIP:

```bash
python3 -m zipfile -c statistika_web.zip report.html report_v1_v2.html grafy
```

Pokud vznikne samostatný `report_v3.html`, přidat ho do ZIPu také.

3. Zkontrolovat obsah ZIPu:

```bash
python3 -m zipfile -l statistika_web.zip
```

### Fáze F — Finální validace před commitem

Povinné kontroly:

```bash
python3 import_csv_to_sqlite.py
python3 predikce.py
python3 validace_predikce.py
python3 kapacitni_model.py
python3 grafy.py
python3 mapa_ohrozenych.py
python3 -m zipfile -c statistika_web.zip report.html report_v1_v2.html grafy
git diff --stat
```

Kontrolní SQL:

```sql
-- Lubina musí zůstat zdrojových 238.
SELECT rok, osob_celkem, muz, zena
FROM scitani
WHERE farnost = 'Lubina' AND rok = 2014;

-- Historické součty.
SELECT rok, SUM(osob_celkem) AS celkem
FROM scitani
GROUP BY rok
ORDER BY rok;

-- Neplatné predikce nesmí být tvářeny jako validní model v kapacitě.
SELECT COUNT(*) AS invalid_used_as_valid
FROM kapacitni_model
WHERE rok > 2024
  AND predikce_validni = 0
  AND vericich_zdroj = 'model_valid';

-- Reportované počty pod 30.
SELECT COUNT(*) AS n_below_30
FROM scitani
WHERE rok = 2024 AND osob_celkem < 30;

-- Vlastní farář vs bez vlastního faráře.
WITH far AS (
  SELECT s.farnost,
         MAX(k.role = 'Farář') AS has_farar,
         MAX(k.role = 'Administrátor excurrendo') AS has_exc
  FROM (SELECT DISTINCT farnost FROM scitani) s
  LEFT JOIN knezi k ON k.farnost = s.farnost
  GROUP BY s.farnost
)
SELECT COUNT(*) AS farnosti,
       SUM(has_farar) AS s_fararem,
       SUM(1 - has_farar) AS bez_farare,
       SUM(has_exc) AS s_excurrendo
FROM far;
```

## Doporučené změny textu reportu

Do reportu přidat nebo upravit tyto formulace:

1. "Verze 3 opravuje použití neplatných farnostních predikcí v kapacitním
   modelu. Farnosti s nevalidním modelem jsou nyní počítány pomocí explicitní
   fallback strategie a ve výstupech jsou označeny."
2. "Nulové hodnoty ve sčítání jsou interpretovány odděleně od NULL. Modely,
   které nedokážou nulu přirozeně zpracovat, ji nepoužívají jako běžný kladný
   trend."
3. "Predikční interval exp modelu je empiricky podkalibrovaný; leave-2024-out
   validace ukazuje, že skutečnost ležela mimo interval. Proto je pro plánování
   důležitější modelové pásmo a scénářová citlivost než samotné 90% CI."
4. "Pokles po roce 2019 zrychlil na úrovni diecéze a ve většině děkanátů, ne
   nutně ve všech."
5. "Počty ohrožených farností jsou scénářový výsledek, nikoli předpověď. Jsou
   citlivé na definici aktivního kněze, fallback pro nevalidní farnosti a limit
   farností na kněze."

## Doporučená commit struktura

Pokud budou změny větší, rozdělit do tří commitů:

1. `Fix prediction validity handling`
   - `predikce.py`,
   - `validace_predikce.py`,
   - nové validační výstupy.
2. `Revise capacity model allocation`
   - `kapacitni_model.py`,
   - `mapa_ohrozenych.py`,
   - DB a grafy/mapy.
3. `Publish validation v3 report`
   - `report.html`,
   - `report_v1_v2.html` nebo nový report verzí,
   - `statistika.md`,
   - `CLAUDE.md`,
   - `statistika_web.zip`.

Pokud bude změna implementována v jednom průchodu, použít commit:

```text
Add validation v3 methodology updates
```

## Otevřené rozhodnutí před implementací

Před kódováním je potřeba rozhodnout:

1. Co přesně znamená `osob_celkem = 0` ve zdrojových datech.
2. Jaká fallback strategie bude hlavní pro nevalidní farnosti:
   `last_known`, `zero_if_last_zero`, nebo `dekanat_scale`.
3. Zda má hlavní report ukazovat jen jeden scénář, nebo dvě vrstvy:
   - "validní modelové predikce",
   - "plánovací fallback pro nevalidní farnosti".
4. Zda počet kněží po děkanátech modelovat jako unikátní osoby nebo kapacitní
   přítomnost kněze v děkanátu.
5. Jestli má být výsledkem jen aktualizovaný `report.html`, nebo nový
   `report_v3.html` plus rozcestník verzí.

## Minimální verze 3, pokud nebude čas na vše

Pokud je potřeba dodat menší, ale smysluplnou verzi 3, udělat alespoň:

1. V `kapacitni_model.py` nepoužívat `validni=0` jako běžný exp model.
2. Opravit `mapa_ohrozenych.py` kontrolu `lat/lon`.
3. Ve `validace_predikce.py` doplnit segmentaci MAPE podle `validni`.
4. Opravit ruční nesoulady v `report.html`.
5. Přidat do reportu varování, že nuly a fallbacky jsou metodicky významné.
6. Přegenerovat DB, validace, grafy, mapy a ZIP.

Tato minimální varianta už odstraní největší rozpor: report nebude tvrdit, že
nevalidní predikce nejsou pro plánování, zatímco kapacitní model je současně
tiše používá.
