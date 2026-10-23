# Hur källor kopplas ihop

Frågan: när antalet källor växer från två till många, hur avgör vi vad som ska
kopplas mot vad? Ska en agent bestämma det, eller ska det finnas en spec?

Kort svar: båda, med en tydlig arbetsdelning.

## Varför en spec och inte bara kod

En rak kedja av sammanslagningar fungerar för två källor men inte för tio. Efter
ett tag står man med tio specialfall i koden och ingen vet vilken kolumn som är
sanning. Problemet är inte koden, det är att ingen har skrivit ner *vad datan
betyder*.

Därför beskrivs dataflödet som entiteter och relationer:

- En **entitet** är ett begrepp datan handlar om (kund, order, produkt) och har
  en nyckel som identifierar en rad.
- En **källa** är en konkret flik i en konkret fil som tillhandahåller en entitet.
- En **relation** säger att en entitet pekar på en annan via en kolumn, med en
  kardinalitet och en policy för rader som inte matchar.
- Ett **bygge** är en utdata som plockas fram ur entiteterna.

Körordningen härleds ur grafen. Ingen skriver tio specialfall: lägger man till en
entitet i specen får man den i planen automatiskt, förutsatt att den hänger ihop
med basen. Gör den inte det avvisas specen, i stället för att tyst ge fel svar.

## Vad en agent kan göra, och vad den inte ska göra

En agent är bra på det mekaniska och det detekterbara:

- Profilera kolumner: typer, unikhet, nollvärden.
- Hitta kandidatnycklar genom att jämföra överlapp mellan datamängder.
- Räkna ut kardinalitet och hur många nycklar som saknar match.
- Föreslå en spec-post och uppdatera golden-filen.
- Upptäcka att en ny källa inte går att nå från basen.

En agent ska inte ensam avgöra det som är affärsbeslut:

- Vad en kolumn *betyder*. Att två kolumner heter `id` betyder inte att de avser
  samma sak.
- Vilken kardinalitet som är *avsedd*. Att datan råkade vara 1:1 i ett utdrag
  betyder inte att den är det i verksamheten.
- Vad som ska hända med rader som inte matchar. Släppa, behålla eller flagga är
  en affärsregel.

Därför är verktygets utdata formulerad som bevis med en tydlig uppmaning att
bekräfta, inte som ett färdigt svar. `python -m excel_merge.cli profile` skriver
ut underlaget och ett utkast till spec-post där kardinalitet och orphaning-policy
är markerade som obekräftade.

## Arbetsflödet när en ny källa ska in

1. Filen laddas upp till `data/isa/`.
2. `register_source` läser flikens kolumner, föreslår en nyckel och en koppling,
   och skriver in posten i `config/relations.yaml`.
3. Specen laddas om och valideras. En post som inte håller skrivs aldrig.
4. Händelsen loggas: `file_received`, `source_declared` och eventuellt
   `entity_declared`.
5. Testerna avgör om ändringen är rimlig: kan den kopplas in, blir kardinaliteten
   vad den ska, ändras golden-filen på ett förklarligt sätt?
6. En människa granskar diffen i `relations.yaml`, särskilt kardinalitet och
   orphaning-policy.

Steg 2 gör att en uppladdad fil alltid blir en källa. Det finns ingen väg där en
fil hamnar i `data/isa/` utan att synas i pipen. Steg 3 och 5 är det som gör
automatiken försvarlig: skrivningen valideras mot kontraktet, och testerna
bevakar att kontraktet fortfarande betyder något.

## Nycklar som maskinen får och inte får bestämma

Maskinen får bestämma **vilken kolumn som identifierar en rad**: en kolumn som är
unik och saknar nollvärden duger, och ett namn som *innehåller* `id`, `nr`,
`nummer`, `kod`, `code`, `nyckel` eller `beteckning` väger tyngre än andra. Det
är en egenskap hos datat och går att avgöra.

Matchningen sker på delsträng, inte på avgränsat ord, eftersom svenska
kolumnnamn ofta sätter ihop orden: `Lanskod`, `Kundnummer`, `Ordernr`. En regel
som krävde understreck före ändelsen hade missat dem, och då hade
bokstavsordningen avgjort - i en tabell som `Länsinfo` hade befolkningssiffran
blivit nyckeln. Se `joins.looks_like_identifier` och `register.candidate_keys`.

