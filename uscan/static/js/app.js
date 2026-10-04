"use strict";
/* uscan front-end. No inline handlers or styles: every interaction goes through data-* attributes and the
   delegated listeners at the bottom, which keeps the page compatible with a strict Content-Security-Policy. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const U = encodeURIComponent;
const app = $("#app");
const S = { cfg: {}, view: "dash", tok: 0, docs: [], sel: new Set(), q: "", status: "", rev: null, comp: null, job: null, progHtml: "", timer: null };

/* ------------------------------------------------------------------ icons */
const ICONS = {
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
  edit: '<path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>',
  rotL: '<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>',
  rotR: '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>',
  refresh: '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
  up: '<line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>',
  down: '<line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/>',
  left: '<polyline points="15 18 9 12 15 6"/>',
  right: '<polyline points="9 18 15 12 9 6"/>',
  chev: '<polyline points="6 9 12 15 18 9"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  alert: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
  zoom: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  lock: '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
};
const ic = n => `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICONS[n] || ""}</svg>`;

/* ------------------------------------------------------------------ helpers */
async function api(url, opt = {}) {
  let r;
  try { r = await fetch(url, { credentials: "same-origin", ...opt }); }
  catch { throw new Error("Can't reach uscan. Check that it is still running, then try again."); }
  if (r.status === 401) { onUnauthorized(); throw new Error("Please sign in to continue."); }
  if (!r.ok) {
    let m = `Something went wrong (error ${r.status}).`;
    try { const j = await r.json(); if (typeof j.detail === "string") m = j.detail; else if (Array.isArray(j.detail)) m = "Some of the values entered are not valid."; } catch { /* keep default */ }
    throw new Error(m);
  }
  return r.json();
}
const jput = (u, b, m = "PUT") => api(u, { method: m, headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });
const post = u => api(u, { method: "POST" });

function toast(msg, o = {}) {
  const t = document.createElement("div");
  t.className = "toast" + (o.err ? " err" : "");
  if (o.err) t.setAttribute("role", "alert");
  const s = document.createElement("span"); s.textContent = msg; t.append(s);
  if (o.action) { const b = document.createElement("button"); b.type = "button"; b.textContent = o.action.label; b.onclick = () => { t.remove(); o.action.fn(); }; t.append(b); }
  $("#toasts").append(t);
  setTimeout(() => t.remove(), o.action ? 9000 : 5000);
}

/* Styled replacement for confirm()/prompt(). Resolves true/false, or the entered text / null when `input` is given. */
function ask({ title, text = "", confirm = "OK", danger = false, input = null }) {
  return new Promise(res => {
    const d = $("#dlg");
    d.innerHTML = `<form><h2 id="dlg-title">${esc(title)}</h2>${text ? `<p>${esc(text)}</p>` : ""}
      ${input ? `<label class="field"><span class="hint">${esc(input.label)}</span><input type="text" id="dlg-in" maxlength="200" autocomplete="off" value="${esc(input.value || "")}"></label>` : ""}
      <div class="row"><button type="button" class="btn" id="dlg-no">Cancel</button><button type="submit" class="btn ${danger ? "danger solid" : "pri"}">${esc(confirm)}</button></div></form>`;
    let done = false;
    const finish = v => { if (done) return; done = true; d.close(); res(v); };
    $("form", d).onsubmit = e => { e.preventDefault(); finish(input ? $("#dlg-in").value : true); };
    $("#dlg-no").onclick = () => finish(input ? null : false);
    d.oncancel = () => { done = true; res(input ? null : false); };  // Esc
    d.showModal();
    if (input) { $("#dlg-in").focus(); $("#dlg-in").select(); } else (danger ? $("#dlg-no") : $("[type=submit]", d)).focus();
  });
}

const applyWidths = (root = document) => $$("[data-w]", root).forEach(e => { e.style.width = Math.max(0, Math.min(100, +e.dataset.w || 0)) + "%"; });
const render = html => { app.innerHTML = html; applyWidths(app); };
const bar = (pct, label) => `<div class="bar" role="progressbar" aria-label="${esc(label)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><i data-w="${pct}"></i></div>`;
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const lowConf = () => S.cfg.low_conf ?? 70;
const isBusy = d => d.status === "processing" || d.status === "uploaded";
const isReady = d => d.status === "processed" || d.status === "needs_review";
const STATUS = { processed: ["check", "Processed"], needs_review: ["alert", "Needs review"], processing: ["refresh", "Processing…"], uploaded: ["refresh", "Queued"], error: ["x", "Error"], draft: ["file", "Draft"], done: ["check", "Ready"] };
const tag = s => { const [i, l] = STATUS[s] || ["", s]; return `<span class="tag ${esc(s)}">${i ? ic(i) + " " : ""}${esc(l)}</span>`; };
const confCell = v => v == null ? "–" : `<span class="conf ${v >= 90 ? "hi" : v >= lowConf() ? "mid" : "lo"}">${v}%</span>`;
const byId = id => S.docs.find(d => d.id === id);
async function busy(btn, fn) {
  const html = btn.innerHTML; btn.disabled = true; btn.setAttribute("aria-busy", "true");
  try { return await fn(); } finally { if (btn.isConnected) { btn.disabled = false; btn.removeAttribute("aria-busy"); btn.innerHTML = html; } }
}

