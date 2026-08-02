"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const state = {
  filters: { type: "gguf", company: "", capability: "", size: "", domain: "", sort: "downloads", period: "30d" },
  sortTouched: false,
  settings: {}, system: {}, results: [], pollTimer: null, watch: new Set(),
};

async function api(path, opts) {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ("Request failed (" + r.status + ")"));
  return data;
}
const post = (path, body) => api(path, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});

function toast(msg, isErr) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  t.className = isErr ? "err" : "";
  clearTimeout(t._h); t._h = setTimeout(() => (t.hidden = true), 4000);
}

function fmtBytes(n) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0; while (n >= 1000 && i < 4) { n /= 1000; i++; }
  return n.toFixed(n >= 100 || i === 0 ? 0 : 1) + " " + u[i];
}
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

// ---- tabs ----
$$(".tab").forEach((b) => b.addEventListener("click", () => {
  $$(".tab").forEach((x) => x.classList.toggle("active", x === b));
  $$(".pane").forEach((p) => p.classList.toggle("active", p.id === "tab-" + b.dataset.tab));
  if (b.dataset.tab === "library") loadLibrary();
  if (b.dataset.tab === "downloads") pollDownloads();
}));

// ---- theme ----
$("#themeBtn").addEventListener("click", () => {
  const next = document.body.dataset.theme === "dark" ? "light" : "dark";
  document.body.dataset.theme = next;
  post("/api/settings", { theme: next }).catch(() => {});
});

// ---- header / system ----
async function refreshSystem() {
  try {
    state.system = await api("/api/system");
    const pill = $("#destPill");
    if (!state.system.destination) {
      $("#destPath").textContent = "No destination: choose in Settings";
      $("#destFree").textContent = ""; pill.classList.add("warn");
    } else if (!state.system.connected) {
      $("#destPath").textContent = state.system.destination;
      $("#destFree").textContent = "drive not connected"; pill.classList.add("warn");
    } else {
      $("#destPath").textContent = state.system.destination;
      $("#destFree").textContent = fmtBytes(state.system.disk.free) + " free";
      pill.classList.remove("warn");
    }
    const gib = (n) => Math.round(n / 1073741824) + " GB";  // RAM is marketed in binary GB
    const src = state.system.ram_source === "manual"
      ? " (manual, this Mac has " + gib(state.system.ram_detected) + ")"
      : " (this Mac, detected)";
    $("#ramInfo").textContent = gib(state.system.ram) + src;
  } catch (e) { /* server briefly busy — retried on next tick */ }
}

// ---- settings ----
async function loadSettings() {
  state.settings = await api("/api/settings");
  document.body.dataset.theme = state.settings.theme || "dark";
  $("#setDest").textContent = state.settings.destination || "none chosen";
  const rec = $("#recents"); rec.replaceChildren();
  (state.settings.recent_destinations || []).forEach((p) => {
    if (p === state.settings.destination) return;
    const b = el("button", "chip", p);
    b.addEventListener("click", () => saveSettings({ destination: p }));
    rec.append(b);
  });
  $$("#quantPref .chip").forEach((c) =>
    c.classList.toggle("active", c.dataset.v === state.settings.preferred_quant));
  $("#ramSel").value = String(state.settings.ram_override_gb || 0);
  $("#hfToken").value = state.settings.hf_token || "";
}
$("#tokenBtn").addEventListener("click", () =>
  saveSettings({ hf_token: $("#hfToken").value.trim() }));
$("#ramSel").addEventListener("change", () =>
  saveSettings({ ram_override_gb: Number($("#ramSel").value) }));
async function saveSettings(patch) {
  try {
    await post("/api/settings", patch);
    await loadSettings(); await refreshSystem();
    toast("Settings saved");
  } catch (e) { toast(e.message, true); }
}
$("#pickBtn").addEventListener("click", async () => {
  try {
    const r = await post("/api/pick-folder");
    if (!r.canceled && r.path) await saveSettings({ destination: r.path });
  } catch (e) { toast(e.message, true); }
});
$("#quantPref").addEventListener("click", (ev) => {
  const c = ev.target.closest(".chip");
  if (c) saveSettings({ preferred_quant: c.dataset.v });
});

