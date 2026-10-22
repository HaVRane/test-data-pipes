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

## Enklaste vägen: uppladdningssidan

GUI:ts uppladdning krånglar. Därför finns en liten tillfällig webbsida där du
drar in filerna. Den skriver till `data/inbox/` och kräver en nyckel i URL:en.

```bash
python scripts/upload_server.py --directory data/inbox --port 12000
```

Skriptet skriver ut en URL med nyckel, ungefär:

```
http://0.0.0.0:12000/?key=<slumpad nyckel>
```

I den här sandboxen nås port 12000 utifrån som:

```
https://work-1-geobaeplpkwzfkiz.prod-runtime.all-hands.dev/?key=<nyckel>
```

Öppna adressen i webbläsaren och dra in dina Excel-filer. Sidan visar vad som
mottagits. Stäng servern (Ctrl+C) när filerna är överförda.

Skyddet: slumpad nyckel krävs, bara kalkylarksändelser accepteras, filnamnet
tvättas så ingen kan skriva utanför katalogen, och det finns en storleksgräns.

## Om uppladdningen ändå strular

Klistra in fliknamn och kolumnrubriker i chatten i stället. Det räcker för att
bygga fixtures och spec-poster; verktyget ovan behöver bara kolumnnamnen, inte
innehållet. Är uppgifterna känsliga är det till och med bättre att beskriva
strukturen än att ladda upp filen.

## Webbapplikationen med tre flikar

Den enkla uppladdningssidan är ersatt av en liten applikation:

```bash
python scripts/webapp.py --data-dir data --inbox data/inbox --port 12000
```

Skriptet skriver ut port och nyckel. I sandboxen nås port 12000 som:

```
https://work-1-geobaeplpkwzfkiz.prod-runtime.all-hands.dev/?key=<nyckel>
```

Flikar:

- **Ladda upp** — dra in Excel-filer. De hamnar i `data/inbox/`.
- **Indata** — arbetsböcker och flikar som hittats i `data/` och `data/inbox/`,
  med rad- och kolumnantal.
- **Kolumner och koppling** — kolumnprofil per datakälla (typ, distinkta värden,
  tomma, möjliga nycklar) samt rangordnade förslag på hur källorna kopplas ihop.
- **Indatarelationer** — en översikt över datakällorna och nycklarna som binder
  dem samman. Varje ruta är en tabell (flik), pilarna visar föreslagna
  kopplingar.
- **Ändringslogg** — vad som ändrats i data sedan senast, med möjlighet att
  filtrera per händelse och källa.

All beräkning sker i Python på servern; JavaScript visar bara resultatet. Det gör
att flikarna visar exakt samma siffror som `cli profile` och testerna.
