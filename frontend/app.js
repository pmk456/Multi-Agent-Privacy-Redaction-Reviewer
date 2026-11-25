// PS 247 frontend. No build step, no framework. Styles live in styles.css.
//
// Safety rules for this file:
//  - Everything from the API is rendered with textContent / createElement, never innerHTML.
//    The only markup set directly is the static SVG paths in ICONS (constants, never data).
//  - Entity spans refer to the ORIGINAL text, not the redacted one, so they are never shown
//    or used to index into redacted_text.
//  - The API never sends filenames back. Errors come with a file_index; the filename shown
//    next to an error is read from the browser's own file picker and goes nowhere.
"use strict";

const API = location.protocol === "file:" ? "http://127.0.0.1:8000" : "";
const LIMITS = { files: 20, bytes: 5 * 1024 * 1024, chars: 200000 };
const ACCEPTED = ["txt", "pdf", "json"];

const RISK_ORDER = ["low", "medium", "high", "critical"];
const STRATEGY_ORDER = ["keep", "generalize", "pseudonymize", "mask", "suppress"];
const STRATEGY_LABEL = { keep: "Kept", generalize: "Generalised", pseudonymize: "Pseudonymised", mask: "Masked", suppress: "Removed" };
// Sequential palette: the more information an action removes, the darker it is.
const VIZ = { 1: "#C9D1DD", 2: "#8FA1BF", 3: "#4F6A99", 4: "#1E3A6B", 5: "#781B17" };
const RISK_COLOR = { low: VIZ[1], medium: VIZ[3], high: "#B5652A", critical: VIZ[5] };
const STRATEGY_COLOR = { keep: VIZ[1], generalize: VIZ[2], pseudonymize: VIZ[3], mask: VIZ[4], suppress: VIZ[5] };
const OK = "#155E75", DANGER = "#781B17";

// [EMAIL_ADDRESS], [REDACTED], PERSON_01, PERSON_7F3A
const PLACEHOLDER = /\[[A-Z][A-Z_]*\]|\b[A-Z]{2,}(?:_[A-Z]+)*_[0-9A-F]{2,}\b/g;

// Actionable wording for server error codes. Falls back to the server's own message,
// which never quotes document content.
const ERROR_HINT = {
  empty_document: "The file is empty. Remove it, or add content and try again.",
  file_too_large: "Larger than 5 MB. Split the document or remove the file.",
  document_too_long: "Longer than 200,000 characters. Split it into smaller documents.",
  unsupported_format: "Only .txt, .pdf and .json files are supported.",
  corrupt_file: "The file looks damaged, or isn't the format its extension says.",
  encrypted_pdf: "The PDF is password-protected. Remove the password and upload it again.",
  scanned_pdf: "The PDF has no text layer (it looks scanned). Upload a text-based PDF or a .txt file.",
  // The ones below follow the server's own message, so they only give the next step.
  too_many_files: "Remove some files so the batch has 20 or fewer, then try again.",
  too_many_documents: "Split the batch so it has 20 or fewer documents.",
  request_too_large: "Send fewer or smaller files.",
  length_required: "Try again. If it keeps happening, reload the page.",
  pipeline_error: "Try again. If it keeps failing, check the server logs.",
  internal_error: "Try again in a moment.",
};

const ICONS = {
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  minus: '<path d="M6 12h12"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><path d="M12 16.5h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.5h.01"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  chart: '<path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/><path d="M22 20H2"/>',
  arrow: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
};

const state = { result: null, demo: false, selected: null, files: [], mode: "files", busy: false };
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

