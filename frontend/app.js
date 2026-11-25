// PS 247 frontend. No build step, no framework.
//
// Safety rules for this file:
//  - Everything from the API is rendered with textContent / createElement, never innerHTML.
//    The only markup set directly is the static SVG icon paths in ICONS below (constants
//    written here, never data).
//  - Entity spans refer to the ORIGINAL text, not the redacted one, so they are never shown
//    or used to index into redacted_text.
//  - The API never sends filenames back. Errors come with a file_index; the local filename
//    shown next to it is read from the browser's own file picker and goes nowhere.
"use strict";

const API = location.protocol === "file:" ? "http://127.0.0.1:8000" : "";
const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const MAX_FILES = 20;

const C = { navy: "#192339", steel: "#1E3A6B", cyan: "#27B2CC", maroon: "#781B17",
            steelSoft: "#7F9BDB", maroonSoft: "#E58A82", grid: "rgba(148,163,184,.12)", text: "#CBD5E1" };
const RISK_ORDER = ["low", "medium", "high", "critical"];
const RISK_COLOR = { low: C.cyan, medium: C.steelSoft, high: C.maroonSoft, critical: C.maroon, unknown: "#64748B" };
const STRATEGY_ORDER = ["keep", "generalize", "pseudonymize", "mask", "suppress"];
const STRATEGY_COLOR = { keep: "#3E5170", generalize: C.steelSoft, pseudonymize: "#5C7CC4", mask: C.cyan, suppress: C.maroon };
const STRATEGY_LABEL = { keep: "Kept", generalize: "Generalised", pseudonymize: "Pseudonymised", mask: "Masked", suppress: "Removed" };

// [EMAIL_ADDRESS], [REDACTED], PERSON_01, PERSON_7F3A
const PLACEHOLDER = /\[[A-Z][A-Z_]*\]|\b[A-Z]{2,}(?:_[A-Z]+)*_[0-9A-F]{2,}\b/g;

const AGENTS = [
  { name: "Privacy Intelligence", short: "Find", sub: "Finds personal data", icon: "search" },
  { name: "Risk & Policy", short: "Judge", sub: "Weighs risk in context", icon: "scale" },
  { name: "Adaptive Redaction", short: "Redact", sub: "Rewrites deterministically", icon: "pen" },
  { name: "Verification", short: "Verify", sub: "Re-checks independently", icon: "shield" },
  { name: "Adversarial", short: "Attack", sub: "Tries to re-identify", icon: "target" },
];

// Static icon paths (lucide-style). Constants only - never data.
const ICONS = {
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  scale: '<path d="M12 3v18"/><path d="M5 7h14"/><path d="m5 7-3 7a4 4 0 0 0 6 0z"/><path d="m19 7-3 7a4 4 0 0 0 6 0z"/><path d="M8 21h8"/>',
  pen: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  minus: '<path d="M5 12h14"/>',
  alert: '<path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  doc: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6"/><path d="M9 17h4"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  sparkle: '<path d="m12 3 1.9 5.8L20 10l-5 3.9L16.2 20 12 16.6 7.8 20 9 13.9 4 10l6.1-1.2z"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
};

const state = { result: null, selected: null, files: [], demo: false };
const $ = (id) => document.getElementById(id);

// ================================================================== DOM helpers

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function icon(name, size = 18, stroke = 2) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", size); svg.setAttribute("height", size);
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", stroke);
  svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = ICONS[name] || "";            // static constant, see ICONS
  return svg;
}

const badge = (text, cls, ic) => el("span", { class: `badge ${cls}` }, ic ? icon(ic, 12, 2.5) : null, text);
const riskCls = (r) => `r-${RISK_ORDER.includes(r) ? r : "unknown"}`;
const pretty = (s) => String(s).replace(/_/g, " ").toLowerCase();
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

function card(title, opts = {}, ...children) {
  return el("section", { class: `glass p-5 sm:p-6 reveal ${opts.cls || ""}`, style: { "--d": `${opts.delay || 0}ms` } },
    title ? el("div", { class: "flex items-center justify-between gap-3 mb-4" },
      el("h3", { class: "font-bold flex items-center gap-2" },
        opts.icon ? el("span", { class: "text-cyan" }, icon(opts.icon, 17)) : null, title),
      opts.action || null) : null,
    ...children);
}

