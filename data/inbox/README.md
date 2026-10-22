# Mottagningskatalog för uppladdade filer

Lägg Excel-filer här. Innehållet är gitignorerat och hamnar aldrig i
versionshantering. Katalogen hålls kvar i git via `.gitkeep`.

Inventera innehållet utan att ändra något:

```bash
python scripts/inspect_uploads.py data/inbox
python scripts/inspect_uploads.py data/inbox --reference data/customers.xlsx
```

Se `docs/ladda-upp-filer.md` för hur filerna kommer hit.
