"""Webbapplikation med tre flikar: ladda upp, indata, kolumner och koppling.

Ersätter den tidigare enkla uppladdningssidan. Sidan är ett tunt skal över
samma logik som CLI:t använder - ingen databehandling sker i JavaScript.

Säkerhetsavvägningar, eftersom tjänsten nås via en extern URL:

- En slumpad nyckel krävs i URL:en. Utan rätt nyckel svarar servern 403.
- Bara kända kalkylarksändelser accepteras vid uppladdning.
- Filnamn tvättas; ingen katalogtraversering kan ske.
- Läsvägarna är begränsade till den angivna data- och mottagningskatalogen.
- Storleksgräns per fil.
"""

from __future__ import annotations

import argparse
import html
import json
import secrets
import sys
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd

from excel_merge.joins import rank_join_candidates
from excel_merge.profile import column_stats, compare_keys

ALLOWED_SUFFIXES = {".xlsx", ".xls", ".xlsm", ".csv"}
MAX_BYTES = 25 * 1024 * 1024

PAGE = """<!doctype html>
<html lang="sv">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Excel-koppling</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0;
         color: #111827; background: #f9fafb; }
  header { background: #fff; border-bottom: 1px solid #e5e7eb; padding: 1rem 1.5rem; }
  h1 { font-size: 1.15rem; margin: 0 0 .75rem; }
  nav { display: flex; gap: .25rem; flex-wrap: wrap; }
  nav button { font: inherit; padding: .5rem .9rem; border: 1px solid transparent;
               background: transparent; border-radius: 6px; cursor: pointer; color: #4b5563; }
  nav button:hover { background: #f3f4f6; }
  nav button[aria-selected="true"] { background: #eff6ff; color: #1d4ed8;
                                     border-color: #bfdbfe; font-weight: 600; }
  main { padding: 1.5rem; max-width: 1100px; }
  section[hidden] { display: none; }
  #drop { border: 2px dashed #9ca3af; border-radius: 8px; padding: 2.5rem 1rem;
          text-align: center; cursor: pointer; background: #fff; color: #4b5563; }
  #drop.hot { border-color: #2563eb; background: #eff6ff; color: #1d4ed8; }
  table { border-collapse: collapse; width: 100%; background: #fff; font-size: .875rem; }
  th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid #e5e7eb; }
  th { background: #f3f4f6; font-weight: 600; white-space: nowrap; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .muted { color: #6b7280; }
  .pill { display: inline-block; padding: .1rem .45rem; border-radius: 999px;
          font-size: .75rem; font-weight: 600; }
  .pill.key { background: #dcfce7; color: #15803d; }
  .pill.rec { background: #dbeafe; color: #1d4ed8; }
  .pill.maybe { background: #fef3c7; color: #b45309; }
  .pill.no { background: #f3f4f6; color: #6b7280; }
  .card { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
          padding: 1rem; margin-bottom: 1rem; }
  ul { padding-left: 1.1rem; margin: .5rem 0 0; }
  li { margin: .15rem 0; }
  .ok { color: #15803d; }
  .err { color: #b91c1c; }
  code { background: #f3f4f6; padding: .05rem .3rem; border-radius: 4px; font-size: .85em; }
  pre { background: #111827; color: #f9fafb; padding: .75rem; border-radius: 6px;
        overflow-x: auto; font-size: .8rem; }
</style>
<header>
  <h1>Excel-koppling</h1>
  <nav id="tabs">
    <button data-tab="upload" aria-selected="true">Ladda upp</button>
    <button data-tab="sources">Indata</button>
    <button data-tab="columns">Kolumner och koppling</button>
  </nav>
</header>
<main>
  <section id="upload">
    <div id="drop">Släpp Excel-filer här, eller klicka för att välja</div>
    <input id="picker" type="file" multiple accept=".xlsx,.xls,.xlsm,.csv" hidden>
    <p class="muted">Filerna hamnar i <code>data/inbox/</code> och versionshanteras inte.</p>
    <ul id="uploadList"></ul>
  </section>

  <section id="sources" hidden>
    <p class="muted">Arbetsböcker och flikar som hittats i <code>data/</code> och <code>data/inbox/</code>.</p>
    <div id="sourcesBody"></div>
  </section>

  <section id="columns" hidden>
    <p class="muted">Kolumner per datakälla, och maskinellt förslag på hur källorna kopplas ihop.</p>
    <div id="columnsBody"></div>
  </section>
</main>
<script>
const KEY = new URLSearchParams(location.search).get("key") || "";
const q = (p) => "/" + p + "?key=" + encodeURIComponent(KEY);
const esc = (s) => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

document.querySelectorAll("#tabs button").forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll("#tabs button").forEach(b => b.setAttribute("aria-selected", b === btn));
    document.querySelectorAll("main > section").forEach(s => { s.hidden = s.id !== btn.dataset.tab; });
    if (btn.dataset.tab === "sources") loadSources();
    if (btn.dataset.tab === "columns") loadColumns();
  };
});

async function get(path) {
  const res = await fetch(q(path));
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

/* --- uppladdning --- */
const drop = document.getElementById("drop");
const picker = document.getElementById("picker");
const uploadList = document.getElementById("uploadList");

async function refreshUploads() {
  try {
    const files = await get("list");
    uploadList.innerHTML = files.length
      ? files.map(f => `<li class="ok">${esc(f.name)} <span class="muted">(${f.size} byte)</span></li>`).join("")
      : "<li class='muted'>Inga filer ännu</li>";
  } catch (e) { uploadList.innerHTML = `<li class="err">Kunde inte läsa katalogen: ${esc(e.message)}</li>`; }
}

async function uploadOne(file) {
  const res = await fetch(q("upload"), {
    method: "POST",
    headers: { "X-Filename": encodeURIComponent(file.name) },
    body: file,
  });
  const out = await res.json().catch(() => ({ detail: res.statusText }));
  const li = document.createElement("li");
  li.className = res.ok ? "ok" : "err";
  li.textContent = file.name + ": " + (res.ok ? "OK" : "FEL - " + out.detail);
  uploadList.prepend(li);
}

async function handle(files) {
  for (const f of files) await uploadOne(f);
  refreshUploads();
}

drop.onclick = () => picker.click();
picker.onchange = () => handle(picker.files);
["dragenter","dragover"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add("hot"); }));
["dragleave","drop"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove("hot"); }));
drop.addEventListener("drop", ev => handle(ev.dataTransfer.files));
refreshUploads();

/* --- indata --- */
async function loadSources() {
  const box = document.getElementById("sourcesBody");
  box.innerHTML = "<p class='muted'>Läser…</p>";
  try {
    const books = await get("sources");
    if (!books.length) { box.innerHTML = "<p class='muted'>Inga arbetsböcker hittades.</p>"; return; }
    box.innerHTML = books.map(b => `
      <div class="card">
        <strong>${esc(b.path)}</strong>
        <table>
          <thead><tr><th>Flik</th><th class="num">Rader</th><th class="num">Kolumner</th></tr></thead>
          <tbody>${b.sheets.map(s => `<tr><td>${esc(s.name)}</td><td class="num">${s.rows}</td><td class="num">${s.columns}</td></tr>`).join("")}</tbody>
        </table>
      </div>`).join("");
  } catch (e) { box.innerHTML = `<p class="err">Fel: ${esc(e.message)}</p>`; }
}

/* --- kolumner och koppling --- */
function statsTable(columns) {
  return `<table>
    <thead><tr><th>Kolumn</th><th>Typ</th><th class="num">Distinkta</th><th class="num">Tomma</th><th></th></tr></thead>
    <tbody>${columns.map(c => `<tr>
      <td>${esc(c.name)}</td>
      <td class="muted">${esc(c.dtype)}</td>
      <td class="num">${c.distinct}</td>
      <td class="num">${c.nulls}</td>
      <td>${c.candidate_key ? '<span class="pill key">möjlig nyckel</span>' : ""}</td>
    </tr>`).join("")}</tbody></table>`;
}

function candidateBlock(cand) {
  const pill = cand.verdict === "rekommenderad" ? "rec" : (cand.verdict === "möjlig" ? "maybe" : "no");
  const c = cand.comparison;
  return `<div class="card">
    <div><strong>${esc(cand.left_column)}</strong> <span class="muted">↔</span> <strong>${esc(cand.right_column)}</strong>
      <span class="pill ${pill}">${esc(cand.verdict)}</span>
      <span class="muted">poäng ${cand.score}</span></div>
    <ul>${cand.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>
    <p class="muted">kardinalitet <code>${esc(c.cardinality)}</code> ·
       föräldralösa vänster ${c.orphans_left} / höger ${c.orphans_right} ·
       nollvärden i nyckel vänster ${c.left_nulls} / höger ${c.right_nulls}</p>
    <details><summary>utkast till spec-post</summary><pre>${esc(cand.spec_entry)}</pre></details>
  </div>`;
}

async function loadColumns() {
  const box = document.getElementById("columnsBody");
  box.innerHTML = "<p class='muted'>Analyserar…</p>";
  try {
    const data = await get("columns");
    if (!data.sources.length) { box.innerHTML = "<p class='muted'>Inga datakällor hittades.</p>"; return; }
    let out = data.sources.map(s => `
      <div class="card">
        <strong>${esc(s.name)}</strong> <span class="muted">(${esc(s.file)})</span>
        ${statsTable(s.columns)}
      </div>`).join("");

    out += "<h2 style='font-size:1rem'>Föreslagen koppling</h2>";
    if (!data.pairs.length) {
      out += "<p class='muted'>Inga kolumnpar att jämföra.</p>";
    }
    for (const pair of data.pairs) {
      out += `<h3 style="font-size:.95rem">${esc(pair.left)} ↔ ${esc(pair.right)}</h3>`;
      out += pair.candidates.length
        ? pair.candidates.map(candidateBlock).join("")
        : "<p class='muted'>Inga kandidater med tillräcklig täckning.</p>";
    }
    box.innerHTML = out;
  } catch (e) { box.innerHTML = `<p class="err">Fel: ${esc(e.message)}</p>`; }
}
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


def read_workbook_sheets(path: Path) -> list[dict]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pd.ExcelFile(path, engine="openpyxl") as book:
            sheets = []
            for name in book.sheet_names:
                frame = book.parse(name)
                sheets.append({"name": name, "rows": len(frame), "columns": len(frame.columns)})
            return sheets


def collect_sources(data_dir: Path, inbox: Path) -> list[dict]:
    """Lista alla arbetsböcker i data/ och data/inbox/."""
    found: list[dict] = []
    seen: set[Path] = set()
    for directory in (data_dir, inbox):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*")):
            if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                sheets = read_workbook_sheets(path)
            except Exception as exc:  # trasig fil ska inte fälla hela sidan
                sheets = []
                found.append({"path": str(path.relative_to(data_dir.parent)), "error": str(exc), "sheets": []})
                continue
            found.append({"path": str(path.relative_to(data_dir.parent)), "sheets": sheets})
    return found


def _load_frames(data_dir: Path, inbox: Path) -> list[tuple[str, str, str, pd.DataFrame]]:
    """Läs första fliken i varje arbetsbok som en (fil, flik, namn, ram)."""
    frames = []
    seen: set[Path] = set()
    for directory in (data_dir, inbox):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*")):
            if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            if path.resolve() in seen:
                continue
            seen.add(path.resolve())
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with pd.ExcelFile(path, engine="openpyxl") as book:
                    for sheet in book.sheet_names:
                        frames.append(
                            (str(path.relative_to(data_dir.parent)), sheet, f"{path.stem}/{sheet}", book.parse(sheet))
                        )
    return frames


def build_column_report(data_dir: Path, inbox: Path, max_candidates: int = 3) -> dict:
    """Kolumner per källa samt rangordnade kopplingskandidater mellan dem."""
    frames = _load_frames(data_dir, inbox)

    sources = []
    for file_name, sheet, name, frame in frames:
        columns = []
        for column in frame.columns:
            stats = column_stats(frame[column], name=str(column))
            columns.append(
                {
                    "name": stats.name,
                    "dtype": stats.dtype,
                    "distinct": stats.distinct,
                    "nulls": stats.nulls,
                    "candidate_key": stats.is_candidate_key,
                }
            )
        sources.append({"name": name, "file": file_name, "sheet": sheet, "columns": columns})

    pairs = []
    for i, (_, _, left_name, left_frame) in enumerate(frames):
        for _, _, right_name, right_frame in frames[i + 1 :]:
            candidates = rank_join_candidates(left_frame, right_frame)[:max_candidates]
            entries = []
            for candidate in candidates:
                comparison = candidate.comparison
                entries.append(
                    {
                        "left_column": candidate.left_column,
                        "right_column": candidate.right_column,
                        "verdict": candidate.verdict,
                        "score": candidate.score,
                        "reasons": candidate.reasons,
                        "comparison": {
                            "cardinality": comparison.cardinality,
                            "orphans_left": comparison.orphans_left,
                            "orphans_right": comparison.orphans_right,
                            "left_nulls": comparison.left_nulls,
                            "right_nulls": comparison.right_nulls,
                            "coverage_left": round(comparison.coverage_left, 4),
                            "coverage_right": round(comparison.coverage_right, 4),
                        },
                        "spec_entry": _spec_entry(comparison, _entity_name(right_name)),
                    }
                )
            pairs.append({"left": left_name, "right": right_name, "candidates": entries})

    return {"sources": sources, "pairs": pairs}


def _entity_name(source_name: str) -> str:
    """Gör "Vattenkraft/Vattenkraftverk" till ett användbart entitetsnamn."""
    tail = source_name.split("/")[-1]
    return _slug(tail)


def _spec_entry(comparison, target: str) -> str:
    from excel_merge.profile import suggest_spec_entry

    return suggest_spec_entry(comparison, target)


def _slug(text: str) -> str:
    """Gör ett fliknamn till ett användbart namn i specen."""
    cleaned = "".join(c if c.isalnum() else "_" for c in text.strip().lower())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "kalla"


class Handler(BaseHTTPRequestHandler):
    inbox: Path
    data_dir: Path
    key: str

    def _authorized(self, query: dict[str, list[str]]) -> bool:
        return secrets.compare_digest(query.get("key", [""])[0], self.key)

    def _json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
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

        if parsed.path == "/sources":
            self._json(200, collect_sources(self.data_dir, self.inbox))
            return

        if parsed.path == "/columns":
            self._json(200, build_column_report(self.data_dir, self.inbox))
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
        (self.inbox / name).write_bytes(data)
        self._json(200, {"success": True, "file": name, "file_size": len(data)})


def serve(data_dir: Path, inbox: Path, port: int, key: str) -> None:
    inbox.mkdir(parents=True, exist_ok=True)
    handler = type(
        "BoundHandler", (Handler,), {"inbox": inbox, "data_dir": data_dir, "key": key}
    )
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"Excel-koppling på port {port}")
    print(f"  data:  {data_dir}")
    print(f"  inbox: {inbox}")
    print(f"  nyckel: {key}")
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Webbapplikation: ladda upp, visa indata och kolumner.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--inbox", type=Path, default=None, help="mottagningskatalog (default: <data>/inbox)")
    parser.add_argument("--port", type=int, default=12000)
    parser.add_argument("--key", default=None, help="nyckel som krävs i URL:en (slumpas annars)")
    args = parser.parse_args(argv)
    data_dir = args.data_dir
    serve(data_dir, args.inbox or data_dir / "inbox", args.port, args.key or secrets.token_urlsafe(16))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
