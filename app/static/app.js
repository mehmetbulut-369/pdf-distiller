/* PDF Distiller arayüzü – derleme adımı yok, düz JavaScript. */
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const TIER_TEXT = {
  0: ["Orijinal", "Hiçbir şey kaldırılmaz"],
  1: ["Hafif", "Zeminler ve tekrar eden tema öğeleri"],
  2: ["Orta", "Hafif + büyük görseller ve şekiller"],
  3: ["Maksimum", "Sadece metin kalır"],
};
const TIER_KEYS = ["remove_backgrounds", "remove_repeated", "remove_large_images",
  "remove_large_shapes", "remove_all_graphics", "text_mode"];
const CLS_TEXT = { background: "Zemin", repeated: "Tekrarlayan", large: "Büyük", other: "Diğer", white: "Beyaz dolgu",
  text: "Metin", text_repeated: "Her sayfada aynı metin", text_image: "Yazılı görsel" };
const KIND_TEXT = { image: "Görsel", fill: "Şekil", stroke: "Çizgi", shading: "Gradyan", text: "Metin" };
const emptyOverrides = () => ({ elements: {}, signatures: {}, regions: [], crops: [] });

const state = {
  doc: null,        // {id, name, n_pages, pages:[{w,h,rot}]}
  tiers: {},
  settings: null,
  overrides: emptyOverrides(),
  tool: "graphics", // graphics | text
  ops: [],          // [{src, rotate}]
  pos: 0,           // ops içindeki konum
  view: "split",
  history: [],
  elements: [],
  reqSeq: 0,
  afterUrl: null,
};

// ------------------------------------------------------------------ yardımcılar
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = `İstek başarısız (${r.status}).`;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
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
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
const pct = (v) => `%${Math.round(v * 100)}`;
const curSrc = () => (state.ops[state.pos] ? state.ops[state.pos].src : null);

// ------------------------------------------------------------------ geçmiş (geri al)
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

// ------------------------------------------------------------------ kademeler ve ayarlar
function currentTier() {
  for (const [t, v] of Object.entries(state.tiers)) {
    if (TIER_KEYS.every((k) => v.settings[k] === state.settings[k])) return Number(t);
  }
  return null;
}
function buildTiers() {
  const box = $("#tiers");
  box.innerHTML = "";
  for (const t of [0, 1, 2, 3]) {
    const b = document.createElement("button");
    b.className = "tier"; b.dataset.t = t; b.setAttribute("role", "radio");
    const bars = [3, 2, 1].map((i) => `<i class="${t >= i ? "f" : ""}"></i>`).join("");
    b.innerHTML = `<span class="lvl" aria-hidden="true">${bars}</span><b>${TIER_TEXT[t][0]}</b><small>${TIER_TEXT[t][1]}</small>`;
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
  const t = currentTier();
  $$(".tier").forEach((b) => {
    const on = Number(b.dataset.t) === t;
    b.classList.toggle("on", on); b.setAttribute("aria-checked", on);
  });
  $("#customNote").textContent = t === null ? "Özel ayar – kademe ayarları elle değiştirildi." : "";
  $$("[data-s]").forEach((el) => {
    const k = el.dataset.s;
    if (el.type === "checkbox") el.checked = !!s[k];
    else if (el.type === "range") el.value = Math.round(s[k] * Number(el.dataset.scale || 1));
    else el.value = s[k];
  });
  $$("output[data-o]").forEach((o) => (o.textContent = pct(s[o.dataset.o])));
  $$("#nup button").forEach((b) => b.classList.toggle("on", Number(b.dataset.n) === s.nup));
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
    // kaydırıcıda her adımda geçmişe yazmamak için: sürükleme başında bir kez
    el.addEventListener(el.type === "range" ? "pointerdown" : "change", () => snapshot());
    el.addEventListener(el.type === "range" ? "input" : "change", el.type === "range" ? debounce(apply, 120) : apply);
    if (el.type === "range") el.addEventListener("keydown", () => snapshot(), { once: false });
  });
  $$("#nup button").forEach((b) => (b.onclick = () => { snapshot(); state.settings.nup = Number(b.dataset.n); syncControls(); refreshSummary(); }));
}

