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
nyckeldetektering är ett *förslag* och inte ett beslut. Läs
`docs/amnesomraden.md` för steget efter kopplingen: hur ämnesområden, fakta,
dimensioner och mått härleds ur specen.

## Kommandon

```bash
pip install -e ".[dev]"                                   # installera med testberoenden
python -m pytest                                          # kör hela sviten (krav: alla gröna)
python -m excel_merge.cli plan    --spec config/relations.yaml   # visa härledd körplan
python -m excel_merge.cli run     --spec config/relations.yaml   # kör och skriv utdata
python -m excel_merge.cli profile --spec config/relations.yaml   # underlag för nya kopplingar
python -m excel_merge.cli subjects --spec config/relations.yaml  # härledda ämnesområden, fakta och mått
python scripts/make_sample_data.py                        # skapa exempeldata i data/
UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py     # uppdatera golden-filen
```

## Så lägger du till en ny källa

I praktiken gör uppladdningen detta åt dig: `register_source` skriver in posten i
`config/relations.yaml`, validerar och loggar. Stegen nedan är vad som händer,
och vad du gör manuellt om registreringen inte räcker.

1. Kör `cli profile` och läs beviset: nyckelkandidat, täckning, kardinalitet,
   antal nycklar utan match. Ändra inget förrän du förstår siffrorna.
2. Om det behövs en ny entitet: lägg till den under `entities:` med sin nyckel.
3. Lägg till källan under `sources:` med `entity`, `columns` och, om den pekar på
   en annan entitet, en post under `relationships` (`to`, `via`, `cardinality`,
   `orphans`). Saknar fliken en egen nyckel, sätt `row_key`.
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
- **Varje uppladdad fil ska bli en källa.** Det finns ingen ignorerad fil. Saknar
  fliken en egen nyckel får den en `row_key` - inte en plats i en undantagslista.
- **Skrivningen av specen ska vara kirurgisk.** `register_source` bygger block och
  sätter in dem på rätt rad, i stället för att skriva om filen med ruamel. Skälet
  är att ruamel fäster sektionskommentarerna på sektionens *sista* post: en ny
  post hamnar då under fel rubrik och diffen blir missvisande. Infoga nedifrån och
  upp (`builds` före `sources`), annars förskjuts radnumren.
- **En post som inte validerar skrivs aldrig.** Skrivningen backas och felet når
  anroparen. En trasig spec på disk är värre än ett felmeddelande.
- **Testdata byggs i kod** (`tests/fixtures.py`). Checka aldrig in `.xlsx`.
- **Inga mockar.** Testerna kör riktig pandas/openpyxl mot temporära filer.
- **Golden-filen är ett kontrakt.** Ändrar du den måste diffen förklaras.

## Ta emot nya filer från användaren

Uppladdning till samtalet kräver att sökvägen ligger innanför arbetskatalogen
`/workspace/project`. Ligger den utanför svarar servern 422 med "path must be
inside the conversation workspace". Be användaren ladda upp till
`data/inbox/` (gitignorerad). Se `docs/ladda-upp-filer.md`.

Webbapplikationen "Automatiserad dataplattform med övervakning" har fem flikar
(anslut datakälla, indata, kolumner och koppling, indatarelationer, ändringslogg).
Starta den med skriptet:

```bash
./scripts/serve_webapp.sh
```

Det kontrollerar beroendena, startar med `-u` och skriver ut adressen med nyckel.
Skriptet finns för att två saker annars tyst går fel:

- **Sessionens hemkatalog kan nollställas mellan tillfällen.** Då är `pandas`
  borta trots att det fungerade förra gången, och felet ser ut som ett kodfel
  (`ModuleNotFoundError`) fast det är miljön. Skriptet installerar `.[dev]` vid
  behov. Ser du det felet för hand: `python -m pip install -e ".[dev]"`.
- **Utan `-u` buffras utskrifterna.** Nyckeln skrivs ut först när bufferten töms,
  så loggfilen ser tom ut och en lyckad start är lätt att missta för en
  misslyckad. Skriptet väntar tills nyckeln syns i loggen.

Kör hellre skriptet än kommandot för hand:

```bash
python -u scripts/webapp.py --data-dir data --inbox data/inbox --port 12000
```

Nyckeln slumpas. Porten är nåbar utifrån i den här miljön, så en fast nyckel i
ett skript eller i git vore en öppen dörr. Skriptet skriver den bara till
terminalen.

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

Starta appen med `./scripts/serve_webapp.sh`. Den startar om sig själv rent och
skriver ut nyckeln; se avsnittet ovan.

Fingeravtrycket hashar **cellvärdena**, inte filen. Excel skriver om filarkivet
vid varje sparning utan att datan ändras; en filhash skulle larma varje gång
någon öppnar filen. Se `docs/andringslogg.md`.

Två filer: `state/changelog.ndjson` (läsbar historik, append-only) och
`state/sources.json` (senast kända fingeravtryck). `state/` är gitignorerad.

Varje händelse har ett **slag** (`kind`): `data`, `structure` eller `ingest`. Alla
hamnar i samma flöde, i tidsordning, så en enda läsning ger hela historiken - när
filen kom in, vad den innehöll och hur pipen byggdes om för att ta emot den.

