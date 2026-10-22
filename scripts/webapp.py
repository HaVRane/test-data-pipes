"""Webbapplikation: anslut datakälla, indata, kolumner, relationer och ändringslogg.

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

from excel_merge.changelog import ChangeLog
from excel_merge.joins import looks_like_measure, rank_join_candidates
from excel_merge.profile import column_stats, compare_keys

ALLOWED_SUFFIXES = {".xlsx", ".xls", ".xlsm", ".csv"}
MAX_BYTES = 25 * 1024 * 1024

PAGE = """<!doctype html>
<html lang="sv">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Automatiserad dataplattform med övervakning</title>
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
  .map-canvas { position: relative; background: #fff; border: 1px solid #e5e7eb;
    border-radius: 8px; overflow: auto; margin-bottom: 1rem; }
  .map-node { position: absolute; background: #f9fafb; border: 1px solid #d1d5db;
    border-radius: 8px; padding: .55rem .7rem; font-size: .8rem; line-height: 1.35;
    display: flex; flex-direction: column; gap: .15rem; }
  .map-node.isolated { border-style: dashed; background: #fff; }
  .map-node .map-keys { display: flex; flex-wrap: wrap; gap: .2rem; margin-top: .2rem; }
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
  <h1>Automatiserad dataplattform med övervakning</h1>
  <nav id="tabs">
    <button data-tab="upload" aria-selected="true">Anslut datakälla</button>
    <button data-tab="sources">Indata</button>
    <button data-tab="columns">Kolumner och koppling</button>
    <button data-tab="map">Indatarelationer</button>
    <button data-tab="changelog">Ändringslogg</button>
  </nav>
</header>
<main>
  <section id="upload">
    <div id="drop">Släpp Excel-filer här, eller klicka för att välja</div>
    <input id="picker" type="file" multiple accept=".xlsx,.xls,.xlsm,.csv" hidden>
    <p class="muted">Filerna hamnar i <code>data/inbox/</code> och versionshanteras inte.
      Varje uppladdad fil blir automatiskt en datakälla: fliken läggs in i
      <code>config/relations.yaml</code>, analysen körs och händelsen loggas.
      Saknar fliken en egen nyckel får den en radnyckel, så att ingen fil lämnas utanför.</p>
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

  <section id="map" hidden>
    <p class="muted">En översikt över datakällorna och nycklarna som binder dem samman. Varje ruta är en tabell (flik), pilarna visar föreslagna relationer.</p>
    <div id="mapBody"></div>
  </section>

  <section id="changelog" hidden>
    <div class="card">
      <div style="display:flex; gap:.75rem; align-items:center; flex-wrap:wrap">
        <strong>Ändringar i datat</strong>
        <span id="watchStatus" class="muted"></span>
        <span style="flex:1"></span>
        <label class="muted">Händelse
          <select id="filterEvent">
            <option value="">alla</option>
            <option value="source_added">tillagd</option>
            <option value="source_changed">ändrad</option>
            <option value="source_removed">borttagen</option>
            <option value="source_unchanged">oförändrad</option>
            <option value="source_unreadable">kunde inte läsas</option>
            <option value="source_recovered">läsbar igen</option>
            <option value="source_declared">inlagd i specen</option>
            <option value="source_undeclared">struken ur specen</option>
            <option value="source_redefined">omdefinierad</option>
            <option value="entity_declared">entitet tillagd</option>
            <option value="entity_undeclared">entitet borttagen</option>
            <option value="entity_redefined">entitet omdefinierad</option>
            <option value="build_redefined">bygge ändrat</option>
            <option value="file_received">fil mottagen</option>
          </select>
        </label>
        <label class="muted">Slag
          <select id="filterKind">
            <option value="">alla</option>
            <option value="data">data</option>
            <option value="structure">struktur</option>
            <option value="ingest">mottagning</option>
          </select>
        </label>
        <label class="muted">Källa <select id="filterSource"><option value="">alla</option></select></label>
        <button id="watchButton">Sök ändringar nu</button>
      </div>
      <p class="muted" style="margin-bottom:0">
        <code>watch</code> jämför källorna mot senast kända innehållsfingeravtryck och loggar
        skillnaderna. Loggen har två slag: <strong>data</strong> beskriver ändringar i
        innehållet, <strong>struktur</strong> beskriver hur pipen byggts om (källor, nycklar,
        byggen). Tillsammans blir de en tidslinje över hela dataflödet.
      </p>
    </div>
    <div id="changelogBody"></div>
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
    if (btn.dataset.tab === "map") loadMap();
    if (btn.dataset.tab === "changelog") loadChangelog();
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
  li.className = res.ok && !out.registration_error ? "ok" : "err";
  let text = file.name + ": ";
  if (!res.ok) {
    text += "FEL - " + out.detail;
  } else if (out.registration_error) {
    text += "mottagen, men källan kunde inte läggas in - " + out.registration_error;
  } else {
    const s = out.source;
    text += `OK - datakällan "${s.name}" (entitet ${s.entity}, nyckel ${s.key})`;
    if (s.relationship_to) text += `, kopplad till ${s.relationship_to} via ${s.relationship_via}`;
  }
  li.textContent = text;
  uploadList.prepend(li);
  return out;
}

