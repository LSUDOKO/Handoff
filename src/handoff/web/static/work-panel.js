// Copyright 2026 The Handoff Authors — SPDX-License-Identifier: Apache-2.0
//
// The work panel under the orb: the workspace card a sentence became, the
// run graph as it fills in, and any decision the run stops on.
//
//   WorkPanel.mountCard(html)        // the /orb/card/<id> partial
//   WorkPanel.watchRun(runId, meta)  // draws the Strands Graph from /events/<runId>
//   WorkPanel.mountDecision(html)    // an activity item
//   WorkPanel.clear()
//
// The graph is the real one — trigger → executor → completer — with a node
// per tool the executor called, all driven by the narrator hook's events.
(() => {
  "use strict";
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const panel = () => document.getElementById("work-panel");

  // How a tool reads on the graph. Anything not listed shows its own name.
  const LABELS = {
    fetch_unread_emails: { name: "gmail", kind: "MCP", doing: "reading unread…", done: (n) => `${n} unread` },
    recall_preferences: { name: "memory", kind: "MEMORY", doing: "recalling rules…", done: (n) => `${n} rule${n === 1 ? "" : "s"} applied` },
    classify_email: { name: "classify", kind: "LLM", doing: "judging…", done: (n) => `${n} judged` },
    submit_action: { name: "act", kind: "ACT", doing: "acting…", done: (n) => `${n} handled` },
    finish_batch: { name: "gate", kind: "ACT", doing: "checking the line…", done: () => "batch closed" },
    store_user_preference: { name: "learn", kind: "MEMORY", doing: "writing a rule…", done: (n) => `${n} rule${n === 1 ? "" : "s"} learned` },
    check_trigger: { name: "trigger", kind: "LLM", doing: "checking…", done: () => "fired" },
    finalize_run: { name: "audit", kind: "ACT", doing: "writing the record…", done: () => "recorded" },
    notify_user: { name: "notify", kind: "SEND", doing: "sending…", done: () => "sent" },
  };
  const NODE_TITLES = { trigger: "trigger", executor: "executor", completer: "completer" };

  function labelFor(name, mcpTools) {
    if (LABELS[name]) return LABELS[name];
    const dot = name.indexOf(".");
    if (dot > 0) return { name: name.slice(0, dot), kind: "MCP", doing: name.slice(dot + 1).replace(/_/g, " ") + "…", done: (n) => `${name.slice(dot + 1).replace(/_/g, " ")} ✓` };
    if ((mcpTools || []).some((t) => name.startsWith(t))) return { name, kind: "MCP", doing: "querying…", done: () => "done" };
    return { name, kind: "LLM", doing: "working…", done: () => "done" };
  }

  function mount(el) { const p = panel(); if (!p) return; p.prepend(el); if (window.htmx) htmx.process(el); }

  const api = {
    mountCard(html) { const w = document.createElement("div"); w.innerHTML = html; const card = w.firstElementChild; if (!card) return; document.getElementById(card.id)?.remove(); mount(card); return card; },
    mountDecision(html) {
      const p = panel(); if (!p) return;
      let box = p.querySelector('[data-role="decisions"]');
      if (!box) { box = document.createElement("div"); box.className = "wp-decisions"; box.dataset.role = "decisions"; p.prepend(box); }
      const w = document.createElement("div"); w.innerHTML = html; const card = w.firstElementChild; if (!card) return;
      document.getElementById(card.id)?.remove(); box.prepend(card); if (window.htmx) htmx.process(card); return card;
    },
    clear() { const p = panel(); if (p) p.innerHTML = ""; },

    watchRun(runId, meta = {}) {
      const p = panel(); if (!p || !runId) return null;
      const mcpTools = meta.mcp_tools || [];
      const root = document.createElement("section");
      root.className = "run-graph"; root.id = `run-${runId}`; root.dataset.status = "running";
      const started = new Date();
      root.innerHTML = `
        <div class="rg-head"><span class="dot"></span><code>${esc(meta.workflow_id || runId)}</code><span class="rg-status">RUNNING</span>
          <span class="rg-meta">triggered by <code>${esc(meta.trigger || "you")}</code>${meta.schedule ? ` · <code>${esc(meta.schedule)}</code>` : ""}</span>
          <span class="rg-when">${started.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })} · ${started.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span></div>
        <div class="rg-canvas">
          <svg class="rg-edges" aria-hidden="true"></svg>
          <div class="rg-col" data-col="sources"></div>
          <div class="rg-col" data-col="executor"></div>
          <div class="rg-col" data-col="completer"></div>
        </div>
        <p class="rg-sub">When the signal fires, Handoff runs the <b>agents</b> and delivers — every time, <b>automatically</b>.</p>`;
      document.getElementById(root.id)?.remove();
      mount(root);

      const cols = { sources: root.querySelector('[data-col="sources"]'), executor: root.querySelector('[data-col="executor"]'), completer: root.querySelector('[data-col="completer"]') };
      const svg = root.querySelector(".rg-edges");
      const nodes = new Map();   // key -> {el, count, ms}

      function node(key, col, title, kind, msg, status) {
        let n = nodes.get(key);
        if (!n) {
          const el = document.createElement("div");
          el.className = "rg-node"; el.dataset.key = key; el.dataset.status = status;
          el.innerHTML = `<div class="rg-name"><svg><use href="/static/icons.svg#i-bolt"/></svg><span>${esc(title)}</span><span class="wc-tag ${kind.toLowerCase()}">${esc(kind)}</span></div><div class="rg-line"><span class="rg-msg">${esc(msg)}</span><span class="rg-ms"></span></div>`;
          cols[col].append(el);
          n = { el, count: 0, ms: 0, kind, title };
          nodes.set(key, n);
          requestAnimationFrame(drawEdges);
        }
        return n;
      }
      function set(n, status, msg, ms) {
        n.el.dataset.status = status;
        n.el.querySelector(".rg-msg").textContent = msg;
        const m = n.el.querySelector(".rg-ms");
        if (status === "queued") m.textContent = "QUEUED"; else if (ms != null) m.textContent = `${ms}ms`;
        requestAnimationFrame(drawEdges);
      }
      function drawEdges() {
        const box = root.querySelector(".rg-canvas").getBoundingClientRect();
        const exec = nodes.get("node:executor")?.el, comp = nodes.get("node:completer")?.el;
        svg.setAttribute("viewBox", `0 0 ${box.width} ${box.height}`);
        let lines = "";
        const mid = (el, side) => { const r = el.getBoundingClientRect(); return { x: (side === "right" ? r.right : r.left) - box.left, y: r.top + r.height / 2 - box.top }; };
        if (exec) {
          for (const [key, n] of nodes) {
            if (!key.startsWith("tool:")) continue;
            const a = mid(n.el, "right"), b = mid(exec, "left");
            lines += `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" class="${n.el.dataset.status === "running" ? "live" : ""}"/>`;
          }
          if (comp) { const a = mid(exec, "right"), b = mid(comp, "left"); lines += `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" class="${comp.dataset.status === "running" ? "live" : ""}"/>`; }
        }
        svg.innerHTML = lines;
      }
      addEventListener("resize", drawEdges);

      // The three graph nodes exist from the start, queued, so the shape is visible before anything runs.
      node("node:executor", "executor", "executor", "LLM", "judges each item", "queued");
      node("node:completer", "completer", "completer", "SEND", "reports back", "queued");

      const es = new EventSource(`/events/${encodeURIComponent(runId)}`);
      const on = (kind, fn) => es.addEventListener(kind, (e) => { try { fn(JSON.parse(e.data)); } catch (err) { console.warn(err); } });
      on("node_start", (ev) => {
        if (ev.node === "trigger") { root.querySelector(".rg-status").textContent = "RUNNING"; return; }
        const n = nodes.get(`node:${ev.node}`); if (n) set(n, "running", ev.node === "executor" ? "working through the batch…" : "writing the summary…");
      });
      on("node_end", (ev) => { const n = nodes.get(`node:${ev.node}`); if (n) set(n, "done", ev.node === "executor" ? "batch judged" : "summary sent", ev.ms); });
      on("tool_start", (ev) => {
        if (ev.node === "trigger") return;
        if (ev.node === "completer") { const n = nodes.get("node:completer"); if (n) set(n, "running", labelFor(ev.name, mcpTools).doing); return; }
        const L = labelFor(ev.name, mcpTools);
        const n = node(`tool:${L.name}`, "sources", L.name, L.kind, L.doing, "running");
        n.el.dataset.status = "running"; n.el.querySelector(".rg-msg").textContent = L.doing; requestAnimationFrame(drawEdges);
      });
      on("tool_end", (ev) => {
        if (ev.node === "trigger") return;
        if (ev.node === "completer") return;
        const L = labelFor(ev.name, mcpTools);
        const n = nodes.get(`tool:${L.name}`); if (!n) return;
        n.count += 1; n.ms += ev.ms || 0;
        let count = n.count;
        // A fetch reports how many it found; that reads better than "1 done".
        if (ev.name === "fetch_unread_emails") { const m = /(\d+)/.exec(ev.text || ""); if (m) count = Number(m[1]); else try { const arr = JSON.parse(ev.output); if (Array.isArray(arr)) count = arr.length; } catch {} }
        set(n, ev.status === "ok" ? "done" : "error", ev.status === "ok" ? L.done(count) : `failed: ${(ev.output || "").slice(0, 60)}`, n.ms);
      });
      const finish = (status, label) => { root.dataset.status = status; root.querySelector(".rg-status").textContent = label; drawEdges(); es.close(); };
      on("completed", (ev) => { finish("done", "DONE"); const n = nodes.get("node:completer"); if (n && n.el.dataset.status !== "done") set(n, "done", ev.text || "done"); });
      on("asked", (ev) => { finish("needs", "NEEDS YOU"); const n = nodes.get("node:executor"); if (n) set(n, "done", `${(ev.pending || []).length || ""} for you`.trim()); root.dispatchEvent(new CustomEvent("run:asked", { bubbles: true, detail: ev })); });
      on("failed", (ev) => { finish("failed", "FAILED"); });
      es.addEventListener("end", () => es.close());
      return root;
    },
  };
  window.WorkPanel = api;
})();