function icon(name, size = 16, stroke = 2) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [k, v] of Object.entries({ width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": stroke, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" })) svg.setAttribute(k, v);
  svg.innerHTML = ICONS[name] || "";            // static constant, see ICONS
  return svg;
}

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`;
const humanType = (t) => String(t).replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
const pretty = (s) => String(s).replace(/_/g, " ").toLowerCase();
const extOf = (name) => (name.includes(".") ? name.split(".").pop().toLowerCase() : "");

function formatBytes(n) {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

// ================================================================== toasts

function toast(kind, title, message) {
  const ic = { ok: "check", error: "alert", info: "info" }[kind] || "info";
  const node = el("div", { class: `toast is-${kind}`, role: kind === "error" ? "alert" : "status" },
    el("span", { class: "toast-icon" }, icon(ic, 17)),
    el("div", {}, el("p", { class: "toast-title" }, title), message ? el("p", { class: "toast-msg" }, message) : null),
    el("button", { class: "icon-btn", style: { width: "24px", height: "24px" }, "aria-label": "Dismiss", onclick: () => dismiss() }, icon("x", 14)));
  const dismiss = () => { node.classList.add("is-leaving"); setTimeout(() => node.remove(), 160); };
  $("toasts").append(node);
  setTimeout(dismiss, kind === "error" ? 8000 : 4500);
}

// ================================================================== navigation

const VIEWS = ["upload", "documents", "aggregate"];

function showView(name, { focus = false } = {}) {
  for (const v of VIEWS) $(`view-${v}`).hidden = v !== name;
  for (const link of document.querySelectorAll("[data-view].nav-link")) {
    if (link.dataset.view === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  if (name === "documents") renderDocuments();
  if (name === "aggregate") renderInsights();
  window.scrollTo({ top: 0 });
  if (focus) $(`view-${name}`).querySelector("h1")?.focus({ preventScroll: true });
}

for (const link of document.querySelectorAll("[data-view]")) {
  link.addEventListener("click", (e) => { e.preventDefault(); showView(link.dataset.view, { focus: true }); });
}

function updateNavCount() {
  const n = state.result?.documents.length || 0;
  for (const badge of document.querySelectorAll("[data-count]")) { badge.textContent = String(n); badge.hidden = !n; }
}

// ================================================================== backend status

async function checkHealth() {
  const pipe = $("status-pipeline"), llm = $("status-llm");
  const set = (cls, text, title) => {
    pipe.replaceChildren(el("span", { class: `status-dot ${cls}` }), el("span", {}, text));
    pipe.title = title;
  };
  try {
    const r = await fetch(`${API}/health`);
    if (!r.ok) throw new Error(String(r.status));
    const h = await r.json();
    if (h.pipeline === "live") set("is-live", "Pipeline live", "Backend online. Documents are processed by the five-agent pipeline.");
    else set("is-stub", "Pipeline unavailable", "Backend online, but the redaction pipeline is not installed. Every document is withheld.");
    llm.textContent = h.llm ? "LLM on" : "LLM off";
    llm.title = h.llm ? "Optional LLM reasoning is enabled. It never receives raw identifiers." : "Deterministic mode. No LLM is used.";
  } catch {
    set("is-off", "Backend offline", location.protocol === "file:"
      ? "Opened from disk. Start the server and open http://127.0.0.1:8000/ui/."
      : "The backend did not respond. The sample batch still works.");
    llm.textContent = "LLM —";
  }
}

// ================================================================== composer: tabs

function setMode(mode) {
  state.mode = mode;
  for (const [tab, panel, m] of [["tab-files", "panel-files", "files"], ["tab-text", "panel-text", "text"]]) {
    const on = m === mode;
    $(tab).setAttribute("aria-selected", String(on));
    $(tab).tabIndex = on ? 0 : -1;
    $(panel).hidden = !on;
  }
  hideRunError();
  updateComposer();
}

$("tab-files").addEventListener("click", () => setMode("files"));
$("tab-text").addEventListener("click", () => { setMode("text"); $("paste").focus(); });
for (const id of ["tab-files", "tab-text"]) {
  $(id).addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const next = state.mode === "files" ? "text" : "files";
    setMode(next);
    $(next === "files" ? "tab-files" : "tab-text").focus();
  });
}

// ================================================================== composer: files

function localProblem(file) {
  if (!ACCEPTED.includes(extOf(file.name))) return "Unsupported type. Use .txt, .pdf or .json.";
  if (file.size === 0) return "The file is empty.";
  if (file.size > LIMITS.bytes) return "Larger than 5 MB.";
  return null;
}

function addFiles(list) {
  let skipped = 0;
  for (const file of Array.from(list)) {
    if (state.files.some((f) => f.file.name === file.name && f.file.size === file.size)) continue;
    if (state.files.length >= LIMITS.files) { skipped += 1; continue; }
    state.files.push({ file, local: localProblem(file), server: null });
  }
  if (skipped) toast("info", `${plural(skipped, "file")} not added`, `A batch can hold at most ${LIMITS.files} files.`);
  hideRunError();
  renderFiles();
}

function renderFiles() {
  const rows = state.files.map((entry, i) => {
    const problem = entry.server ? (ERROR_HINT[entry.server.code] || entry.server.message) : entry.local;
    const status = problem
      ? el("span", { style: { color: "var(--danger)", fontSize: "12.5px" } }, problem)
      : el("span", { class: "t-meta" }, "Ready");
    return el("tr", { class: problem ? "file-row-error" : "" },
      el("td", {}, el("div", { class: "file-name" },
        el("span", { class: "file-type" }, extOf(entry.file.name) || "?"),
        el("span", { title: entry.file.name }, entry.file.name))),
      el("td", { class: "col-size num" }, formatBytes(entry.file.size)),
      el("td", { class: "col-status" }, status),
      el("td", { class: "col-action" },
        el("button", { class: "icon-btn", type: "button", "aria-label": `Remove ${entry.file.name}`, disabled: state.busy || null,
          onclick: () => { state.files.splice(i, 1); hideRunError(); renderFiles(); } }, icon("x", 15))));
  });
  $("file-rows").replaceChildren(...rows);
  $("file-table").hidden = state.files.length === 0;
  $("file-count").textContent = String(state.files.length);
  $("file-count").hidden = state.files.length === 0;
  updateComposer();
}

$("btn-browse").addEventListener("click", () => $("files").click());
$("files").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
$("btn-clear").addEventListener("click", () => {
  if (state.mode === "files") { state.files = []; renderFiles(); } else { $("paste").value = ""; onPaste(); }
  hideRunError();
});

// Drag and drop: the whole composer is the target, so a near-miss still works.
const composer = $("composer");
let dragDepth = 0;
composer.addEventListener("dragenter", (e) => {
  e.preventDefault();
  if (++dragDepth === 1) { composer.classList.add("is-dragging"); $("drop-title").textContent = "Drop to add files"; if (state.mode !== "files") setMode("files"); }
});
composer.addEventListener("dragover", (e) => e.preventDefault());
composer.addEventListener("dragleave", () => { if (--dragDepth <= 0) endDrag(); });
composer.addEventListener("drop", (e) => {
  e.preventDefault(); endDrag();
  if (e.dataTransfer?.files?.length) addFiles(e.dataTransfer.files);
});
function endDrag() { dragDepth = 0; composer.classList.remove("is-dragging"); $("drop-title").textContent = "Drag files here to add them"; }
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

// ================================================================== composer: text

function onPaste() {
  const n = $("paste").value.length;
  const over = n > LIMITS.chars;
  $("paste-count").textContent = `${n.toLocaleString()} / ${LIMITS.chars.toLocaleString()} characters`;
  $("paste-count").style.color = over ? "var(--danger)" : "";
  updateComposer();
}
$("paste").addEventListener("input", onPaste);
$("paste").addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !$("btn-run").disabled) $("btn-run").click();
});

// ================================================================== composer: summary + primary action

function updateComposer() {
  const run = $("btn-run");
  const label = run.querySelector(".btn-label");
  if (state.mode === "files") {
    const n = state.files.length;
    const bad = state.files.filter((f) => f.local || f.server).length;
    const size = state.files.reduce((s, f) => s + f.file.size, 0);
    $("composer-summary").textContent = !n ? "No files added yet"
      : bad ? `${plural(bad, "file")} need${bad === 1 ? "s" : ""} attention`
      : `${plural(n, "file")} · ${formatBytes(size)} · reviewed as one batch`;
    $("composer-summary").style.color = bad ? "var(--danger)" : "";
    if (!state.busy) label.textContent = n ? `Review ${plural(n, "file")}` : "Run review";
    run.disabled = state.busy || !n || bad > 0;
    $("btn-clear").hidden = !n || state.busy;
  } else {
    const text = $("paste").value;
    const over = text.length > LIMITS.chars;
    $("composer-summary").textContent = over ? "Text is over the 200,000-character limit"
      : text.trim() ? "Ctrl + Enter to run" : "Paste text to review it";
    $("composer-summary").style.color = over ? "var(--danger)" : "";
    if (!state.busy) label.textContent = "Review text";
    run.disabled = state.busy || !text.trim() || over;
    $("btn-clear").hidden = !text || state.busy;
  }
}

$("btn-run").addEventListener("click", () => {
  if (state.mode === "files") {
    const body = new FormData();
    for (const f of state.files) body.append("files", f.file);
    submit(`${API}/upload`, { method: "POST", body }, state.files.length);
  } else {
    submit(`${API}/review`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ documents: [{ text: $("paste").value }] }),
    }, 1);
  }
});

let elapsedTimer = null;
function setBusy(on, count = 0) {
  state.busy = on;
  const run = $("btn-run");
  run.classList.toggle("is-loading", on);
  run.querySelector(".spinner").hidden = !on;
  if (on) run.querySelector(".btn-label").textContent = "Reviewing…";
  $("run-status").hidden = !on;
  for (const id of ["btn-browse", "btn-demo", "tab-files", "tab-text", "paste"]) $(id).disabled = on;
  if (on) {
    $("run-status-title").textContent = `Reviewing ${plural(count, "document")}`;
    const t0 = performance.now();
    $("run-elapsed").textContent = "0.0 s";
    elapsedTimer = setInterval(() => { $("run-elapsed").textContent = `${((performance.now() - t0) / 1000).toFixed(1)} s`; }, 100);
  } else {
    clearInterval(elapsedTimer);
  }
  renderFiles();
}

async function submit(url, init, count) {
  hideRunError();
  for (const f of state.files) f.server = null;
  setBusy(true, count);
  try {
    const r = await fetch(url, init);
    const body = await r.json().catch(() => ({}));
    setBusy(false);
    if (r.ok) {
      const a = body.aggregate || {};
      toast("ok", "Review complete", `${a.documents_released ?? 0} released · ${a.documents_blocked ?? 0} blocked`);
      loadResult(body, false);
    } else {
      handleApiError(r.status, body);
    }
  } catch {
    setBusy(false);
    showRunError("Couldn't reach the backend", ["Check that the server is running, then try again. The sample batch works offline."]);
  }
}

function handleApiError(status, body) {
  const errors = Array.isArray(body.errors) ? body.errors : [];
  const fileErrors = errors.filter((e) => typeof e.file_index === "number");
  for (const e of fileErrors) if (state.files[e.file_index]) state.files[e.file_index].server = { code: e.code, message: e.message };
  renderFiles();

  if (fileErrors.length) {
    showRunError(`${plural(fileErrors.length, "file")} couldn't be reviewed`,
      ["Nothing was processed. Fix or remove the highlighted files, then run the review again."]);
    return;
  }
  const lines = errors.map((e) => {
    if (Array.isArray(e.loc)) return `${e.loc.join(" › ")}: ${e.msg}`;
    return ERROR_HINT[e.code] || e.message;
  });
  const next = ERROR_HINT[body.code] || "Try again. If it keeps failing, check the server logs.";
  showRunError(body.detail || `Request failed (${status})`, lines.length ? lines : [next]);
}