Maskinen får inte bestämma **kardinalitet**. Att två kolumner överlappar säger
inget om affärsreglerna: en kund kan ha flera ordrar även om just detta utdrag
råkar ha en order per kund. Därför skriver registreringen `many_to_one` - den
säkra läsningen av en referens till en befintlig entitet - och märker raden med
en kommentar om att den ska bekräftas. Se avsnittet nedan.

Maskinen får inte heller bestämma **orphaning-policy**. Den skriver `keep`, som
bevarar alla rader, och en människa ändrar till `drop` eller `flag` om det är fel
för verksamheten.

## När fliken saknar egen nyckel

En flik utan unik kolumn - en logg, en lista med fritext - får en `row_key`:
radens nummer i fliken. Den blir en källa som alla andra, med en surrogatnyckel i
stället för en naturlig. Utan den vore valet att antingen ignorera filen, vilket
strider mot att varje uppladdad fil ska bli en källa, eller att tyst hitta på en
nyckel ur en kolumn som inte är unik, vilket ger felaktiga kopplingar.

En surrogatnyckel identifierar en *rad*, inte ett *begrepp*. Den duger för att
läsa och bygga med fliken, men den kan inte användas för att koppla ihop fliken
med något annat.

## Varför inte automatisk nyckeldetektering som sanning

Man *kan* låta ett verktyg gissa nycklar utifrån namn och värdeöverlapp. Det är
användbart som förslag och farligt som sanning. Två kolumner med 100 procents
överlapp kan fortfarande betyda olika saker, och en koppling som ser bra ut i
testdata kan vara fel i skarp data. Därför ligger gissningen i `profile`, medan
beslutet ligger i specen och granskas som en diff.

## Ett exempel: en ny fil blir en källa

Utgångsläget är en spec med entiteterna `customer` och `order`. En fil,
`Leverantorer.xlsx`, laddas upp med fliken `Suppliers` och kolumnerna
`supplier_id`, `customer_id`, `supplier_name`.

Registreringen gör följande:

- `supplier_id` är unik och slutar på `_id`, så den blir källans nyckel.
- `customer_id` matchar `customer`-entitetens nyckel i alla rader, så den blir en
  koppling dit. Källans egen nyckel hoppas över när kopplingen söks.
- Nyckelns rot `supplier` blir ett nytt entitetsnamn.
- Kardinaliteten sätts till `many_to_one` och märks som obekräftad.

Resultatet i `relations.yaml` - bara tillägg, inga omformateringar:

```yaml
  supplier:
    key: supplier_id
    description: En rad per supplier_id i Leverantorer.xlsx.
```

```yaml
  - name: leverantorer
    path: ../data/isa/Leverantorer.xlsx
    sheet: Suppliers
    entity: supplier
    columns:
      supplier_id: supplier_id
      customer_id: customer_id
      supplier_name: supplier_name
    relationships:
      - to: customer
        via: customer_id
        cardinality: many_to_one  # maskinellt föreslagen - bekräfta mot verksamheten
        orphans: keep
```

Två saker att lägga märke till. Kommentaren på `cardinality` är kvar i filen, så
den som granskar diffen ser direkt vilket beslut som är maskinens förslag och
vilket som är människans. Och `orphans: keep` bevarar alla rader - ingen data
försvinner för att en koppling saknas.

Saknade fliken en unik kolumn hade posten i stället fått en `row_key`, och
entiteten hade döpts efter fliken.

## Nästa steg: ämnesområden

Kopplingen säger vilka rader som hör ihop. Nästa fråga är vad datan *betyder*:
vilka tabeller som är fakta, vilka som är dimensioner och vilka kolumner som är
mått. Det härleds ur specen och beskrivs i `docs/amnesomraden.md`.

Skillnaden mot kopplingarna är värd att hålla i minnet. En koppling och en
orphan-policy styr vad som skrivs ut, och måste därför bekräftas av en människa.
Ett ämnesområde är en vy som inte skriver något tillbaka, och kan därför härledas
helt automatiskt.

## Vad testerna bevakar

- Att kommentarerna i specen överlever en skrivning.
- Att bara det nya blocket tillkommer - inte en omformaterad fil.
- Att en post som inte validerar lämnar filen orörd.
- Att en flik utan egen nyckel ändå blir en källa, med radnyckel.
- Att en koppling bara läggs till när nycklarna matchar utan föräldralösa rader.
- Att en källa som lagts in går att läsa och bygga med, inte bara står i specen.