// ---- filter chips ----
// Type row is MULTI-select (at least one stays on); other rows are
// single-select where clicking the active chip clears it.
function syncTypeRows() {
  const types = state.filters.type.split(",");
  const chat = types.includes("gguf") || types.includes("mlx");
  const img = types.includes("image");
  $("#capText").hidden = !chat;
  $("#capImage").hidden = !img;
  $("#sizeRow").hidden = !chat;
}
$("#filters").addEventListener("click", (ev) => {
  const chip = ev.target.closest(".chip");
  if (!chip) return;
  const row = chip.parentElement, group = row.dataset.group;
  if (row.dataset.multi) {
    if (group === "type") {
      const actives = row.querySelectorAll(".chip.active");
      if (chip.classList.contains("active") && actives.length === 1) return; // keep >= 1
    }
    chip.classList.toggle("active");
    // Union across every row of this group (both capability rows share one value).
    state.filters[group] = $$('[data-group="' + group + '"] .chip.active')
      .map((c) => c.dataset.v).join(",");
  } else {
    const wasActive = chip.classList.contains("active");
    $$('[data-group="' + group + '"] .chip').forEach((c) => c.classList.remove("active"));
    if (!wasActive || group === "sort") chip.classList.add("active");
    state.filters[group] = chip.classList.contains("active") ? chip.dataset.v : "";
    if (group === "sort" || group === "period") {
      state.sortTouched = true;
      if (!row.querySelector(".chip.active")) {          // period/sort always keep one
        chip.classList.add("active");
        state.filters[group] = chip.dataset.v;
      }
    }
    if (group === "sort") {
      // Progressive disclosure: the Period options belong to "Most downloaded".
      // First click reveals them; clicking it again folds them away.
      if (chip.dataset.v === "downloads") {
        $("#periodRow").hidden = wasActive ? !$("#periodRow").hidden : false;
      } else {
        $("#periodRow").hidden = true;
      }
    }
  }
  if (group === "type") {
    syncTypeRows();
    // Drop capability/size choices that no longer apply to the selected types.
    const types = state.filters.type.split(",");
    const chat = types.includes("gguf") || types.includes("mlx");
    const img = types.includes("image");
    if (!chat) {
      state.filters.size = "";
      $$("#sizeRow .chip, #capText .chip").forEach((c) => c.classList.remove("active"));
    }
    if (!img) $$("#capImage .chip").forEach((c) => c.classList.remove("active"));
    state.filters.capability =
      $$('[data-group="capability"] .chip.active').map((c) => c.dataset.v).join(",");
  }
  if (group === "company") $("#companyFree").value = "";
  runSearch();
});
$("#companyFree").addEventListener("change", () => {
  $$('[data-group="company"] .chip').forEach((c) => c.classList.remove("active"));
  state.filters.company = $("#companyFree").value.trim();
  runSearch();
});
$("#homeBtn").addEventListener("click", () => {
  $("#q").value = "";
  state.filters.company = ""; state.filters.capability = "";
  state.filters.size = ""; state.filters.domain = "";
  state.filters.sort = "downloads"; state.filters.period = "30d"; state.sortTouched = false;
  $$("#filters .chip").forEach((c) => c.classList.remove("active"));
  document.querySelector('[data-group="type"] .chip[data-v="gguf"]').classList.add("active");
  state.filters.type = "gguf";
  document.querySelector('[data-group="sort"] .chip[data-v="downloads"]').classList.add("active");
  document.querySelector('[data-group="period"] .chip[data-v="30d"]').classList.add("active");
  $("#periodRow").hidden = true;
  $("#companyFree").value = "";
  syncTypeRows();
  runSearch();
});
$("#goBtn").addEventListener("click", runSearch);
$("#q").addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); });

// ---- search ----
const CAP_LABELS = { vision: "Vision", thinking: "Thinking", agentic: "Agentic", coding: "Coding" };

async function runSearch() {
  const f = state.filters;
  const qs = new URLSearchParams({ q: $("#q").value.trim(), type: f.type,
    company: f.company, capability: f.capability, size: f.size, domain: f.domain,
    sort: f.sort, period: f.period });
  const dpane = $("#detail");
  dpane.hidden = true; state.detailFor = null;
  $("#results").after(dpane);   // rescue it before the grid is wiped
  if (searchIsEmpty()) { showDiscover(); return; }
  $("#results").replaceChildren(el("div", "msg", "Searching Hugging Face…"));
  try {
    const data = await api("/api/search?" + qs);
    state.results = data.results;
    renderResults();
  } catch (e) {
    $("#results").replaceChildren(el("div", "msg", e.message));
  }
}