function showRunError(title, lines) {
  $("run-error").replaceChildren(
    el("span", { class: "callout-icon" }, icon("alert", 16)),
    el("div", {}, el("p", { style: { fontWeight: 500 } }, title),
      ...lines.map((l) => el("p", { style: { marginTop: "2px" } }, l))));
  $("run-error").hidden = false;
}
function hideRunError() { $("run-error").hidden = true; }

$("btn-demo").addEventListener("click", loadDemo);
async function loadDemo() {
  try {
    const r = await fetch("mock/batch_result.json");
    if (!r.ok) throw new Error(String(r.status));
    loadResult(await r.json(), true);
    toast("info", "Sample batch opened", "Fictional data. Nothing was sent to the pipeline.");
  } catch {
    toast("error", "Couldn't open the sample batch",
      location.protocol === "file:" ? "Open the page through the server instead of from disk." : "mock/batch_result.json is missing.");
  }
}

// ================================================================== results: shared

function loadResult(result, demo) {
  state.result = result;
  state.demo = demo;
  state.selected = result.documents[0]?.doc_id ?? null;
  updateNavCount();
  showView("documents", { focus: true });
}

const advFor = (docId) => (state.result.adversarial?.findings || [])
  .filter((f) => f.doc_id === docId || (f.related_doc_ids || []).includes(docId));
