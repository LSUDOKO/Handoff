// Copyright 2026 The Handoff Authors — SPDX-License-Identifier: Apache-2.0
//
// The orb: a volumetric sphere rendered in WebGL2, whose colour, motion and
// breathing follow what Handoff is doing. The shader is adapted from DORA's
// (MIT) with two changes — it renders over a transparent canvas rather than
// a chroma-key background, and it listens to an audio level so it swells
// with your voice and with its own.
//
//   const orb = HandoffOrb.mount(canvas, { fallbackEl });
//   orb.setState("listening");   // idle | wake | listening | thinking | speaking | acting | needs
//   orb.setLevel(0.4);           // 0..1, from an AnalyserNode
//   orb.destroy();
//
// Without WebGL2 the fallback element gets the same state as a data attribute
// and CSS draws a soft gradient sphere instead.
(() => {
  "use strict";

  const STATES = {
    idle:      { hue: 0.62, sat: 0.85, speed: 0.28, pulse: 0.06, glow: 0.55, noise: 0.55 },
    wake:      { hue: 0.50, sat: 1.00, speed: 0.60, pulse: 0.18, glow: 0.90, noise: 0.75 },
    listening: { hue: 0.45, sat: 1.00, speed: 0.80, pulse: 0.22, glow: 1.00, noise: 0.85 },
    thinking:  { hue: 0.72, sat: 0.95, speed: 1.40, pulse: 0.10, glow: 0.75, noise: 1.10 },
    speaking:  { hue: 0.58, sat: 0.88, speed: 0.90, pulse: 0.28, glow: 0.85, noise: 0.70 },
    acting:    { hue: 0.38, sat: 0.90, speed: 1.10, pulse: 0.14, glow: 0.80, noise: 0.95 },
    needs:     { hue: 0.10, sat: 0.95, speed: 0.45, pulse: 0.30, glow: 0.95, noise: 0.60 },
  };

  const VS = `#version 300 es
in vec2 a_pos; out vec2 v_uv;
void main(){ v_uv = a_pos*0.5+0.5; gl_Position = vec4(a_pos,0.0,1.0); }`;

  const FS = `#version 300 es
precision highp float;
in vec2 v_uv; out vec4 fragColor;
uniform float uTime, uHue, uSat, uSpeed, uPulse, uGlow, uNoise, uAudio; uniform vec2 uRes;
vec4 mod289(vec4 x){ return x - floor(x*(1./289.))*289.; }
vec4 perm(vec4 x){ return mod289(((x*34.)+1.)*x); }
float snoise3(vec3 v){
  const vec2 C = vec2(1./6., 1./3.);
  vec3 i = floor(v + dot(v,C.yyy)); vec3 x0 = v - i + dot(i,C.xxx);
  vec3 g = step(x0.yzx,x0.xyz); vec3 l = 1.-g; vec3 i1 = min(g.xyz,l.zxy); vec3 i2 = max(g.xyz,l.zxy);
  vec3 x1 = x0-i1+C.xxx, x2 = x0-i2+C.yyy, x3 = x0-0.5;
  i = mod289(i);
  vec4 p = perm(perm(perm(i.z+vec4(0,i1.z,i2.z,1))+i.y+vec4(0,i1.y,i2.y,1))+i.x+vec4(0,i1.x,i2.x,1));
  vec3 ns = 0.142857142857*vec3(0,1,-1) - vec3(0,0.5,1)*0.142857142857;
  vec4 j = p-49.*floor(p*ns.z*ns.z); vec4 x_ = floor(j*ns.z); vec4 y_ = floor(j-7.*x_);
  vec4 xx = x_*ns.x+ns.yyyy; vec4 yy = y_*ns.x+ns.yyyy; vec4 h = 1.-abs(xx)-abs(yy);
  vec4 b0 = vec4(xx.xy,yy.xy), b1 = vec4(xx.zw,yy.zw);
  vec4 s0 = floor(b0)*2.+1., s1 = floor(b1)*2.+1.; vec4 sh = -step(h,vec4(0));
  vec4 a0 = b0.xzyw+s0.xzyw*sh.xxyy; vec4 a1 = b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x), p1=vec3(a0.zw,h.y), p2=vec3(a1.xy,h.z), p3=vec3(a1.zw,h.w);
  vec4 norm = 1.79284291400159-0.85373472095314*vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3));
  p0*=norm.x; p1*=norm.y; p2*=norm.z; p3*=norm.w;
  vec4 m = max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.); m=m*m;
  return 42.*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}
float fbm(vec3 p){ float v=0., a=0.5; for(int i=0;i<5;i++){ v += a*snoise3(p); p = p*2.1 + vec3(3.7,1.2,2.5); a *= 0.5; } return v; }
vec3 hsl2rgb(float h, float s, float l){ vec3 rgb = clamp(abs(mod(h*6.+vec3(0,4,2),6.)-3.)-1., 0., 1.); return l + s*(rgb-0.5)*(1.-abs(2.*l-1.)); }
void main(){
  vec2 uv = (gl_FragCoord.xy - 0.5*uRes) / min(uRes.x,uRes.y);
  float t = uTime * uSpeed;
  vec3 ro = vec3(0,0,2.2); vec3 rd = normalize(vec3(uv, -1.2));
  float R = 0.72 + uAudio*0.05;
  float b = dot(ro,rd); float c = dot(ro,ro) - R*R; float disc = b*b - c;
  if(disc < 0.0){
    // Outside the sphere: a soft halo that breathes with the audio level.
    float d = length(uv) - R*0.62;
    float halo = exp(-d*7.0) * (0.10 + uAudio*0.35) * uGlow;
    vec3 hc = hsl2rgb(uHue, uSat, 0.7);
    fragColor = vec4(hc*halo, halo);
    return;
  }
  float t0 = -b - sqrt(disc); float t1 = -b + sqrt(disc);
  vec3 hit = ro + t0*rd; vec3 nrm = normalize(hit);
  float thickness = (t1-t0) / (2.*R);
  vec2 suv = vec2(atan(nrm.z,nrm.x)/(2.*3.14159)+0.5, acos(nrm.y)/3.14159);
  vec3 np = vec3(suv*2.5, t*0.18);
  float n1 = fbm(np); float n2 = fbm(np*1.8 + vec3(n1*0.4, t*0.09, 0.7));
  float n3 = snoise3(np*3.2 + vec3(0, n2*0.3, t*0.22));
  float N = (n1*0.55 + n2*0.30 + n3*0.15) * (uNoise + uAudio*0.6);
  float irid = N*0.18 + thickness*0.25 + dot(nrm,normalize(vec3(0.6,0.8,1.0)))*0.15;
  float hue = mod(uHue + irid, 1.0);
  float fresnel = pow(1.0 - max(dot(nrm, -rd), 0.0), 3.5);
  vec3 ld = normalize(vec3(0.8, 1.2, 1.6)); float diff = max(dot(nrm,ld),0.0);
  float spec = pow(max(dot(reflect(-ld,nrm),-rd),0.),42.);
  vec3 ld2 = normalize(vec3(-1.2,-0.5, 0.8)); float diff2 = max(dot(nrm,ld2),0.0)*0.35;
  float spec2 = pow(max(dot(reflect(-ld2,nrm),-rd),0.),18.)*0.5;
  float sss = thickness * (0.5 + 0.5*N) * 1.3;
  float pulse = sin(uTime*2.8)*uPulse*0.5 + 1.0 + uAudio*0.25;
  float L = 0.38 + sss*0.18 + diff*0.12 + diff2*0.06;
  vec3 col = hsl2rgb(hue, uSat, clamp(L,0.,1.));
  col += spec * vec3(0.95,0.98,1.00) * 0.85;
  col += spec2 * hsl2rgb(mod(hue+0.12,1.), 0.6, 0.75) * 0.4;
  col += fresnel * hsl2rgb(mod(hue+0.05,1.), 0.8, 0.72) * uGlow * 0.9;
  col += sss * hsl2rgb(mod(hue+0.25,1.), 0.7, 0.65) * 0.55;
  float core = smoothstep(0.6,0.0,length(uv)) * 0.35;
  col += core * hsl2rgb(mod(hue+0.08,1.), 0.5, 0.9);
  col *= pulse;
  float edgeMask = smoothstep(R+0.01, R-0.08, length(uv+nrm.xy*0.05));
  float alpha = clamp(edgeMask * (0.82 + fresnel*0.18 + sss*0.10), 0., 1.);
  col = col / (col + 0.9); col = pow(col, vec3(0.88));
  fragColor = vec4(col * alpha, alpha);
}`;

  const lerp = (a, b, t) => a + (b - a) * t;
  const lerpHue = (a, b, t) => { let d = b - a; if (d > 0.5) d -= 1; if (d < -0.5) d += 1; return (a + d * t + 1) % 1; };

  function compile(gl, type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { const log = gl.getShaderInfoLog(s); gl.deleteShader(s); throw new Error(log); }
    return s;
  }

  function mount(canvas, opts = {}) {
    const fallback = opts.fallbackEl || null;
    let state = "idle";
    const current = { ...STATES.idle }, target = { ...STATES.idle };
    let level = 0, levelTarget = 0;
    let raf = 0, alive = true;

    const api = {
      get state() { return state; },
      setState(name) { state = STATES[name] ? name : "idle"; Object.assign(target, STATES[state]); if (fallback) fallback.dataset.state = state; if (canvas) canvas.dataset.state = state; },
      setLevel(v) { levelTarget = Math.max(0, Math.min(1, Number(v) || 0)); if (fallback) fallback.style.setProperty("--level", levelTarget.toFixed(3)); },
      destroy() { alive = false; cancelAnimationFrame(raf); },
    };

    let gl = null;
    try { gl = canvas.getContext("webgl2", { alpha: true, premultipliedAlpha: true, antialias: true, powerPreference: "low-power" }); } catch { gl = null; }
    if (!gl) {
      canvas.hidden = true;
      if (fallback) { fallback.hidden = false; fallback.dataset.state = "idle"; }
      // Still animate the fallback's breathing via a custom property.
      const tick = (ms) => { if (!alive) return; level = lerp(level, levelTarget, 0.15); if (fallback) fallback.style.setProperty("--t", (ms / 1000).toFixed(2)); raf = requestAnimationFrame(tick); };
      raf = requestAnimationFrame(tick);
      return api;
    }
    if (fallback) fallback.hidden = true;

    let prog;
    try {
      prog = gl.createProgram();
      gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VS));
      gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FS));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    } catch (err) {
      console.warn("orb shader failed, using fallback:", err);
      canvas.hidden = true; if (fallback) { fallback.hidden = false; fallback.dataset.state = "idle"; }
      return api;
    }
    gl.useProgram(prog);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "a_pos");
    gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const U = {};
    for (const n of ["uTime", "uHue", "uSat", "uSpeed", "uPulse", "uGlow", "uNoise", "uAudio", "uRes"]) U[n] = gl.getUniformLocation(prog, n);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

    function resize() {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = Math.round((canvas.clientWidth || 320) * dpr), h = Math.round((canvas.clientHeight || 320) * dpr);
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; gl.viewport(0, 0, w, h); }
    }
    const T = 0.035;
    function render(ms) {
      if (!alive) return;
      raf = requestAnimationFrame(render);
      if (document.hidden) return;
      resize();
      current.hue = lerpHue(current.hue, target.hue, T);
      for (const k of ["sat", "speed", "pulse", "glow", "noise"]) current[k] = lerp(current[k], target[k], T);
      level = lerp(level, levelTarget, 0.2);
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform1f(U.uTime, ms * 0.001);
      gl.uniform1f(U.uHue, current.hue); gl.uniform1f(U.uSat, current.sat); gl.uniform1f(U.uSpeed, current.speed);
      gl.uniform1f(U.uPulse, current.pulse); gl.uniform1f(U.uGlow, current.glow); gl.uniform1f(U.uNoise, current.noise);
      gl.uniform1f(U.uAudio, level);
      gl.uniform2f(U.uRes, canvas.width, canvas.height);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
    raf = requestAnimationFrame(render);
    // A short wake pulse on mount, like DORA's, then settle.
    api.setState("wake"); setTimeout(() => { if (state === "wake") api.setState("idle"); }, 1800);
    return api;
  }

  window.HandoffOrb = { mount, STATES };
})();