function starBtn(m) {
  const b = el("button", "star" + (state.watch.has(m.id) ? " on" : ""),
               state.watch.has(m.id) ? "★" : "☆");
  b.title = "Watchlist: save for later without downloading";
  b.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    try {
      if (state.watch.has(m.id)) {
        await post("/api/watchlist/remove", { id: m.id });
        state.watch.delete(m.id);
      } else {
        await post("/api/watchlist", { id: m.id, mtype: m.mtype || "gguf" });
        state.watch.add(m.id);
      }
      b.textContent = state.watch.has(m.id) ? "★" : "☆";
      b.classList.toggle("on", state.watch.has(m.id));
    } catch (e) { toast(e.message, true); }
  });
  return b;
}

function buildCard(m, showFmt) {
  const FMT = { gguf: "GGUF", mlx: "MLX", image: "IMG" };
  const c = el("div", "card");
  const name = el("span", "name", m.id);
  if (showFmt && FMT[m.mtype]) name.append(el("span", "pill fmt", FMT[m.mtype]));
  if (m.params && m.params.moe) name.append(el("span", "pill moe", "MoE"));
  if (m.bucket) name.append(el("span", "pill", m.bucket.replace("<=", "≤")));
  (m.caps || []).forEach((cap) => CAP_LABELS[cap] && name.append(el("span", "pill", CAP_LABELS[cap])));
  if (m.gated) name.append(el("span", "pill gated", "gated"));
  const date = (m.created || m.updated || "").slice(0, 10);
  const dl = (m.downloads_all != null)
    ? m.downloads_all.toLocaleString() + " downloads (all time)"
    : (m.downloads || 0).toLocaleString() + " downloads (30d)";
  const meta = el("span", "meta", dl + " · " + (m.likes || 0) + " ♥ · " + date);
  c.append(name, meta, starBtn(m));
  c.addEventListener("click", () => openDetail(m, c));
  return c;
}

const PERIOD_TITLES = { "30d": "Most downloaded · last 30 days",
  all: "Most downloaded · all time",
  "6m": "Top models released in the last 6 months",
  "1y": "Top models released in the last year" };
const SORT_TITLES = { trending: "Trending right now · momentum over the past few days",
  newest: "Newest releases · first published, newest at the top" };
function browseTitle() {
  return state.filters.sort === "downloads"
    ? PERIOD_TITLES[state.filters.period] || ""
    : SORT_TITLES[state.filters.sort] || "";
}

function renderResults() {
  const box = $("#results"); box.replaceChildren();
  $("#homeBtn").hidden = false;
  if (!state.results.length) {
    box.append(el("div", "msg", "No models found. Try fewer filters or another search term."));
    return;
  }
  if (!$("#q").value.trim()) {
    box.append(el("div", "feed-head", browseTitle()));
  }
  const multiType = state.filters.type.includes(",");
  state.results.forEach((m) => box.append(buildCard(m, multiType)));
}

function searchIsEmpty() {
  const f = state.filters;
  return !$("#q").value.trim() && !f.company && !f.capability && !f.size && !f.domain &&
    !state.sortTouched;
}

async function showDiscover() {
  const box = $("#results");
  $("#homeBtn").hidden = true;
  box.replaceChildren(el("div", "msg", "Loading discovery feed…"));
  try {
    const [wl, feed] = await Promise.all([api("/api/watchlist"), api("/api/discover")]);
    state.watch = new Set(wl.watchlist.map((w) => w.id));
    box.replaceChildren();
    if (wl.watchlist.length) {
      box.append(el("div", "feed-head", "⭐ Your watchlist"));
      wl.watchlist.forEach((w) => box.append(buildCard(
        { id: w.id, mtype: w.mtype, downloads: 0, likes: 0, updated: "" }, false)));
    }
    feed.sections.forEach((sec) => {
      box.append(el("div", "feed-head", sec.title));
      sec.cards.forEach((m) => box.append(buildCard(m, false)));
    });
  } catch (e) {
    box.replaceChildren(el("div", "msg", e.message));
  }
}

