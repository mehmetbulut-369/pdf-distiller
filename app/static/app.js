/* PDF Distiller UI – plain JavaScript, no build step. */
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

// ------------------------------------------------------------------ language (i18n)
// Strings live in static/i18n/<lang>.json. A missing key falls back to English, then to the key itself.
// Plurals: if vars.n is a number, "<key>_<one|other…>" is tried first (Intl.PluralRules).
const LANGS = ["en", "de", "tr"];
const i18n = { lang: "en", dict: {}, en: {} };
function pickLang() {
  try { const s = localStorage.getItem("lang"); if (LANGS.includes(s)) return s; } catch (_) {}
  for (const l of navigator.languages || [navigator.language || ""]) {
    const b = String(l).slice(0, 2).toLowerCase();
    if (LANGS.includes(b)) return b;
  }
  return "en";
}
async function loadLang(lang) {
  const get = async (l) => (await fetch(`/static/i18n/${l}.json`)).json();
  if (!Object.keys(i18n.en).length) i18n.en = await get("en");
  i18n.dict = lang === "en" ? i18n.en : await get(lang);
  i18n.lang = lang;
  document.documentElement.lang = lang;
}
const has = (k) => k in i18n.dict || k in i18n.en;
function t(key, vars = {}) {
  let s;
  if (typeof vars.n === "number") {
    const k = `${key}_${new Intl.PluralRules(i18n.lang).select(vars.n)}`;
    s = i18n.dict[k] ?? i18n.en[k];
  }
  s = s ?? i18n.dict[key] ?? i18n.en[key] ?? key;
  return s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? num(vars[k]) : m));
}
const num = (v) => (typeof v === "number" ? v.toLocaleString(i18n.lang) : v);
function applyDom() {
  $$("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  for (const a of ["title", "aria-label", "placeholder", "alt"]) {
    $$(`[data-i18n-${a}]`).forEach((el) => el.setAttribute(a, t(el.getAttribute(`data-i18n-${a}`))));
  }
  $$("#lang button").forEach((b) => {
    if (b.dataset.lang === i18n.lang) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
  });
}
async function setLang(lang) {
  await loadLang(lang);
  try { localStorage.setItem("lang", lang); } catch (_) {}
  applyDom();
  // redraw everything that renders dynamic text
  buildTiers(); syncControls(); setTool(state.tool); renderThumbs(); renderWords(); renderSummary(); renderDocName();
  if (state.doc) refreshPage();
  loadProfiles().catch(() => {});
}

const TIER_KEYS = ["remove_backgrounds", "remove_repeated", "remove_large_images",
  "remove_large_shapes", "remove_all_graphics", "text_mode"];
const kindText = (k) => t(`kind.${k}`);
const clsText = (c) => t(`cls.${c}`);
const emptyOverrides = () => ({ elements: {}, signatures: {}, regions: [], crops: [] });

const state = {
  doc: null,        // {id, name, n_pages, pages:[{w,h,rot}]}
  tiers: {},
  settings: null,
  overrides: emptyOverrides(),
  tool: "graphics", // graphics | text
  ops: [],          // [{src, rotate}]
  pos: 0,           // position within ops
  view: "split",
  history: [],
  elements: [],
  reqSeq: 0,
  afterUrl: null,
};

// ------------------------------------------------------------------ helpers
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = t("error.request_failed", { status: r.status });
    try { const d = (await r.json()).detail; if (typeof d === "string") msg = has(d) ? t(d) : d; } catch (_) {}
    throw new Error(msg);
  }
  return r;
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const job = (extra = {}) => ({ settings: state.settings, overrides: state.overrides, ...extra });

let toastTimer;
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (err ? " err" : ""); t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), err ? 6000 : 2600);
}
// Confirms a change and offers the way back; users rarely discover Ctrl/Cmd+Z on their own.
function undoToast(msg) {
  const el = $("#toast");
  el.className = "toast"; el.hidden = false;
  el.innerHTML = `${esc(msg)} <button class="lnk">${esc(t("undo"))}</button>`;
  el.querySelector("button").onclick = () => { el.hidden = true; undo(); };
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (el.hidden = true), 5000);
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
const pct = (v) => new Intl.NumberFormat(i18n.lang, { style: "percent", maximumFractionDigits: 0 }).format(v);
const curSrc = () => (state.ops[state.pos] ? state.ops[state.pos].src : null);

// ------------------------------------------------------------------ history (undo)
function snapshot() {
  state.history.push(JSON.stringify({ s: state.settings, o: state.overrides, p: state.ops }));
  if (state.history.length > 100) state.history.shift();
  $("#undo").disabled = false;
}
function undo() {
  const h = state.history.pop();
  if (!h) return;
  const v = JSON.parse(h);
  state.settings = v.s; state.overrides = { ...emptyOverrides(), ...v.o }; state.ops = v.p;
  state.pos = Math.min(state.pos, Math.max(0, state.ops.length - 1));
  $("#undo").disabled = state.history.length === 0;
  syncControls(); renderThumbs(); refreshAll();
}

