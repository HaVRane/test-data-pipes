# Ändringslogg för datakällor

Loggen beskriver ändringar i **datan**, inte i applikationen. Den svarar på
frågan "vad hände med källorna, och när?" och är grunden för att kunna lägga
till, ändra och ta bort källor utan att tappa historiken.

## Kommandon

```bash
python -m excel_merge.cli watch --spec config/relations.yaml
python -m excel_merge.cli log
```

`watch` jämför källorna mot senast kända tillstånd och skriver nya händelser.
`log` visar historiken, nyast först.

```bash
python -m excel_merge.cli log --event source_changed      # bara ändringar
python -m excel_merge.cli log --source customers          # bara en källa
python -m excel_merge.cli log --limit 10                  # de tio senaste
python -m excel_merge.cli watch --verbose                 # logga även oförändrade
```

## Händelser

Varje händelse har ett **slag** (`kind`) som säger vad den handlar om.

### Slag: `data` - ändringar i innehållet

| Händelse | Betyder |
|---|---|
| `source_added` | källan finns men har inte setts förut |
| `source_removed` | källan har setts förut men finns inte längre |
| `source_changed` | innehållet har ett annat fingeravtryck än förra körningen |
| `source_unchanged` | innehållet är identiskt (endast med `--verbose`) |
| `source_unreadable` | filen finns men kunde inte läsas |
| `source_recovered` | källan gick inte att läsa förra körningen men gör det nu |

### Slag: `structure` - ändringar i pipens uppbyggnad

Dessa beskriver specen, inte datat. De svarar på frågan "hur har dataflödet
förändrats?", vilket är precis vad en agent behöver veta innan den rör något.

| Händelse | Betyder |
|---|---|
| `source_declared` | en källa har lagts in i `relations.yaml` |
| `source_undeclared` | en källa har strukits ur specen |
| `source_redefined` | källans nyckel, kolumner eller typer har ändrats |
| `entity_declared` | en ny entitet har definierats |
| `entity_undeclared` | en entitet har tagits bort |
| `entity_redefined` | entitetens nyckel eller beskrivning har ändrats |
| `build_redefined` | ett bygge har ändrats (bas, urval eller kolumner) |

### Slag: `ingest` - filer som kommit in

| Händelse | Betyder |
|---|---|
| `file_received` | en fil har laddats upp till `data/isa/` |

## Ett flöde, tre slag

Alla händelser hamnar i samma fil, `state/changelog.ndjson`, i tidsordning. Det
gör att en enda läsning ger hela historiken: när filen kom in (`ingest`), vad den
innehöll (`data`) och hur pipen byggdes om för att ta emot den (`structure`).
Alternativet - en logg per slag - hade tvingat varje läsare att själv lägga ihop
tidslinjen, och då hade ordningen mellan "filen kom" och "källan lades in"
kunnat gå förlorad.

## Saknad fil och trasig fil är inte samma sak

Detta är den viktigaste distinktionen i bevakningen.

En källa vars **fil eller flik inte finns** existerar inte längre. Den tas bort
ur modellen och rapporteras som `source_removed` med orsaken
`filen eller fliken saknas`. Det är bokstavligen samma sak som att stryka posten
ur specen: `run` och `plan` behandlar den reducerade specen som om posten aldrig
funnits, och ett bygge som förlorat sin enda källa till en entitet ger exakt
samma fel som om posten saknats från början.

En **trasig fil** är något annat. Den finns kvar på disken, vi kan bara inte
tolka den. Den rapporteras som `source_unreadable`, och källan behåller sitt
senaste kända fingeravtryck i tillståndet. Kommer den tillbaka går det att se
att innehållet är oförändrat sedan sist.

Skillnaden avgör vad som händer med modellen: en saknad källa försvinner, en
trasig blir kvar men oläsbar. Att läsa in en trasig fil i modellen vore fel,
men att kasta bort en tillfälligt oläsbar källas historik vore lika fel.

Konsekvensen av att en källa tas bort är att den som kommer tillbaka rapporteras
som `source_added`, inte som återställd. Det finns inget att återställa - den
blev en ny källa när den försvann.

## Varför fingeravtryck av innehållet och inte av filen

Excel skriver om hela filarkivet varje gång filen sparas, även när ingen uppgift
ändrats. En hash av filen skulle därför larma varje gång någon öppnar och
stänger filen. Fingeravtrycket hashar i stället **cellvärdena**, så det är
stabilt så länge datan är stabil. Det finns ett test för just detta
(`test_rewriting_file_without_data_change_is_not_a_change`).

Normaliseringen hanterar att Excel ger samma uppgift olika Python-typ mellan
läsningar: `1` och `1.0` ger samma värde, liksom talet `42` och texten `"42"`.
Utan det skulle loggen fyllas av falska ändringar.

Radordning och kolumnordning ingår i fingeravtrycket. Att sortera om raderna är
en ändring av källan som är värd att känna till.

## Två filer, två syften

| Fil | Roll |
|---|---|
| `state/changelog.ndjson` | läsbar historik, en JSON-rad per händelse |
| `state/sources.json` | senast kända fingeravtryck, det `watch` jämför mot |

Loggen är append-only och skrivs aldrig över. Tillståndet skrivs atomiskt
(temporärfil och namnbyte), så ett avbrott inte lämnar ett halvskrivet tillstånd.

Katalogen `state/` är gitignorerad: den beskriver den lokala datans skick, inte
koden.

## Exempel

```
$ python -m excel_merge.cli watch --spec config/relations.yaml
+ customers tillagd (4 rader)
+ orders tillagd (4 rader)

$ python -m excel_merge.cli watch --spec config/relations.yaml
Inga ändringar sedan förra körningen.

$ python -m excel_merge.cli log
2026-10-22T12:42:25+00:00  source_changed   customers   4 -> 5 rader, a45a51e9f1ef -> 92b85e5c8d36
2026-10-22T12:00:00+00:00  source_added     orders      4 rader
2026-10-22T12:00:00+00:00  source_added     customers   4 rader
```

## Vad loggen inte gör

Loggen beskriver att något ändrats, inte om ändringen är *önskvärd*. Den avgör
inte om en ny kolumn ska in i specen, eller om en försvunnen kolumn ska fälla
körningen. Det är fortfarande ett mänskligt beslut, och testerna är domen.
Loggen ger underlaget.