const findingCount = (doc) => (doc.verification?.findings || []).length + advFor(doc.doc_id).length;
const topRisk = (doc) => doc.risks.reduce((best, r) =>
  RISK_ORDER.indexOf(r.risk) > RISK_ORDER.indexOf(best) ? r.risk : best, doc.risks.length ? "low" : null);

function emptyState(iconName, title, text) {
  return el("div", { class: "empty" },
    el("div", { class: "empty-icon" }, icon(iconName, 20, 1.8)),
    el("h1", { class: "t-heading", tabindex: "-1" }, title),
    el("p", { class: "t-lede" }, text),
    el("div", { class: "empty-actions" },
      el("button", { class: "btn btn-primary", type: "button", onclick: () => showView("upload", { focus: true }) }, "Start a review"),
      el("button", { class: "btn btn-secondary", type: "button", onclick: loadDemo }, "Open sample batch")));
}

function metrics(items) {
  return el("div", { class: "metrics", style: { "--cols": items.length } }, items.map(([label, value, color]) =>
    el("div", { class: "metric" },
      el("p", { class: "metric-label" }, label),
      el("p", { class: "metric-value", style: color ? { color } : null }, value))));
}

function batchHead(title, lede, actions) {
  const { result, demo } = state;
  return el("div", { class: "page-head" },
    el("div", {},
      el("p", { class: "t-overline" }, demo ? "Sample batch · fictional data" : "Batch"),
      el("h1", { class: "t-title", tabindex: "-1" }, title),
      lede ? el("p", { class: "t-lede" }, lede) : null,
      el("p", { class: "t-meta", style: { marginTop: "8px" } }, "Batch ID ", el("span", { class: "t-mono" }, result.batch_id))),
    actions || null);
}

const statusLabel = (doc) => el("span", { class: `status-label ${doc.released ? "is-ok" : "is-danger"}` }, doc.released ? "Released" : "Blocked");
const riskTag = (r) => el("span", { class: `risk-tag risk-${RISK_ORDER.includes(r) ? r : "low"}` }, r || "—");

function distBar(parts) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  return el("div", { class: "dist", role: "img", "aria-label": parts.filter((p) => p.value).map((p) => `${p.label} ${p.value}`).join(", ") },
    parts.filter((p) => p.value).map((p) => el("span", { style: { width: `${(p.value / total) * 100}%`, background: p.color }, title: `${p.label}: ${p.value}` })));
}

// ================================================================== documents view

function renderDocuments() {
  const root = $("documents-root");
  if (!state.result) {
    root.replaceChildren(emptyState("file", "No batch reviewed yet",
      "Run a review from the Review page, or open the sample batch to see how results are presented."));
    return;
  }
  const { result } = state;
  const a = result.aggregate;
  const entities = result.documents.reduce((s, d) => s + d.entities.length, 0);
  const findings = result.documents.reduce((s, d) => s + findingCount(d), 0);

  root.replaceChildren(
    batchHead(`${plural(a.document_count, "document")} reviewed`, null,
      el("button", { class: "btn btn-secondary", type: "button", onclick: () => showView("upload", { focus: true }) }, "New review")),
    metrics([
      ["Released", a.documents_released.toLocaleString(), a.documents_released ? OK : null],
      ["Blocked", a.documents_blocked.toLocaleString(), a.documents_blocked ? DANGER : null],
      ["Entities found", entities.toLocaleString()],
      ["Findings", findings.toLocaleString()],
      ["Remediation rounds", String(a.remediation_rounds)],
    ]),
    el("div", { class: "docs-layout" },
      el("nav", { class: "doc-nav", "aria-label": "Documents in this batch" },
        el("p", { class: "t-overline" }, "Documents"),
        el("ul", { class: "doc-list", id: "doc-list" })),
      el("article", { id: "doc-detail", "aria-live": "polite" })));
  renderDocList();
  renderDocDetail();
}