// ------------------------------------------------------------------ tiers and settings
function currentTier() {
  for (const [t, v] of Object.entries(state.tiers)) {
    if (TIER_KEYS.every((k) => v.settings[k] === state.settings[k])) return Number(t);
  }
  return null;
}
function buildTiers() {
  const tr = t; // the loop variable `t` shadows the translate function
  const box = $("#tiers");
  box.innerHTML = "";
  for (const t of [0, 1, 2, 3]) {
    const b = document.createElement("button");
    b.className = "tier"; b.dataset.t = t; b.setAttribute("role", "radio");
    const bars = [3, 2, 1].map((i) => `<i class="${t >= i ? "f" : ""}"></i>`).join("");
    b.innerHTML = `<span class="lvl" aria-hidden="true">${bars}</span><b>${esc(tr(`tier.${t}.name`))}</b><small>${esc(tr(`tier.${t}.desc`))}</small>`;
    b.onclick = () => setTier(t);
    box.appendChild(b);
  }
  const note = document.createElement("div");
  note.className = "custom-note"; note.id = "customNote";
  box.appendChild(note);
}
function setTier(t) {
  snapshot();
  for (const k of TIER_KEYS) state.settings[k] = state.tiers[t].settings[k];
  syncControls(); refreshAll();
}
function syncControls() {
  const s = state.settings;
  const tier = currentTier();
  $$(".tier").forEach((b) => {
    const on = Number(b.dataset.t) === tier;
    b.classList.toggle("on", on); b.setAttribute("aria-checked", on);
  });
  $("#customNote").textContent = tier === null ? t("tiers.custom") : "";
  $$("[data-s]").forEach((el) => {
    const k = el.dataset.s;
    if (el.type === "checkbox") el.checked = !!s[k];
    else if (el.type === "range") el.value = Math.round(s[k] * Number(el.dataset.scale || 1));
    else el.value = s[k];
  });
  $$("output[data-o]").forEach((o) => (o.textContent = pct(s[o.dataset.o])));
  $$("#nup button").forEach((b) => { const on = Number(b.dataset.n) === s.nup; b.classList.toggle("on", on); b.setAttribute("aria-checked", on); });
}
function bindControls() {
  $$("[data-s]").forEach((el) => {
    const k = el.dataset.s;
    const apply = () => {
      const v = el.type === "checkbox" ? el.checked
        : el.type === "range" ? Number(el.value) / Number(el.dataset.scale || 1) : el.value;
      state.settings[k] = v;
      syncControls(); refreshAll();
    };
    // avoid a history entry per slider step: write once when the drag starts
    el.addEventListener(el.type === "range" ? "pointerdown" : "change", () => snapshot());
    el.addEventListener(el.type === "range" ? "input" : "change", el.type === "range" ? debounce(apply, 120) : apply);
    if (el.type === "range") el.addEventListener("keydown", () => snapshot(), { once: false });
  });
  $$("#nup button").forEach((b) => (b.onclick = () => { snapshot(); state.settings.nup = Number(b.dataset.n); syncControls(); refreshSummary(); }));
}

// ------------------------------------------------------------------ opening a document
async function openFile(file) {
  if (!file) return;
  if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") return toast(t("error.choose_pdf"), true);
  const fd = new FormData();
  fd.append("file", file);
  $("#docname").textContent = t("doc.analyzing", { name: file.name });
  try {
    const r = await api("/api/open", { method: "POST", body: fd });
    const d = await r.json();
    state.doc = d;
    state.ops = d.pages.map((_, i) => ({ src: i, rotate: 0 }));
    state.pos = 0;
    state.overrides = emptyOverrides();
    state.words = null;
    state.history = []; $("#undo").disabled = true;
    renderDocName();
    $("#empty").classList.add("hidden");
    $("#export").disabled = false;
    renderThumbs(); refreshAll();
  } catch (e) {
    $("#docname").textContent = "";
    toast(e.message, true);
  }
}

function renderDocName() {
  const d = state.doc;
  if (!d) return;
  const f = (v) => v.toLocaleString(i18n.lang, { maximumFractionDigits: 1 });
  const secs = d.analysis_seconds < 0.1 ? `<${f(0.1)}` : f(d.analysis_seconds);
  $("#docname").textContent = t("doc.info", { name: d.name, n: d.n_pages, secs });
}

// ------------------------------------------------------------------ preview
function imgWidth(el) {
  const w = (el.closest(".frame")?.clientWidth || 700) * (window.devicePixelRatio || 1);
  return Math.min(1800, Math.max(300, Math.ceil(w / 100) * 100));
}
async function refreshPage() {
  if (!state.doc) return;
  const src = curSrc();
  if (src === null) { $("#pageLabel").textContent = t("page.none"); return; }
  $("#pageLabel").textContent = `${state.pos + 1} / ${state.ops.length}`;
  renderInkWarn();
  const seq = ++state.reqSeq;
  const before = $("#imgBefore");
  const w = imgWidth(before);
  const url = `/api/doc/${state.doc.id}/original/${src}.png?w=${w}`;
  if (before.dataset.url !== url) { before.src = url; before.dataset.url = url; }
  $("#busy").classList.add("on");
  try {
    const [elr, imr] = await Promise.all([
      post(`/api/doc/${state.doc.id}/elements`, job({ page: src })),
      post(`/api/doc/${state.doc.id}/processed.png`, job({ page: src, width: w })),
    ]);
    const els = (await elr.json()).elements;
    const blob = await imr.blob();
    if (seq !== state.reqSeq) return; // a newer request exists
    state.elements = els;
    if (state.crop.target) state.crop.target = els.find((e) => e.id === state.crop.target.id) || null;
    syncCropBar();
    drawOverlay();
    if (state.afterUrl) URL.revokeObjectURL(state.afterUrl);
    state.afterUrl = URL.createObjectURL(blob);
    $("#imgAfter").src = state.afterUrl;
  } catch (e) { toast(e.message, true); }
  finally { if (seq === state.reqSeq) $("#busy").classList.remove("on"); }
}

const inRegion = (v, b) => { const cy = (v[1] + v[3]) / 2; return b[1] <= cy && cy <= b[3] && v[0] < b[2] && v[2] > b[0]; };
const place = (d, [x0, y0, x1, y1]) => Object.assign(d.style, { left: `${x0 * 100}%`, top: `${y0 * 100}%`,
  width: `${Math.max((x1 - x0) * 100, 0.4)}%`, height: `${Math.max((y1 - y0) * 100, 0.4)}%` });
