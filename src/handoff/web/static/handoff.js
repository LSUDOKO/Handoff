/* Copyright 2026 The Handoff Authors — SPDX-License-Identifier: Apache-2.0
 *
 * Two things happen here: watching a run as it works (server-sent events),
 * and talking to Handoff — speaking instead of typing, and having decisions
 * read aloud. Speech goes to real models when the server has a Groq key
 * (Whisper in, Orpheus out) and falls back to the browser's own engines
 * otherwise, so the interface never goes mute over a missing key.
 */
(() => {
  "use strict";

  /* ---------- live feed ---------- */

  const feeds = new Map();

  function attachLive(panel) {
    const runId = panel.dataset.run;
    if (!runId || feeds.has(panel)) return;
    const list = panel.querySelector('[data-role="feed"]');
    const state = panel.querySelector('[data-role="state"]');
    const es = new EventSource(`/events/${encodeURIComponent(runId)}`);
    feeds.set(panel, es);

    const add = (e) => {
      const li = document.createElement("li");
      li.className = `ev ev-${e.kind}`;
      li.innerHTML = `<span class="ev-k">${e.kind}</span>`;
      li.appendChild(document.createTextNode(e.text || ""));
      list.appendChild(li);
      li.scrollIntoView({ block: "nearest" });
      if (runId === "*") panel.closest("section")?.removeAttribute("hidden");
    };

    for (const kind of ["started","fetched","acted","deferred","memory","asked","decided","resumed","completed","failed","repaired","note"]) {
      es.addEventListener(kind, (ev) => {
        const e = JSON.parse(ev.data);
        add(e);
        if (kind === "asked") { state.textContent = "needs you"; state.classList.add("needs"); }
        if (kind === "completed") { state.textContent = "done"; state.classList.add("done"); }
        if (kind === "failed") { state.textContent = "failed"; state.classList.add("needs"); }
        if (kind === "asked" && voice.enabled) voice.say(`Handoff set aside ${e.pending ? e.pending.length : "some"} items for you.`);
        if (kind === "completed" && voice.enabled) voice.say(e.text);
      });
    }
    es.addEventListener("end", () => {
      es.close();
      panel.querySelector(".live-dot")?.classList.add("idle");
      // The row's counters are stale now; refresh the page quietly after the
      // person has had a moment to read the feed.
      if (runId !== "*") setTimeout(() => { if (!document.hidden) location.reload(); }, 4000);
    });
    es.onerror = () => { panel.querySelector(".live-dot")?.classList.add("idle"); };
  }

  function scanLive(root = document) {
    root.querySelectorAll(".live[data-run]").forEach(attachLive);
  }

  /* ---------- voice ---------- */

  const voice = {
    enabled: false,
    serverTTS: document.body.dataset.voice === "on",
    audio: null,

    async say(text) {
      if (!text) return;
      this.stop();
      if (this.serverTTS) {
        try {
          const r = await fetch("/api/voice/speak", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
          });
          if (r.status === 200) {
            const blob = await r.blob();
            this.audio = new Audio(URL.createObjectURL(blob));
            await this.audio.play();
            return;
          }
          if (r.status === 204) this.serverTTS = r.headers.get("X-Handoff-Fallback") === "" ? this.serverTTS : false;
        } catch (_) { /* fall through to the browser */ }
      }
      if ("speechSynthesis" in window) {
        const u = new SpeechSynthesisUtterance(text);
        u.rate = 1.02;
        speechSynthesis.speak(u);
      }
    },

    stop() {
      if (this.audio) { this.audio.pause(); this.audio = null; }
      if ("speechSynthesis" in window) speechSynthesis.cancel();
    },
  };

  try { voice.enabled = localStorage.getItem("handoff:voice") === "on"; } catch (_) {}

  function bindToggle() {
    const btn = document.querySelector('[data-role="voice-toggle"]');
    if (!btn) return;
    const render = () => { btn.textContent = voice.enabled ? "Voice on" : "Voice off"; btn.classList.toggle("on", voice.enabled); };
    render();
    btn.addEventListener("click", () => {
      voice.enabled = !voice.enabled;
      try { localStorage.setItem("handoff:voice", voice.enabled ? "on" : "off"); } catch (_) {}
      render();
      if (voice.enabled) voice.say("Voice is on. I'll read decisions to you.");
      else voice.stop();
    });
  }

  /* --- listening: hold the mic, release to send --- */

  async function transcribeBlob(blob) {
    const fd = new FormData();
    fd.append("audio", blob, "speech.webm");
    const r = await fetch("/api/voice/transcribe", { method: "POST", body: fd });
    if (!r.ok) throw new Error(await r.text());
    return (await r.json()).text || "";
  }

  function browserRecognize() {
    return new Promise((resolve, reject) => {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SR) return reject(new Error("no speech recognition"));
      const rec = new SR();
      rec.lang = "en-US"; rec.interimResults = false; rec.maxAlternatives = 1;
      rec.onresult = (e) => resolve(e.results[0][0].transcript);
      rec.onerror = (e) => reject(new Error(e.error));
      rec.onend = () => resolve("");
      rec.start();
    });
  }

  function bindMic(btn) {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "1";
    const form = btn.closest("form");
    const target = form?.querySelector('[data-role="voice-target"]');
    const heard = form?.querySelector('[data-role="heard"]');
    let rec = null, chunks = [], stream = null;

    const setHeard = (t, cls = "") => { if (heard) { heard.textContent = t; heard.className = `heard ${cls}`; } };

    const onText = async (text) => {
      text = (text || "").trim();
      if (!text) { setHeard("Didn't catch that — try again.", "warn"); return; }
      if (target) { target.value = text; target.focus(); return; }
      // Decision screen: map the phrase to an action and submit it.
      const options = (form.dataset.options || "").split(",").filter(Boolean);
      const r = await fetch("/api/voice/command", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, options }),
      });
      const { action } = await r.json();
      if (!action) { setHeard(`Heard "${text}" — say archive, file a ticket, draft a reply, or leave it.`, "warn"); return; }
      const button = form.querySelector(`button[name="action"][value="${action}"]`) || form.querySelector('button[name="action"]');
      setHeard(`Heard "${text}" → ${button.textContent.trim().split("\n")[0]}`, "ok");
      if (voice.enabled) voice.say(`${button.textContent.trim().split("\n")[0]}. Done.`);
      button.click();
    };

    const start = async () => {
      btn.classList.add("listening");
      setHeard("Listening…");
      voice.stop();
      if (voice.serverTTS && navigator.mediaDevices?.getUserMedia && window.MediaRecorder) {
        try {
          stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          chunks = [];
          rec = new MediaRecorder(stream, { mimeType: MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "" });
          rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
          rec.start();
          return;
        } catch (_) { /* fall back */ }
      }
      try { await onText(await browserRecognize()); } catch (e) { setHeard("Microphone unavailable.", "warn"); }
      btn.classList.remove("listening");
    };

    const stop = async () => {
      if (!rec) return;
      btn.classList.remove("listening");
      const done = new Promise((res) => { rec.onstop = res; });
      rec.stop();
      await done;
      stream?.getTracks().forEach((t) => t.stop());
      rec = null;
      const blob = new Blob(chunks, { type: "audio/webm" });
      setHeard("Transcribing…");
      try { await onText(await transcribeBlob(blob)); }
      catch (e) { setHeard("Couldn't transcribe — check the Groq key.", "warn"); }
    };

    btn.addEventListener("pointerdown", (e) => { e.preventDefault(); start(); });
    btn.addEventListener("pointerup", stop);
    btn.addEventListener("pointerleave", () => { if (rec) stop(); });
    btn.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); if (!rec) start(); } });
    btn.addEventListener("keyup", (e) => { if (e.key === " " || e.key === "Enter") stop(); });
  }

  function scanMics(root = document) {
    root.querySelectorAll('[data-role="mic"]').forEach(bindMic);
  }

  /* --- read the decision aloud when the page opens, if voice is on --- */

  function readDecision() {
    const say = document.querySelector('[data-role="say"]');
    if (say && voice.enabled) voice.say(say.dataset.text);
  }

  /* ---------- wiring ---------- */

  document.addEventListener("DOMContentLoaded", () => {
    bindToggle();
    scanLive();
    scanMics();
    readDecision();
  });
  document.body.addEventListener("htmx:afterSwap", (e) => {
    scanLive(e.target);
    scanMics(e.target);
    readDecision();
  });
})();
