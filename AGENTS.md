# AGENTS.md

Repo-minne för AI-agenter och utvecklare. Läs detta först.

## Vad repot gör

Ett konfigurationsdrivet dataflöde: läser en flik från var och en av flera
Excel-arbetsböcker, kopplar ihop dem enligt en relationsspec och skriver
resultatet till ett nytt Excel-ark. Flödet ska kunna växa från två källor till
godtyckligt många utan att koden ändras.

Arkitekturen har tre lager:

1. **Relationsspec** (`config/relations.yaml`) – entiteter, källor, relationer
   och byggen. Detta är kontraktet. Att lägga till en källa är att lägga till en
   post här, inte att skriva kod.
2. **Relationsmodell** (`src/excel_merge/relations.py`) – tolkar och validerar
   specen samt härleder en körplan ur relationsgrafen.
3. **Körmotor** (`src/excel_merge/engine.py`) – verkställer planen generiskt.
   Den vet ingenting om kunder eller ordrar, bara om nycklar och policies.

Läs `docs/relations.md` för resonemanget bakom modellen, särskilt varför
nyckeldetektering är ett *förslag* och inte ett beslut.

## Kommandon

```bash
pip install -e ".[dev]"                                   # installera med testberoenden
python -m pytest                                          # kör hela sviten (krav: alla gröna)
python -m excel_merge.cli plan    --spec config/relations.yaml   # visa härledd körplan
python -m excel_merge.cli run     --spec config/relations.yaml   # kör och skriv utdata
python -m excel_merge.cli profile --spec config/relations.yaml   # underlag för nya kopplingar
python scripts/make_sample_data.py                        # skapa exempeldata i data/
UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py     # uppdatera golden-filen
```

## Så lägger du till en ny källa

1. Kör `cli profile` och läs beviset: nyckelkandidat, täckning, kardinalitet,
   antal nycklar utan match. Ändra inget förrän du förstår siffrorna.
2. Om det behövs en ny entitet: lägg till den under `entities:` med sin nyckel.
3. Lägg till källan under `sources:` med `entity`, `columns` och, om den pekar på
   en annan entitet, en post under `relationships` (`to`, `via`, `cardinality`,
   `orphans`).
4. Lägg till entiteten i `include:` för det bygge som ska berikas.
5. Lägg till en fixture i `tests/fixtures.py` och ett test i
   `tests/test_engine.py` som bevisar att källan faktiskt bidrar med data.
6. Kör `python -m excel_merge.cli plan` och kontrollera att körordningen blev
   rimlig. Kör sedan `python -m pytest`.
7. Om utdata ändras avsiktligt: `UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py`
   och granska diffen i `tests/golden/` innan du committar.

## Regler som inte får tummas på

- **Kardinalitet och orphaning-policy är affärsbeslut.** Föreslå dem, men
  beskriv dem som obekräftade. `validate`/`cardinality` är skyddsnätet som gör
  att en felaktig koppling går rött i stället för att tyst blåsa upp radantalet.
- **En entitet som inte går att nå från basen ska avvisas**, inte ignoreras.
  `load_relation_spec` gör detta; försvaga inte den kontrollen.
- **Testdata byggs i kod** (`tests/fixtures.py`). Checka aldrig in `.xlsx`.
- **Inga mockar.** Testerna kör riktig pandas/openpyxl mot temporära filer.
- **Golden-filen är ett kontrakt.** Ändrar du den måste diffen förklaras.

## Kända fallgropar

- Sökvägar i specen tolkas relativt `config/`, inte arbetskatalogen.
- Vid flera källor per entitet väljs den första i `relations.py:_step_for`. Ska
  valet styras av något annat (kolumntäckning, prioritet) måste den regeln in där
  och testas.
- `orphans: flag` lägger till en `matched_<källa>`-kolumn som behålls även om den
  inte listas i `build.columns`. Det är avsiktligt: annars försvinner poängen
  med att flagga.
- YAML 1.1 tolkar nyckeln `on:` som boolean `True`. Specen använder `to`/`via`,
  så problemet är borta, men skriv inte `on:` i nya YAML-filer.