function countUp(node, to, { duration = 900, suffix = "" } = {}) {
  if (REDUCED || !to) { node.textContent = `${to}${suffix}`; return; }
  const start = performance.now();
  const tick = (now) => {
    const p = Math.min(1, (now - start) / duration);
    node.textContent = `${Math.round(to * (1 - Math.pow(1 - p, 3)))}${suffix}`;
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function stackBar(parts, height = 10) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  const bar = el("div", { class: "stack", style: { height: `${height}px` } });
  const spans = parts.filter((p) => p.value > 0).map((p) =>
    el("span", { style: { background: p.color }, title: `${p.label}: ${p.value}` }));
  bar.append(...spans);
  const grow = () => spans.forEach((s, i) => { s.style.width = `${(parts.filter((p) => p.value > 0)[i].value / total) * 100}%`; });
  if (REDUCED) grow(); else requestAnimationFrame(() => requestAnimationFrame(grow));
  return bar;
}

// ================================================================== toasts

function toast(kind, title, message) {
  const colors = { success: C.cyan, error: C.maroonSoft, info: C.steelSoft };
  const ic = { success: "check", error: "alert", info: "info" }[kind] || "info";
  const node = el("div", { class: "toast", role: "status" },
    el("span", { style: { color: colors[kind] || C.steelSoft, marginTop: "1px" } }, icon(ic, 18, 2.4)),
    el("div", { class: "min-w-0" },
      el("p", { class: "font-semibold" }, title),
      message ? el("p", { class: "muted text-xs mt-0.5" }, message) : null));
  $("toasts").append(node);
  setTimeout(() => { node.classList.add("leaving"); setTimeout(() => node.remove(), 320); }, 5200);
}

// ================================================================== navigation

function positionIndicators() {
  for (const nav of document.querySelectorAll(".tabs")) {
    const active = nav.querySelector('.tab[aria-selected="true"]');
    const ind = nav.querySelector(".tab-indicator");
    if (!active || !ind || !active.offsetWidth) continue;
    ind.style.width = `${active.offsetWidth}px`;
    ind.style.transform = `translateX(${active.offsetLeft - 4}px)`;
  }
}

function showView(name) {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.setAttribute("aria-selected", String(tab.dataset.view === name));
  }
  for (const v of ["upload", "documents", "aggregate"]) {
    const section = $(`view-${v}`);
    const show = v === name;
    section.classList.toggle("hidden", !show);
    if (show) { section.classList.remove("view-enter"); void section.offsetWidth; section.classList.add("view-enter"); }
  }
  positionIndicators();
  window.scrollTo({ top: 0, behavior: REDUCED ? "auto" : "smooth" });
  if (name === "aggregate" && state.result) requestAnimationFrame(() => renderAggregate(state.result));
}

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => { if (!tab.disabled) showView(tab.dataset.view); });
}
window.addEventListener("resize", positionIndicators);

// ================================================================== hero pipeline

function renderPipeline(host) {
  host.replaceChildren(...AGENTS.map((a, i) =>
    el("div", { class: "agent", style: { "--i": i }, title: a.name },
      el("div", { class: "agent-icon" }, icon(a.icon, 24)),
      el("p", { class: "text-xs font-bold tracking-wide" }, `${i + 1}. ${a.short}`),
      el("p", { class: "agent-sub text-[11px] muted mt-0.5 hidden sm:block" }, a.sub))));
}

// ================================================================== health

async function checkHealth() {
  const pill = $("health");
  const set = (cls, text) => pill.replaceChildren(el("span", { class: `dot ${cls}` }), el("span", {}, text));
  try {
    const r = await fetch(`${API}/health`);
    if (!r.ok) throw new Error(String(r.status));
    const h = await r.json();
    if (h.pipeline === "live") set("live", `Live pipeline${h.llm ? " · LLM on" : ""}`);
    else set("stub", "Stub pipeline · documents withheld");
  } catch {
    set("off", location.protocol === "file:" ? "Open via http://127.0.0.1:8000/ui/" : "Backend offline · demo works");
  }
}

// ================================================================== upload view

const uploadErrors = el("div", { class: "hidden mt-4 rounded-2xl p-4", role: "alert",
  style: { background: "rgba(120,27,23,.22)", border: "1px solid rgba(229,138,130,.4)" } });
$("file-list").before(uploadErrors);

function addFiles(list) {
  const incoming = Array.from(list);
  for (const f of incoming) {
    if (!state.files.some((x) => x.name === f.name && x.size === f.size)) state.files.push(f);
  }
  if (state.files.length > MAX_FILES) {
    state.files = state.files.slice(0, MAX_FILES);
    toast("info", `Only ${MAX_FILES} files per batch`, "Extra files were left out.");
  }
  renderFiles();
}

function renderFiles() {
  const ext = (n) => (n.includes(".") ? n.split(".").pop().toLowerCase() : "");
  $("file-list").replaceChildren(...state.files.map((f, i) =>
    el("li", { class: "file-chip reveal", style: { "--d": `${i * 40}ms` } },
      el("span", { class: "w-8 h-8 rounded-lg grid place-items-center shrink-0 text-[10px] font-bold uppercase",
                   style: { background: "rgba(39,178,204,.12)", color: "#8EE4F3" } }, ext(f.name) || icon("file", 14)),
      el("div", { class: "min-w-0 flex-1" },
        el("p", { class: "text-sm font-medium truncate" }, f.name),
        el("p", { class: "text-[11px] muted" }, formatBytes(f.size))),
      el("button", { class: "icon-btn", "aria-label": "Remove file", onclick: () => { state.files.splice(i, 1); renderFiles(); } },
        icon("x", 15)))));
  $("btn-upload").disabled = state.files.length === 0;
  $("btn-clear").classList.toggle("hidden", state.files.length === 0);
}

$("files").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
$("btn-clear").addEventListener("click", () => { state.files = []; renderFiles(); hideUploadErrors(); });

