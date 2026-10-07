/* deep-orb.js: the living agent orb for the voice call view, plus the Web Audio meter that drives it.
 * No dependencies. Loaded on demand by deep-assistant.js when a call starts (import('./deep-orb.js')).
 *
 * AudioMeter
 *   listenMic()          getUserMedia -> MediaStreamSource -> AnalyserNode (the user's voice, "listening" state)
 *   listenElement(audio) MediaElementSource -> AnalyserNode -> destination (server TTS playback, "speaking" state)
 *   pulse(strength)      synthetic envelope for browser SpeechSynthesis, which exposes no audio stream (word boundaries)
 *   sample(mode)         {level, low, high} 0..1 for the current state; close() stops tracks and the AudioContext
 * Orb(canvas, {reduced})
 *   setState('idle'|'listen'|'think'|'speak'|'muted'), setMeter(meter), start/pause/resume/stop, collapse()
 *   States lerp into each other (~400 ms); audio levels are smoothed so the surface never jitters.
 *   With prefers-reduced-motion: a static sphere whose brightness follows the state, no morphing, no particles.
 */

export class AudioMeter {
  constructor() { this.ctx = null; this.stream = null; this.micAn = null; this.outAn = null; this.buf = null; this.synthetic = 0; this.muted = false; }
  _ctx() {
    if (!this.ctx) { const C = window.AudioContext || window.webkitAudioContext; if (!C) return null; this.ctx = new C(); }
    if (this.ctx.state === 'suspended') this.ctx.resume().catch(() => {});
    return this.ctx;
  }
  async listenMic() {
    if (this.micAn) return true;
    try {
      const ctx = this._ctx(); if (!ctx) return false;
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const src = ctx.createMediaStreamSource(this.stream);
      const an = ctx.createAnalyser(); an.fftSize = 512; an.smoothingTimeConstant = 0.55; src.connect(an); this.micAn = an;
      return true;
    } catch { return false; }
  }
  listenElement(el) {
    try {
      const ctx = this._ctx(); if (!ctx) return false;
      const src = ctx.createMediaElementSource(el); const an = ctx.createAnalyser(); an.fftSize = 512; an.smoothingTimeConstant = 0.5;
      src.connect(an); an.connect(ctx.destination); this.outAn = an; return true;
    } catch { return false; }
  }
  mute(on) { this.muted = !!on; if (this.stream) this.stream.getAudioTracks().forEach((t) => { t.enabled = !on; }); }
  pulse(strength = 1) { this.synthetic = Math.min(1, Math.max(this.synthetic, strength)); }
  _read(an) {
    if (!an) return { level: 0, low: 0, high: 0 };
    const n = an.frequencyBinCount; if (!this.buf || this.buf.length !== n) this.buf = new Uint8Array(n);
    an.getByteFrequencyData(this.buf);
    let sum = 0, low = 0, high = 0; const nl = Math.max(1, Math.floor(n * 0.15)), nh = Math.max(1, n - Math.floor(n * 0.5));
    for (let i = 0; i < n; i++) { const v = this.buf[i] / 255; sum += v; if (i < nl) low += v; else if (i >= n * 0.5) high += v; }
    return { level: Math.min(1, (sum / n) * 2.2), low: Math.min(1, (low / nl) * 1.6), high: Math.min(1, (high / nh) * 3) };
  }
  sample(mode) {
    let r;
    if (mode === 'listen' && !this.muted) r = this._read(this.micAn);
    else if (mode === 'speak') r = this.outAn ? this._read(this.outAn) : { level: this.synthetic, low: this.synthetic, high: this.synthetic * 0.5 };
    else r = { level: 0, low: 0, high: 0 };
    this.synthetic *= 0.9;
    return r;
  }
  close() {
    try { if (this.stream) this.stream.getTracks().forEach((t) => t.stop()); } catch {}
    this.stream = null; this.micAn = null; this.outAn = null;
    if (this.ctx) { const c = this.ctx; this.ctx = null; try { c.close().catch(() => {}); } catch {} }
  }
}

