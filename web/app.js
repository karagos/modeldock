"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const state = {
  filters: { type: "gguf", company: "", capability: "", size: "", sort: "downloads" },
  settings: {}, system: {}, results: [], pollTimer: null,
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
      $("#destPath").textContent = "No destination — choose in Settings";
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
      ? " (manual — this Mac has " + gib(state.system.ram_detected) + ")"
      : " (this Mac, detected)";
    $("#ramInfo").textContent = gib(state.system.ram) + src;
  } catch (e) { /* server briefly busy — retried on next tick */ }
}

// ---- settings ----
async function loadSettings() {
  state.settings = await api("/api/settings");
  document.body.dataset.theme = state.settings.theme || "dark";
  $("#setDest").textContent = state.settings.destination || "— none chosen —";
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
}
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
    const actives = row.querySelectorAll(".chip.active");
    if (chip.classList.contains("active") && actives.length === 1) return; // keep >= 1
    chip.classList.toggle("active");
    state.filters[group] = [...row.querySelectorAll(".chip.active")].map((c) => c.dataset.v).join(",");
  } else {
    const wasActive = chip.classList.contains("active");
    const scope = group === "capability"
      ? $$('[data-group="capability"] .chip')            // both capability rows share one choice
      : [...row.querySelectorAll(".chip")];
    scope.forEach((c) => c.classList.remove("active"));
    if (!wasActive || group === "sort") chip.classList.add("active");
    state.filters[group] = row.querySelector(".chip.active")?.dataset.v || "";
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
      document.querySelector("#capText .chip.active, #capImage .chip.active")?.dataset.v || "";
  }
  if (group === "company") $("#companyFree").value = "";
  runSearch();
});
$("#companyFree").addEventListener("change", () => {
  $$('[data-group="company"] .chip').forEach((c) => c.classList.remove("active"));
  state.filters.company = $("#companyFree").value.trim();
  runSearch();
});
$("#goBtn").addEventListener("click", runSearch);
$("#q").addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); });

// ---- search ----
const CAP_LABELS = { vision: "Vision", thinking: "Thinking", agentic: "Agentic", coding: "Coding" };

async function runSearch() {
  const f = state.filters;
  const qs = new URLSearchParams({ q: $("#q").value.trim(), type: f.type,
    company: f.company, capability: f.capability, size: f.size, sort: f.sort });
  $("#detail").hidden = true;
  $("#results").replaceChildren(el("div", "msg", "Searching Hugging Face…"));
  try {
    const data = await api("/api/search?" + qs);
    state.results = data.results;
    renderResults();
  } catch (e) {
    $("#results").replaceChildren(el("div", "msg", e.message));
  }
}

function renderResults() {
  const box = $("#results"); box.replaceChildren();
  if (!state.results.length) {
    box.append(el("div", "msg", "No models found — try fewer filters or another search term."));
    return;
  }
  const FMT = { gguf: "GGUF", mlx: "MLX", image: "IMG" };
  const multiType = state.filters.type.includes(",");
  state.results.forEach((m) => {
    const c = el("div", "card");
    const name = el("span", "name", m.id);
    if (multiType && FMT[m.mtype]) name.append(el("span", "pill fmt", FMT[m.mtype]));
    if (m.params && m.params.moe) name.append(el("span", "pill moe", "MoE"));
    if (m.bucket) name.append(el("span", "pill", m.bucket.replace("<=", "≤")));
    (m.caps || []).forEach((cap) => CAP_LABELS[cap] && name.append(el("span", "pill", CAP_LABELS[cap])));
    if (m.gated) name.append(el("span", "pill gated", "requires HF account"));
    const meta = el("span", "meta",
      m.downloads.toLocaleString() + " downloads · " + m.likes + " ♥ · " + (m.updated || "").slice(0, 10));
    c.append(name, meta);
    c.addEventListener("click", () => openDetail(m));
    box.append(c);
  });
}