/* ------------------------------------------------------------------ navigation */
const views = { dash, docs, comp, review };
async function show(v) {
  clearTimeout(S.timer); S.view = v; const tok = ++S.tok;
  const nav = v === "review" ? "docs" : v;
  $$("#nav button").forEach(b => b.dataset.v === nav ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"));
  if (v !== "dash") S.progHtml = "";
  render(`<div class="card"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>`);
  try { await views[v](tok); }
  catch (e) { if (tok === S.tok) render(`<div class="card empty">${ic("alert")}<p>${esc(e.message)}</p><button type="button" class="btn" data-act="retry">Try again</button></div>`); }
  if (tok === S.tok) { window.scrollTo(0, 0); app.focus({ preventScroll: true }); }
}
/* Re-draw the current view in place (no skeleton, keeps scroll position). */
function refresh() { clearTimeout(S.timer); return views[S.view](++S.tok).catch(e => toast(e.message, { err: true })); }
const stale = tok => tok !== S.tok;
function autoRefresh(list) { if (!S.job && list.some(isBusy)) S.timer = setTimeout(refresh, 3000); }

/* ------------------------------------------------------------------ sign-in */
function onUnauthorized() { if (S.cfg.auth_required && S.cfg.authenticated !== false) { S.cfg.authenticated = false; showLogin("Your session ended. Please sign in again."); } }
function showLogin(msg = "") {
  S.tok++; $("#nav").hidden = true; $("#signout").hidden = true; $("#wipe").hidden = true;
  app.innerHTML = `<div class="card login"><div class="logo" aria-hidden="true">u</div><h2>Sign in</h2><p class="mut">Enter the password to open uscan.</p>
    <form id="lf"><label class="field">Password<input type="password" id="pw" autocomplete="current-password" required maxlength="256"></label>
    <div class="err-text" id="lerr" role="alert">${esc(msg)}</div><button class="btn pri" type="submit">Sign in</button></form></div>`;
  $("#pw").focus();
  $("#lf").onsubmit = async e => {
    e.preventDefault(); const b = $("button", e.target); b.disabled = true;
    try {
      const r = await fetch("/api/login", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: $("#pw").value }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Sign-in failed. Please try again.");
      S.cfg.authenticated = true; start();
    } catch (err) { $("#lerr").textContent = err.message; b.disabled = false; $("#pw").select(); }
  };
}
function start() {
  $("#nav").hidden = false; $("#signout").hidden = !S.cfg.auth_required;
  $("#wipe").hidden = $("#foot").hidden = !S.cfg.public; show("dash");
}
const privacyNote = () => S.cfg.public ? `<div class="callout">${ic("lock")}<div class="grow"><b>Private to this browser</b><br><small>Nobody else can see your files. ${S.cfg.ttl_hours ? `They are deleted automatically after ${plural(S.cfg.ttl_hours, "hour")} without use.` : "They stay until you delete them."} <a href="/privacy">Privacy details</a></small></div></div>` : "";

/* ------------------------------------------------------------------ dashboard */
const exportMenu = () => `<details class="menu"><summary class="btn">${ic("download")} Export all ${ic("chev")}</summary><div class="items">
  <button type="button" data-act="mergeAll">${ic("layers")}<span>All reports → one PDF<small>With cover, contents and page numbers</small></span></button>
  <button type="button" data-act="text" data-fmt="txt">${ic("file")}<span>All text → .txt file<small>Plain text, edits included</small></span></button>
  <button type="button" data-act="text" data-fmt="pdf">${ic("file")}<span>All text → text-only PDF<small>No page images</small></span></button></div></details>`;

function nextStep(s, d) {
  if (!d.length) return `<ol class="steps"><li><b class="n">1</b><div><b>Upload</b><span>Drop PDFs or photos of your reports above.</span></div></li>
    <li><b class="n">2</b><div><b>Check</b><span>uscan reads the text; you fix anything it isn't sure about.</span></div></li>
    <li><b class="n">3</b><div><b>Compile</b><span>Combine everything into one tidy, searchable PDF.</span></div></li></ol>`;
  const first = d.find(x => x.status === "needs_review");
  if (s.pending_review) return `<div class="callout warn">${ic("alert")}<div class="grow"><b>${plural(s.pending_review, "page")} need${s.pending_review === 1 ? "s" : ""} a quick check</b><br><small>Uncertain text is highlighted. Nothing is ever guessed or auto-corrected.</small></div>${first ? `<button type="button" class="btn pri" data-act="open" data-id="${esc(first.id)}">Start checking</button>` : ""}</div>`;
  if (d.some(isReady)) return `<div class="callout">${ic("check")}<div class="grow"><b>All reviewed</b><br><small>Ready to combine your reports into one PDF.</small></div><button type="button" class="btn pri" data-act="go" data-v="comp">Compile PDF</button></div>`;
  return "";
}

async function dash(tok) {
  const [s, d] = await Promise.all([api("/api/stats"), api("/api/documents")]);
  if (stale(tok)) return;
  S.docs = d;
  const { max_upload_mb: mb, extensions: ext = [] } = S.cfg;
  render(`${privacyNote()}<section class="hero"><h2>Turn scanned reports into <em>clean, searchable PDFs</em></h2><p>Upload, check what the scanner wasn't sure about, and download one tidy file. Nothing is guessed or auto-corrected.</p></section><div class="card"><div class="drop" id="drop" role="button" tabindex="0" aria-label="Upload reports: drop files here or press Enter to browse"><div class="dicon" aria-hidden="true">${ic("upload")}</div>
      <b>Drop reports here</b><span>or click to browse your files</span><small>PDF, JPG, PNG or TIFF · up to ${mb ?? 50} MB each · several files at once is fine</small>
      <input type="file" id="f" multiple hidden accept="${esc(ext.join(","))}"></div><div id="prog" aria-live="polite">${S.progHtml}</div></div>
    ${nextStep(s, d)}
    <div class="stats">${[["file", "Documents scanned", s.documents], ["layers", "Pages processed", s.pages], ["alert", "Pages to check", s.pending_review], ["download", "PDFs compiled", s.compiled]]
      .map(x => `<div class="stat"><i aria-hidden="true">${ic(x[0])}</i><div><b>${x[2]}</b><span>${x[1]}</span></div></div>`).join("")}</div>
    <div class="card"><div class="row"><h2 class="grow nomargin">Recent documents</h2>${d.length > 8 ? `<button type="button" class="btn sm" data-act="go" data-v="docs">View all ${d.length}</button>` : ""}${d.length ? exportMenu() : ""}</div>
    <div class="tablewrap">${docTable(d.slice(0, 8))}</div></div>`);
  applyWidths($("#prog"));
  autoRefresh(d);
}

function docTable(list, pick) {
  if (!list.length) return `<div class="empty">${ic("file")}<b>No documents ${S.q || S.status ? "match your search" : "yet"}</b><br>${S.q || S.status ? "Try a different search or filter." : "Drop a report in the box above to get started."}</div>`;
  return `<table class="stack"><thead><tr>${pick ? `<th><input type="checkbox" aria-label="Select all shown documents" data-change="togAll"></th>` : ""}<th>Document</th><th>Pages</th><th>Status</th><th>Confidence</th><th>Checked</th><th><span class="sr">Actions</span></th></tr></thead><tbody>
  ${list.map(x => `<tr>${pick ? `<td data-label="Select"><input type="checkbox" aria-label="Select ${esc(x.title)}" data-change="tog" data-id="${esc(x.id)}" ${S.sel.has(x.id) ? "checked" : ""}></td>` : ""}
    <td class="first"><span class="docname">${esc(x.title)}</span><br><small>${esc(x.filename)}</small></td><td data-label="Pages">${x.pages}</td>
    <td data-label="Status">${tag(x.status)}${x.error ? `<br><small class="warnline">${esc(x.error)}</small>` : ""}</td><td data-label="Confidence">${confCell(x.confidence)}</td><td data-label="Checked">${x.reviewed_pages}/${x.pages}</td>
    <td class="actions">${x.status === "error" ? `<button type="button" class="btn sm" data-act="reprocess" data-id="${esc(x.id)}">Retry</button> ` : ""}<button type="button" class="btn sm pri" data-act="open" data-id="${esc(x.id)}" ${isBusy(x) ? "disabled" : ""}>Review</button>
      <button type="button" class="btn sm icon" title="Rename" aria-label="Rename ${esc(x.title)}" data-act="rename" data-id="${esc(x.id)}">${ic("edit")}</button>
      <button type="button" class="btn sm icon danger" title="Delete" aria-label="Delete ${esc(x.title)}" data-act="del" data-id="${esc(x.id)}">${ic("trash")}</button></td></tr>`).join("")}</tbody></table>`;
}

/* ---- upload */
function upload(fileList) {
  const files = [...fileList]; if (!files.length) return;
  const { max_upload_mb: mb = 50, max_files: mf = 20, extensions: ext = [] } = S.cfg, send = [];
  let over = 0;
  for (const f of files) {
    const e = "." + (f.name.split(".").pop() || "").toLowerCase();
    if (!ext.includes(e)) toast(`${f.name}: not supported. Use PDF, JPG, PNG or TIFF.`, { err: true });
    else if (f.size > mb * 1048576) toast(`${f.name}: bigger than ${mb} MB.`, { err: true });
    else if (send.length >= mf) over++;
    else send.push(f);
  }
  if (over) toast(`Only ${mf} files can be added at a time — ${plural(over, "file")} skipped.`, { err: true });
  if (send.length) sendFiles(send);
}
function setProg(pct, label, sub = "") {
  const el = $("#prog");
  if (el && $(".bar", el) && $("#pl", el)) {
    const b = $(".bar", el); b.setAttribute("aria-valuenow", pct); $("i", b).style.width = pct + "%"; $("#pl", el).textContent = label; $("#ps", el).textContent = sub;
    S.progHtml = el.innerHTML; return;
  }
  S.progHtml = `<p id="pl">${esc(label)}</p>${bar(pct, "Progress")}<small id="ps">${esc(sub)}</small>`;
  if (el) { el.innerHTML = S.progHtml; applyWidths(el); }
}
function setSummary(html) { S.progHtml = html; const el = $("#prog"); if (el) el.innerHTML = html; }
function sendFiles(files) {
  const fd = new FormData(); files.forEach(f => fd.append("files", f));
  setProg(0, `Uploading ${plural(files.length, "file")}…`);
  const x = new XMLHttpRequest(); x.open("POST", "/api/documents/upload"); x.responseType = "json";
  x.upload.onprogress = e => e.lengthComputable && setProg(Math.round(90 * e.loaded / e.total), `Uploading ${plural(files.length, "file")}…`);
  x.onerror = () => { setSummary(""); toast("The upload didn't go through. Check your connection and try again.", { err: true }); };
  x.onload = () => {
    const r = x.response;
    if (x.status === 401) { setSummary(""); return onUnauthorized(); }
    if (x.status < 200 || x.status >= 300) { setSummary(""); return toast(r && typeof r.detail === "string" ? r.detail : "The upload was rejected.", { err: true }); }
    r.errors.forEach(e => toast(`${e.filename}: ${e.error}`, { err: true }));
    if (r.job_id) poll(r.job_id); else setSummary("");
  };
  x.send(fd);
}
function poll(id) {
  S.job = id;
  const tick = async () => {
    let j;
    try { j = await api("/api/jobs/" + U(id)); }
    catch (e) { S.job = null; setSummary(""); return toast("Lost track of the scan — reload the page to see where things stand.", { err: true }); }
    if (!j.done) { setProg(Math.max(5, j.percent), `Reading report ${j.index} of ${j.total}${j.doc ? ": " + j.doc : ""}`, j.pages ? `Page ${j.page} of ${j.pages} · ${j.op}` : j.op); return setTimeout(tick, 800); }
    S.job = null;
    const ok = j.results.filter(r => r.status !== "error"), pages = ok.reduce((a, r) => a + r.pages, 0), flagged = ok.reduce((a, r) => a + r.flagged_pages, 0), errs = j.results.filter(r => r.status === "error");
    setSummary(`<p>${ic("check")} <b>${plural(ok.length, "report")} ready</b> · ${plural(pages, "page")}${flagged ? ` · <span class="warnline">${plural(flagged, "page")} to check</span>` : ""}</p>
      ${errs.map(r => `<p class="warnline">${ic("alert")} ${esc(r.error || "A report could not be processed.")}</p>`).join("")}`);
    toast(errs.length && !ok.length ? "Processing failed" : "Processing finished", { err: errs.length && !ok.length });
    if (S.view === "dash" || S.view === "docs") refresh();
  };
  tick();
}

/* ---- export */
async function mergeAll() {
  if (!await ask({ title: "Merge all reports?", text: "Every processed report is combined into one PDF with a cover page, contents and page numbers.", confirm: "Merge" })) return;
  toast("Merging reports… this can take a moment.");
  const x = await jput("/api/compilations/merge-all", {}, "POST");
  toast(`Merged ${plural(x.page_count, "page")}`); location.href = x.download;
}
async function exportText(fmt) {
  const r = await fetch("/api/export/text?format=" + U(fmt), { credentials: "same-origin" });
  if (r.status === 401) return onUnauthorized();
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "The export failed.");
  const url = URL.createObjectURL(await r.blob()), a = document.createElement("a");
  a.href = url; a.download = `Merged_Text_${new Date().toISOString().slice(0, 10)}.${fmt}`; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000); toast("All text exported into one file");
}