function renderDocList() {
  const list = $("doc-list");
  if (!list) return;
  list.replaceChildren(...state.result.documents.map((d, i) =>
    el("li", {}, el("button", {
      class: "doc-row", type: "button", "aria-current": String(d.doc_id === state.selected),
      onclick: () => { state.selected = d.doc_id; renderDocList(); renderDocDetail(); },
    },
    el("span", { class: "doc-row-id" }, d.doc_id || `Document ${i + 1}`),
    el("span", { class: "dot " + (d.released ? "dot-ok" : "dot-danger"), title: d.released ? "Released" : "Blocked", style: { alignSelf: "center" } }),
    el("span", { class: "doc-row-meta" },
      `${d.released ? "Released" : "Blocked"} · ${plural(d.entities.length, "entity", "entities")} · ${plural(findingCount(d), "finding")}`)))));
}

function renderDocDetail() {
  const host = $("doc-detail");
  const doc = state.result.documents.find((d) => d.doc_id === state.selected);
  if (!host) return;
  if (!doc) { host.replaceChildren(); return; }
  const risks = new Map(doc.risks.map((r) => [r.entity_id, r]));
  const decisions = new Map(doc.decisions.map((d) => [d.entity_id, d]));
  const r = doc.release;

  host.replaceChildren(
    el("div", { class: "doc-head" },
      el("div", { style: { minWidth: 0 } },
        el("p", { class: "t-overline" }, "Document"),
        el("h2", { class: "doc-title", style: { marginTop: "4px" } }, doc.doc_id)),
      el("div", { style: { display: "flex", alignItems: "center", gap: "10px" } },
        r.remediation_rounds ? el("span", { class: "badge badge-neutral" }, plural(r.remediation_rounds, "remediation round")) : null,
        statusLabel(doc))),
    el("p", { class: `doc-reason ${doc.released ? "" : "is-danger"}` }, r.reason),
    trail(doc),
    redactedSection(doc),
    entitiesSection(doc, risks, decisions),
    findingsSection(doc));
}

// ------------------------------------------------------------------ review trail

function trail(doc) {
  const v = doc.verification;
  const n = doc.entities.length;
  const processed = n > 0 || !!v || doc.decisions.length > 0;
  const advRan = !!state.result.adversarial;
  // Only findings ABOUT this document fail its step; a finding that lists it as the linked
  // document (related_doc_ids) blocks the other document, not this one.
  const advFailed = advFor(doc.doc_id).some((f) => f.doc_id === doc.doc_id && f.severity === "blocking");
  const top = topRisk(doc);
  const actions = new Set(doc.decisions.map((d) => d.strategy)).size;
  const steps = [
    ["Detect", processed ? plural(n, "entity", "entities") : "Not run", processed ? "done" : "skip"],
    ["Assess", top ? `Highest risk: ${top}` : processed ? "No risk" : "Not run", processed ? "done" : "skip"],
    ["Redact", doc.decisions.length ? plural(actions, "action type") : processed ? "Nothing to change" : "Not run", processed ? "done" : "skip"],
    ["Verify", v ? `${v.checks_run.length} checks · ${v.passed ? "passed" : "failed"}` : "Not run", v ? (v.passed ? "done" : "fail") : "skip"],
    ["Attack", advRan ? (advFailed ? "Re-identification risk" : "No re-identification") : "Not run", advRan ? (advFailed ? "fail" : "done") : "skip"],
    [doc.released ? "Released" : "Blocked", doc.released ? "Safe to share" : "Withheld", doc.released ? "done" : "fail"],
  ];
  return el("ol", { class: "trail", "aria-label": "Review trail" }, steps.map(([label, sub, st]) =>
    el("li", { class: `is-${st}` },
      el("div", { class: "trail-head" },
        el("span", { class: "trail-mark" }, icon(st === "fail" ? "x" : st === "skip" ? "minus" : "check", 11, 3)),
        el("span", {}, label),
        el("span", { class: "sr-only" }, st === "done" ? "(passed)" : st === "fail" ? "(failed)" : "(not run)")),
      el("p", { class: "trail-sub" }, sub))));
}

// ------------------------------------------------------------------ redacted output

