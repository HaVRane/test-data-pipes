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

1. Agenten profilerar den nya källan mot befintliga: `cli profile`.
2. Agenten föreslår en ändring i `config/relations.yaml` som en diff.
3. Testerna avgör om ändringen är rimlig: kan den kopplas in, blir kardinaliteten
   vad den ska, ändras golden-filen på ett förklarligt sätt?
4. En människa granskar diffen, särskilt kardinalitet och orphaning-policy.

Punkt 3 är den viktiga. Specen är ett kontrakt som testerna bevakar. En agent kan
därför prova sig fram utan att kunna smyga in en felaktig koppling: antingen
håller den, eller så går ett test rött och visar exakt var.

## Varför inte automatisk nyckeldetektering som sanning

Man *kan* låta ett verktyg gissa nycklar utifrån namn och värdeöverlapp. Det är
användbart som förslag och farligt som sanning. Två kolumner med 100 procents
överlapp kan fortfarande betyda olika saker, och en koppling som ser bra ut i
testdata kan vara fel i skarp data. Därför ligger gissningen i `profile`, medan
beslutet ligger i specen och granskas som en diff.