async function handle(files) {
  let registered = 0;
  for (const f of files) {
    const out = await uploadOne(f);
    if (out && out.source) registered += 1;
  }
  refreshUploads();
  // Nya källor ändrar indata, kolumner, relationer och loggen. Ladda om de
  // vyer som redan ritats, så att de inte visar en bild från före uppladdningen.
  if (registered) {
    if (!document.getElementById("sources").hidden) loadSources();
    if (!document.getElementById("columns").hidden) loadColumns();
    if (!document.getElementById("map").hidden) loadMap();
    if (!document.getElementById("changelog").hidden) loadChangelog();
  }
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

/* --- indatarelationer --- */
function mapNodeBox(node, cx, cy, w, h) {
  const isolated = node.isolated;
  const keys = (node.candidate_keys || []);
  const keyLines = keys.length
    ? keys.slice(0, 4).map(k => `<span class="pill key">${esc(k)}</span>`).join(" ")
    : '<span class="muted">inga självklara nycklar</span>';
  const more = keys.length > 4 ? ` <span class="muted">+${keys.length - 4}</span>` : "";
  return `
    <div class="map-node ${isolated ? "isolated" : ""}" style="left:${cx - w / 2}px; top:${cy - h / 2}px; width:${w}px; min-height:${h}px">
      <strong>${esc(node.id)}</strong>
      <div class="muted">${esc(node.file)} · flik ${esc(node.sheet)}</div>
      <div class="muted">${node.rows} rader · ${node.column_count} kolumner</div>
      <div class="map-keys">${keyLines}${more}</div>
      ${isolated ? '<div class="pill no">kopplas inte till något</div>' : ""}
    </div>`;
}

function loadMap() {
  const box = document.getElementById("mapBody");
  box.innerHTML = "<p class='muted'>Ritar…</p>";
  get("map").then(data => {
    if (!data.nodes.length) { box.innerHTML = "<p class='muted'>Inga datakällor hittades.</p>"; return; }

    const W = 880, H = 520, NW = 190, NH = 104;
    const nodes = data.nodes;
    const cx = W / 2, cy = H / 2;
    // Cirkel ger jämnt avstånd mellan alla noder, oavsett hur många de är.
    const radius = nodes.length === 1 ? 0 : Math.min(W, H) / 2 - NH;
    const pos = {};
    nodes.forEach((node, i) => {
      const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
      pos[node.id] = {
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
      };
    });

    let svg = "";
    for (const e of data.edges) {
      const a = pos[e.left], b = pos[e.right];
      if (!a || !b) continue;
      const good = e.verdict === "rekommenderad";
      const color = good ? "#1d4ed8" : "#b45309";
      const dash = good ? "" : ' stroke-dasharray="5 4"';
      // Kortare linje så pilen möter rutan, inte hamnar under den.
      const dx = b.x - a.x, dy = b.y - a.y;
      const len = Math.hypot(dx, dy) || 1;
      const pad = NH / 2 + 4;
      const x1 = a.x + (dx / len) * pad, y1 = a.y + (dy / len) * pad;
      const x2 = b.x - (dx / len) * pad, y2 = b.y - (dy / len) * pad;
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
      svg += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${color}" stroke-width="2"${dash} marker-end="url(#arrow${good ? "rec" : "maybe"})"/>`;
      const label = `${esc(e.left_column)} = ${esc(e.right_column)}`;
      const wpx = Math.max(96, label.length * 6.4);
      svg += `<rect x="${mx - wpx / 2}" y="${my - 11}" width="${wpx}" height="20" rx="10" fill="#fff" stroke="${color}"/>`;
      svg += `<text x="${mx}" y="${my + 3}" text-anchor="middle" font-size="11" fill="${color}">${label}</text>`;
    }

    const boxes = nodes.map(n => mapNodeBox(n, pos[n.id].x, pos[n.id].y, NW, NH)).join("");
    box.innerHTML = `
      <div class="map-canvas" style="width:${W}px; height:${H}px">
        <svg width="${W}" height="${H}" style="position:absolute; inset:0">
          <defs>
            <marker id="arrowrec" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#1d4ed8"/>
            </marker>
            <marker id="arrowmaybe" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#b45309"/>
            </marker>
          </defs>
          ${svg}
        </svg>
        ${boxes}
      </div>
      <div class="card">
        <strong>Förklaring</strong>
        <p class="muted" style="margin:.4rem 0">
          <span class="pill rec">rekommenderad</span> heldragen linje ·
          <span class="pill maybe">möjlig</span> streckad linje ·
          <span class="pill no">isolerad</span> ingen koppling hittad
        </p>
        <p class="muted" style="margin:0">Tabellerna nedan listar varje koppling med nycklar och täckning.</p>
      </div>
      ${data.edges.length ? `<table>
        <thead><tr><th>Koppling</th><th>Nycklar</th><th>Bedömning</th><th>Täckning</th><th>Kardinalitet</th></tr></thead>
        <tbody>${data.edges.map(e => `<tr>
          <td>${esc(e.left)} ↔ ${esc(e.right)}</td>
          <td><code>${esc(e.left_column)}</code> = <code>${esc(e.right_column)}</code></td>
          <td><span class="pill ${e.verdict === "rekommenderad" ? "rec" : "maybe"}">${esc(e.verdict)}</span></td>
          <td>${Math.round(e.coverage * 100)}%</td>
          <td><code>${esc(e.cardinality)}</code></td>
        </tr>`).join("")}</tbody>
      </table>` : "<p class='muted'>Inga kopplingar hittades mellan tabellerna.</p>"}
    `;
  }).catch(e => { box.innerHTML = `<p class="err">Fel: ${esc(e.message)}</p>`; });
}

/* --- ändringslogg --- */
const EVENT_LABEL = {
  source_added: "tillagd",
  source_changed: "ändrad",
  source_removed: "borttagen",
  source_unchanged: "oförändrad",
  source_unreadable: "kunde inte läsas",
  source_recovered: "läsbar igen",
  source_declared: "inlagd i specen",
  source_undeclared: "struken ur specen",
  source_redefined: "omdefinierad",
  entity_declared: "entitet tillagd",
  entity_undeclared: "entitet borttagen",
  entity_redefined: "entitet omdefinierad",
  build_redefined: "bygge ändrat",
  file_received: "fil mottagen",
};
const EVENT_PILL = {
  source_added: "rec",
  source_changed: "maybe",
  source_removed: "no",
  source_unchanged: "no",
  source_unreadable: "no",
  source_recovered: "rec",
  source_declared: "rec",
  source_undeclared: "no",
  source_redefined: "maybe",
  entity_declared: "rec",
  entity_undeclared: "no",
  entity_redefined: "maybe",
  build_redefined: "maybe",
  file_received: "rec",
};
const KIND_LABEL = { data: "data", structure: "struktur", ingest: "mottagning" };

function changeDetail(e) {
  const parts = [];
  if (e.event === "source_added") parts.push(`${e.rows ?? "?"} rader`);
  if (e.event === "source_removed") {
    parts.push(`senast ${esc(e.last_seen || "okänt")}`);
    if (e.reason) parts.push(esc(e.reason));
  }
  if (e.event === "source_changed") {
    if (e.rows_before !== undefined && e.rows_before !== e.rows) parts.push(`${e.rows_before} → ${e.rows} rader`);
    if ((e.columns_added || []).length) parts.push("nya kolumner: " + e.columns_added.map(esc).join(", "));
    if ((e.columns_removed || []).length) parts.push("borttagna kolumner: " + e.columns_removed.map(esc).join(", "));
    if (!parts.length) parts.push("innehållet har ändrats");
    if (e.fingerprint_before) parts.push(`<code>${esc(e.fingerprint_before)} → ${esc(e.fingerprint_after)}</code>`);
  }
  if (e.event === "source_unchanged") parts.push(`${e.rows ?? "?"} rader`);
  if (e.event === "source_unreadable") {
    parts.push(esc(e.error || "okänt fel"));
    if (!e.known) parts.push("har aldrig lästs");
  }
  if (e.event === "source_recovered") parts.push(`${e.rows ?? "?"} rader`);
  if (e.event === "source_declared" || e.event === "entity_declared") {
    if (e.path) parts.push(esc(e.path));
    if (e.sheet) parts.push("flik " + esc(e.sheet));
    if (e.entity) parts.push("entitet " + esc(e.entity));
    if (e.key) parts.push("nyckel " + esc(e.key));
  }
  if (e.event === "source_undeclared" || e.event === "entity_undeclared") {
    parts.push("fanns tidigare i specen");
  }
  if ((e.event === "source_redefined" || e.event === "entity_redefined" || e.event === "build_redefined")
      && (e.changes || []).length) {
    parts.push(e.changes.map(esc).join(" · "));
  }
  if (e.event === "file_received") parts.push(`${e.bytes ?? "?"} byte`);
  return parts.join(" · ");
}

async function loadChangelog() {
  const box = document.getElementById("changelogBody");
  box.innerHTML = "<p class='muted'>Läser…</p>";
  try {
    const data = await get("changelog");
    const sourceFilter = document.getElementById("filterSource");
    const chosen = sourceFilter.value;
    sourceFilter.innerHTML = '<option value="">alla</option>' +
      data.sources.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
    sourceFilter.value = data.sources.includes(chosen) ? chosen : "";

    renderChangelog(data.events, data.sources);
  } catch (e) { box.innerHTML = `<p class="err">Fel: ${esc(e.message)}</p>`; }
}

function renderChangelog(events, sources) {
  const box = document.getElementById("changelogBody");
  const wantEvent = document.getElementById("filterEvent").value;
  const wantKind = document.getElementById("filterKind").value;
  const wantSource = document.getElementById("filterSource").value;
  let shown = events;
  if (wantEvent) shown = shown.filter(e => e.event === wantEvent);
  if (wantKind) shown = shown.filter(e => (e.kind || "data") === wantKind);
  if (wantSource) shown = shown.filter(e => e.source === wantSource);

  if (!events.length) {
    box.innerHTML = "<p class='muted'>Ingen logg ännu. Ladda upp en fil eller klicka på <em>Sök ändringar nu</em> för att skapa en baslinje.</p>";
    return;
  }
  if (!shown.length) { box.innerHTML = "<p class='muted'>Inga händelser matchar filtret.</p>"; return; }

  box.innerHTML = `<p class="muted">${shown.length} av ${events.length} händelse(r)</p>
    <table>
    <thead><tr><th>Tidpunkt</th><th>Slag</th><th>Händelse</th><th>Källa</th><th>Detalj</th></tr></thead>
    <tbody>${shown.map(e => {
      const kind = e.kind || "data";
      return `<tr>
      <td class="muted">${esc(e.timestamp || "")}</td>
      <td><span class="pill no">${esc(KIND_LABEL[kind] || kind)}</span></td>
      <td><span class="pill ${EVENT_PILL[e.event] || "no"}">${esc(EVENT_LABEL[e.event] || e.event)}</span></td>
      <td>${esc(e.source || "")}</td>
      <td>${changeDetail(e)}</td>
    </tr>`;
    }).join("")}</tbody></table>`;
}

document.getElementById("filterEvent").onchange = () => loadChangelog();
document.getElementById("filterKind").onchange = () => loadChangelog();
document.getElementById("filterSource").onchange = () => loadChangelog();
document.getElementById("watchButton").onclick = async () => {
  const status = document.getElementById("watchStatus");
  const button = document.getElementById("watchButton");
  button.disabled = true;
  status.textContent = "jämför…";
  try {
    const res = await fetch(q("watch"), { method: "POST" });
    const out = await res.json();
    if (!res.ok) throw new Error(out.detail || ("HTTP " + res.status));
    const broken = out.new_events.filter(e => e.event === "source_unreadable");
    const gone = out.new_events.filter(e => e.event === "source_removed");
    const notes = [];
    if (gone.length) notes.push(`${gone.length} källa(or) borttagen`);
    if (broken.length) notes.push(`${broken.length} källa(or) kunde inte läsas`);
    if (notes.length) {
      status.textContent = notes.join(", ");
    } else {
      status.textContent = out.events.length
        ? `${out.events.length} ny(a) händelse(r)`
        : "inga ändringar sedan förra körningen";
    }
    await loadChangelog();
  } catch (e) {
    status.textContent = "fel: " + e.message;
  } finally {
    button.disabled = false;
  }
};
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
                try:
                    book = pd.ExcelFile(path, engine="openpyxl")
                except Exception:  # trasig fil ska hoppas över, inte fälla sidan
                    continue
                with book:
                    for sheet in book.sheet_names:
                        try:
                            frame = book.parse(sheet)
                        except Exception:
                            continue
                        frames.append(
                            (str(path.relative_to(data_dir.parent)), sheet, f"{path.stem}/{sheet}", frame)
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


def build_relationship_map(data_dir: Path, inbox: Path, max_edges_per_pair: int = 2) -> dict:
    """En översikt över källorna och nycklarna som binder dem samman.

    Till skillnad från kolumnrapporten visar den här bara det som behövs för att
    förstå helheten: vilka tabeller som finns och vilka nycklar som kopplar dem.
    Alla kolumner visas inte, bara de som är möjliga nycklar.

    Endast kandidater som är rekommenderade eller möjliga blir kanter. Annars
    fylls relationerna av svaga förslag och blir svårare att läsa än tabellerna.
    """
    frames = _load_frames(data_dir, inbox)

    nodes = []
    for file_name, sheet, name, frame in frames:
        keys = [
            str(column)
            for column in frame.columns
            if column_stats(frame[column], name=str(column)).is_candidate_key
            and not looks_like_measure(str(column))
        ]
        nodes.append(
            {
                "id": name,
                "file": file_name,
                "sheet": sheet,
                "rows": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "candidate_keys": keys,
            }
        )

    edges = []
    for i, (_, _, left_name, left_frame) in enumerate(frames):
        for _, _, right_name, right_frame in frames[i + 1 :]:
            for candidate in rank_join_candidates(left_frame, right_frame):
                if candidate.verdict not in ("rekommenderad", "möjlig"):
                    continue
                edges.append(
                    {
                        "left": left_name,
                        "right": right_name,
                        "left_column": candidate.left_column,
                        "right_column": candidate.right_column,
                        "verdict": candidate.verdict,
                        "score": candidate.score,
                        "cardinality": candidate.comparison.cardinality,
                        "coverage": round(
                            min(candidate.comparison.coverage_left, candidate.comparison.coverage_right), 3
                        ),
                        "orphans_left": candidate.comparison.orphans_left,
                        "orphans_right": candidate.comparison.orphans_right,
                    }
                )
                if sum(1 for e in edges if {e["left"], e["right"]} == {left_name, right_name}) >= max_edges_per_pair:
                    break

    # Isolerade noder är värda att se: de kopplas inte till något alls.
    connected = {e["left"] for e in edges} | {e["right"] for e in edges}
    # En kolumn som faktiskt används i en koppling är en nyckel, även om den inte
    # klarar unikhetskravet ensam (t.ex. en gruppnyckel med många rader per värde).
    # Annars visar rutan "inga nycklar" samtidigt som en pil pekar på den.
    by_node: dict[str, list[str]] = {}
    for edge in edges:
        by_node.setdefault(edge["left"], []).append(edge["left_column"])
        by_node.setdefault(edge["right"], []).append(edge["right_column"])

    for node in nodes:
        extra = [k for k in by_node.get(node["id"], []) if k not in node["candidate_keys"]]
        node["candidate_keys"] = list(node["candidate_keys"]) + extra
        node["isolated"] = node["id"] not in connected

    return {"nodes": nodes, "edges": edges}


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
    spec_path: Path
    log_path: Path
    state_path: Path

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

        if parsed.path == "/map":
            self._json(200, build_relationship_map(self.data_dir, self.inbox))
            return

        if parsed.path == "/changelog":
            self._json(200, self._changelog_payload())
            return

        self.send_error(404)

    def _changelog_payload(self) -> dict:
        """Loggen, nyast först, plus källnamnen för filtrering."""
        log = ChangeLog(self.log_path, self.state_path)
        events = list(reversed(log.read_events()))
        state = log.load_state().get("sources") or {}
        # Bara datakällor: strukturhändelserna handlar om entiteter och byggen,
        # och de hör inte hemma i källfiltret.
        names = {
            e.get("source", "")
            for e in events
            if e.get("kind", "data") == "data" and e.get("source")
        } | set(state)
        return {
            "events": events,
            "sources": sorted(names),
            "state": state,
            "spec": str(self.spec_path),
        }

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._authorized(query):
            self.send_error(403, "ogiltig eller saknad nyckel")
            return
        if parsed.path == "/watch":
            self._run_watch_endpoint()
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
        target = self.inbox / name
        target.write_bytes(data)

        # Registreringen gör filen till en källa i pipen och loggar händelsen.
        # Den får aldrig fälla uppladdningen: filen är redan mottagen, och ett
        # fel här ska rapporteras vid sidan av - inte se ut som en misslyckad
        # överföring.
        from excel_merge.register import RegistrationError, register_source
        from excel_merge.watch import record_ingest, run_watch

        payload: dict = {"success": True, "file": name, "file_size": len(data)}

        try:
            record_ingest(self.log_path, self.state_path, name, {"bytes": len(data)})
        except OSError as exc:
            payload["log_warning"] = f"kunde inte skriva loggen: {exc}"

        try:
            registration = register_source(self.spec_path, target, sheet=self._first_sheet(target))
            payload["source"] = {
                "name": registration.name,
                "entity": registration.entity,
                "key": registration.key,
                "sheet": registration.sheet,
                "columns": registration.columns,
                "relationship_to": registration.relationship_to,
                "relationship_via": registration.relationship_via,
            }
        except RegistrationError as exc:
            payload["registration_error"] = str(exc)
            self._json(200, payload)
            return

        # Registreringen ändrade specen. Kör bevakningen direkt, så att
        # strukturhändelsen och källans första fingeravtryck hamnar i loggen i
        # samma steg - det är det som gör att historiken blir fullständig.
        try:
            from excel_merge.relations import load_relation_spec

            events = run_watch(load_relation_spec(self.spec_path), self.log_path, self.state_path)
            payload["events"] = [e.as_dict() for e in events]
        except Exception as exc:  # bevakningen får inte fälla uppladdningen
            payload["watch_warning"] = f"kunde inte köra bevakningen: {exc}"

        self._json(200, payload)

    @staticmethod
    def _first_sheet(path: Path) -> str:
        """Första fliken i en arbetsbok.

        Uppladdningen gäller en fil; pipen arbetar med flikar. Vi tar den första
        fliken som källan, vilket är det förutsägbara valet när användaren inte
        angett någon.
        """
        import warnings as _warnings

        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            with pd.ExcelFile(path, engine="openpyxl") as book:
                if not book.sheet_names:
                    raise ValueError(f"{path.name} innehåller inga flikar")
                return book.sheet_names[0]

    def _run_watch_endpoint(self) -> None:
        """Kör en ändringsbevakning på begäran från gränssnittet.

        Samma kärna som CLI:t använder, så webben och terminalen aldrig kan
        säga olika saker om samma data.
        """
        from excel_merge.relations import RelationSpecError, load_relation_spec
        from excel_merge.watch import run_watch

        if not self.spec_path.is_file():
            self._json(400, {"detail": f"relationsspecen hittades inte: {self.spec_path}"})
            return
        try:
            spec = load_relation_spec(self.spec_path)
        except RelationSpecError as exc:
            self._json(400, {"detail": f"specen är inte giltig: {exc}"})
            return

        try:
            events = run_watch(spec, self.log_path, self.state_path)
        except OSError as exc:  # t.ex. skrivfel mot loggen
            self._json(500, {"detail": f"kunde inte skriva loggen: {exc}"})
            return

        payload = self._changelog_payload()
        payload["events_written"] = len(events)
        payload["new_events"] = [e.as_dict() for e in events]
        self._json(200, payload)


def serve(
    data_dir: Path,
    inbox: Path,
    port: int,
    key: str,
    spec_path: Path,
    log_path: Path,
    state_path: Path,
) -> None:
    inbox.mkdir(parents=True, exist_ok=True)
    handler = type(
        "BoundHandler",
        (Handler,),
        {
            "inbox": inbox,
            "data_dir": data_dir,
            "key": key,
            "spec_path": spec_path,
            "log_path": log_path,
            "state_path": state_path,
        },
    )
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"Automatiserad dataplattform med övervakning på port {port}")
    print(f"  data:  {data_dir}")
    print(f"  inbox: {inbox}")
    print(f"  spec:  {spec_path}")
    print(f"  logg:  {log_path}")
    print(f"  nyckel: {key}")
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Webbapplikation: anslut datakälla, visa indata, kolumner, relationer och ändringslogg."
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--inbox", type=Path, default=None, help="mottagningskatalog (default: <data>/inbox)")
    parser.add_argument("--port", type=int, default=12000)
    parser.add_argument("--key", default=None, help="nyckel som krävs i URL:en (slumpas annars)")
    parser.add_argument("--spec", type=Path, default=Path("config/relations.yaml"),
                        help="relationsspec för ändringsloggen")
    parser.add_argument("--log", type=Path, default=Path("state/changelog.ndjson"))
    parser.add_argument("--state", type=Path, default=Path("state/sources.json"))
    args = parser.parse_args(argv)
    serve(
        args.data_dir,
        args.inbox or args.data_dir / "inbox",
        args.port,
        args.key or secrets.token_urlsafe(16),
        args.spec,
        args.log,
        args.state,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
