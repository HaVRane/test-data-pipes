# AGENTS.md

Repo-minne för AI-agenter och utvecklare. Läs detta först.

## Vad repot gör

Ett konfigurationsdrivet dataflöde: läser en flik från var och en av två (eller
fler) Excel-arbetsböcker, kopplar ihop dem på en nyckelkolumn och skriver
resultatet till ett nytt Excel-ark.

Flödet är medvetet delat i två lager:

1. **Konfiguration** (`config/pipeline.yaml`) – vilka källor, flikar, kolumner,
   nycklar och utdata som gäller. Ingen kod behöver ändras för att lägga till en
   källa eller byta kolumnnamn.
2. **Kod** (`src/excel_merge/`) – generisk maskineri som tolkar konfigurationen.

## Kommandon

```bash
pip install -e ".[dev]"          # installera med testberoenden
python -m pytest                 # kör hela testsviten (krav: alla gröna)
python -m pytest tests/test_config.py -q   # bara en fil
python scripts/make_sample_data.py         # skapa exempeldata i data/
python -m excel_merge.cli --config config/pipeline.yaml   # kör flödet
```

## Så lägger du till en ny källa

1. Lägg till ett nytt block under `sources:` i `config/pipeline.yaml` med
   `name`, `path`, `sheet`, `columns` (original -> nytt namn) och ev. `dtypes`.
2. Om den nya källan är den tredje eller fler: kontrollera `join.on` och
   `join.validate`. Kedjan kopplas ihop i den ordning källorna listas.
3. Lägg till en fixture för källan i `tests/fixtures.py` (bygg arbetsboken i
   kod, checka aldrig in binära filer).
4. Lägg till minst ett test i `tests/test_pipeline.py` som bevisar att den nya
   källan faktiskt bidrar med data.
5. Uppdatera golden-filen: `UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py`
   och granska diffen i `tests/golden/merged_left.csv` innan du committar.
6. Kör `python -m pytest` – allt ska vara grönt.

## Så ändrar du dataflödet

- Byt kopplingstyp eller nyckel: ändra `join:` i konfigurationen. `validate`
  fungerar som skyddsnät mot oavsiktliga dubbletter (`many_to_one` osv).
- Ändra kolumnordning/urval i utdata: `output.columns`.
- Ny logik som inte ryms i konfigurationen hör hemma i `src/excel_merge/pipeline.py`.
  Lägg då till ett test som beskriver den nya regeln **innan** du ändrar koden.

## Teststrategi (viktigast för agenter)

- `tests/test_config.py` – validering, kräver ingen Excel.
- `tests/test_io.py` – läsning/typning av en enskild flik, inkl. felvägar.
- `tests/test_pipeline.py` – sammanslagning, kopplingstyper, `validate`.
- `tests/test_cli.py` – end-to-end via kommandoraden.
- `tests/test_golden.py` – låser hela utdata för standardflödet.

Principer:
- All testdata byggs i kod (`tests/fixtures.py`), aldrig incheckade `.xlsx`.
- Testa felvägar, inte bara lyckade fall.
- Golden-filen är ett medvetet kontrakt. Ändrar du den måste diffen förklaras.
- Inga mockar: testerna kör riktig pandas/openpyxl mot temporära filer.

## Kända fallgropar

- **YAML 1.1**: nyckeln `on:` tolkas av PyYAML som boolean `True`. `config.py`
  normaliserar detta i `_join_keys`. Skriv inte om den logiken utan att förstå varför.
- Sökvägar i konfigurationen tolkas relativt `config/`, inte arbetskatalogen.
- `read_sheet` väljer bara de kolumner som nämns i `columns`, i den ordningen.