Strukturhändelserna (`source_declared`, `entity_redefined`, `build_redefined`
med flera) beskriver specen. De svarar på frågan "hur har dataflödet förändrats?",
vilket är vad en agent behöver veta innan den rör något. De jämförs mot en
strukturbild som sparas i `state/sources.json` under nyckeln `structure`.

Viktigt för agenter: lägg aldrig affärslogik i `watch`. Den beskriver att något
ändrats, inte om ändringen är önskvärd. Domen ligger i testerna.

En källa vars fil eller flik **saknas** finns inte längre. Den tas bort ur
modellen och rapporteras som `source_removed` - bokstavligen samma sak som att
stryka posten ur specen. `run` och `plan` arbetar på den reducerade specen, så
ett bygge som förlorat sin enda källa till en entitet ger samma fel som om
posten aldrig funnits. Källan sägs högt när den tas bort, så en felstavad
sökväg inte försvinner tyst.

En **trasig fil** är något annat: den finns kvar, vi kan bara inte tolka den.
Den loggas som `source_unreadable` och behåller sitt senaste kända
fingeravtryck. Kommer den tillbaka loggas `source_recovered`, även om innehållet
är oförändrat - annars skulle loggens sista rad påstå att källan fortfarande är
trasig. Upprepade körningar med samma fel ger ingen ny händelse, så en fil som
ligger borta länge fyller inte loggen med dubbletter.

Skiljelinjen: en saknad källa försvinner ur modellen, en trasig blir kvar men
oläsbar. Att läsa in en trasig fil vore fel; att kasta bort en tillfälligt
oläsbar källas historik vore lika fel.

## Indatarelationer

Fliken `Indatarelationer` visar varje tabell som en ruta med sina möjliga
nycklar, och pilarna mellan dem är föreslagna kopplingar. Den svarar på frågan
"vilka tabeller finns och vad binder dem samman", till skillnad från fliken
`Kolumner och koppling` som visar alla kolumner i detalj.

```bash
curl "http://127.0.0.1:12000/map?key=..."   # {"nodes": [...], "edges": [...]}
```

Relationerna visar bara kandidater som är rekommenderade eller möjliga (högst
två per tabellpar), annars dränks de i svaga förslag. En kolumn vars namn
antydar ett mått eller datum (`belopp`, `order_date`, `amount`) visas inte som
nyckel: i ett litet datamaterial blir ett belopp unikt av en slump utan att vara
en identifierare. En kolumn som faktiskt används i en koppling listas som nyckel
även om den inte är unik ensam.

## Ämnesområden

Fliken `Ämnesområden` visar fakta, dimensioner och mått härledda ur specen. En
entitet med mått blir fakta, en som bara beskriver blir dimension, och en
dimension som delas av flera områden är konform. Se `docs/amnesomraden.md`.

```bash
python -m excel_merge.cli subjects --spec config/relations.yaml
curl "http://127.0.0.1:12000/subjects?key=..."   # {"subjects": [...], "conformed": [...], "unassigned": [...]}
```

Härledningen är regelbaserad och deterministisk, utan språkmodell. Den läser
specen och skriver ingenting tillbaka. **Det är därför steget får köras utan
human in the loop, medan kopplingar och orphan-policy inte får det:** gränsen går
vid skrivning, inte vid läsning. En felaktig klassning förstör ingen data.

Två regler är värda att känna till. En nyckel och en främmande nyckel blir
aldrig mått, även när de är tal. Och oklassad är ett giltigt svar: en entitet
utan mått som inget bygge nämner rapporteras i `unassigned` i stället för att
tvingas in i en roll.

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
- Ordningen i registreringen är inte valfri: kopplingen söks **före** egennyckeln.
  En tabell med både `supplier_id` och `customer_id` ska bli entiteten `supplier`
  med en koppling till `customer`. Söks egennyckeln först blir `supplier_id` en
  "främmande nyckel" mot en entitet som inte finns, och tabellen hamnar fel.
- Är den enda kandidatnyckeln referensen till en befintlig entitet är fliken
  **ännu en källa för samma entitet**, inte en ny entitet som pekar på den.
  Referensen till sig själv är ingen relation.
- `ruamel` fäster en sektions rubrikkommentar på sektionens sista post. Lägger man
  en post via ruamel hamnar den under fel rubrik. Därför byggs blocken som text och
  sätts in på radnummer ur `structure.lc.data[sektion][0]`, och insättningen sker
  nedifrån och upp.
- `Path.relative_to` ger fel sökväg om man lägger på `../` manuellt - djupet
  varierar. Använd `os.path.relpath` mot specens katalog.
- En kolumnmappning måste vara injektiv: `Belopp` och `belopp` normaliseras båda
  till `belopp`. Utan avkollision skriver den ena tyst över den andra.
- `ModuleNotFoundError: No module named 'pandas'` betyder nästan alltid att
  sessionens hemkatalog nollställts, inte att koden är fel. Installera om med
  `python -m pip install -e ".[dev]"`, eller starta via `./scripts/serve_webapp.sh`
  som gör det åt dig. Samma sak gäller `/tmp`: filer där (till exempel en
  spec-backup) försvinner mellan tillfällen. Ta backup i `git`, inte i `/tmp`.
- Appen skriver nyckeln med `print`. Startar man utan `-u` buffras den, och en
  lyckad start ser ut som en tom logg. Starta via skriptet.