const cropsOf = (e) => state.overrides.crops.filter((c) => c.id === e.id || (c.all && c.sig === e.sig));
const isManual = (e) => !!(state.overrides.elements[e.id] || state.overrides.signatures[e.sig] ||
  (e.kind === "text" && state.overrides.regions.some((r) => inRegion(e.view, r.box))) ||
  (e.kind === "image" && cropsOf(e).length));
const contains = (v, [x, y]) => v[0] <= x && x <= v[2] && v[1] <= y && y <= v[3];
const SVGNS = "http://www.w3.org/2000/svg";
const ptsAttr = (pts) => pts.map(([x, y]) => `${x},${y}`).join(" ");

// Selectable elements per tool. White fills never use ink, so they are not shown.
function selectable(e) {
  if (state.tool === "text") return e.kind === "text";
  if (state.tool === "crop") return e.kind === "image";
  return e.kind !== "text" && e.cls !== "white";
}
// Elements at the clicked point, smallest first (select the clicked thing, not the large background on top)
function hitsAt(pt) {
  return state.elements.filter((e) => selectable(e) && contains(e.view, pt)).sort((a, b) => a.area - b.area);
}

function drawOverlay() {
  const ov = $("#overlay");
  ov.innerHTML = "";
  ov.dataset.tool = state.tool;
  if (state.tool === "text") {
    state.overrides.regions.forEach((r, k) => {
      const d = document.createElement("div");
      d.className = "region"; d.dataset.region = k; place(d, r.box);
      d.title = t("region.title");
      ov.appendChild(d);
    });
  }
  const els = state.elements.filter(selectable).sort((a, b) => b.area - a.area);
  const hot = new Set(inkRep()?.page_hot?.[String(curSrc())] || []);
  for (const e of els) {
    const d = document.createElement("div");
    d.className = `el k-${e.kind} c-${e.cls}` + (e.drop ? " drop" : "") + (isManual(e) ? " manual" : "") +
      (state.crop.target?.id === e.id ? " target" : "") + (!e.drop && hot.has(e.id) ? " inkhot" : "");
    d.dataset.id = e.id;
    place(d, e.view);
    d.title = describe(e);
    d.tabIndex = 0;
    d.setAttribute("role", "button");
    d.setAttribute("aria-label", describe(e));
    d.onkeydown = (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      ev.preventDefault(); const r = d.getBoundingClientRect(); activate(e, [], r.left + 8, r.top + 8);
    };
    ov.appendChild(d);
  }
  // crop shapes (computed by the server, in view coordinates)
  const svg = document.createElementNS(SVGNS, "svg");
  svg.setAttribute("class", "cropsvg"); svg.setAttribute("viewBox", "0 0 1 1"); svg.setAttribute("preserveAspectRatio", "none");
  if (state.tool === "crop") {
    for (const e of state.elements) {
      if (!e.clips) continue;
      for (const [kind, polys] of Object.entries(e.clips)) {
        for (const p of polys) {
          const poly = document.createElementNS(SVGNS, "polygon");
          poly.setAttribute("points", ptsAttr(p)); poly.setAttribute("class", `clip ${kind}`);
          svg.appendChild(poly);
        }
      }
    }
  }
  const live = document.createElementNS(SVGNS, "polygon");
  live.setAttribute("class", "live"); live.id = "liveShape";
  svg.appendChild(live);
  ov.appendChild(svg);
}

function describe(e) {
  const state_ = t(e.drop ? "el.drop" : "el.keep");
  if (e.kind === "text") return `“${e.text}” · ${state_}`;
  let s = `${kindText(e.kind)} · ${clsText(e.cls)} · ${state_}`;
  if (e.kind === "image" && e.clips) s += ` · ${t("el.cropped")}`;
  return s;
}

function activate(e, others, x, y) {
  if (state.tool === "text") return openTextMenu(e, x, y);
  if (state.tool === "crop") return setCropTarget(e);
  openMenu(e, x, y, others);
}
function markSelected(e) {
  $$(".el.sel").forEach((n) => n.classList.remove("sel"));
  $(`#overlay [data-id="${e.id}"]`)?.classList.add("sel");
}

// ------------------------------------------------------------------ menus
function menuStart(x, y, headHtml) {
  const m = $("#menu");
  m.innerHTML = `<div class="head">${headHtml}</div>`;
  m.hidden = false;
  const button = (label, hint, onclick) => {
    const b = document.createElement("button");
    b.innerHTML = esc(label) + (hint ? `<small>${esc(hint)}</small>` : "");
    b.setAttribute("role", "menuitem");
    b.onclick = onclick;
    m.appendChild(b);
  };
  return {
    // an action that changes settings: undoable, refreshes the preview
    add(label, fn, hint) { button(label, hint, () => { closeMenu(); snapshot(); fn(); refreshAll(); undoToast(t("toast.changed")); }); },
    // navigation only (change selection, switch tool)
    link(label, fn, hint) { button(label, hint, () => { closeMenu(); fn(); }); },
    note(text) { const d = document.createElement("div"); d.className = "note"; d.textContent = text; m.appendChild(d); },
    sep() { m.appendChild(document.createElement("hr")); },
    show() {
      const r = m.getBoundingClientRect();
      m.style.left = `${Math.max(8, Math.min(x, innerWidth - r.width - 8))}px`;
      m.style.top = `${Math.max(8, Math.min(y, innerHeight - r.height - 8))}px`;
      m.querySelector("button")?.focus();
    },
  };
}
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const short = (t, n = 48) => (t.length > n ? t.slice(0, n - 1) + "…" : t);