async function openDetail(card, cardEl) {
  const d = $("#detail");
  // Clicking the open model again collapses it.
  if (!d.hidden && state.detailFor === card.id) {
    d.hidden = true; state.detailFor = null;
    return;
  }
  state.detailFor = card.id;
  const token = (state.detailToken = (state.detailToken || 0) + 1);
  if (cardEl) cardEl.after(d);          // expand right under the clicked model
  d.hidden = false;
  d.replaceChildren(el("div", "msg", "Loading " + card.id + "…"));
  try {
    // Routing (ComfyUI subfolder) needs one image capability, not the whole list.
    const imageCap = state.filters.capability.split(",")
      .find((c) => ["image-gen", "video-gen", "lora", "upscaler"].includes(c)) || "";
    const qs = new URLSearchParams({ id: card.id, type: card.mtype || state.filters.type.split(",")[0],
      capability: imageCap });
    const m = await api("/api/model?" + qs);
    if (token !== state.detailToken) return;   // a newer click superseded this one
    m.mtype = card.mtype || state.filters.type.split(",")[0];
    d.replaceChildren();
    const head = el("div", "dhead");
    head.append(el("h2", "", m.id));
    const close = el("button", "ghost", "Close ✕");
    close.addEventListener("click", () => { d.hidden = true; state.detailFor = null; });
    head.append(close);
    d.append(head);
    const badges = el("div", "dbadges");
    if (m.params && m.params.moe) badges.append(el("span", "pill moe", "MoE"));
    (m.caps || []).forEach((cap) => CAP_LABELS[cap] && badges.append(el("span", "pill", CAP_LABELS[cap])));
    if (m.gated) badges.append(el("span", "pill gated", "requires HF account"));
    if (m.license_verdict) badges.append(
      el("span", "pill lic-" + m.license_verdict.level, m.license_verdict.text));
    const link = el("a", "hflink", "Open on Hugging Face ↗");
    link.href = m.hf_url || "https://huggingface.co/" + m.id;
    link.target = "_blank"; link.rel = "noopener";
    badges.append(link);
    d.append(badges);
    let metaTxt = m.downloads.toLocaleString() + " downloads · license: " + m.license +
      " · updated " + (m.updated || "").slice(0, 10);
    if (m.params) metaTxt += " · " + m.params.total_b + "B parameters";
    d.append(el("div", "dmeta", metaTxt));
    if (m.moe_note) d.append(el("div", "dmeta", "Mixture-of-Experts: " + m.moe_note));
    if (m.description) d.append(el("p", "desc", m.description));
    if (m.gated) {
      d.append(el("div", "msg", m.gated_reason ||
        "This model is gated: it needs a free Hugging Face account and a saved token " +
        "(Settings), plus accepting the license on the model's page."));
      return;
    }
    if (!m.variants.length) {
      d.append(el("div", "msg", "No downloadable files of this type found in this repository."));
      return;
    }
    const prefFam = state.settings.preferred_quant || "";
    // Mirror server-side quant_family: IQ4_XS -> Q4, F16/BF16 stay themselves.
    const famOf = (q) => {
      if (!q) return "";
      if (q.startsWith("MLX")) return q;
      const m = q.match(/^I?Q(\d)/);
      return m ? "Q" + m[1] : q;
    };
    m.variants.forEach((v) => {
      const row = el("div", "variant");
      if (prefFam && famOf(v.quant) === prefFam) row.classList.add("preferred");
      const fit = el("span", "fit " + v.fits);
      fit.title = { green: "Runs comfortably on this Mac", orange: "Tight, will be slow",
        red: "Won't fit in this Mac's memory", unknown: "RAM unknown" }[v.fits];
      row.append(fit);
      row.append(el("span", "vname", v.label + (v.subfolder ? "  → comfyui/" + v.subfolder : "")));
      row.append(el("span", "vsize", fmtBytes(v.size)));
      const btn = el("button", "primary", "Download");
      if (v.already) {
        btn.disabled = true; btn.textContent = "In library ✓";
        btn.classList.add("owned");
        btn.title = "Already downloaded to this destination. Delete it in Library to re-download.";
      } else if (!v.will_fit_disk) { btn.disabled = true; btn.textContent = "Won't fit on drive"; }
      btn.addEventListener("click", async () => {
        try {
          await post("/api/download", { model_id: m.id, variant_label: v.label,
            files: v.files, mtype: m.mtype, capability: imageCap });
          toast("Added to downloads: " + v.label);
          $('[data-tab="downloads"]').click();
        } catch (e) { toast(e.message, true); }
      });
      row.append(btn);
      d.append(row);
    });
  } catch (e) {
    d.replaceChildren(el("div", "msg", e.message));
  }
}

// ---- downloads ----
const speedTrack = {}; // job_id -> {bytes, t}

