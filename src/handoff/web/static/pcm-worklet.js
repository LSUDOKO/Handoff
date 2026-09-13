// Copyright 2026 The Handoff Authors — SPDX-License-Identifier: Apache-2.0
// Runs on the audio thread. Takes whatever rate the microphone gives (44.1 or
// 48 kHz), downsamples to 16 kHz mono Int16, and posts 4096-sample buffers to
// the page. That is exactly what Amazon Transcribe streaming wants, so the
// server never has to transcode.
class PCMWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.target = 16000;
    this.ratio = sampleRate / this.target;
    this.carry = [];      // float samples not yet emitted
    this.out = new Int16Array(4096);
    this.filled = 0;
    this.pos = 0;         // fractional read position into carry
    this.level = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    // Mic level for the orb, before resampling.
    let sum = 0;
    for (let i = 0; i < ch.length; i++) sum += ch[i] * ch[i];
    this.level = Math.sqrt(sum / ch.length);
    for (let i = 0; i < ch.length; i++) this.carry.push(ch[i]);
    // Linear interpolation resample.
    while (this.pos + 1 < this.carry.length) {
      const i = Math.floor(this.pos), f = this.pos - i;
      const s = this.carry[i] * (1 - f) + this.carry[i + 1] * f;
      this.out[this.filled++] = Math.max(-1, Math.min(1, s)) * 0x7fff;
      this.pos += this.ratio;
      if (this.filled === this.out.length) {
        this.port.postMessage({ pcm: this.out.slice(0, this.filled), level: this.level }, [this.out.slice(0, this.filled).buffer]);
        this.filled = 0;
      }
    }
    const drop = Math.floor(this.pos);
    this.carry.splice(0, drop);
    this.pos -= drop;
    if (this.filled === 0) this.port.postMessage({ level: this.level });
    return true;
  }
}
registerProcessor("pcm-worklet", PCMWorklet);
