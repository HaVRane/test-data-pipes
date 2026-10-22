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

## Ta emot nya filer från användaren

Uppladdning till samtalet kräver att sökvägen ligger innanför arbetskatalogen
`/workspace/project`. Ligger den utanför svarar servern 422 med "path must be
inside the conversation workspace". Be användaren ladda upp till
`data/inbox/` (gitignorerad). Se `docs/ladda-upp-filer.md`.

Webbapplikation med fem flikar (uppladdning, indata, kolumner och koppling,
karta, ändringslogg):

```bash
python scripts/webapp.py --data-dir data --inbox data/inbox --port 12000
```

Inventera uppladdade filer utan att skriva något:

```bash
python scripts/inspect_uploads.py data/inbox
python scripts/inspect_uploads.py data/inbox --reference data/customers.xlsx
```

Verktyget listar flikar, profilerar kolumner och skriver utkast till spec-poster.

## Ändringslogg för datakällor

`watch` upptäcker om en källa lagts till, ändrats eller tagits bort, och skriver
det till `state/changelog.ndjson` med tidsstämpel (UTC). `log` visar historiken.

```bash
python -m excel_merge.cli watch --spec config/relations.yaml
python -m excel_merge.cli log
```

Fingeravtrycket hashar **cellvärdena**, inte filen. Excel skriver om filarkivet
vid varje sparning utan att datan ändras; en filhash skulle larma varje gång
någon öppnar filen. Se `docs/andringslogg.md`.

Två filer: `state/changelog.ndjson` (läsbar historik, append-only) och
`state/sources.json` (senast kända fingeravtryck). `state/` är gitignorerad.

Viktigt för agenter: lägg aldrig affärslogik i `watch`. Den beskriver att något
ändrats, inte om ändringen är önskvärd. Domen ligger i testerna.

En källa som inte går att läsa stoppar inte de andra. Den loggas som
`source_unreadable` och behåller sitt senaste kända fingeravtryck. Kommer filen
tillbaka loggas `source_recovered`, även om innehållet är oförändrat - annars
skulle loggens sista rad påstå att källan fortfarande är trasig. Upprepade
körningar med samma fel ger ingen ny händelse, så en fil som ligger borta länge
fyller inte loggen med dubbletter.

## Karta över källorna

Fliken `Karta` visar varje tabell som en ruta med sina möjliga nycklar, och
pilarna mellan dem är föreslagna kopplingar. Den svarar på frågan "vilka
tabeller finns och vad binder dem samman", till skillnad från fliken
`Kolumner och koppling` som visar alla kolumner i detalj.

```bash
curl "http://127.0.0.1:12000/map?key=..."   # {"nodes": [...], "edges": [...]}
```

Kartan visar bara kandidater som är rekommenderade eller möjliga (högst två per
tabellpar), annars dränks den i svaga förslag. En kolumn vars namn antyder ett
mått eller datum (`belopp`, `order_date`, `amount`) visas inte som nyckel: i ett
litet datamaterial blir ett belopp unikt av en slump utan att vara en
identifierare. En kolumn som faktiskt används i en koppling listas som nyckel
även om den inte är unik ensam.

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
- Uppladdade filer måste hamna under `/workspace/project`, annars 422. Lägg dem
  i `data/inbox/` och kör `scripts/inspect_uploads.py`.
- `watch` kräver en giltig spec. Tar man bort en källa som ett bygge fortfarande
  pekar på avvisas specen innan loggning sker. Ta bort källan ur bygget först.
- Fingeravtrycket normaliserar `1`/`1.0` och `42`/"42" till samma värde. Ändra
  inte normaliseringen utan att lägga ett test - annars fylls loggen av falska
  ändringar.
- Kopplingsförslag (`joins.rank_join_candidates`) väger unikhet och namnledtrådar
  tyngre än täckning. En datumkolumn med identiska värden över båda tabellerna
  får 100 % täckning men är inte en nyckel. Lita inte på täckning ensam.
