// Tiny synthesized sound kit (WebAudio, no files). Each event type has its own voice: a counter sounds unlike a
// debuff (GDD §18). Audio starts only after the first user gesture.
export class Sfx {
  constructor() {
    this.enabled = true;
    this.ctx = null;
  }

  unlock() {
    if (!this.ctx) {
      try {
        this.ctx = new (window.AudioContext || window.webkitAudioContext)();
        this.master = this.ctx.createGain();
        this.master.gain.value = 0.32;
        this.master.connect(this.ctx.destination);
      } catch { this.ctx = null; }
    }
    if (this.ctx?.state === 'suspended') this.ctx.resume().catch(() => {});
  }

  tone(type, f0, f1, dur, gain = 0.4, at = 0) {
    const c = this.ctx, t = c.currentTime + at;
    const o = c.createOscillator(), g = c.createGain();
    o.type = type;
    o.frequency.setValueAtTime(f0, t);
    o.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + dur);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + 0.015);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(this.master);
    o.start(t);
    o.stop(t + dur + 0.05);
  }

  noise(dur, { from = 800, to = 2400, q = 1.2, gain = 0.35, at = 0, type = 'bandpass' } = {}) {
    const c = this.ctx, t = c.currentTime + at;
    const buf = c.createBuffer(1, Math.ceil(c.sampleRate * dur), c.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    const src = c.createBufferSource(), f = c.createBiquadFilter(), g = c.createGain();
    src.buffer = buf;
    f.type = type;
    f.Q.value = q;
    f.frequency.setValueAtTime(from, t);
    f.frequency.exponentialRampToValueAtTime(to, t + dur);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + dur * 0.2);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(f).connect(g).connect(this.master);
    src.start(t);
  }

  play(name) {
    if (!this.enabled || !this.ctx) return;
    switch (name) {
      case 'whoosh': this.noise(0.45, { from: 300, to: 2600, gain: 0.3 }); break;
      case 'land': this.tone('sine', 110, 38, 0.4, 0.6); this.noise(0.25, { from: 900, to: 200, type: 'lowpass', gain: 0.4 }); break;
      case 'summon': this.tone('sawtooth', 70, 140, 0.8, 0.12); this.tone('triangle', 330, 660, 0.7, 0.18, 0.15); break;
      case 'reveal': [523, 659, 784, 1046].forEach((f, i) => this.tone('triangle', f, f * 1.01, 0.5, 0.2, i * 0.07)); break;
      case 'card': this.tone('square', 1400, 900, 0.05, 0.08); this.tone('sine', 1600, 2600, 0.3, 0.1, 0.03); break;
      case 'buff': this.tone('sine', 420, 940, 0.32, 0.22); break;
      case 'debuff': this.tone('sawtooth', 520, 170, 0.35, 0.1); this.noise(0.25, { from: 600, to: 150, type: 'lowpass', gain: 0.15 }); break;
      case 'counter': this.tone('sawtooth', 900, 120, 0.45, 0.16); this.tone('square', 700, 90, 0.45, 0.06, 0.04); break;
      case 'shield': this.tone('sine', 1200, 1250, 0.5, 0.12); this.tone('sine', 1800, 1850, 0.5, 0.06); break;
      case 'break': this.noise(0.35, { from: 4000, to: 800, gain: 0.25 }); this.tone('triangle', 1500, 400, 0.3, 0.1); break;
      case 'silence': this.tone('square', 180, 120, 0.4, 0.08); this.noise(0.3, { from: 300, to: 200, gain: 0.12 }); break;
      case 'clash': this.tone('sine', 70, 28, 1.0, 0.9); this.noise(0.9, { from: 2000, to: 90, type: 'lowpass', gain: 0.7 }); this.tone('sawtooth', 200, 60, 0.6, 0.15); break;
      case 'sigil': [880, 1320, 1760].forEach((f, i) => this.tone('sine', f, f, 1.3, 0.16, i * 0.05)); break;
      case 'turn': this.tone('triangle', 660, 660, 0.25, 0.15); this.tone('triangle', 990, 990, 0.35, 0.12, 0.12); break;
      case 'pass': this.tone('sine', 520, 480, 0.12, 0.08); break;
      case 'win': [523, 659, 784, 1046, 1318].forEach((f, i) => this.tone('triangle', f, f, 0.6, 0.2, i * 0.11)); break;
      case 'lose': [659, 587, 523, 392].forEach((f, i) => this.tone('triangle', f, f * 0.98, 0.7, 0.18, i * 0.16)); break;
      default:
    }
  }
}