/* ------------------------------------------------------------------ documents list */
const visible = () => S.docs.filter(d => (!S.status || d.status === S.status) && (!S.q || (d.title + " " + d.filename).toLowerCase().includes(S.q.toLowerCase())));
function drawList() {
  const box = $("#doclist"); if (!box) return;
  const v = visible(); box.innerHTML = docTable(v, true);
  const all = $("[data-change=togAll]", box); if (all) all.checked = v.length > 0 && v.every(d => S.sel.has(d.id));
  const b = $("#csel"); if (b) { b.textContent = `Compile selected (${S.sel.size})`; b.disabled = !S.sel.size; }
}
async function docs(tok) {
  const d = await api("/api/documents"); if (stale(tok)) return;
  S.docs = d; S.sel = new Set([...S.sel].filter(id => byId(id)));
  render(`<div class="card"><div class="row"><h2 class="grow nomargin">Documents</h2>${exportMenu()}<button type="button" class="btn pri" id="csel" data-act="compileSel" disabled>Compile selected (0)</button></div>
    <div class="toolbar"><input type="search" placeholder="Search by title or file name" aria-label="Search documents" data-input="search" value="${esc(S.q)}">
    <select aria-label="Filter by status" data-change="status">${[["", "All statuses"], ["needs_review", "Needs review"], ["processed", "Processed"], ["processing", "Processing"], ["error", "Error"]].map(o => `<option value="${o[0]}" ${S.status === o[0] ? "selected" : ""}>${o[1]}</option>`).join("")}</select>
    <small class="mut">Tick documents to combine just those into a PDF.</small></div><div class="tablewrap" id="doclist"></div></div>`);
  drawList(); autoRefresh(d);
}

