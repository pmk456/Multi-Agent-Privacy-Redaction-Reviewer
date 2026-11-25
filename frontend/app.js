// PS 247 frontend. No build step, no framework.
//
// Safety rules for this file:
//  - Everything from the API is rendered with textContent / createElement, never innerHTML.
//  - Entity spans refer to the ORIGINAL text, not the redacted one, so they are never shown
//    or used to index into redacted_text.
//  - The API never sends filenames back. Errors come with a file_index; the local filename
//    shown next to it is read from the browser's own file picker and goes nowhere.
"use strict";

const API = location.protocol === "file:" ? "http://127.0.0.1:8000" : "";

const COLORS = { navy: "#192339", steel: "#1E3A6B", cyan: "#27B2CC", maroon: "#781B17" };
const RISK_ORDER = ["low", "medium", "high", "critical"];
const STRATEGY_ORDER = ["keep", "generalize", "pseudonymize", "mask", "suppress"];
const RISK_STYLE = {
  low:      { cls: "bg-cyan/15 text-[#0B5566] border-cyan/40",      bar: COLORS.cyan },
  medium:   { cls: "bg-steel/10 text-steel border-steel/30",         bar: COLORS.steel },
  high:     { cls: "bg-maroon/10 text-maroon border-maroon/30",      bar: "#B0524D" },
  critical: { cls: "bg-maroon text-white border-maroon",             bar: COLORS.maroon },
  unknown:  { cls: "bg-slate-100 text-slate-600 border-slate-300",   bar: "#94A3B8" },
};
const SEVERITY_STYLE = {
  info: "bg-steel/10 text-steel",
  warning: "bg-amber-100 text-amber-800",
  blocking: "bg-maroon text-white",
};
// [EMAIL_ADDRESS], [REDACTED], PERSON_01, PERSON_7F3A
const PLACEHOLDER = /\[[A-Z][A-Z_]*\]|\b[A-Z]{2,}(?:_[A-Z]+)*_[0-9A-F]{2,}\b/g;

const state = { result: null, selected: null, fileNames: [] };
const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ DOM helper

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const badge = (text, cls) =>
  el("span", { class: `inline-block text-xs font-semibold px-2 py-0.5 rounded border ${cls}` }, text);

const card = (title, ...children) =>
  el("section", { class: "bg-white rounded-lg border border-slate-200 p-5" },
    title ? el("h3", { class: "font-bold mb-3" }, title) : null, ...children);

const pretty = (s) => String(s).replace(/_/g, " ").toLowerCase();

// ------------------------------------------------------------------ navigation

function showView(name) {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.setAttribute("aria-selected", String(tab.dataset.view === name));
  }
  for (const v of ["upload", "documents", "aggregate"]) {
    $(`view-${v}`).classList.toggle("hidden", v !== name);
  }
  if (name === "aggregate" && state.result) renderAggregate(state.result);
}

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => showView(tab.dataset.view));
}

// ------------------------------------------------------------------ health

async function checkHealth() {
  const out = $("health");
  try {
    const r = await fetch(`${API}/health`);
    if (!r.ok) throw new Error(String(r.status));
    const h = await r.json();
    out.textContent = "";
    out.append(
      "Backend online · pipeline: ",
      el("span", { class: h.pipeline === "live" ? "text-cyan font-semibold" : "text-amber-300 font-semibold" },
        h.pipeline === "live" ? "live" : "stub (documents are withheld)"),
      ` · LLM: ${h.llm ? "on" : "off"}`,
    );
  } catch {
    out.textContent = location.protocol === "file:"
      ? "Opened from disk. Start the backend and open http://127.0.0.1:8000/ui/ instead."
      : "Backend unreachable. Demo mode still works.";
  }
}

// ------------------------------------------------------------------ upload view

$("files").addEventListener("change", () => {
  const files = Array.from($("files").files);
  state.fileNames = files.map((f) => f.name);
  const list = $("file-list");
  list.replaceChildren(...files.map((f) =>
    el("li", {}, f.name, el("span", { class: "text-slate-400" }, ` · ${formatBytes(f.size)}`))));
  $("btn-upload").disabled = files.length === 0;
});

$("paste").addEventListener("input", () => {
  $("btn-paste").disabled = $("paste").value.trim() === "";
});

$("btn-upload").addEventListener("click", () => {
  const body = new FormData();
  for (const f of $("files").files) body.append("files", f);
  submit(`${API}/upload`, { method: "POST", body }, "file");
});

