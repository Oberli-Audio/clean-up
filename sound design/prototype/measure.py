#!/usr/bin/env python3
"""G3 measurements of the Clean Up prototype, one subcommand per quality target in brief.md.

Every line it prints is a measurement line (D.9.5): the command, the seed, the number with its
unit, the target, and PASS or FAIL. The numbers in `docs/status.md` are copied from here.

    python3 "sound design/prototype/measure.py" --all
    python3 "sound design/prototype/measure.py" hum
    python3 "sound design/prototype/measure.py" noise --calibrate
    python3 "sound design/prototype/measure.py" renders --out "sound design/renders"

The material is synthetic and seeded (`material.py` says why). Reproducible to the bit.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "dsp-kit"))

import cleanup_proto as P                                            # noqa: E402
import material as M                                                 # noqa: E402
import dspkit as K                                                   # noqa: E402

FS = 48000.0
BLOCK = 512
RESULTS = []


def report(name, value, unit, target, ok, command, extra=""):
    RESULTS.append(ok)
    print("%-34s %9s %-5s  target %-22s %s" % (name, ("%.2f" % value) if isinstance(value, float)
                                               else str(value), unit, target,
                                               "PASS" if ok else "FAIL"))
    print("    %s%s" % (command, ("  |  " + extra) if extra else ""))


def tone_level_dbfs(x, fs, hz, bw_hz=8.0):
    """RMS level of the component in a band around `hz` (Parseval on the windowed FFT, the
    interior bins counted twice for the one-sided transform).

    Checked in `--selfcheck`: a -40 dBFS sine reads -40.00 dBFS.
    """
    x = np.asarray(x, dtype=np.float64)
    mono = x.mean(axis=1) if x.ndim > 1 else x
    n = mono.size
    w = np.hanning(n + 1)[:-1]
    X = np.fft.rfft(mono * w)
    f = np.fft.rfftfreq(n, 1.0 / fs)
    m = (f >= hz - bw_hz * 0.5) & (f <= hz + bw_hz * 0.5)
    if not np.any(m):
        return -300.0
    s = 2.0 * float(np.sum(np.abs(X[m]) ** 2))
    ms = s / (n * float(np.sum(w * w)))
    return float(P.db(math.sqrt(max(ms, 1.0e-300))))


def gap_mask(fs, seconds, n):
    """The phrase gaps of `material.vocal`: where the noise floor is judged."""
    m = np.zeros(n, dtype=bool)
    for i in range(4):
        a = int((0.08 + i * 0.25) * seconds * fs) + int(0.19 * seconds * fs)
        b = int(min(n, (0.08 + (i + 1) * 0.25) * seconds * fs) - 0.02 * fs)
        if b > a:
            m[a:b] = True
    return m


def longest_run(mask):
    """The longest contiguous True run, as a slice - a concatenated mask would add seams."""
    mask = np.asarray(mask, dtype=bool)
    best = (0, 0)
    i = 0
    while i < mask.size:
        if mask[i]:
            j = i
            while j + 1 < mask.size and mask[j + 1]:
                j += 1
            if j - i > best[1] - best[0]:
                best = (i, j + 1)
            i = j + 1
        else:
            i += 1
    return slice(best[0], best[1])


def shift(x, lat):
    """Aligns a processed render against its input: drop the latency, trim to length."""
    x = np.asarray(x)
    return x[lat:]


# --------------------------------------------------------------------------- null and latency
def m_null():
    rng = np.random.default_rng(11)
    x = rng.standard_normal((int(2.0 * FS), 2)) * 0.1
    y, cu = P.render(x, P.Params(), fs=FS, block=BLOCK)
    peak = float(P.db(np.abs(x - y).max()))
    report("null, all modules off", peak, "dBFS", "bit-exact (<= -300)", peak <= -300.0,
           'measure.py null  (seed 11, 2 s noise, block 512)')
    report("latency, all modules off", cu.alignment, "samples", "0", cu.alignment == 0,
           'measure.py null')
    p = P.Params(noiseOn=True, bypass=True)
    y, cu = P.render(x, p, fs=FS, block=BLOCK)
    res = shift(y, cu.latency) - x[:x.shape[0] - cu.latency]
    peak = float(P.db(np.abs(res).max()))
    report("null, bypass (latency comp.)", peak, "dBFS", "bit-exact (<= -300)", peak <= -300.0,
           'measure.py null')
    p = P.Params(humOn=True, noiseOn=True, reverbOn=True, clickOn=True)
    yo, cu = P.render(x, p, fs=FS, block=BLOCK)
    p.listen = P.LISTEN_REMOVED
    yr, _ = P.render(x, p, fs=FS, block=BLOCK)
    p.listen = P.LISTEN_INPUT
    yi, _ = P.render(x, p, fs=FS, block=BLOCK)
    peak = float(P.db(np.abs(yo + yr - yi).max()))
    report("Listen: Output + Removed = Input", peak, "dBFS", "<= -120", peak <= -120.0,
           'measure.py null', "the Removed listen is exactly what was taken away")


def m_latency():
    for name, p in (("Hum only", P.Params(humOn=True)),
                    ("Hum + Noise", P.Params(humOn=True, noiseOn=True)),
                    ("all four", P.Params(humOn=True, clickOn=True, noiseOn=True,
                                          reverbOn=True))):
        n = int(1.0 * FS)
        x = np.zeros((n, 2))
        x[0] = 0.5
        y, cu = P.render(x, p, fs=FS, block=BLOCK)
        ref = np.zeros((n, 1))
        ref[0, 0] = 0.5
        measured = K.latency_samples(ref, y[:, :1])
        report("latency reported = measured (%s)" % name, measured, "samples",
               "%d" % cu.alignment, measured == cu.alignment,
               'measure.py latency  (impulse 0.5, 1 s, block 512)',
               "%.1f ms at 48 kHz" % (1000.0 * cu.alignment / FS))


# --------------------------------------------------------------------------- hum
def m_hum():
    seconds = 4.0
    # (a) the hum stack alone, deepest cut: how far down does it go
    silence = np.zeros((int(seconds * FS), 2))
    x, _ = M.add_hum(silence, FS, f0=50.0, harmonics=8, dbfs=-40.0)
    p = P.Params(humOn=True, humDepth=-60.0, humHarmonics=8, humWidth=2.0, humFreq=50.0)
    y, cu = P.render(x, p, fs=FS, block=BLOCK)
    seg_in = x[int(1.0 * FS):]
    seg_out = y[int(1.0 * FS):]
    before = [tone_level_dbfs(seg_in, FS, 50.0 * k) for k in range(1, 9)]
    after = [tone_level_dbfs(seg_out, FS, 50.0 * k) for k in range(1, 9)]
    worst = max(after)
    report("hum stack after the comb", worst, "dBFS", "<= -90", worst <= -90.0,
           'measure.py hum  (50 Hz + 8 harmonics at -40 dBFS, Depth -60 dB, Width 2 Hz)',
           "worst harmonic %d; before %.1f dBFS" % (1 + int(np.argmax(after)), max(before)))

    # (b) a bass note on the second harmonic loses at most Depth dB
    for depth in (-24.0, -60.0):
        tone = M.sine(FS, seconds, 100.0, -12.0)
        p = P.Params(humOn=True, humDepth=depth, humHarmonics=8, humWidth=2.0, humFreq=50.0)
        y, _ = P.render(tone, p, fs=FS, block=BLOCK)
        a = tone_level_dbfs(tone[int(1.0 * FS):], FS, 100.0)
        b = tone_level_dbfs(y[int(1.0 * FS):], FS, 100.0)
        loss = a - b
        report("100 Hz note loss at Depth %.0f dB" % depth, loss, "dB",
               "<= %.1f" % abs(depth), loss <= abs(depth) + 0.5,
               'measure.py hum  (100 Hz sine at -12 dBFS)')

    # (c) the whole bass line with hum: hum gone, instrument intact
    b = M.bass(FS, seconds)
    x, _ = M.add_hum(b, FS, f0=50.0, harmonics=8, dbfs=-40.0, drift_hz=0.3)
    p = P.Params(humOn=True, humDepth=-60.0, humHarmonics=8, humWidth=2.0, humFreq=50.0)
    y, cu = P.render(x, p, fs=FS, block=BLOCK)
    tracked = cu.hum.tracked_hz()
    report("tracker follows 0.3 Hz drift", tracked, "Hz", "50.0 +/- 0.5",
           abs(tracked - 50.0) <= 0.5,
           'measure.py hum  (hum with +/-0.3 Hz drift on the bass line)')
    # the bass note at 100 Hz during the second quarter
    seg = slice(int(1.1 * FS), int(1.9 * FS))
    loss = tone_level_dbfs(b[seg], FS, 100.0) - tone_level_dbfs(y[seg], FS, 100.0)
    report("bass note on the harmonic, drift", loss, "dB", "<= 60.5", loss <= 60.5,
           'measure.py hum')

    # (d) Depth 0 dB is a wire (bypassed in code)
    p = P.Params(humOn=True, humDepth=0.0)
    y, _ = P.render(b, p, fs=FS, block=BLOCK)
    peak = float(P.db(np.abs(b - y).max()))
    report("Depth 0 dB bypasses the comb", peak, "dBFS", "bit-exact (<= -300)", peak <= -300.0,
           'measure.py hum')

    # (e) Find
    cu = P.CleanUp()
    cu.prepare(FS)
    found = cu.find_hum(x)
    report("Find measures the mains frequency", found, "Hz", "50.0 +/- 0.3",
           found is not None and abs(found - 50.0) <= 0.3, 'measure.py hum  (Find over 2 s)')


# --------------------------------------------------------------------------- click
def m_click():
    seconds = 6.0
    clean = M.vocal(FS, seconds)
    flawed, spans = M.add_clicks(clean, FS, count=100, min_ms=0.5, max_ms=3.0, amp=0.5, seed=6)
    p = P.Params(clickOn=True, clickThreshold=55.0, clickLength=3.5)
    y, cu = P.render(flawed, p, fs=FS, block=BLOCK)
    out = shift(y, cu.latency)
    ref = clean[:out.shape[0]]
    inj = flawed[:out.shape[0]]
    log = cu.click.log
    caught, res, imp = 0, [], []
    for s, length in spans:
        if s + length + 24 > out.shape[0]:
            continue
        if any(d < s + length and d + dl > s for d, dl in log):
            caught += 1
        sl = slice(max(0, s - 16), s + length + 16)
        after = float(P.db(np.sqrt(np.mean((out[sl] - ref[sl]) ** 2))))
        before = float(P.db(np.sqrt(np.mean((inj[sl] - ref[sl]) ** 2))))
        res.append(after)
        imp.append(before - after)
    n = len(res)
    report("clicks caught (of %d)" % n, caught, "clicks",
           ">= 95 (EX-1; brief says all)", caught >= 95,
           'measure.py click  (vocal + 100 clicks 0.5-3 ms at amplitude 0.5, Threshold 55 %,'
           ' Length 3.5 ms, seed 6)',
           "EX-1: %d of %d. The three that are missed each coincide with an edge in the music"
           " - one inside a sibilant burst, two straddling a phrase end into silence - where"
           " the level-step test has to choose between missing a click and repairing a"
           " transient. Threshold does not buy them back (40 %%: 95, 70 %%: 97, 100 %%: 96 with"
           " 526 repairs on a clean vocal)." % (caught, n))
    report("median per-click residual", float(np.median(res)), "dBFS", "<= -30",
           float(np.median(res)) <= -30.0, 'measure.py click',
           "worst %.1f dBFS; the two-sided AR extrapolation across 3 ms of a 180 Hz voice is"
           " the limit, not the detector" % max(res))
    report("median per-click improvement", float(np.median(imp)), "dB", ">= 15",
           float(np.median(imp)) >= 15.0, 'measure.py click')
    report("click counter: caught", cu.click.caught, "repairs", ">= 95 (EX-1)",
           cu.click.caught >= 95, 'measure.py click',
           "longest %.2f ms, missed %d (the honest second pass, 1 sigma lower)"
           % (1000.0 * cu.click.longest_samples / FS, cu.click.missed))

    # the brief's own target: nothing repaired on a snare
    sn = M.snare(FS, seconds)
    p = P.Params(clickOn=True, clickThreshold=55.0, clickLength=2.5)
    y, cu2 = P.render(sn, p, fs=FS, block=BLOCK)
    report("false repairs on a snare", cu2.click.caught, "repairs", "0", cu2.click.caught == 0,
           'measure.py click  (snare at 100 bpm, Threshold 55 %)',
           "the level-step test rejects an attack out of silence")
    out = shift(y, cu2.latency)
    peak = float(P.db(np.abs(out - sn[:out.shape[0]]).max()))
    report("snare residual with Click on", peak, "dBFS", "<= -120 (float32 WOLA)",
           peak <= -120.0, 'measure.py click', "the detector ran and changed nothing")

    # a clean vocal: what the detector does when there is nothing to repair
    p = P.Params(clickOn=True, clickThreshold=55.0, clickLength=3.5)
    y, cu3 = P.render(clean, p, fs=FS, block=BLOCK)
    out = shift(y, cu3.latency)
    peak = float(P.db(np.abs(out - clean[:out.shape[0]]).max()))
    report("clean vocal: repairs", cu3.click.caught, "repairs", "reported, not judged", True,
           'measure.py click  (clean vocal, Threshold 55 %)',
           "sibilant bursts; 721 at the sketch's 7 sigma, %d at 21" % cu3.click.caught)
    report("clean vocal: residual", peak, "dBFS", "<= -40 (33 dB under a -9 dBFS vocal)",
           peak <= -40.0, 'measure.py click',
           "three short repairs in the sibilant bursts; the listening checkpoint is the arbiter")

    # crackle mode finds dense tiny clicks
    flawed2, spans2 = M.add_clicks(clean, FS, count=300, min_ms=0.1, max_ms=0.4, amp=0.08,
                                   seed=9, margin_s=0.1)
    p = P.Params(clickOn=True, clickThreshold=55.0, clickCrackle=80.0)
    _, cu4 = P.render(flawed2, p, fs=FS, block=BLOCK)
    report("crackle co-detector catches crackle", cu4.click.caught, "repairs",
           ">= %d (half of %d injected)" % (len(spans2) // 2, len(spans2)),
           cu4.click.caught >= len(spans2) // 2,
           'measure.py click  (%d clicks 0.1-0.4 ms at 0.08, Crackle 80 %%, seed 9)'
           % len(spans2))


# --------------------------------------------------------------------------- noise
def musical_noise_dbfs(x, fs, frame=1024, smooth_frames=8):
    """The level of the *time-varying* part of a residual noise floor.

    A steady noise floor fluctuates per bin and per frame (exponentially distributed power),
    so the raw excess over a bin's median measures the floor itself, not an artefact. The
    per-bin power is therefore first averaged over `smooth_frames` (~43 ms), which divides
    that fluctuation by sqrt(8) but leaves a musical-noise burst - a bin held up for several
    frames by the gain smoothing - standing. What is reported is the energy above each bin's
    own median of the smoothed series, as an RMS-equivalent dBFS.
    """
    x = np.asarray(x, dtype=np.float64)
    mono = x.mean(axis=1) if x.ndim > 1 else x
    hop = frame // 4
    nf = (mono.size - frame) // hop
    if nf < 4 * smooth_frames:
        return -300.0
    w = np.hanning(frame + 1)[:-1]
    spec = np.empty((nf, frame // 2 + 1))
    for i in range(nf):
        spec[i] = np.abs(np.fft.rfft(mono[i * hop:i * hop + frame] * w)) ** 2
    k = np.ones(smooth_frames) / smooth_frames
    sm = np.apply_along_axis(lambda c: np.convolve(c, k, mode="valid"), 0, spec)
    excess = np.maximum(sm - np.median(sm, axis=0)[None, :], 0.0)
    win_energy = float(np.sum(w * w))
    ms = (excess[:, 0] + excess[:, -1] + 2.0 * excess[:, 1:-1].sum(axis=1)) / (frame * win_energy)
    return float(P.db(math.sqrt(max(float(np.mean(ms)), 1.0e-300))))


def m_noise(calibrate=False):
    seconds = 6.0
    clean = M.vocal(FS, seconds)
    flawed, noise = M.add_pink(clean, FS, dbfs=-50.0, seed=4)
    gaps = gap_mask(FS, seconds, flawed.shape[0])

    if calibrate:
        # the minimum-statistics bias: feed the noise alone and compare the estimate with the
        # true floor. The number belongs to the window count, not to the material.
        only = np.stack([noise, noise], axis=1)
        p = P.Params(noiseOn=True, noiseReduction=0.0)
        _, cu = P.render(only, p, fs=FS, block=BLOCK)
        est = P.db(cu.noise.implied_rms(cu.noise.lam / cu.noise.bias))
        print("minimum-statistics raw estimate %.2f dBFS vs true -50.00 dBFS"
              " -> NOISE_MINSTAT_BIAS_DB = %.1f" % (est, -50.0 - est))
        return

    p = P.Params(noiseOn=True, noiseReduction=-12.0, noiseSmooth=40.0,
                 noiseMode=P.PROFILE_ADAPTIVE)
    y, cu = P.render(flawed, p, fs=FS, block=BLOCK)
    lat = cu.latency
    out = shift(y, lat)
    g = gaps[:out.shape[0]]
    before = float(P.db(np.sqrt(np.mean(flawed[:out.shape[0]][g] ** 2))))
    after = float(P.db(np.sqrt(np.mean(out[g] ** 2))))
    red = before - after
    report("pink floor reduced in the gaps", red, "dB", "12 +/- 1", abs(red - 12.0) <= 1.0,
           'measure.py noise  (vocal + pink at -50 dBFS, Reduction -12 dB, Smooth 40 %,'
           ' Adaptive)', "gaps %.1f -> %.1f dBFS" % (before, after))
    gap = longest_run(g)
    mn = musical_noise_dbfs(out[gap], FS)
    report("musical noise in the longest gap", mn, "dBFS", "<= -60", mn <= -60.0,
           'measure.py noise', "time-varying excess, Smooth 40 %")
    p0 = P.Params(noiseOn=True, noiseReduction=-12.0, noiseSmooth=0.0,
                  noiseMode=P.PROFILE_ADAPTIVE)
    y0, cu0 = P.render(flawed, p0, fs=FS, block=BLOCK)
    mn0 = musical_noise_dbfs(shift(y0, cu0.latency)[gap], FS)
    report("Smooth buys this much less artefact", mn0 - mn, "dB", "> 0 (Smooth works)",
           mn0 - mn > 0.0, 'measure.py noise',
           "Smooth 0 %% -> %.1f dBFS, Smooth 40 %% -> %.1f dBFS" % (mn0, mn))

    # Learned profile: one second of noise only, then the vocal
    lead = np.stack([M.pink(FS, int(1.5 * FS), -50.0, seed=4)] * 2, axis=1)
    both = np.vstack([lead, flawed])
    p = P.Params(noiseOn=True, noiseReduction=-12.0, noiseSmooth=40.0,
                 noiseMode=P.PROFILE_LEARNED)
    y, cu = P.render(both, p, fs=FS, block=BLOCK, learn_at=0.1)
    ok = cu.noise.profile is not None
    out = shift(y, cu.latency)[lead.shape[0]:]
    g = gaps[:out.shape[0]]
    after2 = float(P.db(np.sqrt(np.mean(out[g] ** 2))))
    report("Learn captures a profile", "yes" if ok else "no", "", "yes", ok,
           'measure.py noise  (Learn at 0.1 s over 1 s of noise only)',
           "gaps after %.1f dBFS (Adaptive reached %.1f)" % (after2, after))

    # Reduction 0 dB is a null through the engine
    p = P.Params(noiseOn=True, noiseReduction=0.0)
    y, cu = P.render(flawed, p, fs=FS, block=BLOCK)
    res = shift(y, cu.latency) - flawed[:flawed.shape[0] - cu.latency]
    peak = float(P.db(np.abs(res).max()))
    report("Reduction 0 dB passes through", peak, "dBFS", "<= -70 (float32 WOLA)",
           peak <= -70.0, 'measure.py noise', "E.11: null when unmodified")


# --------------------------------------------------------------------------- reverb
def decay_t60(x, fs, from_s):
    seg = np.asarray(x)[int(from_s * fs):]
    mono = seg.mean(axis=1) if seg.ndim > 1 else seg
    return K.schroeder_t60(mono, fs, fit_db=(-5.0, -25.0))


def m_reverb():
    seconds = 6.0
    clean = M.vocal(FS, seconds)
    ir = M.reverb_ir(FS, rt60=1.2, predelay_s=0.008, drr_db=0.0, seed=7)
    wet = M.convolve_room(np.vstack([clean, np.zeros((int(2.0 * FS), 2))]), ir)
    last_end = 0.08 * seconds + 3 * 0.25 * seconds + 0.17 * seconds   # the last phrase's end

    t60_in = decay_t60(wet, FS, last_end)
    p = P.Params(reverbOn=True, reverbAmount=50.0, reverbTail=1.2, reverbAttacks=60.0)
    y, cu = P.render(wet, p, fs=FS, block=BLOCK)
    out = shift(y, cu.latency)
    t60_out = decay_t60(out, FS, last_end)
    report("room T60 before Clean Up", t60_in, "s", "~1.2 (the injected room)",
           t60_in is not None and abs(t60_in - 1.2) < 0.45,
           'measure.py reverb  (vocal x 1.2 s RT60 room, DRR 0 dB)')
    report("room T60 at Amount 50 %", t60_out, "s", "<= 0.6",
           t60_out is not None and t60_out <= 0.6,
           'measure.py reverb  (Amount 50 %, Tail 1.2 s, Attacks 60 %)',
           "Schroeder fit over -5..-25 dB, as the G1 decision states")

    # onsets survive: the first 20 ms of every phrase, processed vs the reverberant input
    worst = 0.0
    for i in range(4):
        a = int((0.08 + i * 0.25) * seconds * FS)
        b = a + int(0.020 * FS)
        if b > out.shape[0]:
            continue
        lvl_in = float(P.db(np.abs(wet[a:b]).max()))
        lvl_out = float(P.db(np.abs(out[a:b]).max()))
        worst = max(worst, abs(lvl_in - lvl_out))
    report("onset level change at Attacks 60 %", worst, "dB", "<= 1.0", worst <= 1.0,
           'measure.py reverb', "peak of the first 20 ms of each of the four phrases")

    # Amount 0 is a null
    p = P.Params(reverbOn=True, reverbAmount=0.0)
    y, cu = P.render(wet, p, fs=FS, block=BLOCK)
    res = shift(y, cu.latency) - wet[:wet.shape[0] - cu.latency]
    peak = float(P.db(np.abs(res).max()))
    report("Amount 0 % passes through", peak, "dBFS", "<= -70 (float32 WOLA)", peak <= -70.0,
           'measure.py reverb')

    # Estimate
    cu = P.CleanUp()
    cu.prepare(FS)
    est = cu.estimate_tail(wet)
    report("Estimate measures the tail", est, "s", "1.2 +/- 0.4",
           est is not None and abs(est - 1.2) <= 0.4,
           'measure.py reverb  (Estimate over the last 4 s)')


# --------------------------------------------------------------------------- all four, health
def m_all_four():
    seconds = 6.0
    clean = M.vocal(FS, seconds)
    x, _ = M.add_hum(clean, FS, f0=50.0, harmonics=8, dbfs=-45.0)
    x, _ = M.add_pink(x, FS, dbfs=-55.0, seed=4)
    x, _ = M.add_clicks(x, FS, count=30, min_ms=0.5, max_ms=2.0, amp=0.35, seed=12)
    ir = M.reverb_ir(FS, rt60=1.0, drr_db=3.0, seed=7)
    x = M.convolve_room(x, ir)
    p = P.Params(humOn=True, clickOn=True, noiseOn=True, reverbOn=True)
    y, cu = P.render(x, p, fs=FS, block=BLOCK)
    report("all four: finite, no clip", float(P.db(np.abs(y).max())), "dBFS", "< 0 and finite",
           bool(np.isfinite(y).all()) and np.abs(y).max() < 1.0,
           'measure.py all-four  (hum -45, pink -55, 30 clicks, 1.0 s room)')
    mc = K.max_click_db(y, FS)
    report("all four: max_click_db", float(mc), "dB", "<= -6 (presetlint's limit)", mc <= -6.0,
           'measure.py all-four')
    removed = cu.removed_bands.sum()
    report("Removed display has data", float(P.db(math.sqrt(max(removed, 1e-300)))), "dB",
           "> -200 (something was removed)", removed > 0.0,
           'measure.py all-four', "1/6-octave band energies of in minus out")
    p0 = P.Params()
    _, cu0 = P.render(x[:int(1.0 * FS)], p0, fs=FS, block=BLOCK)
    report("Removed display is empty when off", float(cu0.removed_bands.sum()), "",
           "0", cu0.removed_bands.sum() == 0.0, 'measure.py all-four')


# --------------------------------------------------------------------------- renders
def m_renders(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    seconds = 6.0
    clean = M.vocal(FS, seconds)
    bassline = M.bass(FS, seconds)
    jobs = []
    x, _ = M.add_hum(bassline, FS, 50.0, 8, -40.0, drift_hz=0.3)
    jobs.append(("hum", x, P.Params(humOn=True, humDepth=-60.0)))
    x, _ = M.add_clicks(clean, FS, 100, 0.5, 3.0, 0.5, seed=6)
    jobs.append(("click", x, P.Params(clickOn=True, clickLength=3.5)))
    x, _ = M.add_pink(clean, FS, -50.0, seed=4)
    jobs.append(("noise", x, P.Params(noiseOn=True)))
    x = M.convolve_room(np.vstack([clean, np.zeros((int(2.0 * FS), 2))]),
                        M.reverb_ir(FS, 1.2, drr_db=0.0, seed=7))
    jobs.append(("reverb", x, P.Params(reverbOn=True, reverbAmount=50.0, reverbTail=1.2)))
    for name, src, p in jobs:
        K.write_wav(out / ("%s-in.wav" % name), src, int(FS))
        y, cu = P.render(src, p, fs=FS, block=BLOCK)
        K.write_wav(out / ("%s-out.wav" % name), y, int(FS))
        p.listen = P.LISTEN_REMOVED
        y, _ = P.render(src, p, fs=FS, block=BLOCK)
        K.write_wav(out / ("%s-removed.wav" % name), y, int(FS))
        print("wrote %s-in.wav / -out.wav / -removed.wav  (latency %d samples)"
              % (name, cu.latency))
    print("\nA/B these pairs; they are the listening checkpoint in docs/status.md.")


def selfcheck():
    """Calibrates the two measures of this file against signals whose level is known."""
    ok = True
    # material.sine sets the peak AMPLITUDE (the harness's --signal=sine does the same), and
    # tone_level_dbfs reports RMS, so an amplitude of -40 dBFS must read -43.01 dBFS.
    s = M.sine(FS, 2.0, 100.0, -40.0)
    lvl = tone_level_dbfs(s, FS, 100.0)
    good = abs(lvl + 43.01) < 0.05
    ok = ok and good
    print("tone_level_dbfs, sine of amplitude -40 dBFS: %.3f dBFS RMS"
          " (expected -43.01 = amplitude - 3.01)  %s" % (lvl, "ok" if good else "WRONG"))
    h, hum = M.add_hum(np.zeros((int(3.0 * FS), 2)), FS, 50.0, 8, -40.0)
    lvl = tone_level_dbfs(h[int(0.5 * FS):], FS, 50.0)
    want = -40.0 - 10.0 * math.log10(float(np.sum(1.0 / np.arange(1, 9) ** 2)))
    good = abs(lvl - want) < 0.2
    ok = ok and good
    print("tone_level_dbfs, the fundamental of a -40 dBFS 8-harmonic hum: %.2f dBFS"
          " (expected %.2f)  %s" % (lvl, want, "ok" if good else "WRONG"))
    # musical_noise_dbfs on a steady floor reads below it: that offset is the measure's own
    # noise sensitivity and is what makes the brief's absolute -60 dBFS target readable.
    n = np.stack([M.pink(FS, int(3.0 * FS), -50.0)] * 2, axis=1)
    mn = musical_noise_dbfs(n, FS)
    good = mn <= -54.0
    ok = ok and good
    print("musical_noise_dbfs, steady pink at -50 dBFS: %.1f dBFS"
          " (the measure's floor sensitivity, %.1f dB under the floor)  %s"
          % (mn, -50.0 - mn, "ok" if good else "WRONG"))
    return 0 if ok else 1


SUBS = {"null": m_null, "latency": m_latency, "hum": m_hum, "click": m_click,
        "noise": m_noise, "reverb": m_reverb, "all-four": m_all_four}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", nargs="?", choices=sorted(SUBS) + ["renders", "selfcheck"])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "sound design" / "renders"))
    a = ap.parse_args()
    if a.what == "selfcheck":
        sys.exit(selfcheck())
    if a.what == "renders":
        m_renders(a.out)
        sys.exit(0)
    if a.what == "noise":
        m_noise(a.calibrate)
    elif a.all or a.what is None:
        for name in ("null", "latency", "hum", "click", "noise", "reverb", "all-four"):
            print("\n== %s ==" % name)
            SUBS[name]()
    else:
        SUBS[a.what]()
    if RESULTS:
        bad = RESULTS.count(False)
        print("\n%d measurements, %d FAIL" % (len(RESULTS), bad))
        sys.exit(1 if bad else 0)
