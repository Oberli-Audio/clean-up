#!/usr/bin/env python3
"""Seeded test material for Clean Up's measurements (F.13.3, the brief's `presets.reference`).

The brief's test material is "a vocal and a bass line with injected hum, clicks, pink noise
and a 1.2 s RT60 convolution". There is no sample material in the repository (it lives in
OneDrive, `.gitignore`), so the material here is **synthesised and seeded**: every number in
`docs/status.md` is reproducible from this file with one command, and the ear check on real
church recordings is the listening checkpoint, not a measurement.

Every generator takes a seed and returns float64 (n, 2) at the given rate.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.signal import lfilter


def _stereo(x):
    x = np.asarray(x, dtype=np.float64)
    return np.stack([x, x], axis=1) if x.ndim == 1 else x


def normalise(x, peak_dbfs=-6.0):
    x = np.asarray(x, dtype=np.float64)
    p = np.abs(x).max()
    return x if p <= 0.0 else x * (10.0 ** (peak_dbfs / 20.0) / p)


def resonator(x, fs, hz, q, gain=1.0):
    """One resonant bandpass (a formant), as a direct-form biquad - analysis only."""
    w = 2.0 * math.pi * hz / fs
    r = math.exp(-w / (2.0 * q))
    b = [gain * (1.0 - r), 0.0, -gain * (1.0 - r)]
    a = [1.0, -2.0 * r * math.cos(w), r * r]
    return lfilter(b, a, x)


def vocal(fs, seconds=6.0, seed=1, f0=180.0):
    """A sung line: a band-limited pulse train with vibrato through three formants, in
    phrases with gaps (the gaps are where the noise floor is judged), plus sibilants."""
    rng = np.random.default_rng(seed)
    n = int(round(seconds * fs))
    t = np.arange(n) / fs
    vib = 1.0 + 0.012 * np.sin(2.0 * math.pi * 5.1 * t)
    notes = np.array([0, 2, 3, 5, 7, 5, 3, 0], dtype=float)
    step = seconds / len(notes)
    f = np.empty(n)
    for i, semi in enumerate(notes):
        a, b = int(i * step * fs), int(min(n, (i + 1) * step * fs))
        f[a:b] = f0 * 2.0 ** (semi / 12.0)
    phase = np.cumsum(2.0 * math.pi * f * vib / fs)
    pulses = np.zeros(n)
    for h in range(1, 25):
        if h * f0 * 2.0 ** (7.0 / 12.0) < 0.45 * fs:
            pulses += np.sin(h * phase) / h
    voiced = resonator(pulses, fs, 700.0, 7.0, 1.0)
    voiced += resonator(pulses, fs, 1220.0, 9.0, 0.5)
    voiced += resonator(pulses, fs, 2600.0, 11.0, 0.25)
    # phrase envelope: four phrases with gaps, attacks of 12 ms
    env = np.zeros(n)
    for i in range(4):
        a = int((0.08 + i * 0.25) * seconds * fs)
        b = int(min(n, a + 0.17 * seconds * fs))
        seg = np.ones(b - a)
        ramp = max(1, int(0.012 * fs))
        seg[:ramp] = np.linspace(0.0, 1.0, ramp)
        seg[-int(0.06 * fs):] = np.linspace(1.0, 0.0, int(0.06 * fs))
        env[a:b] = seg
    out = voiced * env
    # sibilants at each phrase start: 4-9 kHz noise bursts, what Attacks has to protect
    sib = rng.standard_normal(n)
    sib = resonator(sib, fs, min(6500.0, 0.4 * fs), 1.2, 1.0)
    for i in range(4):
        a = int((0.08 + i * 0.25) * seconds * fs)
        b = int(min(n, a + 0.05 * fs))
        w = np.hanning(b - a)
        out[a:b] += 0.25 * sib[a:b] * w
    return _stereo(normalise(out, -9.0))


def bass(fs, seconds=6.0, seed=2, notes_hz=(50.0, 100.0, 75.0, 100.0)):
    """A bass line whose notes sit on the mains fundamental and its second harmonic - the
    material that proves the comb does not eat the instrument (the brief's response target)."""
    n = int(round(seconds * fs))
    out = np.zeros(n)
    step = seconds / len(notes_hz)
    for i, hz in enumerate(notes_hz):
        a, b = int(i * step * fs), int(min(n, (i + 1) * step * fs))
        t = np.arange(b - a) / fs
        sig = np.zeros(b - a)
        for h in range(1, 9):
            if h * hz < 0.45 * fs:
                sig += np.sin(2.0 * math.pi * h * hz * t) / h
        env = np.ones(b - a)
        ramp = max(1, int(0.01 * fs))
        env[:ramp] = np.linspace(0.0, 1.0, ramp)
        env[-ramp:] = np.linspace(1.0, 0.0, ramp)
        out[a:b] = sig * env
    return _stereo(normalise(out, -9.0))


def sine(fs, seconds, hz, dbfs=-12.0):
    t = np.arange(int(round(seconds * fs))) / fs
    return _stereo(10.0 ** (dbfs / 20.0) * np.sin(2.0 * math.pi * hz * t))


def snare(fs, seconds=6.0, seed=3, bpm=100.0):
    """Sharp drum hits: the signal a click detector must not repair."""
    rng = np.random.default_rng(seed)
    n = int(round(seconds * fs))
    out = np.zeros(n)
    period = int(round(60.0 / bpm * fs))
    body = 200.0
    for a in range(int(0.05 * fs), n - int(0.3 * fs), period):
        m = int(0.25 * fs)
        t = np.arange(m) / fs
        noise = rng.standard_normal(m) * np.exp(-t / 0.08)
        tone = np.sin(2.0 * math.pi * body * t) * np.exp(-t / 0.05)
        hit = 0.8 * noise + 0.5 * tone
        hit[:8] *= np.linspace(0.0, 1.0, 8)       # a 0.17 ms attack, not a step
        out[a:a + m] += hit
    return _stereo(normalise(out, -6.0))


def pink(fs, n, dbfs=-50.0, seed=4):
    """Paul Kellet's pink approximation - the same shape the harness's `noise:pink` makes."""
    rng = np.random.default_rng(seed)
    w = rng.uniform(-1.0, 1.0, int(n))
    b0 = b1 = b2 = 0.0
    out = np.empty(int(n))
    for i in range(int(n)):
        b0 = 0.99765 * b0 + w[i] * 0.0990460
        b1 = 0.96300 * b1 + w[i] * 0.2965164
        b2 = 0.57000 * b2 + w[i] * 1.0526913
        out[i] = b0 + b1 + b2 + w[i] * 0.1848
    rms = math.sqrt(float(np.mean(out * out)))
    return out * (10.0 ** (dbfs / 20.0) / max(rms, 1.0e-12))


def add_hum(x, fs, f0=50.0, harmonics=8, dbfs=-40.0, drift_hz=0.0, seed=5):
    """Mains hum: fundamental plus harmonics at 1/k, total RMS = dbfs, optional slow drift."""
    x = _stereo(x)
    n = x.shape[0]
    t = np.arange(n) / fs
    inst = np.full(n, float(f0))
    if drift_hz:
        inst += drift_hz * np.sin(2.0 * math.pi * 0.05 * t)
    phase = np.cumsum(2.0 * math.pi * inst / fs)
    hum = np.zeros(n)
    for k in range(1, harmonics + 1):
        hum += np.sin(k * phase) / k
    rms = math.sqrt(float(np.mean(hum * hum)))
    hum *= 10.0 ** (dbfs / 20.0) / max(rms, 1.0e-12)
    return x + hum[:, None], hum


def add_pink(x, fs, dbfs=-50.0, seed=4):
    x = _stereo(x)
    p = pink(fs, x.shape[0], dbfs, seed)
    return x + p[:, None], p


def add_clicks(x, fs, count=100, min_ms=0.5, max_ms=3.0, amp=0.5, seed=6, margin_s=0.15):
    """`count` clicks of min_ms..max_ms, never within one click of each other. Returns
    (y, spans) with spans a list of (start_sample, length_samples)."""
    x = _stereo(x).copy()
    rng = np.random.default_rng(seed)
    n = x.shape[0]
    lo, hi = int(margin_s * fs), n - int(margin_s * fs)
    spans = []
    tries = 0
    while len(spans) < count and tries < count * 200:
        tries += 1
        length = int(round(rng.uniform(min_ms, max_ms) / 1000.0 * fs))
        s = int(rng.integers(lo, hi - length))
        gap = int(0.02 * fs)
        if any(abs(s - s2) < length + l2 + gap for s2, l2 in spans):
            continue
        burst = rng.choice([-1.0, 1.0], size=length) * amp
        burst *= np.hanning(max(3, length))[:length] if length > 2 else 1.0
        x[s:s + length, 0] += burst
        x[s:s + length, 1] += burst
        spans.append((s, length))
    spans.sort()
    return x, spans


def reverb_ir(fs, rt60=1.2, predelay_s=0.008, drr_db=0.0, seed=7):
    """A synthetic room: a direct impulse, then decaying noise. `drr_db` is the
    direct-to-reverberant energy ratio."""
    rng = np.random.default_rng(seed)
    n = int(round((rt60 * 1.3 + predelay_s) * fs))
    ir = np.zeros(n)
    ir[0] = 1.0
    start = int(round(predelay_s * fs))
    t = np.arange(n - start) / fs
    tail = rng.standard_normal(n - start) * np.exp(-3.0 * math.log(10.0) * t / rt60)
    tail *= math.sqrt(10.0 ** (-drr_db / 10.0)) / max(math.sqrt(float(np.sum(tail ** 2))), 1e-12)
    ir[start:] += tail
    return ir


def convolve_room(x, ir):
    x = _stereo(x)
    n = x.shape[0]
    out = np.empty_like(x)
    for ch in range(2):
        out[:, ch] = np.convolve(x[:, ch], ir, mode="full")[:n]
    return out


if __name__ == "__main__":
    import sys
    fs = 48000.0
    v = vocal(fs)
    b = bass(fs)
    s = snare(fs)
    print("vocal  peak %.1f dBFS  rms %.1f dBFS  %d samples"
          % (20 * math.log10(np.abs(v).max()), 10 * math.log10(np.mean(v ** 2)), v.shape[0]))
    print("bass   peak %.1f dBFS  rms %.1f dBFS" % (20 * math.log10(np.abs(b).max()),
                                                    10 * math.log10(np.mean(b ** 2))))
    print("snare  peak %.1f dBFS  rms %.1f dBFS" % (20 * math.log10(np.abs(s).max()),
                                                    10 * math.log10(np.mean(s ** 2))))
    ir = reverb_ir(fs)
    print("room   %d taps, rt60 target 1.2 s" % ir.size)
    sys.exit(0)