function redactedSection(doc) {
  const released = doc.released && doc.redacted_text !== null && doc.redacted_text !== undefined;
  const copy = released
    ? el("button", { class: "btn btn-secondary btn-sm", type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(doc.redacted_text); toast("ok", "Redacted text copied"); }
        catch { toast("error", "Couldn't copy", "The browser blocked clipboard access."); }
      } }, icon("copy", 14), "Copy")
    : null;
  return el("section", { class: "section", "aria-labelledby": "h-output" },
    el("div", { class: "section-head" },
      el("div", {}, el("h3", { class: "t-heading", id: "h-output" }, "Redacted output"),
        el("p", { class: "t-meta" }, released ? "Personal data has been replaced. This is exactly what would be shared." : "Nothing from this document is shown.")),
      copy),
    released
      ? el("div", { class: "paper" }, highlightPlaceholders(doc.redacted_text))
      : el("div", { class: "empty-panel" },
          el("p", { class: "t-subheading" }, "Text withheld"),
          el("p", { class: "t-meta" }, "Blocked documents never send their text to the browser, so there is nothing here to leak.")),
    released ? el("div", { class: "legend" },
      el("span", { class: "legend-item" }, el("span", { class: "token token-mask" }, "[TYPE]"), "Masked"),
      el("span", { class: "legend-item" }, el("span", { class: "token token-pseudo" }, "PERSON_01"), "Pseudonym, consistent across the batch"),
      el("span", { class: "legend-item" }, el("span", { class: "token token-suppress" }, "[REDACTED]"), "Removed"),
      el("span", { class: "legend-item" }, "Generalised values, such as an age band, appear as plain text")) : null);
}

function highlightPlaceholders(text) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(PLACEHOLDER)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const token = m[0];
    const kind = token === "[REDACTED]" ? "token-suppress" : token.startsWith("[") ? "token-mask" : "token-pseudo";
    out.push(el("mark", { class: `token ${kind}` }, token));
    last = m.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// ------------------------------------------------------------------ entities

function entitiesSection(doc, risks, decisions) {
  const head = el("div", { class: "section-head" },
    el("div", {}, el("h3", { class: "t-heading", id: "h-entities" }, "Entities"),
      el("p", { class: "t-meta" }, doc.entities.length
        ? `${plural(doc.entities.length, "item")} of personal data, with the action taken on each and why.`
        : "No personal data was reported for this document.")));
  if (!doc.entities.length) return el("section", { class: "section", "aria-labelledby": "h-entities" }, head);

  const riskParts = RISK_ORDER.map((r) => ({ label: r, value: doc.risks.filter((x) => x.risk === r).length, color: RISK_COLOR[r] }));
  head.append(el("div", { style: { display: "grid", gap: "6px", justifyItems: "end" } },
    distBar(riskParts),
    el("div", { class: "legend", style: { marginTop: 0 } }, riskParts.filter((p) => p.value).map((p) =>
      el("span", { class: "legend-item" }, el("span", { class: "swatch", style: { background: p.color } }), `${p.label} ${p.value}`)))));

  const byType = {};
  for (const e of doc.entities) byType[e.entity_type] = (byType[e.entity_type] || 0) + 1;
  const summary = el("div", { class: "type-summary" }, Object.entries(byType).sort((x, y) => y[1] - x[1]).map(([t, n]) =>
    el("span", { class: "badge badge-neutral" }, humanType(t), el("span", { class: "num", style: { color: "var(--text-3)" } }, String(n)))));

  const rows = doc.entities.map((e) => {
    const risk = risks.get(e.entity_id);
    const dec = decisions.get(e.entity_id);
    return el("tr", {},
      el("td", { class: "t-mono", style: { color: "var(--text-3)", whiteSpace: "nowrap" } }, e.entity_id),
      el("td", {}, humanType(e.entity_type), el("span", { class: "sub" }, pretty(e.identifier_class))),
      el("td", { style: { whiteSpace: "nowrap" } }, riskTag(risk?.risk),
        risk && risk.base_risk !== risk.risk ? el("span", { class: "sub" }, `raised from ${risk.base_risk}`) : null),
      el("td", { style: { whiteSpace: "nowrap" } }, dec ? STRATEGY_LABEL[dec.strategy] || dec.strategy : "—",
        dec?.scope === "batch" ? el("span", { class: "sub" }, "same across batch") : null),
      el("td", { class: "t-mono", style: { color: "var(--text-3)", whiteSpace: "nowrap" } }, dec?.policy_id || "—"),
      el("td", { class: "reason" }, risk?.rationale || "",
        risk?.fired_rules?.length ? el("span", { class: "sub" }, `Rules: ${risk.fired_rules.join(", ")}`) : null));
  });

  return el("section", { class: "section", "aria-labelledby": "h-entities" }, head, summary,
    el("div", { class: "table-wrap" }, el("table", { class: "table" },
      el("caption", { class: "sr-only" }, "Entities, risk and action taken"),
      el("thead", {}, el("tr", {}, ["Entity", "Type", "Risk", "Action", "Policy", "Reason"].map((h) => el("th", { scope: "col" }, h)))),
      el("tbody", {}, rows))));
}

// ------------------------------------------------------------------ findings