function openMenu(e, x, y, others = []) {
  markSelected(e);
  const n = e.pages_with_sig;
  const head = `${kindText(e.kind)} · ${clsText(e.cls)}${n > 1 ? ` · ${t("menu.on_pages", { n })}` : ""} · ${t(e.drop ? "el.drop" : "el.keep")}`;
  const m = menuStart(x, y, esc(head));
  const O = state.overrides;
  if (e.cls === "text_image" && !e.drop) m.note(t("menu.auto_kept"));
  m.add(t(e.drop ? "menu.keep_page" : "menu.remove_page"), () => { O.elements[e.id] = e.drop ? "keep" : "remove"; });
  if (n > 1) {
    m.add(t("menu.remove_all", { n }), () => { O.signatures[e.sig] = "remove"; delete O.elements[e.id]; });
    m.add(t("menu.keep_all", { n }), () => { O.signatures[e.sig] = "keep"; delete O.elements[e.id]; });
  }
  if (e.kind === "image") m.link(t("menu.crop"), () => { setTool("crop"); setCropTarget(e); }, t("menu.crop_hint"));
  if (O.elements[e.id] || O.signatures[e.sig]) {
    m.sep();
    m.add(t("menu.reset_auto"), () => { delete O.elements[e.id]; delete O.signatures[e.sig]; });
  }
  if (others.length) {
    m.sep();
    m.note(t("menu.others"));
    others.slice(0, 4).forEach((o) => m.link(`${kindText(o.kind)} · ${clsText(o.cls)} · ${t(o.drop ? "el.drop" : "el.keep")}`,
      () => openMenu(o, x, y, [e, ...others.filter((z) => z !== o)])));
  }
  m.show();
}

function openTextMenu(e, x, y) {
  markSelected(e);
  const O = state.overrides;
  const n = e.pages_with_sig, r = e.pages_with_region;
  const head = `${kindText("text")}${n > 1 ? ` · ${t("text.same_n", { n })}` : ""}`;
  const m = menuStart(x, y, `${esc(head)}<span class="quote">“${esc(short(e.text || "…", 60))}”</span>`);
  if (e.drop) {
    m.add(t("menu.keep_page"), () => { O.elements[e.id] = "keep"; });
  } else {
    m.add(t("menu.remove_page"), () => { O.elements[e.id] = "remove"; });
    if (n > 1) m.add(t("menu.remove_all", { n }), () => { O.signatures[e.sig] = "remove"; delete O.elements[e.id]; },
      t("text.remove_all_hint"));
    if (r > n) m.add(t("text.remove_region", { n: r }), () => { O.regions.push({ box: e.region, action: "remove" }); delete O.elements[e.id]; },
      t("text.remove_region_hint"));
  }
  if (isManual(e)) {
    m.sep();
    m.add(t("text.undo"), () => {
      delete O.elements[e.id]; delete O.signatures[e.sig];
      O.regions = O.regions.filter((rg) => !inRegion(e.view, rg.box));
    }, t("text.undo_hint"));
  }
  m.show();
}

function openSelectionMenu(sel, box, x, y) {
  const O = state.overrides;
  const allDrop = sel.every((e) => e.drop);
  const sameEverywhere = sel.filter((e) => e.pages_with_sig > 1);
  const m = menuStart(x, y, `${esc(t("sel.head", { n: sel.length }))}<span class="quote">${esc(short(sel.map((e) => e.text).join(" · "), 70))}</span>`);
  if (!allDrop) m.add(t("sel.remove_page"), () => sel.forEach((e) => (O.elements[e.id] = "remove")));
  if (sameEverywhere.length) m.add(t("sel.remove_all"), () => sameEverywhere.forEach((e) => { O.signatures[e.sig] = "remove"; delete O.elements[e.id]; }),
    t("sel.remove_all_hint", { n: sameEverywhere.length }));
  m.add(t("sel.remove_region"), () => O.regions.push({ box, action: "remove" }), t("sel.remove_region_hint"));
  if (sel.some((e) => e.drop)) { m.sep(); m.add(t("sel.keep_page"), () => sel.forEach((e) => (O.elements[e.id] = "keep"))); }
  m.show();
}

function openRegionMenu(k, x, y) {
  const r = state.overrides.regions[k];
  const m = menuStart(x, y, esc(t(r.action === "remove" ? "region.head_remove" : "region.head_keep")));
  m.add(t("region.delete"), () => state.overrides.regions.splice(k, 1));
  m.show();
}
function closeMenu() { $("#menu").hidden = true; $$(".el.sel, .el.picked").forEach((n) => n.classList.remove("sel", "picked")); }

// ------------------------------------------------------------------ crop tool
// "erase" first: a student who circles a logo wants it gone, not printed alone.
state.crop = { target: null, shape: "rect", mode: "erase", all: false };

function setCropTarget(e) {
  state.crop.target = e;
  state.crop.all = state.crop.all && e && e.pages_with_sig > 1;
  syncCropBar(); drawOverlay();
}
function syncCropBar() {
  const c = state.crop, e = c.target;
  $("#cropbar").hidden = state.tool !== "crop";
  $("#cropStatus").textContent = e ? t(c.mode === "keep" ? "crop.drag_keep" : "crop.drag_erase") : t("crop.pick");
  $("#cropStatus").classList.toggle("go", !!e);
  $$("#cropShape button").forEach((b) => b.classList.toggle("on", b.dataset.v === c.shape));
  $$("#cropMode button").forEach((b) => b.classList.toggle("on", b.dataset.v === c.mode));
  const n = e ? e.pages_with_sig : 0;
  $("#cropAll").disabled = !e || n < 2;
  $("#cropAll").checked = !!(e && c.all);
  $("#cropAllLabel").textContent = n > 1 ? t("crop.all_n", { n }) : t("crop.all");
  $("#cropAuto").disabled = !e;
  $("#cropClear").disabled = !e || !cropsOf(e).length;
}
function addCrop(mode, points) {
  const e = state.crop.target;
  if (!e) return;
  snapshot();
  state.overrides.crops.push({ id: e.id, sig: e.sig, all: state.crop.all, mode, points });
  refreshAll();
}
function clearCrops() {
  const e = state.crop.target;
  if (!e) return;
  snapshot();
  state.overrides.crops = state.overrides.crops.filter((c) => !(c.id === e.id || (c.all && c.sig === e.sig)));
  refreshAll();
}