// ------------------------------------------------------------------ belge açma
async function openFile(file) {
  if (!file) return;
  if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") return toast("Lütfen bir PDF dosyası seçin.", true);
  const fd = new FormData();
  fd.append("file", file);
  $("#docname").textContent = `${file.name} – analiz ediliyor…`;
  try {
    const r = await api("/api/open", { method: "POST", body: fd });
    const d = await r.json();
    state.doc = d;
    state.ops = d.pages.map((_, i) => ({ src: i, rotate: 0 }));
    state.pos = 0;
    state.overrides = emptyOverrides();
    state.words = null;
    state.history = []; $("#undo").disabled = true;
    $("#docname").textContent = `${d.name} · ${d.n_pages} sayfa · analiz ${d.analysis_seconds < 0.1 ? "<0,1" : String(d.analysis_seconds).replace(".", ",")} sn`;
    $("#empty").classList.add("hidden");
    $("#export").disabled = false;
    renderThumbs(); refreshAll();
  } catch (e) {
    $("#docname").textContent = "";
    toast(e.message, true);
  }
}

// ------------------------------------------------------------------ önizleme
function imgWidth(el) {
  const w = (el.closest(".frame")?.clientWidth || 700) * (window.devicePixelRatio || 1);
  return Math.min(1800, Math.max(300, Math.ceil(w / 100) * 100));
}
async function refreshPage() {
  if (!state.doc) return;
  const src = curSrc();
  if (src === null) { $("#pageLabel").textContent = "Sayfa yok"; return; }
  $("#pageLabel").textContent = `${state.pos + 1} / ${state.ops.length}`;
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
    if (seq !== state.reqSeq) return; // daha yeni bir istek var
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

// Araca göre seçilebilir öğeler. Beyaz dolgular hiçbir zaman mürekkep harcamadığı için gösterilmez.
function selectable(e) {
  if (state.tool === "text") return e.kind === "text";
  if (state.tool === "crop") return e.kind === "image";
  return e.kind !== "text" && e.cls !== "white";
}
// Tıklanan noktadaki öğeler, en küçüğü önce (üstteki büyük zemin değil, tıklanan şey seçilsin)
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
      d.title = "Alan kuralı: bu alandaki metin her sayfada kaldırılır";
      ov.appendChild(d);
    });
  }
  const els = state.elements.filter(selectable).sort((a, b) => b.area - a.area);
  for (const e of els) {
    const d = document.createElement("div");
    d.className = `el k-${e.kind} c-${e.cls}` + (e.drop ? " drop" : "") + (isManual(e) ? " manual" : "") +
      (state.crop.target?.id === e.id ? " target" : "");
    d.dataset.id = e.id;
    place(d, e.view);
    d.title = describe(e);
    d.tabIndex = 0;
    d.onkeydown = (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      ev.preventDefault(); const r = d.getBoundingClientRect(); activate(e, [], r.left + 8, r.top + 8);
    };
    ov.appendChild(d);
  }
  // kırpma şekilleri (sunucunun hesapladığı, görüntü koordinatlarında)
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
  if (e.kind === "text") return `“${e.text}” · ${e.drop ? "kaldırılacak" : "korunacak"}`;
  let t = `${KIND_TEXT[e.kind] || e.kind} · ${CLS_TEXT[e.cls] || e.cls} · ${e.drop ? "kaldırılacak" : "korunacak"}`;
  if (e.kind === "image" && e.clips) t += " · kırpılmış";
  return t;
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

