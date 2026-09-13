// Copyright 2026 The Handoff Authors — SPDX-License-Identifier: Apache-2.0
// Paints a streaming reply: text as it arrives, a card per tool call, the
// workflow config if one was produced, and any decisions the turn left waiting.

(() => {
  const root = () => document.querySelector(".chat[data-chat]");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const scroll = () => { const m = document.getElementById("messages"); if (m) m.scrollTop = m.scrollHeight; };

  function toolCard(body, ev) {
    const d = document.createElement("details");
    d.className = "tool-card running"; d.dataset.toolId = ev.tool_id; d.open = false;
    d.innerHTML = `<summary class="tool-head"><svg class="icon sm"><use href="/static/icons.svg#i-bolt"/></svg><span class="name">${esc(ev.name)}</span><span class="badge status"><span class="spinner"></span></span></summary>` +
      (ev.input && Object.keys(ev.input).length ? `<pre>${esc(JSON.stringify(ev.input, null, 2))}</pre>` : "");
    body.append(d); scroll(); return d;
  }

  function finishTool(body, ev) {
    const d = body.querySelector(`[data-tool-id="${CSS.escape(ev.tool_id)}"]`) || toolCard(body, ev);
    d.classList.remove("running"); if (ev.status === "error") d.classList.add("error");
    const badge = d.querySelector(".badge"); badge.className = "badge " + (ev.status === "error" ? "error" : "success"); badge.textContent = `${ev.status}${ev.ms ? " · " + ev.ms + " ms" : ""}`;
    if (ev.output) { const pre = document.createElement("pre"); pre.textContent = ev.output; d.append(pre); }
  }

  async function decisionCards(body, ids) {
    for (const id of ids) {
      try { const r = await fetch(`/activity/item/${encodeURIComponent(id)}`); if (!r.ok) continue; const wrap = document.createElement("div"); wrap.innerHTML = await r.text(); const card = wrap.firstElementChild; card.classList.add("in-chat"); body.append(card); if (window.htmx) htmx.process(card); } catch {}
    }
    scroll();
  }

  function bind(el) {
    if (el.dataset.bound) return; el.dataset.bound = "1";
    const chat = root()?.dataset.chat; const turn = el.dataset.liveTurn; if (!chat || !turn) return;
    const body = el.querySelector(".turn-body"); const thinking = el.querySelector(".bubble.thinking");
    let bubble = null, text = "";
    const es = new EventSource(`/chat/${encodeURIComponent(chat)}/events?turn=${encodeURIComponent(turn)}`);
    const ensureBubble = () => { if (!bubble) { bubble = document.createElement("div"); bubble.className = "bubble"; body.append(bubble); thinking?.remove(); } return bubble; };
    const visible = (s) => s.replace(/<thinking>[\s\S]*?<\/thinking>\s*/gi, "").replace(/<thinking>[\s\S]*$/i, "");
    es.addEventListener("delta", (e) => { const ev = JSON.parse(e.data); text += ev.text || ""; const v = visible(text); if (v) ensureBubble().textContent = v; scroll(); });
    es.addEventListener("tool_start", (e) => { toolCard(body, JSON.parse(e.data)); thinking && (thinking.innerHTML = `<span class="spinner"></span> working…`); });
    es.addEventListener("tool_end", (e) => finishTool(body, JSON.parse(e.data)));
    es.addEventListener("asked", (e) => decisionCards(body, JSON.parse(e.data).interrupt_ids || []));
    es.addEventListener("done", (e) => {
      const ev = JSON.parse(e.data);
      if (ev.text) ensureBubble().textContent = ev.text; else if (!bubble) thinking?.remove();
      if (ev.config) {
        const wrap = document.createElement("div");
        wrap.innerHTML = `<div class="tool-card"><div class="tool-head"><svg class="icon sm"><use href="/static/icons.svg#i-flow"/></svg><span class="name">Workflow config</span><span class="badge success">ready</span></div><pre></pre><div class="row"><button class="button accent small" hx-post="/chat/save" hx-target="#thread" hx-swap="beforeend">Save and switch on</button><span class="text-faded text-xs">Saved workflows show up in Workflows and can run on their schedule.</span></div></div>`;
        const card = wrap.firstElementChild; card.querySelector("pre").textContent = ev.config;
        card.querySelector("button").setAttribute("hx-vals", JSON.stringify({ config: ev.config }));
        body.append(card); if (window.htmx) htmx.process(card);
      }
      const meta = document.createElement("div"); meta.className = "actions-row";
      meta.innerHTML = `<span>${ev.ms ? (ev.ms / 1000).toFixed(1) + "s" : ""}</span>${ev.usage && (ev.usage.input || ev.usage.output) ? `<span>${(ev.usage.input || 0) + (ev.usage.output || 0)} tok</span>` : ""}`;
      el.append(meta);
      if (window.handoffVoice?.enabled && ev.text) window.handoffVoice.say(ev.text.slice(0, 600));
      el.removeAttribute("data-live-turn"); es.close(); scroll();
      document.querySelector("[data-role=pending-count]") && fetch("/api/status").catch(() => {});
    });
    es.addEventListener("error", (e) => { try { const ev = JSON.parse(e.data); const c = document.createElement("div"); c.className = "callout error"; c.textContent = ev.text || "Something went wrong."; body.append(c); } catch {} thinking?.remove(); es.close(); });
    es.addEventListener("end", () => es.close());
    es.onerror = () => { /* keep trying; server keepalives every 15s */ };
  }

  const scan = (r = document) => r.querySelectorAll(".message[data-live-turn]").forEach(bind);
  document.addEventListener("DOMContentLoaded", () => { scan(); scroll(); });
  document.body.addEventListener("htmx:afterSwap", (e) => { scan(e.target); scroll(); });
})();