// ------------------------------------------------------------------ mouse on the preview
// Click: the smallest element at the point. Drag: region selection in the text tool, drawing in the crop tool.
const drag = { start: null, pts: [], active: false, justDragged: false };
function bindOverlay() {
  const ov = $("#overlay");
  const rel = (ev) => { const r = ov.getBoundingClientRect(); return [Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height))]; };
  const live = () => $("#liveShape");
  const canDrag = () => state.tool === "text" || (state.tool === "crop" && state.crop.target);
  let hoverId = null;

  ov.addEventListener("pointermove", (ev) => {
    if (drag.start) return;
    const h = hitsAt(rel(ev))[0];
    const id = h ? h.id : null;
    if (id === hoverId) return;
    $$(".el.hover").forEach((n) => n.classList.remove("hover"));
    if (id) $(`#overlay [data-id="${id}"]`)?.classList.add("hover");
    hoverId = id;
  });
  ov.addEventListener("pointerleave", () => { $$(".el.hover").forEach((n) => n.classList.remove("hover")); hoverId = null; });
  ov.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    drag.start = rel(ev); drag.pts = [drag.start]; drag.active = false;
    if (canDrag()) ov.setPointerCapture(ev.pointerId);
  });
  ov.addEventListener("pointermove", (ev) => {
    if (!drag.start || !canDrag()) return;
    const p = rel(ev), [sx, sy] = drag.start;
    if (!drag.active && Math.hypot(p[0] - sx, p[1] - sy) < 0.006) return;
    if (!drag.active) { drag.active = true; closeMenu(); }
    if (state.tool === "crop" && state.crop.shape === "free") {
      const last = drag.pts[drag.pts.length - 1];
      if (Math.hypot(p[0] - last[0], p[1] - last[1]) > 0.004 && drag.pts.length < 400) drag.pts.push(p);
      live()?.setAttribute("points", ptsAttr(drag.pts));
    } else {
      const r = [Math.min(p[0], sx), Math.min(p[1], sy), Math.max(p[0], sx), Math.max(p[1], sy)];
      drag.pts = [[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]];
      live()?.setAttribute("points", ptsAttr(drag.pts));
    }
    live()?.setAttribute("class", `live ${state.tool === "crop" ? state.crop.mode : "select"}`);
  });
  ov.addEventListener("pointerup", (ev) => {
    if (!drag.start) return;
    const start = drag.start, pts = drag.pts.map(([x, y]) => [Math.round(x * 10000) / 10000, Math.round(y * 10000) / 10000]);
    const wasDrag = drag.active;
    drag.start = null; drag.active = false;
    live()?.setAttribute("points", "");
    if (!wasDrag) {
      const hs = hitsAt(start);
      if (state.tool === "text" && !hs.length) {
        const k = state.overrides.regions.findIndex((r) => contains(r.box, start));
        if (k >= 0) return openRegionMenu(k, ev.clientX, ev.clientY);
      }
      if (!hs.length) { closeMenu(); return; }
      // after the click event that follows pointerup, or the document click handler closes the menu again
      setTimeout(() => activate(hs[0], hs.slice(1), ev.clientX, ev.clientY), 0);
      return;
    }
    if (state.tool === "text") {
      const box = [pts[0][0], pts[0][1], pts[2][0], pts[2][1]];
      const sel = state.elements.filter((e) => e.kind === "text" && inRegion(e.view, box));
      if (!sel.length) return toast(t("toast.no_text_here"));
      sel.forEach((e) => ov.querySelector(`[data-id="${e.id}"]`)?.classList.add("picked"));
      setTimeout(() => openSelectionMenu(sel, box, ev.clientX, ev.clientY), 0);
    } else if (state.tool === "crop" && pts.length >= 3) {
      addCrop(state.crop.mode, pts);
    }
  });
}

function setTool(tool) {
  state.tool = tool;
  $$("#tool button").forEach((b) => { const on = b.dataset.t === tool; b.classList.toggle("on", on); b.setAttribute("aria-checked", on); });
  $("#legendGraphics").hidden = tool !== "graphics";
  $("#legendText").hidden = tool !== "text";
  $("#capBefore").textContent = t(`cap.${tool}`);
  if (tool !== "crop") state.crop.target = null;
  syncCropBar(); closeMenu(); drawOverlay();
}

// ------------------------------------------------------------------ summary and ink
const refreshSummary = debounce(async () => {
  if (!state.doc) return;
  try {
    state.summary = await (await post(`/api/doc/${state.doc.id}/summary`, job())).json();
    renderSummary();
  } catch (e) { toast(e.message, true); }
}, 350);
function renderSummary() {
  const d = state.summary;
  if (!d) return;
  const o = d.ink.original, p = d.ink.processed;
  const scale = Math.max(o, 0.05);
  $("#inkBefore").style.height = `${Math.min(100, (o / scale) * 92)}%`;
  $("#inkAfter").style.height = `${Math.min(100, (p / scale) * 92)}%`;
  $("#savingPct").textContent = pct(Math.max(0, d.ink.saving));
  $("#savingNote").textContent = [t("gauge.less_ink"), t("gauge.removed", { n: d.removed }), t("gauge.sample", { n: d.ink.pages })].join(" · ");
  renderInk(); drawOverlay();
}