const drop = $("drop");
for (const evt of ["dragenter", "dragover"]) {
  drop.addEventListener(evt, (e) => { e.preventDefault(); drop.classList.add("dragging"); });
}
for (const evt of ["dragleave", "drop"]) {
  drop.addEventListener(evt, (e) => { e.preventDefault(); drop.classList.remove("dragging"); });
}
drop.addEventListener("drop", (e) => { if (e.dataTransfer?.files?.length) addFiles(e.dataTransfer.files); });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

$("paste").addEventListener("input", () => {
  const n = $("paste").value.length;
  $("paste-count").textContent = `${n.toLocaleString()} character${n === 1 ? "" : "s"}`;
  $("btn-paste").disabled = $("paste").value.trim() === "";
});

$("btn-upload").addEventListener("click", () => {
  const body = new FormData();
  for (const f of state.files) body.append("files", f);
  submit(`${API}/upload`, { method: "POST", body }, "file", state.files.length);
});

$("btn-paste").addEventListener("click", () => {
  submit(`${API}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ documents: [{ text: $("paste").value }] }),
  }, "document", 1);
});

$("btn-demo").addEventListener("click", async () => {
  hideUploadErrors();
  try {
    const r = await fetch("mock/batch_result.json");
    if (!r.ok) throw new Error(String(r.status));
    loadResult(await r.json(), true);
    toast("info", "Demo batch loaded", "Fictional data. Nothing was sent to the pipeline.");
  } catch {
    toast("error", "Could not load the demo batch",
      location.protocol === "file:" ? "Open the page through the backend." : "mock/batch_result.json is missing.");
  }
});

let timer = null;
function setProcessing(on, count = 0) {
  const overlay = $("processing");
  if (on) {
    $("processing-title").textContent = `Agents are reviewing ${plural(count, "document", "documents")}`;
    const t0 = performance.now();
    $("processing-time").textContent = "0.0";
    timer = setInterval(() => { $("processing-time").textContent = ((performance.now() - t0) / 1000).toFixed(1); }, 100);
    overlay.classList.remove("hidden");
  } else {
    clearInterval(timer);
    overlay.classList.add("hidden");
  }
  for (const id of ["btn-upload", "btn-paste", "btn-demo"]) $(id).disabled = on;
  if (!on) {
    $("btn-upload").disabled = state.files.length === 0;
    $("btn-paste").disabled = $("paste").value.trim() === "";
  }
}

async function submit(url, init, kind, count) {
  hideUploadErrors();
  setProcessing(true, count);
  const minimum = new Promise((res) => setTimeout(res, REDUCED ? 0 : 700));   // avoid a flash
  try {
    const [r] = await Promise.all([fetch(url, init), minimum]);
    const body = await r.json().catch(() => ({}));
    setProcessing(false);
    if (r.ok) {
      const a = body.aggregate || {};
      toast("success", `Reviewed ${plural(a.document_count ?? body.documents.length, "document", "documents")}`,
        `${a.documents_released ?? 0} released · ${a.documents_blocked ?? 0} blocked`);
      loadResult(body, false);
    } else {
      renderApiError(r.status, body, kind);
    }
  } catch {
    setProcessing(false);
    toast("error", "Could not reach the backend", "Check that uvicorn is running, or open the demo batch.");
  }
}

function renderApiError(status, body, kind) {
  const errors = Array.isArray(body.errors) ? body.errors : [];
  const lines = errors.map((e) => {
    if (typeof e.file_index === "number") {
      const local = state.files[e.file_index]?.name;
      return [`File ${e.file_index + 1}${local ? ` (${local})` : ""}`, e.code, e.message];
    }
    if (typeof e.document_index === "number") return [`Document ${e.document_index + 1}`, e.code, e.message];
    if (Array.isArray(e.loc)) return [e.loc.join("."), e.type || "invalid", e.msg];
    return ["Request", e.code || "error", e.message || ""];
  });
  const title = body.detail || `Request failed (${status})`;
  toast("error", title, body.code || String(status));
  uploadErrors.replaceChildren(
    el("p", { class: "font-semibold flex items-center gap-2", style: { color: "#FFD3CD" } }, icon("alert", 16), title),
    lines.length
      ? el("ul", { class: "mt-3 space-y-2" }, lines.map(([who, code, msg]) =>
          el("li", { class: "text-sm flex flex-wrap items-center gap-2" },
            el("span", { class: "font-semibold" }, who),
            el("span", { class: "badge s-blocking" }, code),
            el("span", { class: "muted" }, msg))))
      : el("p", { class: "text-sm muted mt-2" }, kind === "file" ? "No file was processed." : "Nothing was processed."));
  uploadErrors.classList.remove("hidden");
}

function hideUploadErrors() { uploadErrors.classList.add("hidden"); }

// ================================================================== results

function loadResult(result, demo) {
  state.result = result;
  state.demo = demo;
  state.selected = result.documents.length ? result.documents[0].doc_id : null;
  for (const tab of document.querySelectorAll(".tab")) tab.disabled = false;
  renderSummary();
  renderDocList();
  renderDocDetail();
  showView("documents");
}

const advFor = (docId) => (state.result.adversarial?.findings || [])
  .filter((f) => f.doc_id === docId || (f.related_doc_ids || []).includes(docId));
const findingsFor = (doc) => (doc.verification?.findings || []).length + advFor(doc.doc_id).length;
const topRisk = (doc) => doc.risks.reduce((best, r) =>
  RISK_ORDER.indexOf(r.risk) > RISK_ORDER.indexOf(best) ? r.risk : best, doc.risks.length ? "low" : null);

function renderSummary() {
  const { result, demo } = state;
  const a = result.aggregate;
  const entities = result.documents.reduce((s, d) => s + d.entities.length, 0);
  const findings = result.documents.reduce((s, d) => s + findingsFor(d), 0);
  const stat = (label, value, color) => {
    const num = el("p", { class: "text-2xl font-extrabold", style: { color } }, "0");
    countUp(num, value);
    return el("div", { class: "text-center px-3" }, num, el("p", { class: "text-[11px] muted uppercase tracking-wider font-semibold" }, label));
  };
  $("batch-summary").replaceChildren(el("div", { class: "glass p-5 sm:p-6 reveal" },
    el("div", { class: "flex flex-col md:flex-row md:items-center justify-between gap-5" },
      el("div", { class: "min-w-0" },
        el("p", { class: "eyebrow" }, demo ? "Demo batch · fictional data" : "Batch reviewed"),
        el("h2", { class: "text-2xl sm:text-3xl font-extrabold tracking-tight mt-1" },
          `${plural(a.document_count, "document", "documents")} reviewed`),
        el("p", { class: "font-mono text-xs muted mt-1 truncate" }, result.batch_id)),
      el("div", { class: "flex items-center divide-x divide-white/10" },
        stat("Released", a.documents_released, "#8EE4F3"),
        stat("Blocked", a.documents_blocked, a.documents_blocked ? "#F6BDB7" : "#E2E8F0"),
        stat("Entities", entities, "#E2E8F0"),
        stat("Findings", findings, "#C3D2F5"))),
    el("div", { class: "mt-5" }, stackBar([
      { label: "Released", value: a.documents_released, color: C.cyan },
      { label: "Blocked", value: a.documents_blocked, color: C.maroon }], 8))));
}

function renderDocList() {
  const { result, selected } = state;
  $("doc-list").replaceChildren(...result.documents.map((d, i) => {
    const counts = RISK_ORDER.map((r) => ({ label: r, value: d.risks.filter((x) => x.risk === r).length, color: RISK_COLOR[r] }));
    return el("li", { class: "reveal", style: { "--d": `${i * 50}ms` } },
      el("button", {
        class: "doc-card", "aria-current": String(d.doc_id === selected),
        onclick: () => { state.selected = d.doc_id; renderDocList(); renderDocDetail(); },
      },
      el("div", { class: "flex items-center justify-between gap-2" },
        el("span", { class: "flex items-center gap-2 min-w-0" },
          el("span", { class: "muted" }, icon("doc", 15)),
          el("span", { class: "truncate font-mono text-xs font-semibold" }, d.doc_id || `document ${i + 1}`)),
        statusBadge(d)),
      el("p", { class: "text-[11px] muted mt-2" },
        `${plural(d.entities.length, "entity", "entities")} · ${plural(findingsFor(d), "finding", "findings")}`),
      d.risks.length ? el("div", { class: "mt-2" }, stackBar(counts, 5)) : null));
  }));
}

function statusBadge(doc) {
  return doc.released ? badge("Released", "b-released", "check") : badge("Blocked", "b-blocked", "lock");
}

function renderDocDetail() {
  const doc = state.result.documents.find((d) => d.doc_id === state.selected);
  const host = $("doc-detail");
  if (!doc) { host.replaceChildren(); return; }
  const risks = new Map(doc.risks.map((r) => [r.entity_id, r]));
  const decisions = new Map(doc.decisions.map((d) => [d.entity_id, d]));
  host.replaceChildren(
    headerCard(doc),
    redactedCard(doc),
    el("div", { class: "grid md:grid-cols-2 gap-5" }, riskMixCard(doc), strategyMixCard(doc)),
    entitiesCard(doc, risks, decisions),
    strategyCard(doc, risks, decisions),
    findingsCard(doc));
}

// ------------------------------------------------------------------ header + journey

function headerCard(doc) {
  const r = doc.release;
  return card(null, { delay: 0 },
    el("div", { class: "flex flex-wrap items-start justify-between gap-3" },
      el("div", { class: "min-w-0" },
        el("p", { class: "eyebrow" }, "Document"),
        el("h2", { class: "font-mono text-lg font-semibold mt-1 break-all" }, doc.doc_id)),
      el("div", { class: "flex items-center gap-2" },
        r.remediation_rounds ? badge(plural(r.remediation_rounds, "remediation round", "remediation rounds"), "r-medium", "refresh") : null,
        statusBadge(doc))),
    el("p", { class: "mt-3 text-sm", style: { color: doc.released ? "#CBD5E1" : "#F6BDB7" } }, r.reason),
    el("div", { class: "journey mt-7" }, journey(doc).map((s, i) =>
      el("div", { class: `step ${s.state} reveal`, style: { "--d": `${120 + i * 110}ms` } },
        el("div", { class: "step-dot" }, icon(s.state === "warn" ? "x" : s.state === "skip" ? "minus" : "check", 15, 2.6)),
        el("p", { class: "step-label" }, s.label),
        el("p", { class: "step-sub" }, s.sub)))));
}

function journey(doc) {
  const v = doc.verification;
  const n = doc.entities.length;
  const processed = n > 0 || !!v || doc.decisions.length > 0;
  // Only findings ABOUT this document turn the step red; a finding that merely lists it as
  // the linked document (related_doc_ids) blocks the other document, not this one.
  const advRan = !!state.result.adversarial;
  const advBlocking = advFor(doc.doc_id).some((f) => f.doc_id === doc.doc_id && f.severity === "blocking");
  const top = topRisk(doc);
  const strategies = new Set(doc.decisions.map((d) => d.strategy)).size;
  return [
    { label: "Detected", sub: processed ? plural(n, "entity", "entities") : "not run", state: processed ? "done" : "skip" },
    { label: "Assessed", sub: top ? `highest: ${top}` : processed ? "no risk" : "not run", state: processed ? "done" : "skip" },
    { label: "Redacted", sub: doc.decisions.length ? plural(strategies, "strategy", "strategies") : processed ? "nothing to do" : "not run",
      state: processed ? "done" : "skip" },
    { label: "Verified", sub: v ? `${v.checks_run.length} checks · ${v.passed ? "passed" : "failed"}` : "not run",
      state: v ? (v.passed ? "done" : "warn") : "skip" },
    { label: "Attacked", sub: advRan ? (advBlocking ? "risk found" : "no re-identification") : "not run",
      state: advRan ? (advBlocking ? "warn" : "done") : "skip" },
    { label: doc.released ? "Released" : "Blocked", sub: doc.released ? "safe to share" : "withheld",
      state: doc.released ? "done" : "warn" },
  ];
}

// ------------------------------------------------------------------ redacted text

function redactedCard(doc) {
  if (!doc.released || doc.redacted_text === null || doc.redacted_text === undefined) {
    return card("Redacted text", { delay: 80, icon: "lock" },
      el("div", { class: "flex flex-col items-center text-center py-8" },
        el("div", { class: "w-14 h-14 rounded-2xl grid place-items-center mb-4",
                    style: { background: "rgba(120,27,23,.35)", color: "#FFD3CD", border: "1px solid rgba(229,138,130,.4)" } },
          icon("lock", 24)),
        el("p", { class: "font-semibold" }, "Withheld"),
        el("p", { class: "text-sm muted mt-1 max-w-md" },
          "A blocked document's text is never sent to the browser, so there is nothing here to leak.")));
  }
  const copy = el("button", { class: "icon-btn", "aria-label": "Copy redacted text", title: "Copy redacted text",
    onclick: async () => {
      try { await navigator.clipboard.writeText(doc.redacted_text); toast("success", "Copied redacted text"); }
      catch { toast("error", "Copy failed", "Your browser blocked clipboard access."); }
    } }, icon("copy", 16));
  const legend = el("div", { class: "flex flex-wrap items-center gap-2 mt-5 text-xs muted" },
    el("span", { class: "ph ph-mask", style: { opacity: 1, transform: "none", animation: "none" } }, "[MASKED]"),
    el("span", { class: "ph ph-pseudo", style: { opacity: 1, transform: "none", animation: "none" } }, "PERSON_01"),
    el("span", { class: "ph ph-suppress", style: { opacity: 1, transform: "none", animation: "none" } }, "[REDACTED]"),
    el("span", {}, "Generalised values (e.g. an age band) appear as plain text, because entity positions refer to the original."));
  return card("Redacted text", { delay: 80, icon: "shield", action: copy },
    el("div", { class: "redacted rounded-2xl p-5", style: { background: "rgba(4,8,20,.45)", border: "1px solid var(--line)" } },
      highlightPlaceholders(doc.redacted_text)),
    legend);
}

function highlightPlaceholders(text) {
  const out = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(PLACEHOLDER)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const token = m[0];
    const kind = token === "[REDACTED]" ? "ph-suppress" : token.startsWith("[") ? "ph-mask" : "ph-pseudo";
    out.push(el("mark", { class: `ph ${kind}`, style: { "--d": `${250 + i * 70}ms` } }, token));
    last = m.index + token.length;
    i += 1;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// ------------------------------------------------------------------ mix cards

function mixCard(title, iconName, delay, parts, empty) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  if (!total) return card(title, { delay, icon: iconName }, el("p", { class: "text-sm muted" }, empty));
  return card(title, { delay, icon: iconName },
    stackBar(parts, 12),
    el("ul", { class: "mt-4 grid grid-cols-2 gap-2" }, parts.filter((p) => p.value).map((p) =>
      el("li", { class: "flex items-center justify-between gap-2 text-sm rounded-xl px-3 py-2",
                 style: { background: "rgba(255,255,255,.03)" } },
        el("span", { class: "flex items-center gap-2" }, el("span", { class: "legend-dot", style: { background: p.color } }), p.label),
        el("span", { class: "font-bold" }, String(p.value))))));
}

function riskMixCard(doc) {
  return mixCard("Risk mix", "alert", 140,
    RISK_ORDER.map((r) => ({ label: r[0].toUpperCase() + r.slice(1), value: doc.risks.filter((x) => x.risk === r).length, color: RISK_COLOR[r] })),
    "No risks assessed for this document.");
}

function strategyMixCard(doc) {
  return mixCard("Actions taken", "pen", 180,
    STRATEGY_ORDER.map((s) => ({ label: STRATEGY_LABEL[s], value: doc.decisions.filter((x) => x.strategy === s).length, color: STRATEGY_COLOR[s] })),
    "No redaction decisions for this document.");
}

// ------------------------------------------------------------------ entities + strategy table

function entitiesCard(doc, risks, decisions) {
  if (!doc.entities.length) {
    return card("Entities", { delay: 220, icon: "search" }, el("p", { class: "text-sm muted" }, "No entities reported."));
  }
  const byType = new Map();
  for (const e of doc.entities) {
    if (!byType.has(e.entity_type)) byType.set(e.entity_type, []);
    byType.get(e.entity_type).push(e);
  }
  let n = 0;
  const groups = [...byType.entries()].sort((a, b) => b[1].length - a[1].length).map(([type, ents]) =>
    el("div", { class: "flex flex-col sm:flex-row sm:items-center gap-2 py-2.5", style: { borderTop: "1px solid var(--line)" } },
      el("span", { class: "text-xs font-bold tracking-wide sm:w-48 shrink-0" }, type.replace(/_/g, " "),
        el("span", { class: "muted font-semibold" }, ` · ${ents.length}`)),
      el("div", { class: "flex flex-wrap gap-1.5" }, ents.map((e) => {
        const risk = risks.get(e.entity_id)?.risk || "unknown";
        const strategy = decisions.get(e.entity_id)?.strategy;
        n += 1;
        return el("span", {
          class: `badge ${riskCls(risk)} reveal`, style: { "--d": `${260 + n * 30}ms` },
          title: `${e.entity_id} · risk ${risk} · confidence ${Math.round(e.confidence * 100)}%`,
        }, risk, el("span", { style: { opacity: 0.55 } }, "·"), strategy ? STRATEGY_LABEL[strategy] || strategy : "no decision");
      }))));
  const legend = el("div", { class: "flex flex-wrap items-center gap-2 mt-4 text-xs muted" },
    "Risk:", ...RISK_ORDER.map((r) => badge(r, riskCls(r))));
  return card("Entities by type", { delay: 220, icon: "search" }, el("div", {}, groups), legend);
}

function strategyCard(doc, risks, decisions) {
  if (!doc.entities.length) return null;
  const rows = doc.entities.map((e) => {
    const risk = risks.get(e.entity_id);
    const dec = decisions.get(e.entity_id);
    const level = risk?.risk || "unknown";
    return el("tr", {},
      el("td", { class: "font-mono text-[11px] muted" }, e.entity_id),
      el("td", {}, el("span", { class: "font-semibold text-xs" }, e.entity_type.replace(/_/g, " ")),
        el("div", { class: "text-[11px] muted" }, pretty(e.identifier_class))),
      el("td", {}, badge(level, riskCls(level)),
        risk && risk.base_risk !== risk.risk ? el("div", { class: "text-[11px] muted mt-1" }, `raised from ${risk.base_risk}`) : null),
      el("td", {}, el("span", { class: "font-semibold" }, dec ? STRATEGY_LABEL[dec.strategy] || dec.strategy : "—"),
        dec?.scope === "batch" ? el("div", { class: "text-[11px] muted" }, "same across batch") : null),
      el("td", { class: "text-xs muted" }, dec?.policy_id || ""),
      el("td", { class: "text-xs", style: { color: "#CBD5E1" } }, risk?.rationale || "",
        risk?.fired_rules?.length ? el("div", { class: "text-[11px] muted mt-1" }, `rules: ${risk.fired_rules.join(", ")}`) : null));
  });
  return card("Why each action was taken", { delay: 260, icon: "scale" },
    el("div", { class: "overflow-x-auto -mx-1 px-1" },
      el("table", { class: "tbl" },
        el("thead", {}, el("tr", {}, ...["Entity", "Type", "Risk", "Action", "Policy", "Reason"].map((h) => el("th", {}, h)))),
        el("tbody", {}, rows))));
}

// ------------------------------------------------------------------ findings

function findingsCard(doc) {
  const v = doc.verification;
  const summary = v
    ? el("div", { class: "flex flex-wrap items-center gap-2 mb-4 text-sm" },
        badge(v.passed ? "Verification passed" : "Verification failed", v.passed ? "b-released" : "b-blocked", v.passed ? "check" : "x"),
        el("span", { class: "muted" }, `revision ${v.revision} · ${v.checks_run.length} checks`),
        el("span", { class: "muted" }, "·"),
        el("span", { class: "muted" }, "utility retained"),
        utilityMeter(v.utility_retained))
    : el("p", { class: "text-sm muted mb-4" }, "No verification report: the document was not processed.");
  const all = [...(v ? v.findings : []).map((f) => ({ f, src: "Verification" })),
               ...advFor(doc.doc_id).map((f) => ({ f, src: "Adversarial" }))];
  const list = all.length
    ? el("ul", { class: "space-y-2.5" }, all.map(({ f, src }, i) => findingItem(f, src, doc.doc_id, i)))
    : el("div", { class: "flex items-center gap-3 rounded-xl p-4", style: { background: "rgba(39,178,204,.07)", border: "1px solid rgba(39,178,204,.25)" } },
        el("span", { class: "text-cyan" }, icon("check", 18, 2.5)), el("span", { class: "text-sm" }, "No findings: nothing left to fix."));
  return card("Verification findings", { delay: 300, icon: "shield" }, summary, list);
}

function utilityMeter(value) {
  const pct = Math.round(value * 100);
  const bar = el("span", { class: "inline-block align-middle w-24 h-1.5 rounded-full overflow-hidden", style: { background: "rgba(255,255,255,.08)" } },
    el("span", { class: "block h-full", style: { width: `${pct}%`, background: `linear-gradient(90deg, ${C.steelSoft}, ${C.cyan})` } }));
  return el("span", { class: "inline-flex items-center gap-2" }, bar, el("span", { class: "font-semibold" }, `${pct}%`));
}

function findingItem(f, src, docId, i) {
  const related = (f.related_doc_ids || []).concat(f.doc_id !== docId ? [f.doc_id] : []).filter((d) => d !== docId);
  const accent = { blocking: C.maroonSoft, warning: "#F2B45A", info: C.steelSoft }[f.severity] || C.steelSoft;
  return el("li", { class: "reveal rounded-xl p-4 flex gap-3",
                    style: { "--d": `${340 + i * 60}ms`, background: "rgba(255,255,255,.03)", borderLeft: `3px solid ${accent}` } },
    el("div", { class: "min-w-0 flex-1" },
      el("div", { class: "flex flex-wrap items-center gap-2" },
        el("span", { class: `badge s-${f.severity}` }, f.severity),
        el("span", { class: "text-sm font-semibold" }, pretty(f.finding_type)),
        el("span", { class: "text-[11px] muted" }, src)),
      el("p", { class: "text-sm mt-1.5", style: { color: "#CBD5E1" } }, f.description),
      el("div", { class: "flex flex-wrap gap-1.5 mt-2" },
        f.entity_type ? badge(f.entity_type.replace(/_/g, " "), "r-unknown") : null,
        f.recommended_strategy ? badge(`fix: ${STRATEGY_LABEL[f.recommended_strategy] || f.recommended_strategy}`, "r-medium") : null,
        f.rule_id ? badge(f.rule_id, "r-unknown") : null,
        related.length ? badge(`linked to ${related.join(", ")}`, "r-high", "link") : null)));
}

// ================================================================== insights view

function renderAggregate(result) {
  const a = result.aggregate;
  const entities = Object.values(a.entities_by_type || {}).reduce((s, n) => s + n, 0);
  const tile = (label, value, ic, color, i) => {
    const num = el("p", { class: "text-3xl font-extrabold mt-2", style: { color } }, "0");
    if (typeof value === "number") countUp(num, value); else num.textContent = value;
    return el("div", { class: "glass lift p-4 reveal", style: { "--d": `${i * 60}ms` } },
      el("div", { class: "flex items-center justify-between" },
        el("p", { class: "text-[11px] muted uppercase tracking-wider font-semibold" }, label),
        el("span", { style: { color } }, icon(ic, 16))),
      num);
  };
  $("stat-tiles").replaceChildren(
    tile("Documents", a.document_count, "layers", "#E2E8F0", 0),
    tile("Released", a.documents_released, "check", "#8EE4F3", 1),
    tile("Blocked", a.documents_blocked, "lock", a.documents_blocked ? "#F6BDB7" : "#E2E8F0", 2),
    tile("Entities found", entities, "search", "#C3D2F5", 3),
    tile("LLM used", a.llm_used ? "Yes" : "No", "sparkle", "#E2E8F0", 4));

  const ids = ["chart-release", "chart-risks", "chart-entities", "chart-strategies", "chart-findings"];
  if (typeof Plotly === "undefined") {
    for (const id of ids) $(id).replaceChildren(el("p", { class: "text-sm muted pt-10 text-center" }, "Charts need the Plotly CDN, which did not load."));
  } else {
    bar("chart-release", ["Released", "Blocked"], [a.documents_released, a.documents_blocked], [C.cyan, C.maroon]);
    const risks = ordered(a.risks_by_level, RISK_ORDER);
    bar("chart-risks", risks.keys, risks.values, risks.keys.map((k) => RISK_COLOR[k] || RISK_COLOR.unknown));
    const ents = sortedDesc(a.entities_by_type);
    bar("chart-entities", ents.keys.map((k) => k.replace(/_/g, " ")), ents.values, C.steelSoft, true);
    const strat = ordered(a.strategies, STRATEGY_ORDER);
    bar("chart-strategies", strat.keys.map((k) => STRATEGY_LABEL[k] || k), strat.values, strat.keys.map((k) => STRATEGY_COLOR[k] || C.steelSoft));
    const finds = sortedDesc(a.findings_by_type);
    bar("chart-findings", finds.keys.map(pretty), finds.values, C.cyan, true);
  }
  renderLinkage(result.adversarial);
}

function ordered(obj, order) {
  const keys = [...order.filter((k) => k in (obj || {})), ...Object.keys(obj || {}).filter((k) => !order.includes(k))];
  return { keys, values: keys.map((k) => obj[k]) };
}

function sortedDesc(obj) {
  const entries = Object.entries(obj || {}).sort((x, y) => y[1] - x[1]);
  return { keys: entries.map((e) => e[0]), values: entries.map((e) => e[1]) };
}

function bar(id, keys, values, color, horizontal = false) {
  const node = $(id);
  if (!keys.length || values.every((v) => !v)) {
    Plotly.purge(node);
    node.replaceChildren(el("div", { class: "h-full grid place-items-center text-sm muted" }, "No data in this batch"));
    return;
  }
  node.replaceChildren();
  const marker = { color: Array.isArray(color) ? (horizontal ? [...color].reverse() : color) : color, cornerradius: 6 };
  const trace = horizontal
    ? { type: "bar", orientation: "h", y: [...keys].reverse(), x: [...values].reverse(), marker }
    : { type: "bar", x: keys, y: values, marker };
  trace.hovertemplate = horizontal ? "%{y}: %{x}<extra></extra>" : "%{x}: %{y}<extra></extra>";
  const axis = { gridcolor: C.grid, zeroline: false, automargin: true, linecolor: "rgba(0,0,0,0)", tickfont: { color: C.text } };
  Plotly.react(node, [trace], {
    margin: { t: 10, r: 10, b: horizontal ? 30 : 40, l: horizontal ? 140 : 36 },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Inter, ui-sans-serif, system-ui, sans-serif", size: 12, color: C.text },
    xaxis: { ...axis, ...(horizontal ? { dtick: 1 } : {}) },
    yaxis: { ...axis, ...(horizontal ? {} : { dtick: 1 }) },
    bargap: 0.38,
    hoverlabel: { bgcolor: C.navy, bordercolor: C.cyan, font: { color: "#fff", family: "Inter" } },
    transition: REDUCED ? undefined : { duration: 500, easing: "cubic-in-out" },
  }, { displayModeBar: false, responsive: true });
}

function renderLinkage(adv) {
  const host = $("linkage");
  const head = el("div", { class: "flex flex-wrap items-center justify-between gap-3 mb-4" },
    el("div", {},
      el("h3", { class: "font-bold flex items-center gap-2" }, el("span", { class: "text-cyan" }, icon("link", 17)), "Cross-document linkage"),
      el("p", { class: "text-xs muted mt-1" },
        "k = how many people share the combined clues. k = 1 means a single person can be picked out.")),
    adv ? badge(adv.safe_to_release ? "Safe to release" : "Not safe to release", adv.safe_to_release ? "b-released" : "b-blocked",
                adv.safe_to_release ? "check" : "alert") : null);
  if (!adv || !adv.components.length) {
    host.replaceChildren(head, el("p", { class: "text-sm muted" },
      adv ? "No linked document groups found." : "No adversarial report in this batch."));
    return;
  }
  host.replaceChildren(head, el("div", { class: "space-y-3" }, adv.components.map((c, i) => {
    const identifiable = c.anonymity_set_size <= 1;
    const docs = [];
    c.doc_ids.forEach((d, j) => {
      if (j) docs.push(el("span", { class: "link-line", "aria-hidden": "true" }));
      docs.push(el("span", { class: "badge r-unknown font-mono" }, icon("doc", 12), d));
    });
    return el("div", { class: "reveal rounded-2xl p-4 flex flex-col lg:flex-row lg:items-center gap-4",
                       style: { "--d": `${i * 80}ms`, background: "rgba(255,255,255,.03)", border: "1px solid var(--line)" } },
      el("div", { class: "flex items-center gap-2 flex-1 min-w-0 flex-wrap" }, docs),
      el("div", { class: "flex flex-wrap items-center gap-1.5" },
        el("span", { class: "text-[11px] muted" }, "linked by"),
        c.linked_by.map((t) => badge(t.replace(/_/g, " "), "r-medium")),
        c.visible_quasi_types.length ? el("span", { class: "text-[11px] muted ml-1" }, "visible") : null,
        c.visible_quasi_types.map((t) => badge(t.replace(/_/g, " "), "r-unknown"))),
      el("div", { class: "text-center rounded-xl px-4 py-2 shrink-0",
                  style: identifiable
                    ? { background: "rgba(120,27,23,.55)", border: "1px solid rgba(229,138,130,.5)", boxShadow: "0 0 24px -6px rgba(229,138,130,.6)" }
                    : { background: "rgba(39,178,204,.1)", border: "1px solid rgba(39,178,204,.35)" } },
        el("p", { class: "text-xl font-extrabold" }, `k = ${c.anonymity_set_size}`),
        el("p", { class: "text-[10px] uppercase tracking-wider font-bold", style: { color: identifiable ? "#FFD3CD" : "#8EE4F3" } },
          identifiable ? "identifiable" : "hidden in crowd")));
  })));
}

// ================================================================== misc

function formatBytes(n) {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

renderPipeline($("hero-pipeline"));
renderPipeline($("processing-agents"));
positionIndicators();
if (document.fonts?.ready) document.fonts.ready.then(positionIndicators);
checkHealth();