// ------------------------------------------------------------------ menüler
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
    // ayarı değiştiren eylem: geri alınabilir, önizleme yenilenir
    add(label, fn, hint) { button(label, hint, () => { closeMenu(); snapshot(); fn(); refreshAll(); }); },
    // sadece gezinme (seçimi değiştir, araca geç)
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
  const m = menuStart(x, y, `${KIND_TEXT[e.kind] || e.kind} · ${CLS_TEXT[e.cls] || e.cls} · alan ${pct(e.area)}${n > 1 ? ` · ${n} sayfada var` : ""}`);
  const O = state.overrides;
  if (e.cls === "text_image" && !e.drop) m.note("Yazı içerdiği için otomatik korunuyor.");
  m.add(e.drop ? "Bu sayfada koru" : "Bu sayfada kaldır", () => { O.elements[e.id] = e.drop ? "keep" : "remove"; });
  if (n > 1) {
    m.add(`Tüm sayfalarda kaldır (${n})`, () => { O.signatures[e.sig] = "remove"; delete O.elements[e.id]; });
    m.add(`Tüm sayfalarda koru (${n})`, () => { O.signatures[e.sig] = "keep"; delete O.elements[e.id]; });
  }
  if (e.kind === "image") m.link("Kırp…", () => { setTool("crop"); setCropTarget(e); }, "Görselin bir kısmını bırak veya sil");
  if (O.elements[e.id] || O.signatures[e.sig]) {
    m.sep();
    m.add("Otomatik karara bırak", () => { delete O.elements[e.id]; delete O.signatures[e.sig]; });
  }
  if (others.length) {
    m.sep();
    m.note("Bu noktadaki diğer öğeler");
    others.slice(0, 4).forEach((o) => m.link(`${KIND_TEXT[o.kind] || o.kind} · ${CLS_TEXT[o.cls] || o.cls} · alan ${pct(o.area)}`,
      () => openMenu(o, x, y, [e, ...others.filter((z) => z !== o)])));
  }
  m.show();
}

function openTextMenu(e, x, y) {
  markSelected(e);
  const O = state.overrides;
  const n = e.pages_with_sig, r = e.pages_with_region;
  const m = menuStart(x, y, `Metin${n > 1 ? ` · ${n} sayfada birebir aynı` : ""}<span class="quote">“${esc(short(e.text || "…", 60))}”</span>`);
  if (e.drop) {
    m.add("Bu sayfada koru", () => { O.elements[e.id] = "keep"; });
  } else {
    m.add("Bu sayfada kaldır", () => { O.elements[e.id] = "remove"; });
    if (n > 1) m.add(`Tüm sayfalarda kaldır (${n})`, () => { O.signatures[e.sig] = "remove"; delete O.elements[e.id]; },
      "Sadece aynı yerdeki birebir aynı metin");
    if (r > n) m.add(`Bu konumdaki metni her sayfada kaldır (${r})`, () => { O.regions.push({ box: e.region, action: "remove" }); delete O.elements[e.id]; },
      "İçerik farklı olsa da: sayfa numarası, bölüm adı");
  }
  if (isManual(e)) {
    m.sep();
    m.add("Bu metindeki kararları geri al", () => {
      delete O.elements[e.id]; delete O.signatures[e.sig];
      O.regions = O.regions.filter((rg) => !inRegion(e.view, rg.box));
    }, "Seçim ve alan kurallarını kaldırır");
  }
  m.show();
}

function openSelectionMenu(sel, box, x, y) {
  const O = state.overrides;
  const allDrop = sel.every((e) => e.drop);
  const sameEverywhere = sel.filter((e) => e.pages_with_sig > 1);
  const m = menuStart(x, y, `${sel.length} metin seçildi<span class="quote">${esc(short(sel.map((e) => e.text).join(" · "), 70))}</span>`);
  if (!allDrop) m.add("Seçilenleri bu sayfada kaldır", () => sel.forEach((e) => (O.elements[e.id] = "remove")));
  if (sameEverywhere.length) m.add(`Seçilenleri tüm sayfalarda kaldır`, () => sameEverywhere.forEach((e) => { O.signatures[e.sig] = "remove"; delete O.elements[e.id]; }),
    `Aynı yerdeki birebir aynı metin (${sameEverywhere.length} kutu)`);
  m.add("Bu alandaki metni her sayfada kaldır", () => O.regions.push({ box, action: "remove" }), "İçerik farklı olsa da");
  if (sel.some((e) => e.drop)) { m.sep(); m.add("Seçilenleri bu sayfada koru", () => sel.forEach((e) => (O.elements[e.id] = "keep"))); }
  m.show();
}

function openRegionMenu(k, x, y) {
  const r = state.overrides.regions[k];
  const m = menuStart(x, y, `Alan kuralı · ${r.action === "remove" ? "metin kaldırılıyor" : "metin korunuyor"}`);
  m.add("Alan kuralını sil", () => state.overrides.regions.splice(k, 1));
  m.show();
}
function closeMenu() { $("#menu").hidden = true; $$(".el.sel, .el.picked").forEach((n) => n.classList.remove("sel", "picked")); }

// ------------------------------------------------------------------ kırpma aracı
state.crop = { target: null, shape: "rect", mode: "keep", all: false };