/* ------------------------------------------------------------------ review */
let saveQ = Promise.resolve();
const cur = () => S.rev.pages[S.rev.i];
const markHtml = p => p.reviewed ? ic("check") : p.flags ? ic("alert") : "";
const pageLabel = (p, i) => `Page ${i + 1}${p.reviewed ? ", reviewed" : p.flags ? ", needs checking" : ""}`;
const src = p => p.image + (p.v ? "?v=" + p.v : "");

async function review(tok) {
  const r = S.rev, [pages, doc] = await Promise.all([api(`/api/documents/${U(r.id)}/pages`), api("/api/documents/" + U(r.id))]);
  if (stale(tok)) return;
  r.pages = pages; r.doc = doc; r.i = Math.max(0, Math.min(r.i || 0, pages.length - 1));
  drawReview();
}
function drawReview() {
  const r = S.rev, d = r.doc, back = `<button type="button" class="btn" data-act="go" data-v="docs">${ic("left")} Documents</button>`;
  if (!r.pages.length) return render(`<div class="row">${back}<h2 class="nomargin">${esc(d.title)}</h2></div><div class="card empty">${ic("file")}<p>${isBusy(d) ? "This report is still being read. Check back in a moment." : "This report has no pages."}</p></div>`);
  render(`<div class="row">${back}<h2 class="grow nomargin">${esc(d.title)}</h2><span id="rprog" class="miniprog"></span><button type="button" class="btn" id="nextflag" data-act="nextflag">Next page to check ${ic("right")}</button></div>
    <div class="rev"><nav class="thumbs" id="thumbs" aria-label="Pages">${r.pages.map((p, i) => `<button type="button" class="t" data-act="pg" data-i="${i}" aria-label="${esc(pageLabel(p, i))}"><img loading="lazy" alt="" src="${esc(src(p))}"><span>p${i + 1} <span data-mark="${i}">${markHtml(p)}</span></span></button>`).join("")}</nav>
    <div id="pane-img"></div><div id="pane-txt"></div></div>`);
  drawHead(); drawPage();
}
function drawHead() {
  const r = S.rev, done = r.pages.filter(p => p.reviewed).length, more = r.pages.some((p, i) => i !== r.i && p.flags && !p.reviewed);
  $("#rprog").innerHTML = `<b>${done}</b> of ${r.pages.length} pages checked${bar(Math.round(100 * done / r.pages.length), "Pages checked")}`;
  applyWidths($("#rprog")); $("#nextflag").hidden = !more;
  $$("#thumbs .t").forEach((t, i) => { t.setAttribute("aria-current", i === r.i ? "true" : "false"); });
}
function updateMark(i) { const p = S.rev.pages[i], m = $(`[data-mark="${i}"]`); if (m) { m.innerHTML = markHtml(p); m.closest(".t").setAttribute("aria-label", pageLabel(p, i)); } }
function reviewBtn(p) { const last = S.rev.i >= S.rev.pages.length - 1; return p.reviewed ? [ic("check") + " Checked — undo", "btn"] : [ic("check") + (last ? " Mark as checked" : " Mark as checked & next"), "btn pri"]; }
function flagLine(p) { return p.flags ? `${ic("alert")} ${plural(p.flags, "item")} to verify — highlighted below.` : ""; }

