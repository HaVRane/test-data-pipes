# Ladda upp Excel-filer till den här sessionen

## Problemet

GUI:t kan visa:

```
HTTP request failed (422): {"detail":"path must be inside the conversation workspace"}
```

Det betyder att uppladdningen försöker skriva filen till en sökväg utanför
samtalets arbetskatalog. Den här sessionens arbetskatalog är:

```
/workspace/project
```

Servern avvisar allt utanför den, även `/workspace`, `/tmp` och hemkatalogen.

## Verifierat beteende

Testat mot den lokala agent-servern på port 60000:

| Endpoint | Sökväg | Resultat |
|---|---|---|
| `/api/conversations/{id}/file/upload` | `/tmp/probe2.csv` | 422, "path must be inside the conversation workspace" |
| `/api/conversations/{id}/file/upload` | `/workspace/project/data/probe2.csv` | 200, filen skriven |

Slutsats: samma felmeddelande uppstår om den valda sökvägen ligger utanför
`/workspace/project`. Välj en plats innanför den katalogen.

## Vad du gör

Ladda upp till exempelvis:

```
/workspace/project/data/inbox/customers.xlsx
/workspace/project/data/inbox/orders.xlsx
```

Skapa `data/inbox/` först om den inte finns. Katalogen är gitignorerad, så
uppladdade filer hamnar aldrig i versionshantering.

## Sedan: en fil i taget

När filerna ligger i `data/inbox/` kan du inventera dem utan att skriva något:

```bash
python scripts/inspect_uploads.py data/inbox
```

Verktyget listar varje arbetsbok och flik, profilerar kolumnerna och skriver ut
ett utkast till spec-post som du kan klistra in i `config/relations.yaml`. Det
läser bara, det ändrar ingenting.

Vill du jämföra en ny fil mot en befintlig nyckel:

```bash
python scripts/inspect_uploads.py data/inbox --reference data/customers.xlsx
```

Då visas även kandidatkoppling med täckning, föräldralösa nycklar och föreslagen
kardinalitet — samma bevis som `cli profile`, men för en fil i taget.

## Om uppladdningen ändå strular

Klistra in fliknamn och kolumnrubriker i chatten i stället. Det räcker för att
bygga fixtures och spec-poster; verktyget ovan behöver bara kolumnnamnen, inte
innehållet. Är uppgifterna känsliga är det till och med bättre att beskriva
strukturen än att ladda upp filen.
