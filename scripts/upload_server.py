"""Tillfällig uppladdningssida för att få in Excel-filer i sandboxen.

Startar en liten webbsida där man drar in sina filer. Filerna skrivs till
data/inbox/ och kan sedan inventeras med scripts/inspect_uploads.py.

Säkerhetsavvägningar, eftersom tjänsten nås via en extern URL:

- En slumpad nyckel krävs (?key=...). Utan rätt nyckel svarar servern 403.
- Bara kända kalkylarksändelser accepteras.
- Filnamnet tvättas; ingen katalogtraversering kan ske.
- En storleksgräns per fil.
- Servern skriver bara i den angivna mottagningskatalogen.

Kör den bara medan filerna ska överföras.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ALLOWED_SUFFIXES = {".xlsx", ".xls", ".xlsm", ".csv"}
MAX_BYTES = 25 * 1024 * 1024

PAGE = """<!doctype html>
<html lang="sv">
<meta charset="utf-8">
<title>Ladda upp Excel-filer</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 42rem; margin: 3rem auto; padding: 0 1rem; }}
  #drop {{ border: 2px dashed #888; border-radius: 8px; padding: 3rem 1rem; text-align: center;
           cursor: pointer; background: #fafafa; }}
  #drop.hot {{ border-color: #2563eb; background: #eff6ff; }}
  ul {{ padding-left: 1.2rem; }}
  .ok {{ color: #15803d; }}
  .err {{ color: #b91c1c; }}
  code {{ background: #f3f4f6; padding: 0 .25rem; }}
</style>
<h1>Ladda upp Excel-filer</h1>
<p>Dra in filerna i rutan. De hamnar i <code>data/inbox/</code> och versionshanteras inte.</p>
<div id="drop">Släpp filerna här, eller klicka för att välja</div>
<input id="picker" type="file" multiple accept=".xlsx,.xls,.xlsm,.csv" hidden>
<h2>Mottaget</h2>
<ul id="list"></ul>
<script>
const KEY = new URLSearchParams(location.search).get("key") || "";
const drop = document.getElementById("drop");
const picker = document.getElementById("picker");
const list = document.getElementById("list");

async function refresh() {{
  const res = await fetch("/list?key=" + encodeURIComponent(KEY));
  if (!res.ok) {{ list.innerHTML = "<li class='err'>Kunde inte läsa katalogen</li>"; return; }}
  const files = await res.json();
  list.innerHTML = files.length
    ? files.map(f => `<li class="ok">${{f.name}} <small>(${{f.size}} byte)</small></li>`).join("")
    : "<li>Inga filer ännu</li>";
}}

async function upload(file) {{
  const res = await fetch("/upload?key=" + encodeURIComponent(KEY), {{
    method: "POST",
    headers: {{ "X-Filename": encodeURIComponent(file.name) }},
    body: file,
  }});
  const out = await res.json().catch(() => ({{ detail: res.statusText }}));
  return `${{file.name}}: ${{res.ok ? "OK" : "FEL - " + out.detail}}`;
}}

async function handle(files) {{
  for (const file of files) {{
    const msg = await upload(file);
    const li = document.createElement("li");
    li.textContent = msg;
    li.className = msg.includes("OK") ? "ok" : "err";
    list.prepend(li);
  }}
  refresh();
}}

drop.onclick = () => picker.click();
picker.onchange = () => handle(picker.files);
["dragenter", "dragover"].forEach(e => drop.addEventListener(e, ev => {{
  ev.preventDefault(); drop.classList.add("hot");
}}));
["dragleave", "drop"].forEach(e => drop.addEventListener(e, ev => {{
  ev.preventDefault(); drop.classList.remove("hot");
}}));
drop.addEventListener("drop", ev => handle(ev.dataTransfer.files));
refresh();
</script>
</html>
"""


def safe_name(raw: str) -> str:
    """Tvättar filnamnet så att ingen kan skriva utanför katalogen."""
    name = Path(raw).name
    name = name.replace("\x00", "").strip()
    if not name or name.startswith("."):
        raise ValueError("ogiltigt filnamn")
    if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"filtypen tillåts inte (tillåtna: {sorted(ALLOWED_SUFFIXES)})")
    return name


class Handler(BaseHTTPRequestHandler):
    inbox: Path
    key: str

    def _authorized(self, query: dict[str, list[str]]) -> bool:
        return secrets.compare_digest(query.get("key", [""])[0], self.key)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # tystare logg
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._authorized(query):
            self.send_error(403, "ogiltig eller saknad nyckel")
            return
        if parsed.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/list":
            files = [
                {"name": p.name, "size": p.stat().st_size}
                for p in sorted(self.inbox.iterdir())
                if p.is_file() and p.suffix.lower() in ALLOWED_SUFFIXES
            ]
            self._json(200, files)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._authorized(query):
            self.send_error(403, "ogiltig eller saknad nyckel")
            return
        if parsed.path != "/upload":
            self.send_error(404)
            return

        from urllib.parse import unquote

        raw_name = unquote(self.headers.get("X-Filename", ""))
        try:
            name = safe_name(raw_name)
        except ValueError as exc:
            self._json(400, {"detail": str(exc)})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json(400, {"detail": "tom fil"})
            return
        if length > MAX_BYTES:
            self._json(413, {"detail": f"filen är större än {MAX_BYTES // (1024 * 1024)} MB"})
            return

        data = self.rfile.read(length)
        target = self.inbox / name
        target.write_bytes(data)
        self._json(200, {"success": True, "file": name, "file_size": len(data)})


def serve(directory: Path, port: int, key: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    handler = type("BoundHandler", (Handler,), {"inbox": directory, "key": key})
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"Uppladdningssida på port {port}, mottagningskatalog {directory}")
    print(f"Nyckel: {key}")
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tillfällig uppladdningssida för Excel-filer.")
    parser.add_argument("--directory", type=Path, default=Path("data/inbox"))
    parser.add_argument("--port", type=int, default=12000)
    parser.add_argument("--key", default=None, help="Nyckel som krävs i URL:en (slumpas annars)")
    args = parser.parse_args(argv)
    serve(args.directory, args.port, args.key or secrets.token_urlsafe(16))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
