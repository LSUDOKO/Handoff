// Copyright 2026 The Handoff Authors — SPDX-License-Identifier: Apache-2.0
//
// The speech loop on the Talk page. Record → hear → send → paint → speak,
// with the orb following along. Hearing streams to Amazon Transcribe over a
// WebSocket while you are still talking, so the caption fills in live and
// the text is ready the moment you stop; when that is not available it
// uploads a WAV (Groq) or uses the browser's own recogniser.
(() => {
  "use strict";
  const page = document.getElementById("orb-page");
  if (!page) return;
  const $ = (s) => page.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  const chatId = page.dataset.chat;
  const provider = page.dataset.provider;         // aws | groq | browser
  const button = $("#orb-button"), canvas = $("#orb"), fallbackEl = $("#orb-fallback");
  const caption = $('[data-role="caption"]'), transcript = $('[data-role="transcript"]'), thread = $('[data-role="thread"]');
  const handsfreeBox = $('[data-role="handsfree"]');

  const orb = window.HandoffOrb ? HandoffOrb.mount(canvas, { fallbackEl }) : { setState() {}, setLevel() {} };
  let mode = "idle";                               // idle | listening | thinking | speaking
  let handsfree = false;
  try { handsfree = localStorage.getItem("handoff:handsfree") === "on"; } catch {}
  if (handsfreeBox) { handsfreeBox.checked = handsfree; handsfreeBox.addEventListener("change", () => { handsfree = handsfreeBox.checked; try { localStorage.setItem("handoff:handsfree", handsfree ? "on" : "off"); } catch {} if (handsfree && mode === "idle") startListening(); }); }

  function setMode(m, text) {
    mode = m;
    button.dataset.state = m === "idle" ? (pendingCount() ? "needs" : "idle") : m;
    orb.setState(button.dataset.state);
    if (text != null) { caption.textContent = text; caption.dataset.mode = m; }
  }
  const pendingCount = () => document.querySelectorAll('#work-panel .waiting-card.needs').length;

  // ---- thread ---------------------------------------------------------------
  function line(cls, who, text) {
    const el = document.createElement("div"); el.className = `ot-line ${cls}`;
    el.innerHTML = `<span class="ot-who">${esc(who)}</span><span class="ot-text">${esc(text)}</span>`;
    thread.append(el); return el;
  }
  function toolLine(ev) {
    const el = document.createElement("div"); el.className = "ot-line tool running"; el.dataset.toolId = ev.tool_id;
    el.innerHTML = `<span class="ot-who"><svg class="icon xs"><use href="/static/icons.svg#i-bolt"/></svg></span><span class="ot-text mono">${esc(ev.name)}<span class="ms"></span></span>`;
    thread.append(el); return el;
  }

  // ---- microphone -------------------------------------------------------------
  let ctx = null, stream = null, source = null, worklet = null, analyser = null;
  async function openMic() {
    if (ctx) return true;
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    await ctx.audioWorklet.addModule("/static/pcm-worklet.js");
    source = ctx.createMediaStreamSource(stream);
    worklet = new AudioWorkletNode(ctx, "pcm-worklet");
    source.connect(worklet);
    // The worklet must be connected somewhere to run; a muted gain keeps it silent.
    const mute = ctx.createGain(); mute.gain.value = 0; worklet.connect(mute).connect(ctx.destination);
    return true;
  }
  function closeMic() {
    try { worklet?.disconnect(); source?.disconnect(); } catch {}
    stream?.getTracks().forEach((t) => t.stop());
    ctx?.close().catch(() => {});
    ctx = stream = source = worklet = null;
  }

  // ---- one utterance ------------------------------------------------------------
  let rec = null;   // { chunks, ws, text, stop() }
  async function startListening() {
    if (mode !== "idle" || rec) return;
    stopSpeaking();
    setMode("listening", "Listening…");
    transcript.textContent = ""; transcript.classList.remove("partial");
    if (provider === "browser" || !navigator.mediaDevices?.getUserMedia) { return browserRecognise(); }
    try { await openMic(); } catch (err) {
      if (window.pywebview?.api?.start_listening) return bridgeListen();
      setMode("idle", "Microphone unavailable — allow it in the browser, or type in Chat."); caption.dataset.mode = "warn"; return;
    }
    if (ctx.state === "suspended") await ctx.resume();
    const chunks = [];
    let ws = null, live = "", finals = [], done = null;
    if (provider === "aws" && "WebSocket" in window) {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/voice/stream`);
      ws.binaryType = "arraybuffer";
      done = new Promise((resolve) => {
        ws.onmessage = (m) => {
          let ev; try { ev = JSON.parse(m.data); } catch { return; }
          if (ev.type === "partial") { live = ev.text; transcript.textContent = [...finals, live].join(" "); transcript.classList.add("partial"); }
          if (ev.type === "final") { finals.push(ev.text); live = ""; transcript.textContent = finals.join(" "); }
          if (ev.type === "done") { resolve(ev.text || finals.join(" ")); }
          if (ev.type === "unsupported" || ev.type === "error") { resolve(null); }
        };
        ws.onerror = () => resolve(null);
        ws.onclose = () => resolve(finals.join(" ") || null);
      });
    }
    let speechMs = 0, silentSince = 0, lastTick = performance.now();
    worklet.port.onmessage = (m) => {
      const { pcm, level } = m.data;
      orb.setLevel(Math.min(1, level * 9)); button.style.setProperty("--level", Math.min(1, level * 9).toFixed(2));
      if (pcm) { chunks.push(pcm); if (ws && ws.readyState === 1) ws.send(pcm.buffer); }
      // Hands-free: end the utterance after 1.1 s of quiet following at least 0.6 s of speech.
      const now = performance.now(), dt = now - lastTick; lastTick = now;
      if (level > 0.02) { speechMs += dt; silentSince = 0; } else if (speechMs > 600) { silentSince += dt; if (handsfree && silentSince > 1100 && rec) rec.stop(); }
    };
    rec = { stop: async () => {
      if (!rec) return; const me = rec; rec = null;
      worklet.port.onmessage = null; orb.setLevel(0);
      setMode("thinking", "Transcribing…");
      let text = null;
      if (ws) {
        // Wait briefly for the final; the stabilised partial is already on
        // screen and is what a person would accept, so use it if the final is slow.
        try { if (ws.readyState === 1) ws.send(JSON.stringify({ type: "end" })); text = await Promise.race([done, new Promise((r) => setTimeout(() => r(undefined), 2500))]); } catch { text = null; }
        if (text === undefined) text = [...finals, live].join(" ").trim() || null;
        try { ws.close(); } catch {}
      }
      if (text == null) text = await uploadTranscribe(chunks);
      transcript.classList.remove("partial");
      await heard(text);
    } };
  }
  async function uploadTranscribe(chunks) {
    const total = chunks.reduce((n, c) => n + c.length, 0);
    if (!total) return "";
    const wav = toWav(chunks, total);
    const fd = new FormData(); fd.append("audio", new Blob([wav], { type: "audio/wav" }), "speech.wav");
    try { const r = await fetch("/api/voice/transcribe", { method: "POST", body: fd }); if (!r.ok) throw new Error(await r.text()); return (await r.json()).text || ""; }
    catch (err) { console.warn(err); return ""; }
  }
  function toWav(chunks, total) {
    const buf = new ArrayBuffer(44 + total * 2), v = new DataView(buf);
    const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    str(0, "RIFF"); v.setUint32(4, 36 + total * 2, true); str(8, "WAVE"); str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, 16000, true); v.setUint32(28, 32000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, total * 2, true);
    let o = 44; for (const c of chunks) { for (let i = 0; i < c.length; i++, o += 2) v.setInt16(o, c[i], true); }
    return buf;
  }
  function browserRecognise() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { setMode("idle", "This browser cannot hear — add AWS credentials or a Groq key for server speech."); caption.dataset.mode = "warn"; return; }
    const r = new SR(); r.lang = "en-US"; r.interimResults = true; r.maxAlternatives = 1;
    r.onresult = (e) => { const t = [...e.results].map((x) => x[0].transcript).join(" "); transcript.textContent = t; transcript.classList.toggle("partial", !e.results[e.results.length - 1].isFinal); };
    r.onerror = () => { rec = null; setMode("idle", "Didn't catch that — tap to try again."); };
    r.onend = () => { const t = transcript.textContent; rec = null; transcript.classList.remove("partial"); heard(t); };
    r.start();
    rec = { stop: () => r.stop() };
  }
  async function bridgeListen() {
    const api = window.pywebview.api;
    const ok = await api.start_listening();
    if (!ok || ok.ok === false) { setMode("idle", "Microphone unavailable in this window."); caption.dataset.mode = "warn"; return; }
    rec = { stop: async () => {
      rec = null; setMode("thinking", "Transcribing…");
      const out = await api.stop_listening();
      const bytes = Uint8Array.from(atob(out.wav_b64 || ""), (c) => c.charCodeAt(0));
      const fd = new FormData(); fd.append("audio", new Blob([bytes], { type: "audio/wav" }), "speech.wav");
      let text = ""; try { const r = await fetch("/api/voice/transcribe", { method: "POST", body: fd }); text = (await r.json()).text || ""; } catch {}
      await heard(text);
    } };
  }

  // ---- after hearing --------------------------------------------------------------
  async function heard(text) {
    text = (text || "").trim();
    if (!text) { setMode("idle", "Didn't catch that — tap to try again."); if (handsfree) setTimeout(() => mode === "idle" && startListening(), 400); return; }
    transcript.textContent = text;
    line("you", "You", text);
    // A decision on screen and a phrase like "archive it": answer it here, no model round-trip.
    const card = document.querySelector("#work-panel .waiting-card.needs form.quick");
    if (card) {
      const options = [...card.querySelectorAll('button[name="action"]')].map((b) => b.value);
      try {
        const r = await fetch("/api/voice/command", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, options }) });
        const { action } = await r.json();
        if (action) {
          const btn = card.querySelector(`button[name="action"][value="${action}"]`) || card.querySelector('button[name="action"]');
          const label = btn.textContent.trim();
          btn.click();
          line("handoff", "Handoff", `${label}. Done.`);
          await say(`${label}. Done.`);
          return;
        }
      } catch {}
    }
    await send(text);
  }

  // ---- the turn ----------------------------------------------------------------------
  async function send(text) {
    setMode("thinking", "Thinking…");
    let turn;
    try {
      const r = await fetch(`/orb/${encodeURIComponent(chatId)}/send`, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "message=" + encodeURIComponent(text) });
      if (!r.ok) throw new Error(await r.text());
      turn = (await r.json()).turn;
    } catch (err) { setMode("idle", "Couldn't reach Handoff — is it still running?"); caption.dataset.mode = "warn"; return; }
    follow(turn);
  }
  function follow(turn) {
    const es = new EventSource(`/orb/${encodeURIComponent(chatId)}/events?turn=${encodeURIComponent(turn)}`);
    const on = (k, fn) => es.addEventListener(k, (e) => { try { fn(JSON.parse(e.data)); } catch (err) { console.warn(err); } });
    let reply = null, text = "";
    const visible = (s) => s.replace(/<thinking>[\s\S]*?<\/thinking>\s*/gi, "").replace(/<thinking>[\s\S]*$/i, "").replace(/```[\s\S]*?```/g, "").trim();
    on("delta", (ev) => { text += ev.text || ""; const v = visible(text); if (v) { if (!reply) reply = line("handoff", "Handoff", ""); reply.querySelector(".ot-text").textContent = v; caption.textContent = v.slice(-140); } });
    on("tool_start", (ev) => { setMode("acting", `${ev.name.replace(/_/g, " ")}…`); toolLine(ev); });
    on("tool_end", (ev) => { const el = thread.querySelector(`[data-tool-id="${CSS.escape(ev.tool_id)}"]`); if (el) { el.classList.remove("running"); el.classList.add(ev.status === "ok" ? "done" : "error"); el.querySelector(".ms").textContent = ev.ms ? ` ${ev.ms}ms` : ""; } if (mode === "acting") setMode("thinking", "Thinking…"); });
    on("workflow_saved", async (ev) => { try { const r = await fetch(`/orb/card/${encodeURIComponent(ev.workflow_id)}?source=voice`); if (r.ok) WorkPanel.mountCard(await r.text()); } catch {} });
    on("run_started", (ev) => { WorkPanel.watchRun(ev.run, { workflow_id: ev.workflow_id, mcp_tools: ev.mcp_tools, trigger: "you" }); });
    on("asked", (ev) => mountDecisions(ev.interrupt_ids || []));
    on("done", async (ev) => {
      es.close();
      const final = visible(ev.text || text) || (reply ? "" : "Done.");
      if (final) { if (!reply) reply = line("handoff", "Handoff", ""); reply.querySelector(".ot-text").textContent = final; }
      await say(final);
    });
    on("error", (ev) => { es.close(); line("handoff", "Handoff", ev.text || "Something went wrong."); setMode("idle", ev.text || "Something went wrong."); caption.dataset.mode = "warn"; });
  }
  async function mountDecisions(ids) {
    for (const id of ids) { try { const r = await fetch(`/activity/item/${encodeURIComponent(id)}`); if (r.ok) WorkPanel.mountDecision(await r.text()); } catch {} }
    if (ids.length) { const n = ids.length; await say(`I set aside ${n === 1 ? "one" : n} for you. Tell me what to do, or take a look.`); }
  }
  // A run started here may stop on a decision after the turn is over.
  document.addEventListener("run:asked", (e) => { const p = (e.detail && e.detail.pending) || []; mountDecisions(p.map((x) => x.interrupt_id || x)); });
  document.body.addEventListener("htmx:afterSwap", () => { if (mode === "idle") setMode("idle"); });

  // ---- speaking --------------------------------------------------------------------
  let audio = null, outCtx = null, meter = 0;
  function stopSpeaking() { if (audio) { audio.pause(); audio = null; } if ("speechSynthesis" in window) speechSynthesis.cancel(); cancelAnimationFrame(meter); orb.setLevel(0); }
  async function say(text) {
    text = (text || "").trim();
    if (!text) { finishTurn(); return; }
    setMode("speaking", text.slice(0, 160));
    if (page.dataset.tts === "on") {
      try {
        const r = await fetch("/api/voice/speak", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: text.slice(0, 1200) }) });
        if (r.status === 200) {
          const blob = await r.blob();
          audio = new Audio(URL.createObjectURL(blob));
          try {
            outCtx = outCtx || new (window.AudioContext || window.webkitAudioContext)();
            const src = outCtx.createMediaElementSource(audio); analyser = outCtx.createAnalyser(); analyser.fftSize = 512;
            src.connect(analyser); analyser.connect(outCtx.destination);
            const data = new Uint8Array(analyser.frequencyBinCount);
            const tick = () => { if (!audio) return; analyser.getByteTimeDomainData(data); let s = 0; for (const x of data) { const d = (x - 128) / 128; s += d * d; } orb.setLevel(Math.min(1, Math.sqrt(s / data.length) * 4)); meter = requestAnimationFrame(tick); };
            tick();
          } catch {}
          await new Promise((res) => { audio.onended = res; audio.onerror = res; audio.play().catch(res); });
          audio = null; cancelAnimationFrame(meter); orb.setLevel(0);
          finishTurn(); return;
        }
      } catch (err) { console.warn(err); }
    }
    if ("speechSynthesis" in window) {
      await new Promise((res) => { const u = new SpeechSynthesisUtterance(text); u.rate = 1.03; u.onend = res; u.onerror = res; let t = 0; const pulse = () => { if (!speechSynthesis.speaking) return; orb.setLevel(0.3 + 0.3 * Math.abs(Math.sin(t += 0.25))); meter = requestAnimationFrame(pulse); }; pulse(); speechSynthesis.speak(u); });
      cancelAnimationFrame(meter); orb.setLevel(0);
    }
    finishTurn();
  }
  function finishTurn() {
    setMode("idle", pendingCount() ? "Say archive it, file a ticket, draft a reply, or leave it." : "Tap to talk, or hold Space");
    if (handsfree) setTimeout(() => { if (mode === "idle") startListening(); }, 350);
  }

  // ---- controls ----------------------------------------------------------------------
  button.addEventListener("click", () => { if (rec) rec.stop(); else if (mode === "idle") startListening(); else if (mode === "speaking") { stopSpeaking(); finishTurn(); } });
  let spaceHeld = false;
  document.addEventListener("keydown", (e) => {
    if (e.code !== "Space" || e.repeat || spaceHeld) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "") || document.activeElement?.isContentEditable) return;
    e.preventDefault(); spaceHeld = true; if (mode === "idle" && !rec) startListening();
  });
  document.addEventListener("keyup", (e) => { if (e.code !== "Space") return; spaceHeld = false; if (rec && !handsfree) rec.stop(); });
  addEventListener("pagehide", () => { closeMic(); stopSpeaking(); });

  // Resume a reply that was mid-flight when the page opened; auto-listen when asked to.
  if (page.dataset.liveTurn) follow(Number(page.dataset.liveTurn));
  if (pendingCount()) setMode("idle", "Say archive it, file a ticket, draft a reply, or leave it.");
  if (page.dataset.listen === "1") setTimeout(startListening, 300);
  else if (handsfree) caption.textContent = "Hands-free is on — tap once to start.";
})();