function refreshAll() { refreshPage(); refreshSummary(); refreshWords(); }

// ------------------------------------------------------------------ ink warnings
// The server estimates every printed page (area x darkness of what is kept) and lists the elements
// that cost the most ink, so a student sees "this photo will drink your cartridge" before printing.
const inkRep = () => state.summary?.ink_report;
const posOfSrc = (src) => state.ops.findIndex((o) => o.src === src);
function renderInk() {
  const r = inkRep();
  const list = $("#inkList");
  list.innerHTML = "";
  const hot = (r?.hotspots || []).filter((h) => posOfSrc(h.page) >= 0);
  $("#inkHot").hidden = !hot.length;
  for (const h of hot) {
    const li = document.createElement("li");
    const where = h.pages > 1 ? t("ink.on_pages", { n: h.pages }) : t("ink.on_page", { n: posOfSrc(h.page) + 1 });
    li.innerHTML = `<button class="lnk" data-a="show">${esc(kindText(h.kind))} · ${esc(where)}</button>
      <span class="inkpct">${esc(t("ink.share", { pct: pct(h.share) }))}</span>
      <button class="btn small" data-a="rm">${esc(t(h.pages > 1 ? "ink.remove_all" : "ink.remove"))}</button>`;
    li.querySelector('[data-a="show"]').onclick = () => goTo(posOfSrc(h.page));
    li.querySelector('[data-a="rm"]').onclick = () => {
      snapshot();
      if (h.pages > 1) state.overrides.signatures[h.sig] = "remove"; else state.overrides.elements[h.id] = "remove";
      refreshAll(); undoToast(t("toast.removed"));
    };
    list.appendChild(li);
  }
  const heavy = new Set(r?.heavy || []);
  $$(".thumb").forEach((li, i) => li.classList.toggle("heavy", heavy.has(state.ops[i]?.src)));
  renderInkWarn();
}
function renderInkWarn() {
  const r = inkRep(), src = curSrc(), box = $("#inkWarn");
  const v = r && src !== null ? r.pages[src] : 0;
  box.hidden = !(r && v >= r.limit);
  if (box.hidden) return;
  box.innerHTML = `<strong>${esc(t("ink.page_heavy", { pct: pct(v) }))}</strong> ${esc(t("ink.page_heavy_hint"))}`;
}

// ------------------------------------------------------------------ page strip
function renderThumbs() {
  const ol = $("#thumbs");
  ol.innerHTML = "";
  if (!state.doc) return;
  $("#railCount").textContent = t("rail.count", { shown: state.ops.length, total: state.doc.n_pages });
  state.ops.forEach((op, i) => {
    const p = state.doc.pages[op.src];
    const li = document.createElement("li");
    li.className = "thumb" + (i === state.pos ? " cur" : "");
    const rot = op.rotate % 180 !== 0;
    li.style.setProperty("--ar", rot ? `${p.h}/${p.w}` : `${p.w}/${p.h}`);
    const up = esc(t("thumb.up")), down = esc(t("thumb.down")), rotT = esc(t("thumb.rotate"));
    li.innerHTML = `<button class="pick" aria-label="${esc(t("thumb.page", { n: i + 1 }))}"><div class="tw"><img loading="lazy" alt="" src="/api/doc/${state.doc.id}/original/${op.src}.png?w=280" style="transform:rotate(${op.rotate}deg);${rot ? `width:${(p.h / p.w) * 100}%` : ""}"></div></button>
      <div class="meta"><span>${i + 1}${op.src !== i ? ` <small>${esc(t("thumb.orig", { n: op.src + 1 }))}</small>` : ""} <span class="inkbadge">${esc(t("ink.badge"))}</span></span><span class="acts">
      <button data-a="up" title="${up}" aria-label="${up}">↑</button><button data-a="down" title="${down}" aria-label="${down}">↓</button>
      <button data-a="rot" title="${rotT}" aria-label="${rotT}">↻</button><button data-a="del" title="${esc(t("thumb.delete_title"))}" aria-label="${esc(t("thumb.delete"))}">✕</button></span></div>`;
    li.querySelector(".pick").onclick = () => goTo(i);
    li.querySelectorAll(".acts button").forEach((b) => (b.onclick = () => pageAction(i, b.dataset.a)));
    ol.appendChild(li);
  });
}
function pageAction(i, a) {
  snapshot();
  const ops = state.ops;
  if (a === "del") { ops.splice(i, 1); if (state.pos >= ops.length) state.pos = Math.max(0, ops.length - 1); }
  if (a === "rot") ops[i].rotate = (ops[i].rotate + 90) % 360;
  if (a === "up" && i > 0) { [ops[i - 1], ops[i]] = [ops[i], ops[i - 1]]; if (state.pos === i) state.pos--; }
  if (a === "down" && i < ops.length - 1) { [ops[i + 1], ops[i]] = [ops[i], ops[i + 1]]; if (state.pos === i) state.pos++; }
  renderThumbs(); renderInk(); refreshPage(); refreshWords();
  if (a === "del") undoToast(t("toast.page_removed", { n: i + 1 }));
}
function goTo(i) {
  if (!state.ops.length) return;
  state.pos = Math.max(0, Math.min(state.ops.length - 1, i));
  $$(".thumb").forEach((t, k) => t.classList.toggle("cur", k === state.pos));
  $$(".thumb")[state.pos]?.scrollIntoView({ block: "nearest" });
  closeMenu(); refreshPage();
}