function drawPage() {
  const r = S.rev, p = cur(), i = r.i, n = r.pages.length, [rl, rc] = reviewBtn(p);
  $("#pane-img").innerHTML = `<div class="row"><button type="button" class="btn sm" data-act="rot" data-d="270" title="Rotate left">${ic("rotL")} Left</button><button type="button" class="btn sm" data-act="rot" data-d="90" title="Rotate right">${ic("rotR")} Right</button>
      <button type="button" class="btn sm" data-act="rescan" title="Read this page again">${ic("refresh")} Re-scan</button><button type="button" class="btn sm" data-act="zoom" aria-pressed="false">${ic("zoom")} Zoom</button></div>
    <div class="pagewrap" id="pw"><img class="pageimg" alt="Scan of page ${i + 1}" src="${esc(src(p))}"></div>
    <div class="pager"><button type="button" class="btn sm" data-act="pg" data-d="-1" ${i === 0 ? "disabled" : ""}>${ic("left")} Previous</button><span>Page <b>${i + 1}</b> of ${n}</span><button type="button" class="btn sm" data-act="pg" data-d="1" ${i === n - 1 ? "disabled" : ""}>Next ${ic("right")}</button></div>
    <div class="row"><button type="button" class="btn sm" data-act="mv" data-d="-1" ${i === 0 ? "disabled" : ""}>${ic("up")} Move earlier</button><button type="button" class="btn sm" data-act="mv" data-d="1" ${i === n - 1 ? "disabled" : ""}>${ic("down")} Move later</button>
      <button type="button" class="btn sm danger right" data-act="rm">${ic("trash")} Delete page</button></div>
    <small>${esc(p.kind === "digital" ? "Text taken directly from the PDF" : "Read by OCR")}${p.ops.length ? " · " + esc(p.ops.join(", ")) : ""}</small>`;
  $("#pane-txt").innerHTML = `<div class="row"><button type="button" class="${rc}" id="btn-rev" data-act="reviewed">${rl}</button><span>Confidence ${confCell(p.confidence)}</span><span class="savestate right" id="ss" role="status"></span></div>
    <p class="warnline nomargin" id="flagline">${flagLine(p)}</p>${p.error ? `<p class="warnline">${esc(p.error)}</p>` : ""}
    ${p.tables.map((t, ti) => `<div class="tbl card"><b>Table ${ti + 1}</b> <small>(${esc(t.kind)})</small><div class="tablewrap"><table><tbody>${t.rows.map((row, ri) => `<tr>${row.map((c, ci) =>
      `<td colspan="${+c.colspan || 1}"><input type="text" class="${c.needs_review ? "low" : ""}" value="${esc(c.text)}" maxlength="2000" aria-label="Table ${ti + 1}, row ${ri + 1}, column ${ci + 1}" data-change="cell" data-t="${ti}" data-r="${ri}" data-c="${ci}"></td>`).join("")}</tr>`).join("")}</tbody></table></div></div>`).join("")}
    ${p.blocks.map((b, bi) => `<div class="blk ${b.needs_review ? "low" : ""}" data-blk="${bi}"><small>${esc(b.kind)}${(b.tags || []).length ? " · " + esc(b.tags.join(", ")) : ""} · ${+b.conf}%${b.needs_review ? ` · <b class="warnline nr">Needs review</b>` : ""}</small>
      ${b.needs_review && (b.words || []).length ? `<div class="words">${b.words.map(w => w[1] < lowConf() ? `<mark>${esc(w[0])}[?]</mark>` : esc(w[0])).join(" ")}</div>` : ""}
      <textarea rows="${Math.max(1, Math.ceil(String(b.text).length / 55))}" maxlength="2000" aria-label="Text line ${bi + 1}" data-change="blk" data-i="${bi}">${esc(b.text)}</textarea></div>`).join("")}
    ${!p.blocks.length && !p.tables.length ? `<p class="empty">No text was found on this page.</p>` : ""}
    <small class="mut">Tip: <kbd>←</kbd> <kbd>→</kbd> switch pages. Edits save automatically.</small>`;
  drawHead();
}
function setSave(kind, msg) {
  const el = $("#ss"); if (!el) return;
  el.className = "savestate right" + (kind === "error" ? " err" : "");
  el.innerHTML = kind === "saving" ? "Saving…" : kind === "saved" ? `${ic("check")} Saved` : `${ic("alert")} ${esc(msg || "Couldn't save")}`;
}
function save(patch, onFail) {
  const p = cur(); setSave("saving");
  saveQ = saveQ.then(async () => {  // one at a time, so the last edit always wins
    try {
      const r = await jput("/api/pages/" + U(p.id), patch);
      p.flags = r.flags; p.confidence = r.confidence;
      if (cur() === p) { setSave("saved"); const fl = $("#flagline"); if (fl) fl.innerHTML = flagLine(p); updateMark(S.rev.i); drawHead(); }
    } catch (e) { if (onFail) onFail(); if (cur() === p) setSave("error", e.message); toast(e.message, { err: true }); }
  });
  return saveQ;
}
function goPage(i) {
  const r = S.rev; if (i < 0 || i >= r.pages.length) return;
  r.i = i; drawPage(); $$("#thumbs .t")[i]?.scrollIntoView({ block: "nearest", inline: "nearest" }); window.scrollTo({ top: 0 });
}
const confirmLoss = async (p, what) => !p.blocks.some(b => b.edited) || ask({ title: `${what} this page?`, text: "The text is read again from scratch, so edits you made on this page will be replaced.", confirm: what, danger: true });
function replacePage(np) {
  const r = S.rev; np.v = Date.now(); r.pages[r.i] = np; drawPage();
  const img = $(`.thumbs .t:nth-child(${r.i + 1}) img`); if (img) img.src = src(np); updateMark(r.i);
}

