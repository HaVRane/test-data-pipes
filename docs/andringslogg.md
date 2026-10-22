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

| Händelse | Betyder |
|---|---|
| `source_added` | källan finns i specen men har inte setts förut |
| `source_removed` | källan har setts förut men finns inte i specen längre |
| `source_changed` | innehållet har ett annat fingeravtryck än förra körningen |
| `source_unchanged` | innehållet är identiskt (endast med `--verbose`) |

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
