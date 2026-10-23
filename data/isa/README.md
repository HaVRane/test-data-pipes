# Datakatalog

Här ligger datakällorna: de Excel-ark flödet läser. Innehållet är gitignorerat
och hamnar aldrig i versionshantering. Katalogen hålls kvar i git via
`.gitkeep`.

Uppladdning via webbapplikationen landar här, och det är samma katalog som
specen pekar på. Det finns alltså en plats för datat, inte två.

Skapa exempeldata att köra mot:

```bash
python scripts/make_sample_data.py
```

Inventera innehållet utan att ändra något:

```bash
python scripts/inspect_uploads.py data/isa
python scripts/inspect_uploads.py data/isa --reference data/isa/customers.xlsx
```

Se `docs/ladda-upp-filer.md` för hur filerna kommer hit.