async function openDetail(card) {
  const d = $("#detail");
  d.hidden = false;
  d.replaceChildren(el("div", "msg", "Loading " + card.id + "…"));
  d.scrollIntoView({ behavior: "smooth" });
  try {
    const qs = new URLSearchParams({ id: card.id, type: card.mtype || state.filters.type.split(",")[0],
      capability: state.filters.capability });
    const m = await api("/api/model?" + qs);
    m.mtype = card.mtype || state.filters.type.split(",")[0];
    d.replaceChildren();
    const back = el("button", "ghost", "← back to results");
    back.addEventListener("click", () => { d.hidden = true; });
    d.append(back, el("h2", "", m.id));
    let metaTxt = m.downloads.toLocaleString() + " downloads · license: " + m.license +
      " · updated " + (m.updated || "").slice(0, 10);
    if (m.params) metaTxt += " · " + m.params.total_b + "B parameters";
    d.append(el("div", "dmeta", metaTxt));
    if (m.moe_note) d.append(el("div", "dmeta", "Mixture-of-Experts: " + m.moe_note));
    if (m.gated) {
      d.append(el("div", "msg",
        "This model requires a free Hugging Face account and license acceptance on huggingface.co. " +
        "ModelDock v1 supports open models only — pick a non-gated alternative."));
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
      fit.title = { green: "Runs comfortably on this Mac", orange: "Tight — will be slow",
        red: "Won't fit in this Mac's memory", unknown: "RAM unknown" }[v.fits];
      row.append(fit);
      row.append(el("span", "vname", v.label + (v.subfolder ? "  → comfyui/" + v.subfolder : "")));
      row.append(el("span", "vsize", fmtBytes(v.size)));
      const btn = el("button", "primary", "Download");
      if (!v.will_fit_disk) { btn.disabled = true; btn.textContent = "Won't fit on drive"; }
      btn.addEventListener("click", async () => {
        try {
          await post("/api/download", { model_id: m.id, variant_label: v.label,
            files: v.files, mtype: m.mtype, capability: state.filters.capability });
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
  if (!jobs.length) { box.append(el("div", "msg", "No downloads yet — find a model in Search.")); return; }
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
async function loadLibrary() {
  const box = $("#libList"); box.replaceChildren(el("div", "msg", "Reading destination…"));
  try {
    const lib = await api("/api/library");
    box.replaceChildren();
    if (!lib.connected) {
      $("#libStats").textContent = "";
      box.append(el("div", "msg", "Destination drive is not connected (or no destination chosen in Settings)."));
      return;
    }
    $("#libStats").textContent = "Models: " + fmtBytes(lib.total_bytes) +
      " · Free on drive: " + fmtBytes(lib.disk.free);
    const mkActions = (path) => {
      const rev = el("button", "ghost", "Reveal");
      rev.addEventListener("click", () => post("/api/reveal", { path }));
      const del = el("button", "ghost", "Delete");
      del.addEventListener("click", async () => {
        if (!confirm("Move to Trash?\n\n" + path)) return;
        try { await post("/api/library/delete", { path }); toast("Moved to Trash"); loadLibrary(); }
        catch (e) { toast(e.message, true); }
      });
      return [rev, del];
    };
    if (lib.text_models.length) {
      const g = el("div", "lib-group"); g.append(el("h3", "", "Chat & text models"));
      lib.text_models.forEach((m) => {
        const it = el("div", "lib-item");
        const nm = el("span", "", m.company + " / " + m.model);
        if (m.incomplete) nm.append(el("span", "pill gated", "incomplete"));
        it.append(nm, el("span", "meta", m.format + " · " + (m.quants.join(", ") || "—") +
          " · " + fmtBytes(m.size) + " · " + new Date(m.mtime * 1000).toLocaleDateString()));
        it.append(...mkActions(m.path));
        g.append(it);
      });
      box.append(g);
    }
    if (lib.comfy_models.length) {
      const g = el("div", "lib-group"); g.append(el("h3", "", "Image & video models (ComfyUI)"));
      lib.comfy_models.forEach((m) => {
        const it = el("div", "lib-item");
        it.append(el("span", "", m.name),
          el("span", "meta", m.subfolder + " · " + fmtBytes(m.size)));
        it.append(...mkActions(m.path));
        g.append(it);
      });
      box.append(g);
    }
    if (!lib.text_models.length && !lib.comfy_models.length) {
      box.append(el("div", "msg", "Nothing downloaded yet to this destination."));
    }
  } catch (e) {
    box.replaceChildren(el("div", "msg", e.message));
  }
}

// ---- boot ----
(async function boot() {
  syncTypeRows();
  await loadSettings();
  await refreshSystem();
  setInterval(refreshSystem, 5000);
  pollDownloads();
})();
