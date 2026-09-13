/* Copyright 2026 The Handoff Authors — SPDX-License-Identifier: Apache-2.0
 *
 * Behaviour for the landing page and the docs. No framework, no build step.
 * Every feature checks for its element first, so the same file runs on both
 * page types.
 */
(function () {
  "use strict";

  var REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  /* ---- Theme: the new theme wipes out from the button as a circle ---------- */

  function currentTheme() {
    var t = document.documentElement.dataset.theme;
    if (t === "dark" || t === "light") { return t; }
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function applyTheme(next) {
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("handoff-theme", next); } catch (e) { /* private window */ }
    $$(".theme-toggle").forEach(function (b) {
      b.setAttribute("aria-label", next === "dark" ? "Switch to light mode" : "Switch to dark mode");
      var icon = $(".theme-icon", b);
      if (icon) { icon.style.animation = "none"; void icon.offsetWidth; icon.style.animation = ""; }
    });
  }
  $$(".theme-toggle").forEach(function (button) {
    button.addEventListener("click", function (e) {
      var next = currentTheme() === "dark" ? "light" : "dark";
      if (!document.startViewTransition || REDUCED) { applyTheme(next); return; }
      var x = e.clientX || innerWidth - 40, y = e.clientY || 30;
      var radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
      var transition = document.startViewTransition(function () { applyTheme(next); });
      transition.ready.then(function () {
        document.documentElement.animate(
          { clipPath: ["circle(0px at " + x + "px " + y + "px)", "circle(" + radius + "px at " + x + "px " + y + "px)"] },
          { duration: 900, easing: "cubic-bezier(0.16, 1, 0.3, 1)", pseudoElement: "::view-transition-new(root)" }
        );
      });
    });
  });

  /* ---- Mobile nav drawer ---------------------------------------------------- */

  var menu = $(".nav-menu"), drawer = $(".nav-drawer");
  if (menu && drawer) {
    menu.addEventListener("click", function () {
      var open = drawer.hidden;
      drawer.hidden = !open;
      menu.setAttribute("aria-expanded", String(open));
    });
    $$("a", drawer).forEach(function (a) { a.addEventListener("click", function () { drawer.hidden = true; menu.setAttribute("aria-expanded", "false"); }); });
  }

  /* ---- Copy buttons: data-copy targets and every code block in the docs ----- */

  var COPY_SVG = '<svg class="idle" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>' +
    '<svg class="ok" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';
  function makeCopy(getText) {
    var b = document.createElement("button");
    b.type = "button"; b.className = "copy"; b.setAttribute("aria-label", "Copy"); b.innerHTML = COPY_SVG;
    b.addEventListener("click", function () {
      var text = getText();
      var done = function () { b.dataset.done = "true"; setTimeout(function () { delete b.dataset.done; }, 1800); };
      if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(text).then(done, done); }
      else {
        var ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
        try { document.execCommand("copy"); } catch (e) { /* nothing to do */ }
        document.body.removeChild(ta); done();
      }
    });
    return b;
  }
  $$(".cmd").forEach(function (cmd) {
    var code = $("code", cmd);
    if (code && !$(".copy", cmd)) { cmd.appendChild(makeCopy(function () { return code.textContent; })); }
  });
  $$(".doc-content pre").forEach(function (pre) {
    var code = $("code", pre) || pre;
    pre.appendChild(makeCopy(function () { return code.textContent.replace(/\n$/, ""); }));
  });

  /* ---- Scroll reveal ----------------------------------------------------------- */

  var reveals = $$(".reveal");
  if (reveals.length) {
    if (REDUCED || !("IntersectionObserver" in window)) { reveals.forEach(function (el) { el.classList.add("revealed"); }); }
    else {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add("revealed"); io.unobserve(en.target); } });
      }, { threshold: 0.15, rootMargin: "0px 0px -40px 0px" });
      reveals.forEach(function (el) { io.observe(el); });
    }
  }

  /* ---- Hero: the drifting wall of tiles ---------------------------------------- */

  var GLYPHS = {
    doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/><path d="M9 13h6M9 17h6"/></svg>',
    clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    plug: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3v5M15 3v5M7 8h10v3a5 5 0 0 1-10 0V8zM12 16v5"/></svg>',
    gate: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v6M12 15v6"/><circle cx="12" cy="12" r="3"/><path d="M5 12h4M15 12h4"/></svg>',
    mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
    cloud: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7 18a4 4 0 0 1-.5-8 6 6 0 0 1 11.6 1.5A3.5 3.5 0 0 1 17.5 18H7z"/></svg>'
  };
  var TILES = [
    ["Morning Inbox Triage", "doc"], ["Gmail", "plug"], ["0 8 * * 1-5", "clock"], ["archive", "gate"],
    ["PR Review Triage", "doc"], ["GitHub", "plug"], ["0 9 * * 1-5", "clock"], ["file_ticket", "gate"],
    ["Competitor Pricing Watch", "doc"], ["Linear", "plug"], ["0 9 * * 1", "clock"], ["draft_reply", "gate"],
    ["Slack Channel Digest", "doc"], ["Slack", "plug"], ["0 18 * * 1-5", "clock"], ["skip", "gate"],
    ["Meeting Follow-up", "doc"], ["Web fetch", "plug"], ["confidence 0.7", "gate"], ["Talk", "mic"],
    ["Amazon Bedrock", "cloud"], ["AgentCore Runtime", "cloud"], ["AgentCore Memory", "cloud"], ["Transcribe", "mic"],
    ["Polly", "mic"], ["Strands Graph", "doc"], ["trigger → executor", "gate"], ["executor → completer", "gate"],
    ["asks once", "gate"], ["learned rule", "doc"], ["EventBridge", "clock"], ["DynamoDB", "cloud"],
    ["MCP", "plug"], ["AgentCore Browser", "cloud"], ["Code Interpreter", "cloud"], ["decided_by: human", "gate"],
    ["decided_by: memory", "gate"], ["one screen", "doc"], ["Nova Pro", "cloud"], ["workspace.yml", "doc"]
  ];
  var drift = $(".drift");
  if (drift) {
    var LANES = 8;
    for (var i = 0; i < LANES; i++) {
      var lane = document.createElement("div");
      lane.className = "drift-lane " + (i % 2 ? "down" : "up");
      lane.style.animationDuration = (55 + i * 7) + "s";
      var mine = TILES.filter(function (_, j) { return j % LANES === i; });
      mine.concat(mine).forEach(function (t) {
        var tile = document.createElement("div");
        tile.className = "drift-tile";
        tile.innerHTML = GLYPHS[t[1]] + "<span></span>";
        tile.lastChild.textContent = t[0];
        lane.appendChild(tile);
      });
      drift.appendChild(lane);
    }
  }

  /* ---- Hero: the rotating "Hand off … Gmail." line ------------------------------ */

  var roll = $("#hero-roll");
  if (roll && !REDUCED) {
    var WORDS = ["Gmail.", "Linear.", "Slack.", "GitHub."];
    var wi = 0;
    setInterval(function () {
      wi = (wi + 1) % WORDS.length;
      var next = roll.cloneNode(false);
      next.textContent = WORDS[wi];
      roll.parentNode.replaceChild(next, roll);
      roll = next;
    }, 2600);
  }

  /* ---- Hero: the orb ------------------------------------------------------------- */

  var canvas = $("#orb");
  if (canvas && window.HandoffOrb) {
    var caption = $("#orb-caption");
    var CAPTIONS = { idle: "Tap to talk", wake: "Listening…", listening: "Listening…", thinking: "Thinking…", speaking: "Every weekday at eight, I'll triage your inbox and ask about anything unsure.", acting: "Saving the workflow…", needs: "A decision is waiting on you" };
    var CYCLE = ["idle", "wake", "listening", "thinking", "acting", "speaking"];
    var orb = window.HandoffOrb.mount(canvas, { fallbackEl: $(".orb-fallback") });
    var ci = 0, hovering = false, t0 = performance.now();
    function show(state) {
      orb.setState(state);
      if (caption) { caption.textContent = CAPTIONS[state] || ""; }
    }
    show("idle");
    if (!REDUCED) {
      setInterval(function () {
        if (hovering) { return; }
        ci = (ci + 1) % CYCLE.length;
        show(CYCLE[ci]);
      }, 2800);
      // A synthetic level, so listening and speaking look alive without a microphone.
      (function tick(now) {
        var s = hovering ? "listening" : CYCLE[ci];
        var t = (now - t0) / 1000;
        var lvl = 0;
        if (s === "listening" || s === "speaking") { lvl = 0.35 + 0.3 * Math.abs(Math.sin(t * 3.1) * Math.sin(t * 1.7)); }
        else if (s === "thinking" || s === "acting") { lvl = 0.15 + 0.1 * Math.sin(t * 2); }
        orb.setLevel(lvl);
        requestAnimationFrame(tick);
      })(t0);
    }
    var hero = canvas.closest(".hero-orb") || canvas;
    hero.addEventListener("pointerenter", function () { hovering = true; show("listening"); });
    hero.addEventListener("pointerleave", function () { hovering = false; show(CYCLE[ci]); });
    hero.addEventListener("click", function () { hovering = !hovering; show(hovering ? "listening" : CYCLE[ci]); });
  }

  /* ---- Hero: "Watch the demo" only exists once there is a video ------------------- */

  var watch = $("#watch-demo");
  if (watch) {
    var url = (watch.dataset.video || "").trim();
    if (!url) { watch.hidden = true; } else { watch.href = url; }
  }

  /* ---- Setup card tabs -------------------------------------------------------------- */

  var tabs = $$(".setup-tabs [role=tab]");
  if (tabs.length) {
    function pick(id) {
      tabs.forEach(function (t) { t.setAttribute("aria-selected", String(t.dataset.tab === id)); });
      $$(".setup-pane").forEach(function (p) { p.hidden = p.dataset.pane !== id; });
    }
    tabs.forEach(function (t) { t.addEventListener("click", function () { pick(t.dataset.tab); }); });
    pick(tabs[0].dataset.tab);
  }

  /* ---- "Handoff for": scroll-driven on wide screens, click-driven on narrow ---------- */

  var forSection = $(".for");
  if (forSection) {
    var items = $$(".for-list li", forSection), shots = $$(".for-shot img", forSection);
    var active = -1;
    function setActive(i) {
      if (i === active) { return; }
      active = i;
      items.forEach(function (li, k) { li.classList.toggle("on", k === i); });
      shots.forEach(function (img, k) { img.classList.toggle("on", k === i); });
    }
    items.forEach(function (li, i) {
      li.addEventListener("mouseenter", function () { setActive(i); });
      $("button", li).addEventListener("click", function () { setActive(i); });
    });
    var wide = matchMedia("(min-width: 900px)");
    function onScroll() {
      if (!wide.matches || REDUCED) { return; }
      var r = forSection.getBoundingClientRect();
      var total = r.height - innerHeight;
      if (total <= 0) { return; }
      var p = Math.min(1, Math.max(0, -r.top / total));
      setActive(Math.min(items.length - 1, Math.floor(p * items.length)));
    }
    addEventListener("scroll", onScroll, { passive: true });
    setActive(0);
    onScroll();
  }

  /* ---- Screen strip: slides sideways as the section scrolls through --------------------- */

  var stripWrap = $(".strip-wrap"), strip = $(".strip");
  if (stripWrap && strip) {
    var frames = $$(".screen-frame", strip), mid = (frames.length - 1) / 2;
    frames.forEach(function (f, i) {
      var d = i - mid;
      f.style.transform = "translate3d(0, " + (1.23 * d * d).toFixed(1) + "px, 0) rotate(" + (0.85 * d).toFixed(2) + "deg)";
    });
    if (!REDUCED) {
      var raf = 0;
      var tickStrip = function () {
        raf = 0;
        var r = stripWrap.getBoundingClientRect();
        var p = Math.min(1, Math.max(0, (innerHeight - r.top) / (innerHeight + r.height)));
        strip.style.transform = "translateX(" + (80 - p * 520) + "px)";
      };
      var onStrip = function () { if (!raf) { raf = requestAnimationFrame(tickStrip); } };
      addEventListener("scroll", onStrip, { passive: true });
      addEventListener("resize", onStrip);
      tickStrip();
    }
  }

  /* ---- Keycaps: a cursor-following glare and a small tilt toward the pointer --------- */

  $$(".keycap").forEach(function (el) {
    el.addEventListener("pointermove", function (e) {
      var r = el.getBoundingClientRect();
      var px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height;
      el.style.setProperty("--mx", (px * 100).toFixed(1) + "%");
      el.style.setProperty("--my", (py * 100).toFixed(1) + "%");
      if (!REDUCED) {
        el.style.setProperty("--ry", ((px - 0.5) * 14).toFixed(2) + "deg");
        el.style.setProperty("--rx", ((0.5 - py) * 14).toFixed(2) + "deg");
      }
    });
    el.addEventListener("pointerleave", function () { el.style.removeProperty("--rx"); el.style.removeProperty("--ry"); });
  });

  /* ---- Docs: the outline tracks the heading you are reading ----------------------------- */

  var outline = $(".doc-outline");
  if (outline && "IntersectionObserver" in window) {
    var links = {};
    $$("a[href^='#']", outline).forEach(function (a) { links[a.getAttribute("href").slice(1)] = a; });
    var heads = $$(".doc-content h2[id], .doc-content h3[id]").filter(function (h) { return links[h.id]; });
    var visible = {};
    function mark() {
      var first = heads.filter(function (h) { return visible[h.id]; })[0];
      if (!first) { return; }
      Object.keys(links).forEach(function (id) { links[id].removeAttribute("aria-current"); });
      links[first.id].setAttribute("aria-current", "true");
    }
    var ho = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { visible[en.target.id] = en.isIntersecting; });
      mark();
    }, { rootMargin: "-80px 0px -60% 0px", threshold: 0 });
    heads.forEach(function (h) { ho.observe(h); });
  }
})();