// ------------------------------------------------------------------ word counter
const STOP = new Set(("der die das und in zu den von mit ist im dem nicht ein eine einer eines einem einen für auf auch es sich des sie wir " +
  "ich er als an bei aus oder wie so zum zur nach vom über unter durch wird werden wurde sind war hat haben kann können man nur noch wenn dass " +
  "da was wo um am aber bis bzw ggf usw sowie z b d h " +
  "the a an and or of to in on for is are be with as by at from this that it not can will was were has have its into if then than " +
  "ve ile bir bu da de için çok gibi daha olan ama ya veya mi mı mu mü ne o şu").split(" "));
const SORTS = ["desc", "asc", "alpha"];
const words = { data: null, sort: 0, seq: 0, cursor: {} };

const refreshWords = debounce(async () => {
  if (!state.doc || $("#paneWords").hidden) return;
  const seq = ++words.seq;
  try {
    const r = await post(`/api/doc/${state.doc.id}/words`, job({ pages: state.ops.map((o) => o.src), exclude_removed: $("#wRemoved").checked }));
    const d = await r.json();
    if (seq !== words.seq) return;
    words.data = d; renderWords();
  } catch (e) { toast(e.message, true); }
}, 300);

function visibleWords() {
  if (!words.data) return [];
  // Turkish İ/ı casing only in the Turkish UI (so a German/English "I" search does not become "ı")
  const lower = (s) => s.toLocaleLowerCase(i18n.lang === "tr" ? "tr" : "de");
  const q = lower($("#wordSearch").value.trim());
  const hideStop = $("#wStop").checked, hideNum = $("#wNum").checked;
  let list = words.data.words.filter((w) => {
    const k = w.w.toLocaleLowerCase("de");
    if (hideNum && w.num) return false;
    if (hideStop && (STOP.has(k) || w.w.length < 2)) return false;
    return !q || lower(w.w).includes(q);
  });
  const mode = SORTS[words.sort];
  const cmp = (a, b) => a.w.localeCompare(b.w, i18n.lang);
  if (mode === "asc") list = [...list].sort((a, b) => a.n - b.n || cmp(a, b));
  else if (mode === "alpha") list = [...list].sort(cmp);
  else list = [...list].sort((a, b) => b.n - a.n || cmp(a, b));
  return list;
}

function renderWords() {
  const ol = $("#words");
  const list = visibleWords();
  const d = words.data;
  $("#wordSort").textContent = t(`sort.${SORTS[words.sort]}`);
  $("#wordSum").textContent = d ? t("words.summary", { total: d.total, unique: d.unique, shown: list.length }) : "";
  const max = list.reduce((m, w) => Math.max(m, w.n), 1);
  const LIMIT = 1500;
  const pagesTitle = (w) => t("words.pages_title", { n: w.pages.length,
    list: w.pages.slice(0, 30).map((p) => p + 1).join(", ") + (w.pages.length > 30 ? "…" : "") });
  ol.innerHTML = list.slice(0, LIMIT).map((w, i) =>
    `<li tabindex="0" data-i="${i}" title="${esc(pagesTitle(w))}">
       <span class="w">${esc(w.w)}</span><span class="n">${num(w.n)}</span><span class="bar" style="width:calc(${(w.n / max) * 100}% - 12px)"></span></li>`).join("") +
    (list.length > LIMIT ? `<li class="more">${esc(t("words.limit", { n: LIMIT }))}</li>` : "");
  ol.querySelectorAll("li[data-i]").forEach((li) => {
    const w = list[Number(li.dataset.i)];
    const go = () => jumpToWord(w);
    li.onclick = go;
    li.onkeydown = (e) => { if (e.key === "Enter") go(); };
  });
}

function jumpToWord(w) {
  // each click jumps to the next page containing the word
  const positions = state.ops.map((o, i) => (w.pages.includes(o.src) ? i : -1)).filter((i) => i >= 0);
  if (!positions.length) return;
  const next = positions.find((i) => i > state.pos) ?? positions[0];
  goTo(next);
  toast(t("words.jump", { word: w.w, i: positions.indexOf(next) + 1, n: positions.length }));
}

