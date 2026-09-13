// Copyright 2026 The Handoff Authors — SPDX-License-Identifier: Apache-2.0
//
// The shell: theme, command palette, toasts, hotkeys, live sidebar counts,
// small interaction helpers. Voice lives in handoff.js.

(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  // ---- Theme -----------------------------------------------------------------
  const THEME_KEY = "handoff.theme";
  function applyTheme(value) {
    if (value === "light" || value === "dark") document.documentElement.dataset.theme = value;
    else delete document.documentElement.dataset.theme;
    $$("[data-role=theme]").forEach((b) => {
      const dark = value === "dark" || (!value && matchMedia("(prefers-color-scheme: dark)").matches);
      b.setAttribute("aria-label", dark ? "Switch to light" : "Switch to dark");
      b.querySelector("use")?.setAttribute("href", `/static/icons.svg#${dark ? "i-sun" : "i-moon"}`);
    });
  }
  function readTheme() { try { return localStorage.getItem(THEME_KEY) || ""; } catch { return ""; } }
  applyTheme(readTheme());
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-role=theme]");
    if (!btn) return;
    const current = readTheme() || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    try { localStorage.setItem(THEME_KEY, next); } catch {}
    applyTheme(next);
  });

  // ---- Toasts ------------------------------------------------------------------
  function toast(title, opts = {}) {
    let host = $(".toasts");
    if (!host) { host = document.createElement("div"); host.className = "toasts"; document.body.append(host); }
    const el = document.createElement("div");
    el.className = "toast" + (opts.error ? " error" : "");
    el.setAttribute("role", "status");
    el.textContent = title;
    host.append(el);
    setTimeout(() => { el.classList.add("leaving"); setTimeout(() => el.remove(), 220); }, opts.duration || 3200);
    return el;
  }
  window.toast = toast;

  document.body.addEventListener("htmx:responseError", (e) => {
    const status = e.detail?.xhr?.status;
    toast(status ? `Request failed (${status})` : "Request failed", { error: true });
  });
  document.body.addEventListener("htmx:sendError", () => toast("Can’t reach Handoff — is it running?", { error: true }));
  document.body.addEventListener("htmx:afterRequest", (e) => {
    const msg = e.detail?.xhr?.getResponseHeader("X-Toast");
    if (msg) toast(msg, { error: e.detail.xhr.status >= 400 });
  });

  // ---- Copy buttons --------------------------------------------------------------
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-copy]");
    if (!btn) return;
    const sel = btn.getAttribute("data-copy");
    const text = sel ? ($(sel)?.innerText ?? "") : (btn.closest(".data")?.querySelector("pre")?.innerText ?? "");
    try { await navigator.clipboard.writeText(text); toast("Copied"); } catch { toast("Couldn’t copy", { error: true }); }
  });

  // ---- Dropdowns: close on outside click / escape ------------------------------
  document.addEventListener("click", (e) => {
    $$("details.dropdown[open]").forEach((d) => { if (!d.contains(e.target)) d.removeAttribute("open"); });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") $$("details.dropdown[open]").forEach((d) => d.removeAttribute("open"));
  });

  // ---- Dialogs -------------------------------------------------------------------
  document.addEventListener("click", (e) => {
    const open = e.target.closest("[data-dialog]");
    if (open) { const dlg = $(open.getAttribute("data-dialog")); if (dlg) { dlg.showModal(); dlg.querySelector("input,textarea,select")?.focus(); } return; }
    const close = e.target.closest("[data-dialog-close]");
    if (close) close.closest("dialog")?.close();
  });
  document.addEventListener("click", (e) => {
    if (e.target instanceof HTMLDialogElement && e.target.open) {
      const r = e.target.querySelector(".dialog-panel")?.getBoundingClientRect();
      if (r && (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)) e.target.close();
    }
  });

  // ---- Subtitle expand -----------------------------------------------------------
  document.addEventListener("click", (e) => {
    const s = e.target.closest(".page-title .subtitle"); if (s) s.classList.toggle("open");
  });

  // ---- Mobile nav ------------------------------------------------------------------
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-role=nav-toggle]")) $(".app-shell")?.classList.toggle("nav-open");
    else if (!e.target.closest(".sidebar")) $(".app-shell")?.classList.remove("nav-open");
  });

  // ---- Live sidebar counts + online dot ----------------------------------------
  async function refreshStatus() {
    try {
      const r = await fetch("/api/status", { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      const s = await r.json();
      $$("[data-role=pending-count]").forEach((el) => { el.textContent = s.pending || ""; el.hidden = !s.pending; });
      const dot = $("[data-role=online]");
      if (dot) { dot.className = "status " + (s.busy ? "busy" : "online"); dot.querySelector("span").textContent = s.busy ? `Running ${s.busy}` : "Online"; }
      document.title = (s.pending ? `(${s.pending}) ` : "") + document.title.replace(/^\(\d+\) /, "");
    } catch {
      const dot = $("[data-role=online]");
      if (dot) { dot.className = "status offline"; dot.querySelector("span").textContent = "Offline"; }
    }
  }
  refreshStatus();
  setInterval(refreshStatus, 12000);
  document.body.addEventListener("htmx:afterSwap", () => setTimeout(refreshStatus, 400));

  // ---- Relative times ---------------------------------------------------------------
  function relTime(iso) {
    const t = new Date(iso).getTime(); if (!isFinite(t)) return "";
    const d = Math.round((Date.now() - t) / 1000);
    if (d < 45) return "just now"; if (d < 3600) return `${Math.floor(d / 60)}m ago`;
    if (d < 86400) return `${Math.floor(d / 3600)}h ago`; return `${Math.floor(d / 86400)}d ago`;
  }
  function tickTimes() { $$("time[data-rel]").forEach((t) => { t.textContent = relTime(t.getAttribute("datetime")); }); }
  tickTimes(); setInterval(tickTimes, 30000);
  document.body.addEventListener("htmx:afterSwap", tickTimes);

  // ---- Command palette ----------------------------------------------------------------
  let palette = null;
  function workspaces() { return JSON.parse($("#ws-data")?.textContent || "[]"); }
  function currentWorkspace() { return document.body.dataset.workspace || (workspaces()[0]?.id ?? "personal"); }

  function openPalette(mode = "chat") {
    closePalette();
    const list = workspaces();
    let target = currentWorkspace();
    let index = Math.max(0, list.findIndex((w) => w.id === target));
    const root = document.createElement("div");
    root.className = "palette-backdrop";
    root.innerHTML = `
      <div class="palette" role="dialog" aria-label="Command palette">
        <div class="palette-head">
          <span class="target" data-role="target"></span>
          <span class="text-faded text-xs" data-role="mode-hint"></span>
          <kbd class="ml-auto">esc</kbd>
        </div>
        <div data-role="body"></div>
        <div class="palette-foot"><span><kbd>↵</kbd> send</span><span><kbd>⇧↵</kbd> newline</span><span><kbd>⌘/</kbd> switch workspace</span></div>
      </div>`;
    document.body.append(root);
    palette = root;
    const targetEl = $("[data-role=target]", root), body = $("[data-role=body]", root), hint = $("[data-role=mode-hint]", root);

    function paint() {
      const ws = list.find((w) => w.id === target) || {};
      targetEl.innerHTML = `<span class="ws-dot" data-color="${ws.color || "amber"}"></span>${ws.name || target}`;
      if (mode === "chat") {
        hint.textContent = "Ask this workspace";
        body.innerHTML = `<textarea rows="1" placeholder="Describe a chore, ask a question, or type / to switch…" aria-label="Message"></textarea>`;
        const ta = $("textarea", body); ta.focus();
        ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; if (ta.value === "/") { ta.value = ""; mode = "switcher"; paint(); } });
        ta.addEventListener("keydown", (e) => {
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); const msg = ta.value.trim(); if (!msg) return; sessionStorage.setItem(`handoff.seed.${target}`, msg); location.href = `/platform/${encodeURIComponent(target)}/chat?seed=1`; }
        });
      } else {
        hint.textContent = "Switch workspace";
        body.innerHTML = `<input type="search" placeholder="Search workspaces…" aria-label="Search"><ul class="palette-list" role="listbox"></ul>`;
        const input = $("input", body), ul = $("ul", body); input.focus();
        const render = () => {
          const q = input.value.trim().toLowerCase();
          const rows = list.filter((w) => !q || w.name.toLowerCase().includes(q) || w.id.includes(q));
          if (index >= rows.length) index = 0;
          ul.innerHTML = rows.map((w, i) => `<li role="option" aria-selected="${i === index}" data-id="${w.id}"><span class="ws-dot" data-color="${w.color || "amber"}"></span><span class="grow">${w.name}</span>${i === index ? '<kbd class="hint-k">↵</kbd>' : ""}</li>`).join("") || `<li class="text-faded">No workspaces match</li>`;
          return rows;
        };
        let rows = render();
        input.addEventListener("input", () => { index = 0; rows = render(); });
        input.addEventListener("keydown", (e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); index = Math.min(index + 1, rows.length - 1); rows = render(); }
          else if (e.key === "ArrowUp") { e.preventDefault(); index = Math.max(index - 1, 0); rows = render(); }
          else if (e.key === "Enter") { e.preventDefault(); const w = rows[index]; if (!w) return; target = w.id; if (e.metaKey || e.ctrlKey) { location.href = `/platform/${encodeURIComponent(w.id)}`; return; } mode = "chat"; paint(); }
        });
        ul.addEventListener("click", (e) => { const li = e.target.closest("li[data-id]"); if (!li) return; location.href = `/platform/${encodeURIComponent(li.dataset.id)}`; });
      }
    }
    paint();
    root.addEventListener("click", (e) => { if (e.target === root) closePalette(); });
    root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closePalette(); } });
  }
  function closePalette() { palette?.remove(); palette = null; }
  window.openPalette = openPalette;

  const inTextField = (el) => el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
  document.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette("chat"); return; }
    if (mod && e.key === "/" && !(e.target.isContentEditable)) { e.preventDefault(); openPalette("switcher"); return; }
    if (e.key === "/" && !inTextField(e.target) && !palette) { e.preventDefault(); openPalette("chat"); return; }
    if (e.key === "Escape" && palette) closePalette();
  });
  document.addEventListener("click", (e) => { if (e.target.closest("[data-role=open-palette]")) openPalette("chat"); });

  // Chat seed handoff from the palette → chat page.
  document.addEventListener("DOMContentLoaded", () => {
    const seedFor = document.body.dataset.workspace;
    const key = `handoff.seed.${seedFor}`;
    const seed = sessionStorage.getItem(key);
    const input = $("[data-role=chat-input]");
    if (seed && input) { sessionStorage.removeItem(key); input.value = seed; input.dispatchEvent(new Event("input")); input.form?.requestSubmit(); }
  });

  // ---- Autosize textareas -------------------------------------------------------------
  document.addEventListener("input", (e) => {
    const t = e.target; if (t.tagName === "TEXTAREA" && t.hasAttribute("data-autosize")) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 320) + "px"; }
  });
  // Enter sends in autosize composers; Shift+Enter is a newline.
  document.addEventListener("keydown", (e) => {
    const t = e.target; if (t.tagName === "TEXTAREA" && t.hasAttribute("data-submit-on-enter") && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); t.form?.requestSubmit(); }
  });
})();