function renderDownloads(jobs) {
  const box = $("#dlList"); box.replaceChildren();
  const active = jobs.filter((j) => j.state === "active" || j.state === "queued").length;
  const badge = $("#dlBadge");
  badge.hidden = !active; badge.textContent = active;
  if (!jobs.length) { box.append(el("div", "msg", "No downloads yet. Find a model in Search.")); return; }
  jobs.forEach((j) => {
    const item = el("div", "dl-item");
    const top = el("div", "dl-top");
    top.append(el("span", "dl-label", j.label));
    let stats = j.state;
    if (j.state === "active") {
      const prev = speedTrack[j.id], now = Date.now();
      let speed = 0;
      if (prev) speed = Math.max(0, (j.downloaded_bytes - prev.bytes) / ((now - prev.t) / 1000));
      speedTrack[j.id] = { bytes: j.downloaded_bytes, t: now };
      const remain = speed > 0 ? (j.total_bytes - j.downloaded_bytes) / speed : 0;
      stats = fmtBytes(j.downloaded_bytes) + " / " + fmtBytes(j.total_bytes) +
        (speed ? " · " + fmtBytes(speed) + "/s" : "") +
        (remain ? " · ~" + (remain > 90 ? Math.round(remain / 60) + " min" : Math.round(remain) + " s") + " left" : "");
    } else if (j.state === "done") {
      stats = "done · " + fmtBytes(j.total_bytes);
    }
    top.append(el("span", "dl-stats", stats));
    const mk = (label, action) => {
      const b = el("button", "ghost", label);
      b.addEventListener("click", async () => {
        await post("/api/downloads/action", { id: j.id, action });
        pollDownloads();
      });
      return b;
    };
    if (j.state === "active") top.append(mk("Pause", "pause"));
    if (j.state === "paused" || j.state === "error") top.append(mk("Resume", "resume"));
    if (j.state !== "done") top.append(mk("Cancel", "cancel"));
    item.append(top);
    const bar = el("div", "bar"); const fill = el("div");
    fill.style.width = (j.total_bytes ? (100 * j.downloaded_bytes / j.total_bytes) : 0) + "%";
    bar.append(fill); item.append(bar);
    if (j.error) item.append(el("div", "dl-err", j.error));
    box.append(item);
  });
}

async function pollDownloads() {
  clearTimeout(state.pollTimer);
  try {
    const data = await api("/api/downloads");
    renderDownloads(data.jobs);
    if (data.jobs.some((j) => j.state === "active" || j.state === "queued")) {
      state.pollTimer = setTimeout(pollDownloads, 1000);
    }
  } catch (e) { /* transient */ }
}
$("#clearDone").addEventListener("click", async () => {
  await post("/api/downloads/action", { action: "clear_done" });
  pollDownloads();
});

// ---- library ----
const LIB_CAPS = { vision: "Vision", thinking: "Thinking", agentic: "Agentic", coding: "Coding" };
const FIT_TITLES = { green: "Runs comfortably on this Mac", orange: "Tight, will be slow",
  red: "Won't fit in this Mac's memory", unknown: "Memory unknown" };

function libActions(path) {
  const rev = el("button", "ghost", "Reveal");
  rev.addEventListener("click", () => post("/api/reveal", { path }));
  const del = el("button", "ghost", "Delete");
  del.addEventListener("click", async () => {
    if (!confirm("Move to Trash?\n\n" + path)) return;
    try { await post("/api/library/delete", { path }); toast("Moved to Trash"); state.lib = null; loadLibrary(); }
    catch (e) { toast(e.message, true); }
  });
  const ver = el("button", "ghost", "Verify");
  ver.title = "Re-check this model against its recorded checksums (big models take a while)";
  ver.addEventListener("click", async () => {
    ver.textContent = "Verifying…"; ver.disabled = true;
    try {
      const r = await post("/api/library/verify", { path });
      if (r.no_record) toast(r.note);
      else if (r.healthy) toast(r.results.length + " file(s) verified, all healthy ✓");
      else toast("Problem found: " + r.results.filter((x) => x.status !== "ok")
        .map((x) => x.file + " " + x.status).join("; "), true);
    } catch (e) { toast(e.message, true); }
    ver.textContent = "Verify"; ver.disabled = false;
  });
  return [ver, rev, del];
}