const docStem = () => (state.doc?.name || "document").replace(/\.pdf$/i, "");
function exportCsv() {
  const list = visibleWords();
  const rows = [[t("csv.word"), t("csv.count"), t("csv.page_count"), t("csv.pages")], ...list.map((w) => [w.w, w.n, w.pages.length, w.pages.map((p) => p + 1).join(" ")])];
  const csv = "﻿" + rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(";")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  a.download = `${docStem()}_${t("file.words_suffix")}.csv`; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

function showTab(which) {
  const words_ = which === "words";
  $("#tabPages").setAttribute("aria-selected", !words_); $("#tabWords").setAttribute("aria-selected", words_);
  $("#panePages").hidden = words_; $("#paneWords").hidden = !words_;
  if (words_) refreshWords();
}

// ------------------------------------------------------------------ export
async function doExport() {
  const b = $("#export");
  b.disabled = true; b.textContent = t("export.busy");
  try {
    const r = await post(`/api/doc/${state.doc.id}/export`, job({ ops: state.ops }));
    const blob = await r.blob();
    const name = `${docStem()}_${t("file.print_suffix")}.pdf`; // the client names the file: suffix depends on the language
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    toast(t("export.done", { name }));
  } catch (e) { toast(e.message, true); }
  finally { b.disabled = false; b.textContent = t("export"); }
}

// ------------------------------------------------------------------ profiles
let profiles = [];
async function loadProfiles(select) {
  profiles = await (await api("/api/profiles")).json();
  const sel = $("#profiles");
  const prev = sel.value;
  sel.innerHTML = profiles.map((p, i) => `<option value="${i}">${esc(profileLabel(p))}</option>`).join("");
  if (select) { const i = profiles.findIndex((p) => p.name === select && !p.builtin); if (i >= 0) sel.value = i; }
  else if (prev && profiles[Number(prev)]) sel.value = prev;
}
// Built-in profiles come with their file name (id); the display name is translated. User profiles keep their name.
const profileLabel = (p) => (p.builtin
  ? `${has(`profile.${p.name}`) ? t(`profile.${p.name}`) : p.name} ${t("profile.builtin_suffix")}` : p.name);
function bindProfiles() {
  $("#profApply").onclick = () => {
    const p = profiles[Number($("#profiles").value)];
    if (!p) return;
    snapshot(); state.settings = { ...p.settings }; syncControls(); refreshAll();
    toast(t("profile.applied", { name: profileLabel(p) }));
  };
  $("#profSave").onclick = async () => {
    const name = prompt(t("profile.prompt"));
    if (!name) return;
    try { const r = await (await api(`/api/profiles/${encodeURIComponent(name)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state.settings) })).json();
      await loadProfiles(r.name); toast(t("profile.saved", { name: r.name })); } catch (e) { toast(e.message, true); }
  };
  $("#profDelete").onclick = async () => {
    const p = profiles[Number($("#profiles").value)];
    if (!p) return;
    if (p.builtin) return toast(t("profile.cannot_delete_builtin"), true);
    if (!confirm(t("profile.confirm_delete", { name: p.name }))) return;
    try { await api(`/api/profiles/${encodeURIComponent(p.name)}`, { method: "DELETE" }); await loadProfiles(); toast(t("profile.deleted")); }
    catch (e) { toast(e.message, true); }
  };
}

// ------------------------------------------------------------------ startup
// day/night: html[data-theme] is set only by a pick (saved in localStorage, applied in index.html <head>)
const darkMq = matchMedia("(prefers-color-scheme: dark)");
const isDark = () => (document.documentElement.dataset.theme || (darkMq.matches ? "dark" : "light")) === "dark";
const syncTheme = () => $("#theme").setAttribute("aria-pressed", String(isDark()));
function toggleTheme() {
  const next = isDark() ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("theme", next); } catch (_) {}
  syncTheme();
}
async function init() {
  await loadLang(pickLang());
  applyDom();
  state.tiers = await (await api("/api/tiers")).json();
  state.settings = { ...state.tiers[1].settings };
  buildTiers(); bindControls(); bindProfiles(); syncControls(); setTool("graphics");
  loadProfiles().catch(() => {});
  syncTheme(); $("#theme").onclick = toggleTheme; darkMq.addEventListener("change", syncTheme);
  $$("#lang button").forEach((b) => (b.onclick = () => setLang(b.dataset.lang).catch((err) => toast(err.message, true))));

  $("#file").onchange = (e) => { openFile(e.target.files[0]); e.target.value = ""; };
  $("#export").onclick = doExport;
  $("#undo").onclick = undo;
  $("#prev").onclick = () => goTo(state.pos - 1);
  $("#next").onclick = () => goTo(state.pos + 1);
  $("#resetPages").onclick = () => { if (!state.doc) return; snapshot(); state.ops = state.doc.pages.map((_, i) => ({ src: i, rotate: 0 })); state.pos = 0; renderThumbs(); refreshPage(); refreshWords(); };
  $$("#tool button").forEach((b) => (b.onclick = () => setTool(b.dataset.t)));
  bindOverlay();
  $$("#cropShape button").forEach((b) => (b.onclick = () => { state.crop.shape = b.dataset.v; syncCropBar(); }));
  $$("#cropMode button").forEach((b) => (b.onclick = () => { state.crop.mode = b.dataset.v; syncCropBar(); }));
  $("#cropAll").onchange = (e) => { state.crop.all = e.target.checked; };
  $("#cropAuto").onclick = () => addCrop("auto", []);
  $("#cropClear").onclick = clearCrops;
  $("#cropDone").onclick = () => setTool("graphics");
  $("#tabPages").onclick = () => showTab("pages");
  $("#tabWords").onclick = () => showTab("words");
  $("#wordSort").onclick = () => { words.sort = (words.sort + 1) % SORTS.length; renderWords(); };
  $("#wordCsv").onclick = exportCsv;
  $("#wordSearch").oninput = debounce(renderWords, 120);
  $("#wStop").onchange = renderWords; $("#wNum").onchange = renderWords; $("#wRemoved").onchange = refreshWords;
  document.addEventListener("keydown", (e) => {
    if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName) || e.metaKey || e.ctrlKey) return;
    if (e.key === "t") setTool(state.tool === "text" ? "graphics" : "text");
    if (e.key === "k" || e.key === "c") setTool(state.tool === "crop" ? "graphics" : "crop"); // k: "Kırp" (TR), c: crop
  });
  $("#showOverlay").onchange = (e) => $("#overlay").classList.toggle("hidden", !e.target.checked);
  $$("#viewmode button").forEach((b) => (b.onclick = () => {
    state.view = b.dataset.v; $("#views").dataset.mode = state.view;
    $$("#viewmode button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); });
    refreshPage();
  }));

  document.addEventListener("click", (e) => { if (!$("#menu").contains(e.target)) closeMenu(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeMenu();
    if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) return; // let fields undo their own typing
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); return; }
    if (e.key === "ArrowRight" || e.key === "PageDown") goTo(state.pos + 1);
    if (e.key === "ArrowLeft" || e.key === "PageUp") goTo(state.pos - 1);
  });
  window.addEventListener("resize", debounce(refreshPage, 300));

  const empty = $("#empty");
  ["dragenter", "dragover"].forEach((t) => window.addEventListener(t, (e) => { e.preventDefault(); empty.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((t) => window.addEventListener(t, (e) => { e.preventDefault(); empty.classList.remove("drag"); }));
  window.addEventListener("drop", (e) => openFile(e.dataTransfer.files[0]));
}
init().catch((e) => toast(e.message, true));