/* ------------------------------------------------------------------ compile */
const RANGE = /^\s*(\d+)\s*(?:-\s*(\d+))?\s*$/;
function parseRange(spec, n) {
  spec = (spec || "all").trim().toLowerCase(); if (spec === "all") return { count: n };
  const seen = new Set();
  for (const part of spec.split(",")) {
    const m = RANGE.exec(part); if (!m) return { err: "Use “all”, or numbers like 1-3,5" };
    const a = +m[1], b = +(m[2] || m[1]); if (a < 1 || b < a || b > n) return { err: `Pages must be between 1 and ${n}` };
    for (let k = a; k <= b; k++) seen.add(k);
  }
  return { count: seen.size };
}
const DEFAULT_OPTS = { cover: true, toc: true, separators: false, page_numbers: true, text_layer: true, page_size: "original", quality: "original", header: "", footer: "" };
async function comp(tok) {
  const all = await api("/api/documents"); if (stale(tok)) return;
  S.docs = all; const ready = all.filter(isReady);
  const c = S.comp = S.comp || { title: "Compiled Report", items: [], opts: { ...DEFAULT_OPTS } };
  c.ready = ready; c.items = c.items.filter(i => ready.some(d => d.id === i.document_id));
  S.sel.forEach(id => { if (ready.some(d => d.id === id) && !c.items.some(i => i.document_id === id)) c.items.push({ document_id: id, title: byId(id).title, pages: "all" }); });
  S.sel.clear();
  if (!ready.length) return render(`<div class="card empty">${ic("layers")}<b>Nothing to compile yet</b><p>Upload and scan at least one report first.</p><button type="button" class="btn pri" data-act="go" data-v="dash">Go to Dashboard</button></div>`);
  const o = c.opts, chk = (k, l) => `<label class="check"><input type="checkbox" data-change="copt" data-k="${k}" ${o[k] ? "checked" : ""}> ${l}</label>`;
  const free = ready.filter(d => !c.items.some(i => i.document_id === d.id));
  render(`<div class="card"><h2>1 · Choose the reports</h2>
    <div class="row"><label class="field grow">PDF title<input type="text" maxlength="200" value="${esc(c.title)}" data-input="ctitle"></label></div>
    <div class="row"><select aria-label="Add a report" data-change="cadd"><option value="">+ Add a report…</option>${free.map(d => `<option value="${esc(d.id)}">${esc(d.title)}</option>`).join("")}</select>
      ${free.length ? `<button type="button" class="btn" data-act="caddall">Add all ${free.length} remaining</button>` : ""}</div>
    ${c.items.length ? `<div class="tablewrap"><table class="stack"><thead><tr><th>Order</th><th>Section title</th><th>Pages to include</th><th><span class="sr">Move or remove</span></th></tr></thead><tbody>${c.items.map((it, i) => { const n = byId(it.document_id)?.pages ?? 0; return `<tr><td data-label="Order">${i + 1}</td>
      <td data-label="Section"><input type="text" maxlength="200" value="${esc(it.title)}" aria-label="Section title ${i + 1}" data-input="ctl" data-i="${i}"></td>
      <td data-label="Pages"><input type="text" size="12" maxlength="200" value="${esc(it.pages)}" aria-label="Pages of section ${i + 1}" data-input="cpg" data-i="${i}"> <small>of ${n}</small><div class="err-text" id="perr-${i}"></div></td>
      <td class="actions"><button type="button" class="btn sm icon" aria-label="Move up" data-act="cm" data-i="${i}" data-d="-1" ${i === 0 ? "disabled" : ""}>${ic("up")}</button>
      <button type="button" class="btn sm icon" aria-label="Move down" data-act="cm" data-i="${i}" data-d="1" ${i === c.items.length - 1 ? "disabled" : ""}>${ic("down")}</button>
      <button type="button" class="btn sm icon danger" aria-label="Remove ${esc(it.title)}" data-act="crm" data-i="${i}">${ic("x")}</button></td></tr>`; }).join("")}</tbody></table></div>` : `<p class="empty">Pick at least one report above.</p>`}</div>
    <div class="card"><h2>2 · Options</h2><h3 class="sub">Include</h3><div class="opts">${chk("cover", "Cover page")}${chk("toc", "Table of contents")}${chk("separators", "Divider page before each report")}${chk("page_numbers", "Page numbers")}${chk("text_layer", "Make scanned pages searchable")}</div>
      <h3 class="sub">Format</h3><div class="opts fields">
      <label class="field">Page size<select data-change="copt" data-k="page_size">${[["original", "Keep original"], ["A4", "A4"], ["LETTER", "Letter"], ["LEGAL", "Legal"]].map(x => `<option value="${x[0]}" ${o.page_size === x[0] ? "selected" : ""}>${x[1]}</option>`).join("")}</select></label>
      <label class="field">Image quality<select data-change="copt" data-k="quality"><option value="original" ${o.quality === "original" ? "selected" : ""}>Original</option><option value="optimized" ${o.quality === "optimized" ? "selected" : ""}>Smaller file</option></select></label>
      <label class="field">Header text<input type="text" maxlength="120" value="${esc(o.header)}" data-input="copt" data-k="header"></label>
      <label class="field">Footer text<input type="text" maxlength="120" value="${esc(o.footer)}" data-input="copt" data-k="footer"></label></div></div>
    <div class="buildbar"><button type="button" class="btn pri" id="build" data-act="build">${ic("download")} Generate PDF</button><span id="csum" class="mut"></span><span id="res" aria-live="polite"></span></div>
    <div class="card"><h2>Previous PDFs</h2><div id="hist"><div class="skel"></div></div></div>`);
  c.items.forEach((_, i) => checkRow(i)); updateBuild(); hist();
}
function checkRow(i) {
  const it = S.comp.items[i], inp = $(`[data-input=cpg][data-i="${i}"]`), out = $("#perr-" + i); if (!it || !inp) return "";
  const e = parseRange(it.pages, byId(it.document_id)?.pages ?? 0).err || "";
  inp.setAttribute("aria-invalid", e ? "true" : "false"); if (out) out.textContent = e; return e;
}
function updateBuild() {
  const c = S.comp, b = $("#build"); if (!b) return;
  const errs = c.items.some(it => parseRange(it.pages, byId(it.document_id)?.pages ?? 0).err);
  const pages = c.items.reduce((a, it) => a + (parseRange(it.pages, byId(it.document_id)?.pages ?? 0).count || 0), 0);
  b.disabled = !c.items.length || errs;
  $("#csum").textContent = c.items.length ? `${plural(c.items.length, "report")} · about ${plural(pages, "page")} of content` : "Add a report to begin";
}
async function build(btn) {
  const c = S.comp, res = $("#res"); res.textContent = "Generating… large reports can take a minute.";
  await busy(btn, async () => {
    try {
      const made = await jput("/api/compilations", { title: c.title, items: c.items.map(i => ({ document_id: i.document_id, title: (i.title || "").trim() || null, pages: (i.pages || "all").trim() || "all" })), options: c.opts }, "POST");
      const x = await api(`/api/compilations/${U(made.id)}/export`, { method: "POST" });
      res.innerHTML = `${ic("check")} ${plural(x.page_count, "page")} · <a class="btn pri sm" href="${esc(x.download)}">Download PDF</a>`; toast("Your PDF is ready"); hist();
    } catch (e) { res.textContent = ""; toast(e.message, { err: true }); }
  });
  updateBuild();  // busy() re-enables the button; re-apply the "nothing valid to build" state
}
async function hist() {
  const h = $("#hist"); if (!h) return;
  const list = await api("/api/compilations").catch(() => null); if (!$("#hist")) return;
  $("#hist").innerHTML = !list ? "Couldn't load earlier PDFs." : list.length ? list.map(x => `<div class="row histrow"><span class="grow"><b>${esc(x.title)}</b> · ${plural(x.page_count, "page")}</span>${tag(x.status)}
    ${x.download ? `<a class="btn sm" href="${esc(x.download)}">${ic("download")} Download</a>` : ""}<button type="button" class="btn sm icon danger" aria-label="Delete ${esc(x.title)}" data-act="delc" data-id="${esc(x.id)}">${ic("trash")}</button></div>`).join("") : "<span class=\"mut\">None yet — your compiled PDFs will appear here.</span>";
}