const STATES = {
  idle:   { scale: 0.92, morph: 0.35, swirl: 0.25, particles: 0, grey: 0, bright: 0.85, breathe: 1 },
  listen: { scale: 1.00, morph: 0.80, swirl: 0.45, particles: 0, grey: 0, bright: 1.00, breathe: 0.4 },
  think:  { scale: 0.84, morph: 0.55, swirl: 1.00, particles: 1, grey: 0, bright: 0.80, breathe: 0.6 },
  speak:  { scale: 1.04, morph: 0.90, swirl: 0.35, particles: 0, grey: 0, bright: 1.25, breathe: 0.3 },
  muted:  { scale: 0.90, morph: 0.00, swirl: 0.10, particles: 0, grey: 1, bright: 0.55, breathe: 0.5 },
};
const PALETTE = {
  base: ['#FFD9B0', '#F28C28', '#FF6A3D', '#E9487A'],       // orange -> coral -> rose
  speak: ['#FFF3E3', '#FFB45E', '#FF7A3D', '#FF5F8E'],      // warmer and brighter while the agent talks
  grey: ['#D9D9DC', '#9A9AA0', '#6B6B72', '#4A4A52'],
};
const lerp = (a, b, k) => a + (b - a) * k;
const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
const toRGB = (c) => (Array.isArray(c) ? c : hex(c));
const mix = (a, b, k) => { const x = toRGB(a), y = toRGB(b); return [lerp(x[0], y[0], k), lerp(x[1], y[1], k), lerp(x[2], y[2], k)]; };  // RGB triplet, mixable again
const css = (c, alpha) => { const [r, g, b] = toRGB(c).map(Math.round); return alpha == null ? `rgb(${r},${g},${b})` : `rgba(${r},${g},${b},${alpha})`; };
const mixA = (a, b, k, alpha) => css(mix(a, b, k), alpha);