function setCropTarget(e) {
  state.crop.target = e;
  state.crop.all = state.crop.all && e && e.pages_with_sig > 1;
  syncCropBar(); drawOverlay();
}
function syncCropBar() {
  const c = state.crop, e = c.target;
  $("#cropbar").hidden = state.tool !== "crop";
  $("#cropStatus").textContent = e
    ? `Seçili görsel · alan ${pct(e.area)}${e.cls === "text_image" ? " · yazı içeriyor" : ""} — üzerinde sürükleyin`
    : "Kırpmak için bir görsele tıklayın";
  $$("#cropShape button").forEach((b) => b.classList.toggle("on", b.dataset.v === c.shape));
  $$("#cropMode button").forEach((b) => b.classList.toggle("on", b.dataset.v === c.mode));
  const n = e ? e.pages_with_sig : 0;
  $("#cropAll").disabled = !e || n < 2;
  $("#cropAll").checked = !!(e && c.all);
  $("#cropAllLabel").textContent = n > 1 ? `Aynı görsele tüm sayfalarda uygula (${n})` : "Aynı görsele tüm sayfalarda uygula";
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

// ------------------------------------------------------------------ önizleme üzerindeki fare hareketleri
// Tıklama: noktadaki en küçük öğe. Sürükleme: Metin seç aracında alan seçimi, Kırp aracında çizim.
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
      activate(hs[0], hs.slice(1), ev.clientX, ev.clientY);
      return;
    }
    if (state.tool === "text") {
      const box = [pts[0][0], pts[0][1], pts[2][0], pts[2][1]];
      const sel = state.elements.filter((e) => e.kind === "text" && inRegion(e.view, box));
      if (!sel.length) return toast("Bu alanda metin yok.");
      sel.forEach((e) => ov.querySelector(`[data-id="${e.id}"]`)?.classList.add("picked"));
      setTimeout(() => openSelectionMenu(sel, box, ev.clientX, ev.clientY), 0);
    } else if (state.tool === "crop" && pts.length >= 3) {
      addCrop(state.crop.mode, pts);
    }
  });
}

function setTool(t) {
  state.tool = t;
  $$("#tool button").forEach((b) => { const on = b.dataset.t === t; b.classList.toggle("on", on); b.setAttribute("aria-checked", on); });
  $("#legendGraphics").hidden = t !== "graphics";
  $("#legendText").hidden = t !== "text";
  $("#capBefore").textContent = {
    text: "Orijinal · metne tıklayın veya sürükleyerek alan seçin",
    crop: "Orijinal · görsele tıklayın, sonra kırpmak için üzerinde sürükleyin",
    graphics: "Orijinal · öğeye tıklayıp karar verin",
  }[t];
  if (t !== "crop") state.crop.target = null;
  syncCropBar(); closeMenu(); drawOverlay();
}

// ------------------------------------------------------------------ özet ve mürekkep
const refreshSummary = debounce(async () => {
  if (!state.doc) return;
  try {
    const d = await (await post(`/api/doc/${state.doc.id}/summary`, job())).json();
    const o = d.ink.original, p = d.ink.processed;
    const scale = Math.max(o, 0.05);
    $("#inkBefore").style.height = `${Math.min(100, (o / scale) * 92)}%`;
    $("#inkAfter").style.height = `${Math.min(100, (p / scale) * 92)}%`;
    $("#savingPct").textContent = pct(Math.max(0, d.ink.saving));
    $("#savingNote").textContent = `daha az mürekkep · ${d.removed} öğe kaldırılıyor · ${d.ink.pages} örnek sayfaya göre`;
  } catch (e) { toast(e.message, true); }
}, 350);

function refreshAll() { refreshPage(); refreshSummary(); refreshWords(); }