function findingsSection(doc) {
  const v = doc.verification;
  const all = [...(v ? v.findings : []).map((f) => ({ f, src: "Verification" })),
               ...advFor(doc.doc_id).map((f) => ({ f, src: "Adversarial check" }))];
  const pct = v ? Math.round(v.utility_retained * 100) : null;
  const line = v
    ? el("div", { class: "verify-line" },
        el("span", { class: `badge ${v.passed ? "badge-ok" : "badge-danger"}` }, icon(v.passed ? "check" : "x", 12, 2.6), v.passed ? "Verification passed" : "Verification failed"),
        el("span", {}, `${plural(v.checks_run.length, "check")} · revision ${v.revision}`),
        el("span", { class: "meter", title: "Share of non-personal text kept" }, "Utility retained",
          el("span", { class: "meter-track" }, el("span", { style: { width: `${pct}%` } })),
          el("span", { class: "num", style: { color: "var(--text)", fontWeight: 500 } }, `${pct}%`)))
    : el("p", { class: "t-meta", style: { marginBottom: "14px" } }, "No verification report. The document was not processed.");

  const sev = { blocking: ["badge-solid-danger", "Blocking"], warning: ["badge-warn", "Warning"], info: ["badge-neutral", "Info"] };
  const list = all.length
    ? el("ul", { class: "findings" }, all.map(({ f, src }) => {
        const related = (f.related_doc_ids || []).concat(f.doc_id !== doc.doc_id ? [f.doc_id] : []).filter((d) => d !== doc.doc_id);
        const [cls, label] = sev[f.severity] || sev.info;
        return el("li", { class: "finding" },
          el("div", {}, el("span", { class: `badge ${cls}` }, label)),
          el("div", {},
            el("p", { class: "finding-title" }, pretty(f.finding_type)),
            el("p", { class: "finding-desc" }, f.description),
            el("div", { class: "finding-meta" },
              el("span", { class: "t-meta" }, src),
              f.entity_type ? el("span", { class: "badge badge-neutral" }, humanType(f.entity_type)) : null,
              f.recommended_strategy ? el("span", { class: "badge badge-accent" }, `Suggested: ${STRATEGY_LABEL[f.recommended_strategy] || f.recommended_strategy}`) : null,
              f.rule_id ? el("span", { class: "badge badge-neutral t-mono" }, f.rule_id) : null,
              related.length ? el("span", { class: "badge badge-danger" }, `Linked to ${related.join(", ")}`) : null)));
      }))
    : el("div", { class: "empty-panel", style: { padding: "18px", textAlign: "left" } },
        el("p", { class: "t-subheading" }, "No findings"),
        el("p", { class: "t-meta" }, v ? "Nothing was left to fix." : "Findings appear once the document has been processed."));

  return el("section", { class: "section", "aria-labelledby": "h-findings" },
    el("div", { class: "section-head" }, el("div", {},
      el("h3", { class: "t-heading", id: "h-findings" }, "Findings"),
      el("p", { class: "t-meta" }, "Issues raised by independent verification and the adversarial check."))),
    line, list);
}

// ================================================================== insights view

function renderInsights() {
  const root = $("insights-root");
  if (!state.result) {
    root.replaceChildren(emptyState("chart", "No insights yet",
      "Insights summarise a whole batch: how much personal data was found, how risky it was and what was done about it."));
    return;
  }
  const { result } = state;
  const a = result.aggregate;
  const entities = Object.values(a.entities_by_type || {}).reduce((s, n) => s + n, 0);
  const chart = (id, title, desc, cls = "") => el("section", { class: `chart ${cls}` },
    el("div", { class: "chart-head" }, el("h3", { class: "t-subheading" }, title), el("p", { class: "t-meta" }, desc)),
    el("div", { class: `chart-plot ${cls === "tall" ? "tall" : ""}`, id }));

  root.replaceChildren(
    batchHead("Batch overview", "Counts only. No value from any document appears on this page."),
    metrics([
      ["Documents", a.document_count.toLocaleString()],
      ["Released", a.documents_released.toLocaleString(), a.documents_released ? OK : null],
      ["Blocked", a.documents_blocked.toLocaleString(), a.documents_blocked ? DANGER : null],
      ["Entities found", entities.toLocaleString()],
      ["Remediation rounds", String(a.remediation_rounds)],
      ["LLM used", a.llm_used ? "Yes" : "No"],
    ]),
    el("div", { class: "chart-grid" },
      chart("chart-release", "Release outcome", "Documents released or blocked."),
      chart("chart-risks", "Risk levels", "Risk after context rules were applied."),
      chart("chart-entities", "Entities by type", "What kind of personal data was found.", "tall"),
      chart("chart-strategies", "Actions taken", "Darker bars remove more information.", "tall"),
      chart("chart-findings", "Findings", "Raised by verification and the adversarial check.", "wide")),
    linkageSection(result.adversarial));
  requestAnimationFrame(() => drawCharts(a));
}