/* ------------------------------------------------------------------ actions (buttons) */
const A = {
  go: el => show(el.dataset.v),
  retry: () => show(S.view),
  logout: async () => { try { await post("/api/logout"); } catch { /* already signed out */ } S.cfg.authenticated = false; S.comp = null; S.rev = null; showLogin(); },
  open: el => { S.rev = { id: el.dataset.id, i: 0 }; return show("review"); },
  mergeAll, text: el => exportText(el.dataset.fmt), compileSel: () => show("comp"),
  rename: async el => {
    const d = byId(el.dataset.id); if (!d) return;
    const n = await ask({ title: "Rename document", input: { label: "Document title", value: d.title }, confirm: "Save" });
    if (n && n.trim() && n.trim() !== d.title) { await jput("/api/documents/" + U(d.id), { title: n.trim() }); toast("Renamed"); refresh(); }
  },
  reprocess: async el => {
    const r = await post(`/api/documents/${U(el.dataset.id)}/process`);
    toast("Reading the report again…"); S.progHtml = ""; poll(r.job_id); refresh();
  },
  wipe: async () => {
    if (!await ask({ title: "Delete all your data?", text: "Every report, page image and compiled PDF in this workspace is removed from the server right now. This can't be undone.", confirm: "Delete everything", danger: true })) return;
    await api("/api/workspace", { method: "DELETE" });
    S.docs = []; S.sel.clear(); S.comp = null; S.rev = null; S.progHtml = ""; toast("All your data was deleted."); show("dash");
  },
  del: async el => {
    const d = byId(el.dataset.id); if (!d) return;
    if (!await ask({ title: `Delete “${d.title}”?`, text: "This removes the document, all of its pages and the original upload. It can't be undone.", confirm: "Delete", danger: true })) return;
    await api("/api/documents/" + U(d.id), { method: "DELETE" }); S.sel.delete(d.id); toast("Document deleted"); refresh();
  },
  /* review */
  pg: el => goPage(el.dataset.d ? S.rev.i + +el.dataset.d : +el.dataset.i),
  nextflag: () => { const r = S.rev, n = r.pages.length; for (let k = 1; k <= n; k++) { const j = (r.i + k) % n; if (r.pages[j].flags && !r.pages[j].reviewed) return goPage(j); } },
  zoom: el => { const on = el.getAttribute("aria-pressed") !== "true"; el.setAttribute("aria-pressed", on); $("#pw").classList.toggle("zoom", on); },
  reviewed: () => {
    const r = S.rev, p = cur(), next = !p.reviewed, adv = next && r.i < r.pages.length - 1, idx = r.i;
    p.reviewed = next; updateMark(idx);
    save({ reviewed: next }, () => { p.reviewed = !next; updateMark(idx); if (cur() === p) drawPage(); });
    if (adv) goPage(idx + 1); else { drawPage(); }
  },
  rot: async el => { const p = cur(); if (!await confirmLoss(p, "Rotate")) return; await busy(el, async () => replacePage(await post(`/api/pages/${U(p.id)}/rotate?degrees=${+el.dataset.d}`))); },
  rescan: async el => { const p = cur(); if (!await confirmLoss(p, "Re-scan")) return; await busy(el, async () => replacePage(await post(`/api/pages/${U(p.id)}/rescan`))); },
  mv: async el => {
    const r = S.rev, i = r.i, j = i + +el.dataset.d; if (j < 0 || j >= r.pages.length) return;
    const ids = r.pages.map(p => p.id); [ids[i], ids[j]] = [ids[j], ids[i]];
    await jput(`/api/documents/${U(r.id)}/order`, { page_ids: ids });
    [r.pages[i], r.pages[j]] = [r.pages[j], r.pages[i]]; r.i = j; drawReview();
  },
  rm: async () => {
    const r = S.rev, p = cur(), idx = r.i;
    await api("/api/pages/" + U(p.id), { method: "DELETE" });
    r.pages.splice(idx, 1); r.i = Math.min(idx, r.pages.length - 1); drawReview();
    toast("Page deleted", { action: { label: "Undo", fn: async () => { try { await post(`/api/pages/${U(p.id)}/restore`); r.i = idx; await review(++S.tok); } catch (e) { toast(e.message, { err: true }); } } } });
  },
  /* compile */
  caddall: () => { const c = S.comp; c.ready.filter(d => !c.items.some(i => i.document_id === d.id)).forEach(d => c.items.push({ document_id: d.id, title: d.title, pages: "all" })); refresh(); },
  cm: el => { const a = S.comp.items, i = +el.dataset.i, j = i + +el.dataset.d; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; refresh(); },
  crm: el => { S.comp.items.splice(+el.dataset.i, 1); refresh(); },
  build: el => build(el),
  delc: async el => {
    if (!await ask({ title: "Delete this compiled PDF?", text: "The generated file is removed. Your reports are not affected.", confirm: "Delete", danger: true })) return;
    await api("/api/compilations/" + U(el.dataset.id), { method: "DELETE" }); hist();
  },
};
/* ---- change / input handlers */
const copt = el => { S.comp.opts[el.dataset.k] = el.type === "checkbox" ? el.checked : el.value; };
const H = {
  tog: el => { el.checked ? S.sel.add(el.dataset.id) : S.sel.delete(el.dataset.id); drawList(); },
  togAll: el => { visible().forEach(d => el.checked ? S.sel.add(d.id) : S.sel.delete(d.id)); drawList(); },
  status: el => { S.status = el.value; drawList(); },
  cadd: el => { const d = byId(el.value); if (d) { S.comp.items.push({ document_id: d.id, title: d.title, pages: "all" }); refresh(); } },
  copt,
  blk: el => {
    const p = cur(), i = +el.dataset.i, b = p.blocks[i]; if (!b || b.text === el.value) return;
    b.text = el.value; b.edited = true; b.needs_review = false;
    const w = $(`[data-blk="${i}"]`); if (w) { w.classList.remove("low"); $(".words", w)?.remove(); $(".nr", w)?.remove(); }
    save({ blocks: p.blocks });
  },
  cell: el => {
    const p = cur(), c = p.tables[+el.dataset.t].rows[+el.dataset.r][+el.dataset.c]; if (!c || c.text === el.value) return;
    c.text = el.value; c.needs_review = false; el.classList.remove("low"); save({ tables: p.tables });
  },
};
const I = {
  search: el => { S.q = el.value; drawList(); },
  ctitle: el => { S.comp.title = el.value; },
  ctl: el => { S.comp.items[+el.dataset.i].title = el.value; },
  cpg: el => { S.comp.items[+el.dataset.i].pages = el.value; checkRow(+el.dataset.i); updateBuild(); },
  copt,
};
const report = e => toast(e && e.message ? e.message : "Something went wrong.", { err: true });
document.addEventListener("click", e => {
  $$("details.menu[open]").forEach(m => { if (!m.contains(e.target) || e.target.closest(".items button")) m.open = false; });
  const el = e.target.closest("[data-act]"); if (!el || el.disabled) return;
  const fn = A[el.dataset.act]; if (!fn) return;
  try { Promise.resolve(fn(el, e)).catch(report); } catch (err) { report(err); }
});
document.addEventListener("change", e => {
  const dz = e.target.closest("#f"); if (dz) { const files = [...dz.files]; dz.value = ""; return upload(files); }
  const el = e.target.closest("[data-change]"); if (el) try { H[el.dataset.change]?.(el, e); } catch (err) { report(err); }
});
document.addEventListener("input", e => { const el = e.target.closest("[data-input]"); if (el) try { I[el.dataset.input]?.(el, e); } catch (err) { report(err); } });
document.addEventListener("click", e => { if (e.target.closest("#drop") && !e.target.closest("#f")) $("#f")?.click(); });
document.addEventListener("keydown", e => {
  if (e.key === "Escape") $$("details.menu[open]").forEach(m => { m.open = false; });
  if ((e.key === "Enter" || e.key === " ") && e.target.id === "drop") { e.preventDefault(); $("#f")?.click(); return; }
  if (S.view !== "review" || !S.rev?.pages?.length || e.altKey || e.ctrlKey || e.metaKey || $("#dlg").open) return;
  if (e.target.closest("input,textarea,select,summary")) return;
  if (e.key === "ArrowLeft") goPage(S.rev.i - 1); else if (e.key === "ArrowRight") goPage(S.rev.i + 1);
});
/* Dropping a file next to the upload box must not make the browser navigate away from the app. */
window.addEventListener("dragover", e => { e.preventDefault(); $("#drop")?.classList.toggle("over", !!e.target.closest?.("#drop")); });
window.addEventListener("dragleave", e => { if (!e.relatedTarget) $("#drop")?.classList.remove("over"); });
window.addEventListener("drop", e => {
  e.preventDefault(); $("#drop")?.classList.remove("over");
  const files = [...(e.dataTransfer?.files || [])]; if (!files.length) return;
  if (e.target.closest?.("#drop")) upload(files); else toast("Drop files onto the upload box on the Dashboard.");
});

/* ------------------------------------------------------------------ boot */
(async function boot() {
  try {
    const r = await fetch("/api/session", { credentials: "same-origin" });
    if (!r.ok) throw new Error();
    S.cfg = await r.json();
  } catch { app.innerHTML = `<div class="card empty">${ic("alert")}<p>Can't reach uscan. Check that it is still running.</p><button type="button" class="btn" data-act="reload">Try again</button></div>`; A.reload = () => location.reload(); return; }
  if (S.cfg.auth_required && !S.cfg.authenticated) return showLogin();
  start();
})();