export class Orb {
  constructor(canvas, opts = {}) {
    this.c = canvas; this.g = canvas.getContext('2d'); this.reduced = !!opts.reduced;
    this.state = 'idle'; this.cur = { ...STATES.idle, level: 0, low: 0, high: 0, speakMix: 0 }; this.target = { ...STATES.idle };
    this.meter = null; this.t = 0; this.last = 0; this.raf = 0; this.running = false; this.hidden = false; this.collapsing = 0; this.onGlow = opts.onGlow || null;
    this.particles = Array.from({ length: 14 }, (_, i) => ({ a: (i / 14) * Math.PI * 2, r: 1.3 + (i % 3) * 0.12, s: 0.35 + (i % 4) * 0.08, size: 1.5 + (i % 3) }));
    this._vis = () => { this.hidden = document.visibilityState === 'hidden'; if (!this.hidden && this.running && !this.raf) this._loop(); };
    document.addEventListener('visibilitychange', this._vis);
  }
  setMeter(m) { this.meter = m; }
  setState(s) { if (!STATES[s]) s = 'idle'; this.state = s; this.target = { ...STATES[s] }; if (this.reduced) { this.cur = { ...this.cur, ...this.target }; this.draw(0); } }
  start() { this.running = true; this.last = performance.now(); if (!this.raf) this._loop(); }
  pause() { this.running = false; if (this.raf) { cancelAnimationFrame(this.raf); this.raf = 0; } }
  resume() { if (!this.running) this.start(); }
  stop() { this.pause(); document.removeEventListener('visibilitychange', this._vis); }
  collapse(ms = 350) { this.collapsing = performance.now() + ms; this.collapseMs = ms; }
  _loop() {
    this.raf = 0; if (!this.running || this.hidden) return;
    const now = performance.now(); const dt = Math.min(0.05, (now - this.last) / 1000); this.last = now; this.t += dt;
    this.step(dt); this.draw(dt);
    this.raf = requestAnimationFrame(() => this._loop());
  }
  step(dt) {
    const k = this.reduced ? 1 : 1 - Math.exp(-dt / 0.13);  // ~400 ms to settle between states
    for (const key of Object.keys(STATES.idle)) this.cur[key] = lerp(this.cur[key], this.target[key], k);
    this.cur.speakMix = lerp(this.cur.speakMix, this.state === 'speak' ? 1 : 0, k);
    const s = this.meter ? this.meter.sample(this.state === 'muted' ? 'idle' : this.state) : { level: 0, low: 0, high: 0 };
    const up = 1 - Math.exp(-dt / 0.05), down = 1 - Math.exp(-dt / 0.22);
    for (const key of ['level', 'low', 'high']) { const v = Math.min(1, s[key] || 0); this.cur[key] = lerp(this.cur[key], v, v > this.cur[key] ? up : down); }
    if (this.onGlow) this.onGlow(this.cur.bright * (0.55 + this.cur.level * 0.45), this.cur.grey);
  }
  draw(dt) {
    const g = this.g, W = this.c.width, H = this.c.height, cx = W / 2, cy = H / 2; const R0 = Math.min(W, H) * 0.28; const c = this.cur;
    g.clearRect(0, 0, W, H);
    let collapse = 1;
    if (this.collapsing) { const left = (this.collapsing - performance.now()) / this.collapseMs; collapse = Math.max(0, left); if (left <= 0) this.collapsing = 0; }
    const breathe = this.reduced ? 1 : 1 + Math.sin(this.t * 1.1) * 0.022 * c.breathe;
    const R = R0 * c.scale * breathe * (1 + c.level * 0.16 + c.low * 0.06) * (0.15 + 0.85 * collapse);
    const pal = (i) => css(mix(mix(PALETTE.base[i], PALETTE.speak[i], c.speakMix), PALETTE.grey[i], c.grey));
    // soft halo
    const halo = g.createRadialGradient(cx, cy, R * 0.8, cx, cy, R * 2.1);
    halo.addColorStop(0, mixA(PALETTE.base[2], PALETTE.grey[2], c.grey, 0.28 * c.bright * collapse)); halo.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = halo; g.fillRect(0, 0, W, H);
    // outer ring on louder speech (listening) or agent emphasis (speaking)
    const ring = Math.max(0, c.level - 0.3) * (this.state === 'listen' ? 1.4 : this.state === 'speak' ? 1 : 0);
    if (ring > 0.02 && !this.reduced) { g.beginPath(); g.arc(cx, cy, R * (1.18 + ring * 0.35), 0, Math.PI * 2); g.strokeStyle = mixA(PALETTE.base[1], PALETTE.grey[1], c.grey, Math.min(0.6, ring)); g.lineWidth = 2 + ring * 4; g.stroke(); }
    // the sphere: morphing outline
    g.beginPath();
    const N = 96; const m = this.reduced ? 0 : c.morph;
    for (let i = 0; i <= N; i++) {
      const a = (i / N) * Math.PI * 2;
      const wob = 1 + m * (0.045 * Math.sin(3 * a + this.t * 1.3 * (0.6 + c.swirl)) + 0.03 * Math.sin(5 * a - this.t * 0.9) + 0.025 * Math.sin(7 * a + this.t * 2.1))
        + c.high * 0.09 * Math.sin(9 * a + this.t * 6) + c.level * 0.05 * Math.sin(2 * a - this.t * 2);
      const r = R * wob; const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
      if (i === 0) g.moveTo(x, y); else g.lineTo(x, y);
    }
    g.closePath();
    const hx = cx - R * 0.35 + Math.cos(this.t * 0.6) * R * 0.08 * c.swirl, hy = cy - R * 0.38 + Math.sin(this.t * 0.5) * R * 0.08 * c.swirl;
    const grad = g.createRadialGradient(hx, hy, R * 0.05, cx, cy, R * 1.05);
    grad.addColorStop(0, pal(0)); grad.addColorStop(0.35, pal(1)); grad.addColorStop(0.72, pal(2)); grad.addColorStop(1, pal(3));
    g.fillStyle = grad; g.globalAlpha = Math.min(1, 0.7 + 0.3 * c.bright) * (0.35 + 0.65 * collapse); g.fill(); g.globalAlpha = 1;
    // inner swirl: two translucent lobes rotating slowly (the "fluid" surface)
    if (!this.reduced) {
      g.save(); g.beginPath(); g.arc(cx, cy, R * 0.98, 0, Math.PI * 2); g.clip();
      for (let j = 0; j < 2; j++) {
        const ang = this.t * (0.35 + j * 0.2) * (0.5 + c.swirl) + j * 2.1; const lx = cx + Math.cos(ang) * R * 0.35, ly = cy + Math.sin(ang) * R * 0.35;
        const lob = g.createRadialGradient(lx, ly, 0, lx, ly, R * 0.75); lob.addColorStop(0, `rgba(255,255,255,${0.10 + c.speakMix * 0.08})`); lob.addColorStop(1, 'rgba(255,255,255,0)');
        g.fillStyle = lob; g.fillRect(0, 0, W, H);
      }
      g.restore();
    }
    // particles while thinking
    if (c.particles > 0.02 && !this.reduced) {
      for (const p of this.particles) {
        p.a += dt * p.s * (0.6 + c.swirl); const pr = R * p.r + Math.sin(this.t * 1.7 + p.a * 3) * R * 0.05;
        const px = cx + Math.cos(p.a) * pr, py = cy + Math.sin(p.a) * pr * 0.92;
        g.beginPath(); g.arc(px, py, p.size * (W / 440), 0, Math.PI * 2); g.fillStyle = mixA(PALETTE.base[1], PALETTE.grey[1], c.grey, 0.75 * c.particles); g.fill();
      }
    }
  }
}