$("btn-paste").addEventListener("click", () => {
  const payload = { documents: [{ text: $("paste").value }] };
  submit(`${API}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }, "document");
});

$("btn-demo").addEventListener("click", async () => {
  hideErrors();
  try {
    const r = await fetch("mock/batch_result.json");
    if (!r.ok) throw new Error(String(r.status));
    loadResult(await r.json(), true);
  } catch {
    showErrors("Could not load the demo batch.",
      [location.protocol === "file:" ? "Open the page through the backend (http://127.0.0.1:8000/ui/)." :
        "mock/batch_result.json is missing."]);
  }
});

async function submit(url, init, kind) {
  hideErrors();
  setBusy(true);
  try {
    const r = await fetch(url, init);
    const body = await r.json().catch(() => ({}));
    if (r.ok) {
      loadResult(body, false);
      return;
    }
    renderApiError(r.status, body, kind);
  } catch {
    showErrors("Could not reach the backend.", ["Check that uvicorn is running, or try demo mode."]);
  } finally {
    setBusy(false);
  }
}

function renderApiError(status, body, kind) {
  const errors = Array.isArray(body.errors) ? body.errors : [];
  const lines = errors.map((e) => {
    if (typeof e.file_index === "number") {
      const local = state.fileNames[e.file_index];
      return [`File ${e.file_index + 1}`, local ? ` (${local})` : "", ` · ${e.code}: ${e.message}`].join("");
    }
    if (typeof e.document_index === "number") {
      return `Document ${e.document_index + 1} · ${e.code}: ${e.message}`;
    }
    if (Array.isArray(e.loc)) return `${e.loc.join(".")} · ${e.msg}`;
    return `${e.code || "error"}: ${e.message || ""}`;
  });
  const title = body.detail ? `${body.detail} (${body.code || status})` : `Request failed (${status})`;
  showErrors(title, lines.length ? lines : [kind === "file" ? "No file was processed." : "Nothing was processed."]);
}

function showErrors(title, lines) {
  $("error-title").textContent = title;
  $("error-list").replaceChildren(...lines.map((l) => el("li", {}, l)));
  $("error-panel").classList.remove("hidden");
}

function hideErrors() { $("error-panel").classList.add("hidden"); }

function setBusy(on) {
  $("busy").classList.toggle("hidden", !on);
  for (const id of ["btn-upload", "btn-paste", "btn-demo"]) {
    if (on) $(id).disabled = true;
  }
  if (!on) {
    $("btn-demo").disabled = false;
    $("btn-upload").disabled = $("files").files.length === 0;
    $("btn-paste").disabled = $("paste").value.trim() === "";
  }
}

// ------------------------------------------------------------------ results

function loadResult(result, demo) {
  state.result = result;
  state.selected = result.documents.length ? result.documents[0].doc_id : null;
  for (const tab of document.querySelectorAll(".tab")) tab.disabled = false;
  $("batch-label").textContent =
    `${demo ? "Demo batch (fictional data)" : "Batch"} ${result.batch_id} · ${result.documents.length} document(s)`;
  renderDocList();
  renderDocDetail();
  showView("documents");
}

function renderDocList() {
  const { result, selected } = state;
  $("doc-list").replaceChildren(...result.documents.map((d, i) =>
    el("li", {},
      el("button", {
        class: `w-full text-left px-3 py-2 rounded border text-sm flex items-center justify-between gap-2 ${
          d.doc_id === selected ? "bg-white border-cyan shadow-sm" : "border-transparent hover:bg-white"}`,
        onclick: () => { state.selected = d.doc_id; renderDocList(); renderDocDetail(); },
      },
      el("span", { class: "truncate font-mono text-xs" }, d.doc_id || `document ${i + 1}`),
      statusBadge(d)))));
}

function statusBadge(doc) {
  return doc.released
    ? badge("released", "bg-cyan/15 text-[#0B5566] border-cyan/40")
    : badge("blocked", "bg-maroon text-white border-maroon");
}

function renderDocDetail() {
  const doc = state.result.documents.find((d) => d.doc_id === state.selected);
  const host = $("doc-detail");
  if (!doc) { host.replaceChildren(); return; }

  const risks = new Map(doc.risks.map((r) => [r.entity_id, r]));
  const decisions = new Map(doc.decisions.map((d) => [d.entity_id, d]));
  const adversarial = adversarialFor(doc.doc_id);

  host.replaceChildren(
    releaseCard(doc),
    redactedCard(doc),
    entitiesCard(doc, risks, decisions),
    strategyCard(doc, risks, decisions),
    findingsCard(doc, adversarial),
  );
}

function releaseCard(doc) {
  const r = doc.release;
  return card(null,
    el("div", { class: "flex flex-wrap items-center gap-3" },
      el("h2", { class: "font-mono text-sm font-semibold" }, doc.doc_id),
      statusBadge(doc),
      r.remediation_rounds ? el("span", { class: "text-xs text-slate-500" },
        `${r.remediation_rounds} remediation round(s)`) : null),
    el("p", { class: `mt-2 text-sm ${doc.released ? "text-slate-700" : "text-maroon"}` }, r.reason));
}

function redactedCard(doc) {
  if (!doc.released || doc.redacted_text === null || doc.redacted_text === undefined) {
    return card("Redacted text",
      el("p", { class: "text-sm text-slate-500 italic" },
        "Withheld. A blocked document's text is never sent to the browser."));
  }
  return card("Redacted text",
    el("div", { class: "redacted font-mono text-sm leading-relaxed bg-slate-50 rounded p-4 border border-slate-100" },
      highlightPlaceholders(doc.redacted_text)),
    el("p", { class: "mt-2 text-xs text-slate-500" },
      "Highlighted: placeholders and pseudonyms. Generalised values (for example an age band) " +
      "are not highlighted, because entity positions refer to the original text."));
}

function highlightPlaceholders(text) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(PLACEHOLDER)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(el("mark", { class: "ph" }, m[0]));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function entitiesCard(doc, risks, decisions) {
  if (!doc.entities.length) return card("Entities", el("p", { class: "text-sm text-slate-500" }, "No entities reported."));
  const byType = new Map();
  for (const e of doc.entities) {
    if (!byType.has(e.entity_type)) byType.set(e.entity_type, []);
    byType.get(e.entity_type).push(e);
  }
  const groups = [...byType.entries()].sort((a, b) => b[1].length - a[1].length).map(([type, ents]) =>
    el("div", { class: "flex flex-wrap items-center gap-2" },
      el("span", { class: "text-xs font-semibold text-slate-500 w-40 shrink-0" }, `${type} (${ents.length})`),
      ...ents.map((e) => {
        const risk = risks.get(e.entity_id)?.risk || "unknown";
        const strategy = decisions.get(e.entity_id)?.strategy || "—";
        const style = (RISK_STYLE[risk] || RISK_STYLE.unknown).cls;
        return el("span", {
          class: `text-xs px-2 py-1 rounded-full border ${style}`,
          title: `${e.entity_id} · risk ${risk} · confidence ${Math.round(e.confidence * 100)}%`,
        }, `${risk} · ${strategy}`);
      })));
  const legend = el("div", { class: "flex flex-wrap gap-2 mt-4 text-xs text-slate-500 items-center" },
    "Risk:", ...RISK_ORDER.map((r) => badge(r, RISK_STYLE[r].cls)));
  return card("Entities by type", el("div", { class: "space-y-2" }, groups), legend);
}

function strategyCard(doc, risks, decisions) {
  if (!doc.entities.length) return null;
  const rows = doc.entities.map((e) => {
    const risk = risks.get(e.entity_id);
    const dec = decisions.get(e.entity_id);
    const level = risk?.risk || "unknown";
    return el("tr", { class: "border-t border-slate-100 align-top" },
      el("td", { class: "py-2 pr-3 font-mono text-xs text-slate-500" }, e.entity_id),
      el("td", { class: "py-2 pr-3" }, e.entity_type,
        el("div", { class: "text-xs text-slate-400" }, pretty(e.identifier_class))),
      el("td", { class: "py-2 pr-3" }, badge(level, (RISK_STYLE[level] || RISK_STYLE.unknown).cls),
        risk && risk.base_risk !== risk.risk ? el("div", { class: "text-xs text-slate-400" }, `from ${risk.base_risk}`) : null),
      el("td", { class: "py-2 pr-3 font-semibold" }, dec ? dec.strategy : "—",
        dec?.scope === "batch" ? el("div", { class: "text-xs text-slate-400 font-normal" }, "batch-consistent") : null),
      el("td", { class: "py-2 pr-3 text-xs text-slate-600" }, dec?.policy_id || ""),
      el("td", { class: "py-2 text-xs text-slate-600" }, risk?.rationale || "",
        risk?.fired_rules?.length ? el("div", { class: "text-slate-400" }, `rules: ${risk.fired_rules.join(", ")}`) : null));
  });
  return card("Strategy per entity",
    el("div", { class: "overflow-x-auto" },
      el("table", { class: "w-full text-sm" },
        el("thead", {}, el("tr", { class: "text-left text-xs text-slate-500" },
          ...["Entity", "Type", "Risk", "Strategy", "Policy", "Why"].map((h) => el("th", { class: "pb-2 pr-3 font-semibold" }, h)))),
        el("tbody", {}, rows))));
}

function adversarialFor(docId) {
  const adv = state.result.adversarial;
  if (!adv) return [];
  return adv.findings.filter((f) => f.doc_id === docId || (f.related_doc_ids || []).includes(docId));
}

function findingsCard(doc, adversarial) {
  const v = doc.verification;
  const summary = v
    ? el("p", { class: "text-sm text-slate-600 mb-3" },
        badge(v.passed ? "passed" : "failed", v.passed ? "bg-cyan/15 text-[#0B5566] border-cyan/40" : "bg-maroon text-white border-maroon"),
        ` revision ${v.revision} · utility retained ${Math.round(v.utility_retained * 100)}% · ${v.checks_run.length} checks run`)
    : el("p", { class: "text-sm text-slate-500 mb-3" }, "No verification report (document was not processed).");
  const all = [...(v ? v.findings : []).map((f) => ({ f, src: "verification" })),
               ...adversarial.map((f) => ({ f, src: "adversarial" }))];
  const list = all.length
    ? el("ul", { class: "space-y-3" }, all.map(({ f, src }) => findingItem(f, src, doc.doc_id)))
    : el("p", { class: "text-sm text-slate-500" }, "No findings.");
  return card("Verification findings", summary, list);
}

function findingItem(f, src, docId) {
  const related = (f.related_doc_ids || []).concat(f.doc_id !== docId ? [f.doc_id] : []).filter((d) => d !== docId);
  const meta = [
    src,
    f.entity_type ? `entity type ${f.entity_type}` : null,
    f.recommended_strategy ? `recommended: ${f.recommended_strategy}` : null,
    f.rule_id ? `rule ${f.rule_id}` : null,
    related.length ? `linked to ${related.join(", ")}` : null,
  ].filter(Boolean).join(" · ");
  return el("li", { class: "flex gap-3" },
    el("span", { class: `shrink-0 h-fit text-xs font-semibold px-2 py-0.5 rounded ${SEVERITY_STYLE[f.severity] || ""}` }, f.severity),
    el("div", {},
      el("div", { class: "text-sm font-semibold" }, pretty(f.finding_type)),
      el("div", { class: "text-sm text-slate-700" }, f.description),
      el("div", { class: "text-xs text-slate-400 mt-0.5" }, meta)));
}

// ------------------------------------------------------------------ aggregate view

function renderAggregate(result) {
  const a = result.aggregate;
  const tile = (label, value, accent) =>
    el("div", { class: "bg-white rounded-lg border border-slate-200 p-4" },
      el("div", { class: "text-xs text-slate-500" }, label),
      el("div", { class: `text-2xl font-bold ${accent || "text-navy"}` }, String(value)));
  $("stat-tiles").replaceChildren(
    tile("Documents", a.document_count),
    tile("Released", a.documents_released, "text-[#0B5566]"),
    tile("Blocked", a.documents_blocked, a.documents_blocked ? "text-maroon" : "text-navy"),
    tile("Remediation rounds", a.remediation_rounds),
    tile("LLM used", a.llm_used ? "yes" : "no"));

  if (typeof Plotly === "undefined") {
    for (const id of ["chart-release", "chart-risks", "chart-entities", "chart-strategies", "chart-findings"]) {
      $(id).textContent = "Charts need the Plotly CDN, which did not load.";
    }
  } else {
    bar("chart-release", ["released", "blocked"], [a.documents_released, a.documents_blocked],
      [COLORS.cyan, COLORS.maroon]);
    const risks = ordered(a.risks_by_level, RISK_ORDER);
    bar("chart-risks", risks.keys, risks.values, risks.keys.map((k) => (RISK_STYLE[k] || RISK_STYLE.unknown).bar));
    const ents = sortedDesc(a.entities_by_type);
    bar("chart-entities", ents.keys, ents.values, COLORS.steel, true);
    const strat = ordered(a.strategies, STRATEGY_ORDER);
    bar("chart-strategies", strat.keys, strat.values, COLORS.navy);
    const finds = sortedDesc(a.findings_by_type);
    bar("chart-findings", finds.keys.map(pretty), finds.values, COLORS.steel, true);
  }
  renderLinkage(result.adversarial);
}

function ordered(obj, order) {
  const keys = [...order.filter((k) => k in (obj || {})), ...Object.keys(obj || {}).filter((k) => !order.includes(k))];
  return { keys, values: keys.map((k) => obj[k]) };
}

function sortedDesc(obj) {
  const entries = Object.entries(obj || {}).sort((a, b) => b[1] - a[1]);
  return { keys: entries.map((e) => e[0]), values: entries.map((e) => e[1]) };
}

function bar(id, keys, values, color, horizontal = false) {
  const node = $(id);
  if (!keys.length || values.every((v) => !v)) {
    Plotly.purge(node);
    node.replaceChildren(el("p", { class: "text-sm text-slate-400 pt-8 text-center" }, "No data in this batch."));
    return;
  }
  node.replaceChildren();
  const trace = horizontal
    ? { type: "bar", orientation: "h", y: [...keys].reverse(), x: [...values].reverse(),
        marker: { color: Array.isArray(color) ? [...color].reverse() : color } }
    : { type: "bar", x: keys, y: values, marker: { color } };
  const hovertemplate = horizontal ? "%{y}: %{x}<extra></extra>" : "%{x}: %{y}<extra></extra>";
  Plotly.react(node, [{ ...trace, hovertemplate }], {
    margin: { t: 8, r: 8, b: horizontal ? 32 : 48, l: horizontal ? 150 : 40 },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "ui-sans-serif, system-ui, sans-serif", size: 12, color: "#334155" },
    xaxis: { gridcolor: "#E2E8F0", zeroline: false, automargin: true, ...(horizontal ? { dtick: 1 } : {}) },
    yaxis: { gridcolor: "#E2E8F0", zeroline: false, automargin: true, ...(horizontal ? {} : { dtick: 1 }) },
    bargap: 0.35,
  }, { displayModeBar: false, responsive: true });
}

function renderLinkage(adv) {
  const host = $("linkage");
  if (!adv || !adv.components.length) {
    host.replaceChildren(el("h3", { class: "font-semibold text-sm mb-1" }, "Cross-document linkage"),
      el("p", { class: "text-sm text-slate-500" }, adv ? "No linked document groups found." : "No adversarial report in this batch."));
    return;
  }
  host.replaceChildren(
    el("h3", { class: "font-semibold text-sm mb-1" }, "Cross-document linkage"),
    el("p", { class: "text-xs text-slate-500 mb-3" },
      `Adversarial revision ${adv.revision} · ${adv.safe_to_release ? "safe to release" : "not safe to release"}. ` +
      "k is how many people share the fingerprint; k = 1 means one person is identifiable."),
    el("div", { class: "overflow-x-auto" }, el("table", { class: "w-full text-sm" },
      el("thead", {}, el("tr", { class: "text-left text-xs text-slate-500" },
        ...["Group", "Documents", "Linked by", "Visible quasi-identifiers", "k", "Risk"].map((h) =>
          el("th", { class: "pb-2 pr-3 font-semibold" }, h)))),
      el("tbody", {}, adv.components.map((c) => el("tr", { class: "border-t border-slate-100" },
        el("td", { class: "py-2 pr-3 font-mono text-xs" }, c.component_id),
        el("td", { class: "py-2 pr-3 font-mono text-xs" }, c.doc_ids.join(", ")),
        el("td", { class: "py-2 pr-3" }, c.linked_by.join(", ")),
        el("td", { class: "py-2 pr-3" }, c.visible_quasi_types.join(", ")),
        el("td", { class: `py-2 pr-3 font-semibold ${c.anonymity_set_size <= 1 ? "text-maroon" : ""}` }, c.anonymity_set_size),
        el("td", { class: "py-2" }, badge(c.risk, (RISK_STYLE[c.risk] || RISK_STYLE.unknown).cls))))))));
}

// ------------------------------------------------------------------ misc

function formatBytes(n) {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

checkHealth();
