/* Copyright 2026 The Handoff Authors — SPDX-License-Identifier: Apache-2.0
 *
 * A small canvas-2D orb with the same contract as the app's WebGL orb, so the
 * landing page always has a working orb even when orb.js is not built yet:
 *
 *   window.HandoffOrb.mount(canvas, { fallbackEl }) -> orb
 *   orb.setState("idle" | "wake" | "listening" | "thinking" | "speaking" | "acting" | "needs")
 *   orb.setLevel(0..1)
 *   orb.destroy()
 *
 * A soft radial-gradient sphere with a breathing pulse and a slow hue drift.
 * Amber ("needs") means exactly one thing in this product: waiting on you.
 */
(function () {
  "use strict";

  // Hue per state, as a fraction of the colour wheel — the same table orb.js uses.
  var HUES = { idle: 0.62, wake: 0.50, listening: 0.45, thinking: 0.72, speaking: 0.58, acting: 0.38, needs: 0.10 };
  // How fast the inner motion runs per state.
  var SPEED = { idle: 0.35, wake: 0.8, listening: 0.7, thinking: 1.6, speaking: 1.0, acting: 1.2, needs: 0.5 };
  var REDUCED = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

  function lerp(a, b, t) { return a + (b - a) * t; }

  function mount(canvas, opts) {
    opts = opts || {};
    var ctx = null;
    try { ctx = canvas.getContext("2d", { alpha: true }); } catch (e) { ctx = null; }
    if (!ctx) {
      if (opts.fallbackEl) { opts.fallbackEl.hidden = false; }
      canvas.hidden = true;
      return { setState: function () {}, setLevel: function () {}, destroy: function () {} };
    }
    if (opts.fallbackEl) { opts.fallbackEl.hidden = true; }

    var state = "idle";
    var hue = HUES.idle, hueTarget = HUES.idle;
    var level = 0, levelTarget = 0;
    var speed = SPEED.idle, speedTarget = SPEED.idle;
    var phase = 0, last = 0, raf = 0, alive = true, w = 0, h = 0, dpr = 1;

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      var r = canvas.getBoundingClientRect();
      w = Math.max(1, Math.round(r.width));
      h = Math.max(1, Math.round(r.height));
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    var ro = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
    if (ro) { ro.observe(canvas); } else { window.addEventListener("resize", resize); }
    resize();

    function paint(t) {
      if (!alive) { return; }
      raf = 0;
      if (!last) { last = t; }
      var dt = Math.min(0.05, (t - last) / 1000);
      last = t;
      phase += dt * speed;

      hue = lerp(hue, hueTarget, 1 - Math.pow(0.001, dt));      // ~2 s to settle
      level = lerp(level, levelTarget, 1 - Math.pow(0.0001, dt)); // snappier
      speed = lerp(speed, speedTarget, 1 - Math.pow(0.01, dt));

      var drift = Math.sin(phase * 0.13) * 8;                       // slow hue wander, degrees
      var H = ((hue * 360 + drift) % 360 + 360) % 360;
      var breathe = REDUCED ? 0 : Math.sin(phase * 1.4) * 0.03;
      var R = Math.min(w, h) * 0.30 * (1 + breathe + level * 0.10);
      var cx = w / 2, cy = h / 2;

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      // Outer glow.
      var glow = ctx.createRadialGradient(cx, cy, R * 0.6, cx, cy, R * (1.8 + level * 0.5));
      glow.addColorStop(0, "hsla(" + H + ", 70%, 60%, " + (0.28 + level * 0.25) + ")");
      glow.addColorStop(1, "hsla(" + H + ", 70%, 60%, 0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, w, h);

      // The sphere: a lit body with the highlight up and to the left.
      var body = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R);
      body.addColorStop(0, "hsl(" + H + ", 60%, 88%)");
      body.addColorStop(0.35, "hsl(" + H + ", 65%, 64%)");
      body.addColorStop(0.8, "hsl(" + (H + 12) + ", 60%, 38%)");
      body.addColorStop(1, "hsl(" + (H + 20) + ", 55%, 22%)");
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.fillStyle = body;
      ctx.fill();

      // Inner volume: three soft blobs drifting inside the sphere.
      ctx.save();
      ctx.clip();
      ctx.globalCompositeOperation = "lighter";
      for (var i = 0; i < 3; i++) {
        var a = phase * (0.5 + i * 0.23) + i * 2.1;
        var bx = cx + Math.cos(a) * R * (0.35 + level * 0.2);
        var by = cy + Math.sin(a * 1.3) * R * 0.35;
        var br = R * (0.45 + 0.12 * Math.sin(phase * 0.9 + i));
        var blob = ctx.createRadialGradient(bx, by, 0, bx, by, br);
        blob.addColorStop(0, "hsla(" + (H + 30 * i) + ", 80%, 70%, " + (0.22 + level * 0.15) + ")");
        blob.addColorStop(1, "hsla(" + (H + 30 * i) + ", 80%, 70%, 0)");
        ctx.fillStyle = blob;
        ctx.fillRect(cx - R, cy - R, R * 2, R * 2);
      }
      ctx.restore();

      // Rim light.
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = "hsla(" + H + ", 60%, 90%, 0.35)";
      ctx.stroke();

      if (!document.hidden) { raf = requestAnimationFrame(paint); }
    }

    function start() { if (!raf && alive) { last = 0; raf = requestAnimationFrame(paint); } }
    function onVisibility() { if (document.hidden) { if (raf) { cancelAnimationFrame(raf); raf = 0; } } else { start(); } }
    document.addEventListener("visibilitychange", onVisibility);
    start();

    return {
      setState: function (name) {
        if (!(name in HUES)) { return; }
        state = name;
        hueTarget = HUES[name];
        speedTarget = SPEED[name];
        if (name === "idle" || name === "needs") { levelTarget = 0; }
      },
      setLevel: function (v) {
        v = Number(v);
        levelTarget = isNaN(v) ? 0 : Math.max(0, Math.min(1, v));
      },
      get state() { return state; },
      destroy: function () {
        alive = false;
        if (raf) { cancelAnimationFrame(raf); }
        document.removeEventListener("visibilitychange", onVisibility);
        if (ro) { ro.disconnect(); } else { window.removeEventListener("resize", resize); }
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
    };
  }

  window.HandoffOrb = { mount: mount, HUES: HUES };
})();
