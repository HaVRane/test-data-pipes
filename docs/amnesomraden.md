# Ämnesområden, fakta och mått

Relationsspecen beskriver *vad* datan handlar om: entiteter, nycklar och hur de
hänger ihop. Den beskriver inte *hur datan ska läsas*: vilka tabeller som är
fakta, vilka som är dimensioner och vilka kolumner som är mått.

Det steget är härlett. Den här sidan beskriver hur, och varför det får ske utan
att någon granskar resultatet först.

## Varför det kan köras utan human in the loop

Kardinalitet och orphaning-policy är affärsbeslut som måste bekräftas, eftersom
de styr vad som skrivs ut. En felaktig sådan ändrar data.

Ämnesområdena är något annat: en **vy** över specen. De skriver ingenting
tillbaka. En felaktig klassning förstör ingen data och gör ingen pipeline fel -
den visar bara en rad på fel ställe, och nästa körning visar rätt igen.

Gränsen går alltså vid skrivning, inte vid läsning. Det är därför det här steget
kan vara helt automatiskt medan kopplingarna inte kan vara det.

## Vad som härleds

Klassningen följer dimensionell modellering:

- En **fakta** är en entitet som går att mäta på: den har mått utöver sin nyckel
  och sina främmande nycklar.
- En **dimension** är en entitet som beskriver något. Dess kolumner är attribut,
  och den pekas på av fakta.
- Ett **mått** är en kolumn som går att summera eller jämföra över tid, alltså
  ett tal eller en tidpunkt.
- En **konform dimension** används av mer än ett ämnesområde. Det är samma
  begrepp på flera ställen, och därför värt att se separat.
- Ett **ämnesområde** är en sammanhängande grupp. Det motsvarar ett bygge, och
  saknas byggen en sammanhängande del av entitetsgrafen.

Ett ämnesområde motsvarar ett bygge eftersom bygget redan definierar en
sammanhängande grupp. Fallbacken till grafen gör att vyn är användbar även innan
något bygge skrivits.

## Reglerna, och varför de ser ut som de gör

En nyckel är aldrig ett mått, och en främmande nyckel är aldrig ett mått, även
när de råkar vara tal. `customer_id` är ett tal, men att summera det vore
meningslöst: det är en referens, inte en storhet.

Slaget avgörs av verkliga värden när filen går att läsa, annars av deklarerade
typer i specen. Verkliga värden är säkrare, men deklarationen räddar klassningen
när filen inte är tillgänglig - en kolumn som specen säger är `float` är ett mått
oavsett.

Saknas båda blir entiteten en dimension. Det är rätt svar på fel fråga: vi vet
inte att kolumnen är ett mått, och att gissa vore värre än att avstå.

**Oklassad är ett giltigt svar.** En entitet utan mått som ingen pekar på tvingas
inte in i en roll. Den rapporteras i stället, av samma skäl som att ingen
uppladdad fil får ignoreras tyst.

## Så ser det ut

```bash
python -m excel_merge.cli subjects --spec config/relations.yaml
```

```
ämnesområde: customer_orders
  härlett ur bygget 'customer_orders' (bas: customer, inkluderar: order)
  fakta: order (nyckel order_id, källor: orders)
    radnivå: en rad per order_id och de nycklar den pekar på
    mått: order_amount [numeric]
    mått: order_date [datetime]
    främmande nyckel: customer_id -> customer (many_to_one)
  dimension: customer (nyckel customer_id)
    attribut: customer_name, segment
```

Samma sak visas i webbapplikationen under fliken **Ämnesområden**, med konforma
dimensioner och entiteter utanför varje område i egna tabeller.

## Varje roll bär sitt skäl

Ingen rad visas utan motivering. Ett mått säger varför det är ett mått:

> kolumnen 'amount' är ett tal och är varken nyckel eller främmande nyckel

Skälet finns med för att en agent ska kunna granska sin egen klassning och för
att en människa ska kunna invända mot en specifik regel i stället för mot
resultatet som helhet.

## Gränsen mot kopplingarna

| Fråga | Vem avgör | Får ändra data? |
|---|---|---|
| Vilka kolumner är mått? | härleds automatiskt | nej |
| Vilka entiteter är fakta? | härleds automatiskt | nej |
| Vilken nyckel kopplar ihop två källor? | människa, med maskinellt underlag | ja |
| Vad händer med rader utan matchning? | människa | ja |

De två nedersta raderna kräver en människa. De två översta gör det inte, och det
är just skillnaden mellan att läsa och att skriva.

## Vad testerna bevakar

`tests/test_subjects.py` prövar klassningen: fakta mot dimension, att nycklar
aldrig blir mått, konforma dimensioner, att ett tomt mått inte ger en falsk
fakta, att en entitet utanför alla byggen rapporteras, att fallbacken till grafen
fungerar, och att körningen är deterministisk.

Ett test bevakar särskilt att härledningen inte skriver något: specen läses före
och efter, och ska vara tecken för tecken identisk. Det är kärnan i varför
steget får köras utan granskning.

`tests/test_webapp_subjects.py` bevakar samma sak genom webbapplikationens
endpoint, plus att en trasig eller saknad spec blir ett begripligt meddelande i
stället för en tom sida.