$("#libCopy").addEventListener("click", async () => {
  if (!state.lib) return;
  const rows = state.lib.text_models.map((m) =>
    "| " + m.company + "/" + m.model + " | " + m.format + " " + (m.quants.join(", ") || "") +
    " | " + fmtBytes(m.size) + " | " + ((m.params && m.params.total_b) ? m.params.total_b + "B" : "") +
    ((m.params && m.params.moe) ? " MoE" : "") + " | " + (m.caps || []).join(", ") +
    " | https://huggingface.co/" + m.company + "/" + m.model.replace(/-GGUF$|-MLX.*$/i, "") + " |");
  const md = ["| Model | Format | Size | Params | Capabilities | Link |",
              "|---|---|---|---|---|---|"].concat(rows).join("\n");
  try { await navigator.clipboard.writeText(md); toast("Library copied as Markdown"); }
  catch (e) { toast("Could not copy: " + e.message, true); }
});

function renderLibrary() {
  const lib = state.lib;
  const box = $("#libList"); box.replaceChildren();
  const q = ($("#libFilter").value || "").trim().toLowerCase();
  const sort = $("#libSort").value;
  const matches = (hay) => !q || hay.toLowerCase().includes(q);
  const text = lib.text_models.filter((m) => matches(
    [m.company, m.model, m.format, m.quants.join(" "), (m.caps || []).join(" "),
     m.params && m.params.moe ? "moe" : ""].join(" ")));
  const sorters = {
    date: (a, b) => b.mtime - a.mtime,
    size: (a, b) => b.size - a.size,
    name: (a, b) => a.model.localeCompare(b.model),
    company: (a, b) => a.company.localeCompare(b.company) || a.model.localeCompare(b.model),
  };
  text.sort(sorters[sort] || sorters.date);
  if (text.length) {
    const g = el("div", "lib-group"); g.append(el("h3", "", "Chat & text models"));
    text.forEach((m) => {
      const it = el("div", "lib-item");
      const nm = el("div", "lib-name");
      const fit = el("span", "fit " + (m.fits || "unknown"));
      fit.title = FIT_TITLES[m.fits || "unknown"];
      nm.append(fit, el("span", "", m.company + " / " + m.model));
      if (m.params && m.params.moe) nm.append(el("span", "pill moe", "MoE"));
      if (m.params && m.params.total_b) nm.append(el("span", "pill", m.params.total_b + "B"));
      (m.caps || []).forEach((c) => LIB_CAPS[c] && nm.append(el("span", "pill", LIB_CAPS[c])));
      if (m.incomplete) nm.append(el("span", "pill gated", "incomplete"));
      it.append(nm, el("span", "meta", m.format + " · " + (m.quants.join(", ") || "n/a") +
        " · " + fmtBytes(m.size) + " · " + new Date(m.mtime * 1000).toLocaleDateString()));
      it.append(...libActions(m.path));
      g.append(it);
    });
    box.append(g);
  }
  const comfy = lib.comfy_models.filter((m) => matches(m.name + " " + m.subfolder));
  if (comfy.length) {
    const g = el("div", "lib-group"); g.append(el("h3", "", "Image & video models (ComfyUI)"));
    comfy.forEach((m) => {
      const it = el("div", "lib-item");
      it.append(el("span", "", m.name),
        el("span", "meta", m.subfolder + " · " + fmtBytes(m.size)));
      it.append(...libActions(m.path));
      g.append(it);
    });
    box.append(g);
  }
  if (!text.length && !comfy.length) {
    box.append(el("div", "msg", q ? "No models match this filter."
      : "Nothing downloaded yet to this destination."));
  }
}

async function loadLibrary() {
  const box = $("#libList");
  if (!state.lib) box.replaceChildren(el("div", "msg", "Reading destination…"));
  try {
    const lib = await api("/api/library");
    if (!lib.connected) {
      $("#libStats").textContent = ""; $("#libBar").hidden = true;
      box.replaceChildren(el("div", "msg",
        "Destination drive is not connected (or no destination chosen in Settings)."));
      return;
    }
    const count = lib.text_models.length + lib.comfy_models.length;
    $("#libStats").textContent = count + (count === 1 ? " model · " : " models · ") +
      fmtBytes(lib.total_bytes) + " · Free on drive: " + fmtBytes(lib.disk.free);
    $("#libBar").hidden = false;
    state.lib = lib;
    renderLibrary();
  } catch (e) {
    box.replaceChildren(el("div", "msg", e.message));
  }
}
$("#libFilter").addEventListener("input", () => state.lib && renderLibrary());
$("#libSort").addEventListener("change", () => state.lib && renderLibrary());

// ---- boot ----
(async function boot() {
  syncTypeRows();
  await loadSettings();
  await refreshSystem();
  setInterval(refreshSystem, 5000);
  pollDownloads();
  showDiscover();
})();