// ------------------------------------------------------------------ sayfa şeridi
function renderThumbs() {
  const ol = $("#thumbs");
  ol.innerHTML = "";
  if (!state.doc) return;
  $("#railCount").textContent = `${state.ops.length} / ${state.doc.n_pages} sayfa`;
  state.ops.forEach((op, i) => {
    const p = state.doc.pages[op.src];
    const li = document.createElement("li");
    li.className = "thumb" + (i === state.pos ? " cur" : "");
    const rot = op.rotate % 180 !== 0;
    li.style.setProperty("--ar", rot ? `${p.h}/${p.w}` : `${p.w}/${p.h}`);
    li.innerHTML = `<button class="pick" aria-label="Sayfa ${i + 1}"><div class="tw"><img loading="lazy" alt="" src="/api/doc/${state.doc.id}/original/${op.src}.png?w=280" style="transform:rotate(${op.rotate}deg);${rot ? `width:${(p.h / p.w) * 100}%` : ""}"></div></button>
      <div class="meta"><span>${i + 1}${op.src !== i ? ` <small>(orj. ${op.src + 1})</small>` : ""}</span><span class="acts">
      <button data-a="up" title="Yukarı taşı" aria-label="Yukarı taşı">↑</button><button data-a="down" title="Aşağı taşı" aria-label="Aşağı taşı">↓</button>
      <button data-a="rot" title="Döndür" aria-label="Döndür">↻</button><button data-a="del" title="Sayfayı çıktıdan çıkar" aria-label="Sayfayı sil">✕</button></span></div>`;
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
  renderThumbs(); refreshPage(); refreshWords();
}
function goTo(i) {
  if (!state.ops.length) return;
  state.pos = Math.max(0, Math.min(state.ops.length - 1, i));
  $$(".thumb").forEach((t, k) => t.classList.toggle("cur", k === state.pos));
  $$(".thumb")[state.pos]?.scrollIntoView({ block: "nearest" });
  closeMenu(); refreshPage();
}

// ------------------------------------------------------------------ kelime sayacı
const STOP = new Set(("der die das und in zu den von mit ist im dem nicht ein eine einer eines einem einen für auf auch es sich des sie wir " +
  "ich er als an bei aus oder wie so zum zur nach vom über unter durch wird werden wurde sind war hat haben kann können man nur noch wenn dass " +
  "da was wo um am aber bis bzw ggf usw sowie z b d h " +
  "the a an and or of to in on for is are be with as by at from this that it not can will was were has have its into if then than " +
  "ve ile bir bu da de için çok gibi daha olan ama ya veya mi mı mu mü ne o şu").split(" "));
const SORTS = [["desc", "En çok → en az"], ["asc", "En az → en çok"], ["alpha", "A → Z"]];
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
  const q = $("#wordSearch").value.trim().toLocaleLowerCase("tr");
  const hideStop = $("#wStop").checked, hideNum = $("#wNum").checked;
  let list = words.data.words.filter((w) => {
    const k = w.w.toLocaleLowerCase("de");
    if (hideNum && w.num) return false;
    if (hideStop && (STOP.has(k) || w.w.length < 2)) return false;
    return !q || w.w.toLocaleLowerCase("tr").includes(q);
  });
  const mode = SORTS[words.sort][0];
  if (mode === "asc") list = [...list].sort((a, b) => a.n - b.n || a.w.localeCompare(b.w, "de"));
  else if (mode === "alpha") list = [...list].sort((a, b) => a.w.localeCompare(b.w, "de"));
  else list = [...list].sort((a, b) => b.n - a.n || a.w.localeCompare(b.w, "de"));
  return list;
}

function renderWords() {
  const ol = $("#words");
  const list = visibleWords();
  const d = words.data;
  $("#wordSort").textContent = SORTS[words.sort][1];
  $("#wordSum").textContent = d ? `${d.total.toLocaleString("tr")} kelime · ${d.unique.toLocaleString("tr")} farklı · ${list.length.toLocaleString("tr")} gösteriliyor` : "";
  const max = list.reduce((m, w) => Math.max(m, w.n), 1);
  const LIMIT = 1500;
  ol.innerHTML = list.slice(0, LIMIT).map((w, i) =>
    `<li tabindex="0" data-i="${i}" title="${w.pages.length} sayfada · s. ${esc(w.pages.slice(0, 30).map((p) => p + 1).join(", "))}${w.pages.length > 30 ? "…" : ""}">
       <span class="w">${esc(w.w)}</span><span class="n">${w.n}</span><span class="bar" style="width:calc(${(w.n / max) * 100}% - 12px)"></span></li>`).join("") +
    (list.length > LIMIT ? `<li class="more">İlk ${LIMIT} kelime gösteriliyor; daraltmak için arayın.</li>` : "");
  ol.querySelectorAll("li[data-i]").forEach((li) => {
    const w = list[Number(li.dataset.i)];
    const go = () => jumpToWord(w);
    li.onclick = go;
    li.onkeydown = (e) => { if (e.key === "Enter") go(); };
  });
}

function jumpToWord(w) {
  // her tıklamada kelimenin geçtiği bir sonraki sayfaya git
  const positions = state.ops.map((o, i) => (w.pages.includes(o.src) ? i : -1)).filter((i) => i >= 0);
  if (!positions.length) return;
  const next = positions.find((i) => i > state.pos) ?? positions[0];
  goTo(next);
  toast(`“${w.w}”: ${positions.indexOf(next) + 1}/${positions.length}. sayfa`);
}

function exportCsv() {
  const list = visibleWords();
  const rows = [["kelime", "adet", "sayfa_sayisi", "sayfalar"], ...list.map((w) => [w.w, w.n, w.pages.length, w.pages.map((p) => p + 1).join(" ")])];
  const csv = "﻿" + rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(";")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  a.download = `${(state.doc?.name || "belge").replace(/\.pdf$/i, "")}_kelimeler.csv`; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

function showTab(which) {
  const words_ = which === "words";
  $("#tabPages").setAttribute("aria-selected", !words_); $("#tabWords").setAttribute("aria-selected", words_);
  $("#panePages").hidden = words_; $("#paneWords").hidden = !words_;
  if (words_) refreshWords();
}

// ------------------------------------------------------------------ dışa aktarma
async function doExport() {
  const b = $("#export");
  b.disabled = true; const label = b.textContent; b.textContent = "Hazırlanıyor…";
  try {
    const r = await post(`/api/doc/${state.doc.id}/export`, job({ ops: state.ops }));
    const blob = await r.blob();
    const cd = r.headers.get("Content-Disposition") || "";
    const utf8 = cd.match(/filename\*=UTF-8''([^;]+)/);
    const name = (utf8 && decodeURIComponent(utf8[1])) || (cd.match(/filename="(.+?)"/) || [])[1] || "baski.pdf";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    toast(`İndirildi: ${name}`);
  } catch (e) { toast(e.message, true); }
  finally { b.disabled = false; b.textContent = label; }
}

// ------------------------------------------------------------------ profiller
let profiles = [];
async function loadProfiles(select) {
  profiles = await (await api("/api/profiles")).json();
  const sel = $("#profiles");
  sel.innerHTML = profiles.map((p, i) => `<option value="${i}">${p.name.replace(/</g, "&lt;")}${p.builtin ? " (hazır)" : ""}</option>`).join("");
  if (select) { const i = profiles.findIndex((p) => p.name === select && !p.builtin); if (i >= 0) sel.value = i; }
}
function bindProfiles() {
  $("#profApply").onclick = () => {
    const p = profiles[Number($("#profiles").value)];
    if (!p) return;
    snapshot(); state.settings = { ...p.settings }; syncControls(); refreshAll();
    toast(`"${p.name}" profili uygulandı.`);
  };
  $("#profSave").onclick = async () => {
    const name = prompt("Profil adı (ör. Ders slaydı – istatistik):");
    if (!name) return;
    try { const r = await (await api(`/api/profiles/${encodeURIComponent(name)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state.settings) })).json();
      await loadProfiles(r.name); toast(`"${r.name}" profili kaydedildi.`); } catch (e) { toast(e.message, true); }
  };
  $("#profDelete").onclick = async () => {
    const p = profiles[Number($("#profiles").value)];
    if (!p) return;
    if (p.builtin) return toast("Hazır profiller silinemez.", true);
    if (!confirm(`"${p.name}" profili silinsin mi?`)) return;
    try { await api(`/api/profiles/${encodeURIComponent(p.name)}`, { method: "DELETE" }); await loadProfiles(); toast("Profil silindi."); }
    catch (e) { toast(e.message, true); }
  };
}

// ------------------------------------------------------------------ başlangıç
async function init() {
  state.tiers = await (await api("/api/tiers")).json();
  state.settings = { ...state.tiers[1].settings };
  buildTiers(); bindControls(); bindProfiles(); syncControls();
  loadProfiles().catch(() => {});

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
    if (e.key === "k") setTool(state.tool === "crop" ? "graphics" : "crop");
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
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); return; }
    if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
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