function drawCharts(a) {
  const ids = ["chart-release", "chart-risks", "chart-entities", "chart-strategies", "chart-findings"];
  if (typeof Plotly === "undefined") {
    for (const id of ids) $(id).replaceChildren(el("div", { class: "chart-empty" }, "Charts couldn't load (the Plotly CDN is unreachable)."));
    return;
  }
  bar("chart-release", ["Released", "Blocked"], [a.documents_released, a.documents_blocked], [OK, DANGER]);
  const risks = ordered(a.risks_by_level, RISK_ORDER);
  bar("chart-risks", risks.keys.map((k) => k[0].toUpperCase() + k.slice(1)), risks.values, risks.keys.map((k) => RISK_COLOR[k] || VIZ[2]));
  const ents = sortedDesc(a.entities_by_type);
  bar("chart-entities", ents.keys.map(humanType), ents.values, VIZ[4], true);
  const strat = ordered(a.strategies, STRATEGY_ORDER);
  bar("chart-strategies", strat.keys.map((k) => STRATEGY_LABEL[k] || k), strat.values, strat.keys.map((k) => STRATEGY_COLOR[k] || VIZ[2]));
  const finds = sortedDesc(a.findings_by_type);
  bar("chart-findings", finds.keys.map((k) => humanType(k)), finds.values, VIZ[3], true);
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
    node.replaceChildren(el("div", { class: "chart-empty" }, "No data in this batch"));
    return;
  }
  node.replaceChildren();
  const colors = Array.isArray(color) ? (horizontal ? [...color].reverse() : color) : color;
  const trace = horizontal
    ? { type: "bar", orientation: "h", y: [...keys].reverse(), x: [...values].reverse() }
    : { type: "bar", x: keys, y: values };
  trace.marker = { color: colors, cornerradius: 3 };
  trace.hovertemplate = horizontal ? "%{y}: %{x}<extra></extra>" : "%{x}: %{y}<extra></extra>";
  trace.width = horizontal ? undefined : Math.min(0.55, 0.18 * keys.length + 0.2);
  const axis = { gridcolor: "#ECECE8", zeroline: false, automargin: true, linecolor: "#D2D2CB", tickfont: { color: "#686D78", size: 11.5 } };
  Plotly.react(node, [trace], {
    margin: { t: 8, r: 8, b: horizontal ? 28 : 36, l: horizontal ? 130 : 32 },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Inter, ui-sans-serif, system-ui, sans-serif", size: 12, color: "#444955" },
    xaxis: { ...axis, showgrid: horizontal, showline: !horizontal, ...(horizontal ? { dtick: 1 } : {}) },
    yaxis: { ...axis, showgrid: !horizontal, showline: horizontal, ...(horizontal ? {} : { dtick: 1 }) },
    bargap: 0.45,
    hoverlabel: { bgcolor: "#FFFFFF", bordercolor: "#D2D2CB", font: { color: "#15171C", family: "Inter", size: 12 } },
  }, { displayModeBar: false, responsive: true });
}

function linkageSection(adv) {
  const head = el("div", { class: "section-head" },
    el("div", {}, el("h3", { class: "t-heading", id: "h-linkage" }, "Cross-document linkage"),
      el("p", { class: "t-meta" }, "Groups of documents that can be joined, and k: how many people share the combined clues. k = 1 means one person can be singled out.")),
    adv ? el("span", { class: `badge ${adv.safe_to_release ? "badge-ok" : "badge-danger"}` },
      adv.safe_to_release ? "Safe to release" : "Not safe to release") : null);
  const wrap = (body) => el("section", { class: "section", "aria-labelledby": "h-linkage", style: { marginTop: "56px" } }, head, body);
  if (!adv || !adv.components.length) {
    return wrap(el("div", { class: "empty-panel", style: { padding: "18px", textAlign: "left" } },
      el("p", { class: "t-subheading" }, adv ? "No linked documents" : "No adversarial report"),
      el("p", { class: "t-meta" }, adv ? "No group of documents could be joined to single someone out." : "The adversarial check did not run for this batch.")));
  }
  const rows = adv.components.map((c) => {
    const unique = c.anonymity_set_size <= 1;
    return el("tr", {},
      el("td", { class: "t-mono", style: { color: "var(--text-3)" } }, c.component_id),
      el("td", {}, el("div", { style: { display: "flex", flexWrap: "wrap", gap: "4px" } }, c.doc_ids.map((d) => el("span", { class: "badge badge-neutral t-mono" }, d)))),
      el("td", {}, c.linked_by.map(humanType).join(", ")),
      el("td", {}, c.visible_quasi_types.length ? c.visible_quasi_types.map(humanType).join(", ") : "—"),
      el("td", { class: "num", style: { whiteSpace: "nowrap", fontWeight: 600, color: unique ? DANGER : "var(--text)" } },
        String(c.anonymity_set_size), el("span", { class: "sub", style: { fontWeight: 400 } }, unique ? "identifiable" : "in a crowd")),
      el("td", {}, riskTag(c.risk)));
  });
  return wrap(el("div", { class: "table-wrap" }, el("table", { class: "table" },
    el("caption", { class: "sr-only" }, "Linked document groups"),
    el("thead", {}, el("tr", {}, ["Group", "Documents", "Linked by", "Visible clues", "k", "Risk"].map((h) => el("th", { scope: "col" }, h)))),
    el("tbody", {}, rows))));
}

// ================================================================== start

setMode("files");
renderFiles();
onPaste();
checkHealth();
