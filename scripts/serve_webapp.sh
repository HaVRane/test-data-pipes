#!/usr/bin/env bash
#
# Startar webbapplikationen i bakgrunden och skriver ut adressen med nyckel.
#
# Skriptet finns för att två saker annars går fel:
#
#   1. Beroendena kan saknas. Sessionens hemkatalog kan nollställas mellan
#      tillfällen, och då är pandas borta trots att det fungerade förra gången.
#      Därför kontrolleras importen först och pyproject installeras vid behov.
#   2. Utan -u buffras utskrifterna. Nyckeln skrivs ut först när bufferten
#      töms, så en loggfil ser tom ut och det är lätt att tro att starten
#      misslyckades. -u gör att nyckeln syns direkt.
#
# Nyckeln slumpas av applikationen och skrivs aldrig till disk här. Porten är
# nåbar utifrån i den här miljön, så en fast nyckel i ett skript vore en öppen
# dörr.

set -u

cd "$(dirname "$0")/.."

PORT="${PORT:-12000}"
LOG="${LOG:-/tmp/webapp.log}"

if ! python -c "import pandas" 2>/dev/null; then
  echo "Beroenden saknas - installerar (kan ta en stund)..."
  python -m pip install -q -e ".[dev]" || {
    echo "Kunde inte installera beroendena. Kör för hand:" >&2
    echo "  python -m pip install -e '.[dev]'" >&2
    exit 1
  }
fi

# Stoppa en tidigare instans på samma port, så att den nya inte tyst hamnar
# bakom en gammal process.
if pgrep -f "webapp.py .*--port $PORT" >/dev/null 2>&1; then
  echo "Stoppar tidigare instans på port $PORT..."
  pkill -f "webapp.py .*--port $PORT"
  sleep 1
fi

: > "$LOG"
nohup python -u scripts/webapp.py --data-dir data/isa --port "$PORT" \
  >> "$LOG" 2>&1 &

for _ in $(seq 1 30); do
  if grep -q "nyckel:" "$LOG" 2>/dev/null; then break; fi
  sleep 0.5
done

if ! grep -q "nyckel:" "$LOG" 2>/dev/null; then
  echo "Starten misslyckades. Loggen säger:" >&2
  cat "$LOG" >&2
  exit 1
fi

KEY="$(sed -n 's/.*nyckel: //p' "$LOG" | head -1)"

if curl -s -o /dev/null --max-time 5 "http://127.0.0.1:$PORT/?key=$KEY"; then
  echo "Applikationen körs på port $PORT."
else
  echo "Applikationen startade men svarar inte på port $PORT." >&2
  exit 1
fi

echo
echo "  Lokalt:   http://127.0.0.1:$PORT/?key=$KEY"
echo "  Sandlådan: https://work-1-geobaeplpkwzfkiz.prod-runtime.all-hands.dev/?key=$KEY"
echo
echo "  Logg:     $LOG"
echo "  Stoppa:   pkill -f 'webapp.py .*--port $PORT'"
