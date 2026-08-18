'use strict';
/*
  Speaker Diarization Module
  --------------------------
  Uses Web Audio API (AnalyserNode) to capture pitch + spectral features
  while the SpeechRecognition mic is active.

  Workflow:
    1. Call SpeakerDiarization.start(mediaStream) when mic opens.
    2. After each STT final result, call identifySpeaker(knownName).
       - knownName = parsed name from speech (may be null).
       - Returns { id, name, color, isNew }.
    3. Call SpeakerDiarization.stop() when mic closes.
*/

const SpeakerDiarization = (() => {

  /* ── config ─────────────────────────────────────── */
  const FFT_SIZE           = 2048;
  const SAMPLE_HZ          = 8;          // how often we grab a frame
  const MIN_PITCH_HZ       = 80;
  const MAX_PITCH_HZ       = 450;
  const SILENCE_RMS        = 0.015;
  const SIMILARITY_THRESH  = 0.72;       // cosine similarity cutoff
  const MAX_FRAMES_STORED  = 12;         // rolling window per speaker

  const COLORS = [
    '#3b82f6','#22c55e','#f59e0b','#ef4444',
    '#8b5cf6','#ec4899','#06b6d4','#84cc16',
  ];

  /* ── state ───────────────────────────────────────── */
  let _ctx       = null;
  let _analyser  = null;
  let _source    = null;
  let _timer     = null;
  let _active    = false;
  let _frames    = [];     // feature frames captured since last identifySpeaker call
  let _speakers  = [];     // [{ id, name, frames: [], color }]

  /* ── public: lifecycle ───────────────────────────── */

  function start(mediaStream) {
    if (_active) return;
    try {
      _ctx = new (window.AudioContext || window.webkitAudioContext)();
      _analyser = _ctx.createAnalyser();
      _analyser.fftSize = FFT_SIZE;
      _analyser.smoothingTimeConstant = 0.75;
      _source = _ctx.createMediaStreamSource(mediaStream);
      _source.connect(_analyser);
      _active = true;
      _frames = [];
      _timer = setInterval(_sampleFrame, 1000 / SAMPLE_HZ);
    } catch (e) {
      console.warn('[Diarization] init failed:', e.message);
    }
  }

  function stop() {
    _active = false;
    clearInterval(_timer);
    _timer = null;
    _frames = [];
    try { if (_source)  _source.disconnect(); } catch {}
    try { if (_ctx)     _ctx.close(); }         catch {}
    _source  = null;
    _analyser = null;
    _ctx     = null;
  }

  function reset() {
    stop();
    _speakers = [];
  }

  /* ── public: identify current speaker ───────────── */
  /**
   * Call this right after STT delivers a final transcript.
   * @param {string|null} knownName  — name parsed from speech text, or null
   * @returns {{ id: number, name: string, color: string, isNew: boolean }}
   */
  function identifySpeaker(knownName) {
    const fp = _buildFingerprint();
    _frames  = [];   // reset for next utterance

    if (!fp) {
      // Not enough audio data — fall back to existing name or create generic
      if (knownName) return _getOrCreate(knownName, null);
      return { id: 0, name: 'תלמיד', color: COLORS[0], isNew: false };
    }

    if (knownName) {
      // Named — register/update voice profile
      const spk = _getOrCreate(knownName, fp);
      return { id: spk.id, name: spk.name, color: spk.color, isNew: false };
    }

    // Unnamed — try to match known profile
    return _matchOrCreate(fp);
  }

  /* ── public: accessors ───────────────────────────── */

  function getSpeakers()        { return _speakers.slice(); }
  function isActive()           { return _active; }
  function registerName(id, name) {
    const s = _speakers.find(x => x.id === id);
    if (s) s.name = name;
  }

  /* ── private: audio sampling ──────────────────────── */

  function _sampleFrame() {
    if (!_analyser || !_active) return;

    const td = new Float32Array(FFT_SIZE);
    _analyser.getFloatTimeDomainData(td);

    const rms = _rms(td);
    if (rms < SILENCE_RMS) return;   // silence — skip

    const fd = new Float32Array(_analyser.frequencyBinCount);
    _analyser.getFloatFrequencyData(fd);

    const pitch    = _estimatePitch(td, _ctx.sampleRate);
    const centroid = _spectralCentroid(fd, _ctx.sampleRate);

    if (pitch > MIN_PITCH_HZ && pitch < MAX_PITCH_HZ) {
      _frames.push({ pitch, centroid, rms });
    }
  }

  /* ── private: feature extraction ────────────────── */

  function _rms(buf) {
    let s = 0;
    for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
    return Math.sqrt(s / buf.length);
  }

  function _estimatePitch(buf, sr) {
    // Autocorrelation
    const SIZE   = buf.length;
    const minLag = Math.floor(sr / MAX_PITCH_HZ);
    const maxLag = Math.floor(sr / MIN_PITCH_HZ);

    let bestLag = -1, bestVal = -Infinity;
    for (let lag = minLag; lag <= maxLag; lag++) {
      let sum = 0;
      for (let i = 0; i < SIZE - lag; i++) sum += buf[i] * buf[i + lag];
      if (sum > bestVal) { bestVal = sum; bestLag = lag; }
    }
    return bestLag > 0 ? sr / bestLag : 0;
  }

  function _spectralCentroid(fd, sr) {
    const binHz = sr / (fd.length * 2);
    let wSum = 0, mSum = 0;
    for (let i = 0; i < fd.length; i++) {
      const mag = Math.pow(10, fd[i] / 20);
      wSum += i * binHz * mag;
      mSum += mag;
    }
    return mSum > 0 ? wSum / mSum : 0;
  }

  /* ── private: fingerprint builder ────────────────── */

  function _buildFingerprint() {
    if (_frames.length < 3) return null;
    const n    = _frames.length;
    const pitch    = _frames.reduce((s, f) => s + f.pitch, 0) / n;
    const centroid = _frames.reduce((s, f) => s + f.centroid, 0) / n;
    return { pitch, centroid };
  }

  /* ── private: speaker management ─────────────────── */

  function _cosineSim(a, b) {
    // Normalise pitch to [0,1] over [MIN,MAX], centroid over [0,4000]
    const p1 = (a.pitch    - MIN_PITCH_HZ) / (MAX_PITCH_HZ - MIN_PITCH_HZ);
    const c1 = a.centroid / 4000;
    const p2 = (b.pitch    - MIN_PITCH_HZ) / (MAX_PITCH_HZ - MIN_PITCH_HZ);
    const c2 = b.centroid / 4000;
    const dot = p1 * p2 + c1 * c2;
    const m1  = Math.sqrt(p1 * p1 + c1 * c1);
    const m2  = Math.sqrt(p2 * p2 + c2 * c2);
    return (m1 && m2) ? dot / (m1 * m2) : 0;
  }

  function _avgFingerprint(spk) {
    if (!spk.frames.length) return null;
    const n = spk.frames.length;
    return {
      pitch:    spk.frames.reduce((s, f) => s + f.pitch, 0) / n,
      centroid: spk.frames.reduce((s, f) => s + f.centroid, 0) / n,
    };
  }

  function _pushFrame(spk, fp) {
    spk.frames.push(fp);
    if (spk.frames.length > MAX_FRAMES_STORED) spk.frames.shift();
  }

  function _getOrCreate(name, fp) {
    let spk = _speakers.find(s => s.name === name);
    if (!spk) {
      spk = { id: _speakers.length + 1, name, frames: [], color: COLORS[_speakers.length % COLORS.length] };
      _speakers.push(spk);
    }
    if (fp) _pushFrame(spk, fp);
    return spk;
  }

  function _matchOrCreate(fp) {
    let bestSpk = null, bestSim = 0;
    for (const spk of _speakers) {
      const avg = _avgFingerprint(spk);
      if (!avg) continue;
      const sim = _cosineSim(fp, avg);
      if (sim > bestSim) { bestSim = sim; bestSpk = spk; }
    }

    if (bestSpk && bestSim >= SIMILARITY_THRESH) {
      _pushFrame(bestSpk, fp);
      return { id: bestSpk.id, name: bestSpk.name, color: bestSpk.color, isNew: false };
    }

    // Unknown speaker
    const name = `תלמיד ${_speakers.length + 1}`;
    const spk  = { id: _speakers.length + 1, name, frames: [fp], color: COLORS[_speakers.length % COLORS.length] };
    _speakers.push(spk);
    return { id: spk.id, name, color: spk.color, isNew: true };
  }

  /* ── export ─────────────────────────────────────── */
  return { start, stop, reset, identifySpeaker, getSpeakers, isActive, registerName };

})();
