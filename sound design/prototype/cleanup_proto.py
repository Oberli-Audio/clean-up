#!/usr/bin/env python3
"""Clean Up - the G2 prototype (sound-design-bob F.15.1, effect + STFT row: numpy, not Faust).

The reference implementation of the four modules, written in **the structure the C++ port is
forced to use** (F.8): the hum comb is a per-sample TPT SVF loop, the three spectral modules
run inside one WOLA STFT driven by a hop loop, the click stage sits in the same framing and
takes its lookahead from it. G5 nulls `Source/dsp/*` against this file.

Every length is in seconds and converted in `prepare` (rule 12); every constant that is not a
parameter is named here once with its reason, and the C++ repeats the name and the value.

    python3 cleanup_proto.py --selftest        # the programmatic checks of G2

Numerics: the hum comb runs in float64 (the C++ comb too - a Q of 400 needs it); the spectral
path casts to float32 at every stage boundary, so the G5 null against JUCE's float FFT is a
precision difference and nothing else.

Latency, derived once (the sketch's "one STFT hop plus the click lookahead" is loose: a 2048
frame at 4x overlap costs frame - hop by itself):

    priming of the output FIFO   hop            (a host block is not a multiple of the hop)
    WOLA delay                   frame - hop
    click lookahead              round(CLICK_LOOKAHEAD_S * fs)
    -------------------------------------------------------------
    reported latency             frame + lookahead

At 48 kHz: 2048 + 576 = 2624 samples = 54.7 ms. Two states only, as the sketch decided: 0 with
Hum alone or nothing on, `frame + lookahead` as soon as Click, Noise or Reverb is on - the
lookahead is always in the budget so switching Click alone never moves the latency.
"""
from __future__ import annotations

import argparse
import math
import sys

import numpy as np

# --------------------------------------------------------------------------- constants
# Framing. The sketch decided 2048 at 48 kHz with 4x overlap; stated in seconds and rounded up
# to a power of two at the prepared rate, so the time resolution is the same at every rate
# (rule 12, and it keeps "different at 96 kHz" out of the failure library).
FRAME_SECONDS = 2048.0 / 48000.0        # 42.667 ms
OVERLAP = 4                             # hop = frame / 4; periodic Hann then satisfies COLA
WOLA_HANN_SUM = 1.5                     # sum of squared periodic Hann at hop = N/4

# Hum. The tracker is an I/Q frequency estimator on the fundamental: the complex envelope's
# phase advance over one sub-block is the offset in Hz (one atan2 per sub-block, no per-sample
# transcendental).
HUM_TRACK_TAU_S = 2.0                   # sketch 4.2
HUM_TRACK_RANGE_HZ = 0.5                # sketch 4.2: mains drift, not a frequency search
HUM_TRACK_UPDATE_S = 32.0 / 48000.0     # 0.667 ms: the tracker's sub-block
HUM_TRACK_LP_TAU_S = 0.200              # I/Q lowpass per stage: passes the drift, not the music
HUM_TRACK_LP_STAGES = 2                 # one pole leaves the 2nd harmonic 24 dB down in I/Q,
                                        # which biases the estimate by ~0.01 Hz - and 0.01 Hz
                                        # off a 2 Hz notch is -40 dB instead of -60, because
                                        # |H(f0+d)| = max(A^2, 2 d / Width). Two poles fix it.
HUM_TRACK_PHASE_GAP_S = 0.100           # the phase advance is read over 100 ms, not over one
                                        # sub-block: at 0.667 ms a 0.001 Hz offset is 4e-9 rad
HUM_TRACK_GATE = 1.0e-5                 # |z| below this is not a fundamental: freeze the track
HUM_TRACK_WARMUP_S = 5.0 * HUM_TRACK_LP_TAU_S
                                        # The loop stays open until the two I/Q poles and the
                                        # phase ring have settled. Without it the first,
                                        # meaningless estimates pushed the track 17 mHz off and
                                        # the 2 s loop then took 8 s to creep back - measured as
                                        # -80 dBFS of hum over 1-2 s against -91 over 3-4 s. The
                                        # cost is a 1 s lock time, which is the right trade.
HUM_TRACK_RECOEF_HZ = 0.001             # deadband on the *coefficient* write: below this step
                                        # the notches are left alone, so a locked comb is a
                                        # static comb and costs nothing per sub-block. A frozen
                                        # comb reaches -102 dBFS on the brief's hum stack, so
                                        # what is left after this is the tracking error itself:
                                        # harmonic k's notch is off by k x delta while Width
                                        # stays, and |H| = max(A^2, 2 k delta / Width).
HUM_BYPASS_DEPTH_DB = -0.01             # Depth 0 dB is no cut, so the comb is a wire

# Click. Threshold 0-100 % maps to 12-3 sigma (sketch 4.3): 0 % = only loud clicks.
CLICK_AR_ORDER = 32                     # detection: a low order leaves a large residual, so a
                                        # click stands out (measured on the clean vocal: 14 false
                                        # detections at order 32, 442 at order 256, because an
                                        # over-fitted model shrinks sigma with the error)
CLICK_CRACKLE_AR_ORDER = 8
CLICK_BURG_BLOCK_S = 0.010              # the detection model is refitted on the 10 ms before
                                        # the hop - clean history, so a click cannot bias it
CLICK_REPAIR_AR_ORDER = 192             # repair: extrapolating 3 ms of a 180 Hz voice needs more
                                        # history than 32 samples. Median per-click residual
                                        # 32 -> -31.5 dBFS, 192 -> -42.0, 256 -> -43.5; 192 is
                                        # where the curve flattens. Fitted at most once per hop.
CLICK_REPAIR_BURG_BLOCK_S = 0.040       # Burg needs N >> order: 40 ms is 1920 samples at 48 kHz
CLICK_SIGMA_AT_0 = 40.0                 # Threshold 0 % = only loud clicks. The sketch's 12-3
CLICK_SIGMA_AT_100 = 6.0                # was measured far too sensitive: the glottal pulses of
                                        # a voice are the AR model's own excitation and stand
                                        # 7-8 sigma out, so at the default 55 % (7 sigma) the
                                        # detector fired once per pitch period - 721 repairs on
                                        # a clean vocal. 40-6 puts the default at 21 sigma: 12
                                        # false detections on the same vocal, 83 of 100 clicks
                                        # repaired, 3 on a snare (and the step test below takes
                                        # those).
CLICK_MERGE_S = 0.001                   # two detections closer than this are one click
CLICK_EXTEND_SIGMA = 6.0                # hysteresis: a detected run grows outwards while the
                                        # prediction error stays above this many sigma. The
                                        # detection threshold (21 sigma at 55 %) finds only a
                                        # click's core: measured in a room with hum and noise, the
                                        # repairs started 13-46 samples into the click and ended
                                        # 17-45 before its end, and left a -13.8 dBFS residual
CLICK_EXTEND_MAX_S = 0.001              # at most this much growth on each side
CLICK_EXTEND_GAP_S = 0.00025            # the growth crosses dips this short: a burst's error
                                        # dips below any threshold every few samples, and a
                                        # sample-by-sample walk stopped at the first one
CLICK_RUN_SLACK_ORDER = 1.0             # a click of L samples keeps the prediction error high
                                        # for about L + order samples, because the model's own
                                        # history is corrupted that long. A run longer than
                                        # max_span + order x this is **rejected**, not clamped:
                                        # it is music. Clamping it is what repaired 28 snare
                                        # hits as clicks.
CLICK_ABS_FLOOR_DBFS = -80.0            # absolute floor under the threshold. In a true silence
                                        # the median of |e| is 0, the threshold with it, and
                                        # every last-bit wiggle is a click: measured 863
                                        # detections for 100 injected. Nothing under -80 dBFS
                                        # is an audible click anyway.
CLICK_MAX_STEP_DB = 12.0                # A click is a discontinuity *between two similar
                                        # contexts*; a note starting out of silence is a level
                                        # step, and the run-length test cannot tell them apart
                                        # (a snare attack settles into a well-predicted noise
                                        # burst after ~95 samples, so its run is short). If the
                                        # context RMS either side of the span differs by more
                                        # than this, the span is an edge in the music and is
                                        # left alone.
CLICK_RUNAWAY_FACTOR = 4.0              # safety net: an AR extrapolation that exceeds this
                                        # times the local peak is replaced by a cosine bridge
                                        # between the two context ends. Burg is minimum phase
                                        # in theory; in float it is not always.
CLICK_CRACKLE_LENGTH_S = 0.0005         # the crackle detector's span clamp
CLICK_CONTEXT_S = 64.0 / 48000.0        # 1.333 ms of context each side, >= the AR order
CLICK_STEP_LONG_S = 0.005               # the level-step test's second scale, longer than a sung
                                        # pitch period: an edge in the music is a step at both
                                        # scales. At 1.333 ms alone the RMS swung with where a
                                        # window fell between glottal pulses (-31.0 against
                                        # -18.6 dBFS around a click in a held note); at 5 ms
                                        # alone a click 4 ms before a phrase onset read as one
CLICK_XFADE_S = 8.0 / 48000.0           # 0.167 ms raised-cosine seam at each edge
CLICK_LOOKAHEAD_S = 0.012               # >= the longest span (10 ms) + the context (1.33 ms)
CLICK_MISSED_SIGMA_MARGIN = 1.0         # the honest counter: the second pass is 1 sigma lower
CLICK_COUNT_WINDOW_S = 6.0              # the readout is "n clicks in 6 s" (sketch 4.3)

# Noise. Minimum statistics over 1.5 s in 6 sub-windows. The minimum of a set of smoothed
# power estimates is biased low; NOISE_MINSTAT_BIAS_DB is the compensation, a property of the
# window count and not of the material, measured by `measure.py noise --calibrate`.
NOISE_MINSTAT_WINDOW_S = 1.5
NOISE_MINSTAT_SUBWINDOWS = 6
NOISE_MINSTAT_SMOOTH_S = 0.200          # Martin's method tracks the minimum of a *smoothed*
                                        # periodogram. Taking the minimum of the raw one is what
                                        # the first version did and it read 21.8 dB low - the
                                        # minimum of N exponential samples has mean 1/N of their
                                        # mean, and a 1.5 s window at a 10.7 ms hop is N = 140.
NOISE_MINSTAT_BIAS_DB = 1.8             # what is left of that bias after the smoothing, measured
                                        # by `measure.py noise --calibrate` on pink noise. A
                                        # property of the window count, not of the material.
# Decision-directed a-priori SNR (Ephraim-Malah): xi = a G(l-1)^2 gamma(l-1) + (1-a) max(gamma-1, 0),
# a = exp(-hop / tau) with tau from Smooth %, log-spaced (rule 12: a time, not a per-frame factor).
# The sketch's 0.5-0.98 put the default (0.69) where the Wiener cannot reach its own floor in
# pure noise: measured, 8.6 dB at a floor of -42 dB. A noise-only bin then reaches its floor
# only when a >= ~0.98, i.e. tau >= ~0.5 s at a 10.7 ms hop (`measure.py noise`).
NOISE_DD_TAU_AT_0_S = 0.25              # Smooth 0 %: onsets lose 0.30 dB in their first 10 ms
NOISE_DD_TAU_AT_100_S = 4.0             # Smooth 100 %: 1.08 dB; the default 40 % is 0.76 s
NOISE_LEARN_S = 1.0                     # Learn captures one second
NOISE_LEARN_MAX_DBFS = -40.0            # louder than this during Learn is not a noise profile

# Reverb. Lebart-style: the late power is predicted from the frame REVERB_PREDELAY_S back,
# scaled by the Tail decay, so the direct sound is not part of the estimate.
REVERB_PREDELAY_S = 0.050
REVERB_SMOOTH_FRAMES = 2.0
REVERB_FLOOR_DB_AT_FULL = -24.0         # the deepest suppression, at Amount 100 %
REVERB_ATTACK_HOLD_S = 0.040            # Attacks % of this window is held at gain 1
REVERB_FLUX_TAU_S = 0.200               # running mean of the spectral flux
REVERB_FLUX_FACTOR = 1.6                # an onset is a flux this much above its mean

# Switching between the two latency states, and Hum on/off, Listen and Bypass (rule 2:
# switches crossfaded over 10-20 ms).
SWITCH_XFADE_S = 0.015
TRIM_RAMP_S = 0.092                     # Trim's multiplicative ramp: 4.6 x the table's 20 ms tau

LISTEN_OUTPUT, LISTEN_REMOVED, LISTEN_INPUT = 0, 1, 2
MODE_CLICKS, MODE_CRACKLE = 0, 1
PROFILE_LEARNED, PROFILE_ADAPTIVE = 0, 1

# The bands of the Removed display: 1/6 octave, 50 Hz to 10 kHz (sketch 4.6).
BAND_LOW_HZ, BAND_HIGH_HZ, BANDS_PER_OCTAVE = 50.0, 10000.0, 6


def db(x, floor=-300.0):
    a = np.abs(np.asarray(x, dtype=np.float64))
    with np.errstate(divide="ignore"):
        d = 20.0 * np.log10(np.where(a > 0.0, a, 1.0e-300))
    d = np.maximum(d, floor)
    return d if d.shape else float(d)


def undb(d):
    return 10.0 ** (float(d) / 20.0)


def next_pow2(n):
    p = 1
    while p < n:
        p *= 2
    return p


# --------------------------------------------------------------------------- Params
class Params:
    """The plugin's parameters in plain units, exactly the rows of parameters.csv."""

    def __init__(self, **kw):
        self.humOn = False
        self.humDepth = -24.0
        self.humHarmonics = 8
        self.humWidth = 2.0
        self.humFreq = 50.0
        self.clickOn = False
        self.clickThreshold = 55.0
        self.clickLength = 2.5
        self.clickCrackle = 0.0
        self.clickMode = MODE_CLICKS
        self.noiseOn = False
        self.noiseReduction = -12.0
        self.noiseSmooth = 40.0
        self.noiseFloor = -60.0
        self.noiseMode = PROFILE_ADAPTIVE
        self.reverbOn = False
        self.reverbAmount = 35.0
        self.reverbTail = 0.9
        self.reverbAttacks = 60.0
        self.listen = LISTEN_OUTPUT
        self.trim = 0.0
        self.bypass = False
        for k, v in kw.items():
            if not hasattr(self, k):
                raise KeyError("no such parameter: %s" % k)
            setattr(self, k, v)

    @property
    def spectral(self):
        return bool(self.clickOn or self.noiseOn or self.reverbOn)


# --------------------------------------------------------------------------- building blocks
class SvfBell:
    """One TPT (Cytomic / Simper) state-variable filter in its bell form, float64.

    Its transfer function, which the selftest and the C++ unit test both check:
        a0 = 1 + k g + g^2,  a1 = 2 g^2 - 2,  a2 = 1 - k g + g^2
        b  = ([a0, a1, a2] + m1 g [1, 0, -1]) / a0,   m1 = k (A^2 - 1)
    with g = tan(pi f / fs) and A = 10^(gain_db / 40).

    **k is the bandwidth, not 1/(Q A).** The bell's centre gain is A^2 for *any* k, because
    the SVF bandpass peaks at 1/k and m1 carries the k back; k alone sets the width, and the
    underlying bandpass's -3 dB bandwidth is k * f0. Simper's published `k = 1/(Q A)` makes
    the width scale with the depth: at Depth -60 dB (A = 0.0316) a Width of 2 Hz would come
    out 63 Hz wide, and the comb would eat the bass instead of the hum (measured on the bass
    line: 61.5 dB of loss on a 100 Hz note where the target is at most Depth). So Width is
    handed in as Hz and k = Width / f0.
    """

    __slots__ = ("g", "k", "a1", "a2", "a3", "m1", "ic1", "ic2")

    def __init__(self):
        self.g = self.k = self.a1 = self.a2 = self.a3 = self.m1 = 0.0
        self.ic1 = self.ic2 = 0.0

    def reset(self):
        self.ic1 = self.ic2 = 0.0

    def set(self, fs, hz, bw_hz, gain_db):
        hz = min(max(hz, 1.0), 0.45 * fs)
        a = 10.0 ** (gain_db / 40.0)
        self.g = math.tan(math.pi * hz / fs)
        self.k = max(bw_hz / hz, 1.0e-6)
        self.m1 = self.k * (a * a - 1.0)
        self.a1 = 1.0 / (1.0 + self.g * (self.g + self.k))
        self.a2 = self.g * self.a1
        self.a3 = self.g * self.a2

    def process(self, x):
        v3 = x - self.ic2
        v1 = self.a1 * self.ic1 + self.a2 * v3
        v2 = self.ic2 + self.a2 * self.ic1 + self.a3 * v3
        self.ic1 = 2.0 * v1 - self.ic1
        self.ic2 = 2.0 * v2 - self.ic2
        return x + self.m1 * v1          # m0 = 1, m2 = 0

    def coeffs(self):
        """The equivalent biquad, for the selftest only (never used in the signal path)."""
        g, k, m1 = self.g, self.k, self.m1
        a0 = 1.0 + k * g + g * g
        a1 = 2.0 * g * g - 2.0
        a2 = 1.0 - k * g + g * g
        b = np.array([a0 + m1 * g, a1, a2 - m1 * g]) / a0
        return b, np.array([1.0, a1 / a0, a2 / a0])


class OnePole:
    __slots__ = ("a", "z")

    def __init__(self):
        self.a = 0.0
        self.z = 0.0

    def set(self, fs, tau_s):
        self.a = math.exp(-1.0 / max(tau_s * fs, 1.0))

    def reset(self, v=0.0):
        self.z = v

    def process(self, x):
        self.z = self.a * self.z + (1.0 - self.a) * x
        return self.z


# --------------------------------------------------------------------------- Hum
class HumComb:
    """Adaptive notch comb of bell filters, time domain, zero latency, bypassed when off."""

    MAX_HARMONICS = 16

    def __init__(self):
        self.bells = [[SvfBell() for _ in range(self.MAX_HARMONICS)] for _ in range(2)]
        self.iq_i = [OnePole() for _ in range(HUM_TRACK_LP_STAGES)]
        self.iq_q = [OnePole() for _ in range(HUM_TRACK_LP_STAGES)]
        self.fs = 48000.0
        self.tracked = None

    def prepare(self, fs):
        self.fs = float(fs)
        self.update_samples = max(1, int(round(HUM_TRACK_UPDATE_S * fs)))
        for s in self.iq_i + self.iq_q:
            s.set(fs, HUM_TRACK_LP_TAU_S)
        self.track_coef = 1.0 - math.exp(-(self.update_samples / fs) / HUM_TRACK_TAU_S)
        self.gap = max(1, int(round(HUM_TRACK_PHASE_GAP_S * fs / self.update_samples)))
        self.warmup = max(self.gap + 1,
                          int(round(HUM_TRACK_WARMUP_S * fs / self.update_samples)))
        self.reset()

    def reset(self):
        for ch in self.bells:
            for b in ch:
                b.reset()
        for s in self.iq_i + self.iq_q:
            s.reset()
        self.osc_phase = 0.0
        self.tracked = None
        self.ring_i = [0.0] * (self.gap + 1)
        self.ring_q = [0.0] * (self.gap + 1)
        self.ring_at = 0
        self.ring_filled = 0
        self.counter = 0
        self.active_harmonics = 0
        self.coef_freq = 0.0

    def tracked_hz(self):
        return float(self.tracked) if self.tracked is not None else 0.0

    def _set_coeffs(self, p):
        f0 = self.tracked
        self.coef_freq = f0
        n = int(min(max(p.humHarmonics, 1), self.MAX_HARMONICS))
        bw = max(p.humWidth, 1.0e-3)        # Width is the notch bandwidth in Hz, every harmonic
        for k in range(n):
            hz = f0 * (k + 1)
            for ch in range(2):
                self.bells[ch][k].set(self.fs, hz, bw, p.humDepth)
        self.active_harmonics = n

    def process(self, x, p):
        """x: (n, 2) float64 -> (n, 2) float64."""
        if self.tracked is None:
            self.tracked = float(p.humFreq)
        if p.humDepth >= HUM_BYPASS_DEPTH_DB:
            return x                                 # bypassed in code, not a 0 dB filter
        self._set_coeffs(p)
        n = x.shape[0]
        y = np.empty_like(x)
        nh = self.active_harmonics
        rows = (self.bells[0][:nh], self.bells[1][:nh])
        dphi = 2.0 * math.pi / self.fs
        lo = p.humFreq - HUM_TRACK_RANGE_HZ
        hi = p.humFreq + HUM_TRACK_RANGE_HZ
        for i in range(n):
            xl = x[i, 0]
            xr = x[i, 1]
            mid = 0.5 * (xl + xr)
            c = math.cos(self.osc_phase)
            s = math.sin(self.osc_phase)
            vi = mid * c
            vq = -mid * s
            for st in self.iq_i:
                vi = st.process(vi)
            for st in self.iq_q:
                vq = st.process(vq)
            self.osc_phase += dphi * self.tracked
            if self.osc_phase > 2.0 * math.pi:
                self.osc_phase -= 2.0 * math.pi
            self.counter += 1
            if self.counter >= self.update_samples:
                self.counter = 0
                old = (self.ring_at + 1) % (self.gap + 1)
                pi_, pq_ = self.ring_i[old], self.ring_q[old]
                self.ring_at = old
                self.ring_i[old], self.ring_q[old] = vi, vq
                if self.ring_filled <= self.warmup:
                    self.ring_filled += 1
                elif math.hypot(vi, vq) > HUM_TRACK_GATE:
                    # phase advance of the complex envelope over HUM_TRACK_PHASE_GAP_S -> Hz
                    cr = vi * pi_ + vq * pq_
                    ci = vq * pi_ - vi * pq_
                    hz = (math.atan2(ci, cr) * self.fs
                          / (2.0 * math.pi * self.update_samples * self.gap))
                    target = min(max(self.tracked + hz, lo), hi)
                    self.tracked += self.track_coef * (target - self.tracked)
                    if abs(self.tracked - self.coef_freq) > HUM_TRACK_RECOEF_HZ:
                        self._set_coeffs(p)
                        rows = (self.bells[0][:nh], self.bells[1][:nh])
            for b in rows[0]:
                xl = b.process(xl)
            for b in rows[1]:
                xr = b.process(xr)
            y[i, 0] = xl
            y[i, 1] = xr
        return y


# --------------------------------------------------------------------------- Click
def burg(x, order):
    """Burg's method. Returns `pred` with xhat[n] = sum_k pred[k] x[n-1-k].

    Checked in --selftest against a known AR(2) process.

    The denominator is computed directly at every order, not by the textbook recursion
    d = (1 - mu^2) d - f[m+1]^2 - b[n-m-2]^2. On a highly predictable source (a sustained vowel
    over 40 ms) d falls from ~2.6 to ~6e-10 by order 24 and the recursion's subtraction is then
    all rounding. Found at G5: the C++ port's sequential sums and numpy's pairwise ones left
    the recursion at different orders in 29 of the 90 repair fits of the click battery - the
    port stopped at order 27 with |mu| = 2.9, this file went on to 192 by luck.
    """
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    if n <= order + 1:
        return np.zeros(order)
    f = x.copy()
    b = x.copy()
    a = np.zeros(order + 1)
    a[0] = 1.0
    for m in range(order):
        fm, bm = f[m + 1:n], b[0:n - m - 1]
        d = float(np.dot(fm, fm)) + float(np.dot(bm, bm))
        if d <= 1.0e-300:
            break
        mu = 2.0 * float(np.dot(fm, bm)) / d
        if not (abs(mu) < 0.999):
            break        # |mu| >= 1 is what makes the model non-minimum-phase in float
        a[: m + 2] = a[: m + 2] - mu * a[m + 1::-1]
        ff = f[m + 1:n].copy()
        bb = b[0:n - m - 1].copy()
        f[m + 1:n] = ff - mu * bb
        b[0:n - m - 1] = bb - mu * ff
    return -a[1:]


def ar_error(x, pred):
    """e[n] = x[n] - sum_k pred[k] x[n-1-k] (the C++ does the same dot product per sample)."""
    e = x.astype(np.float64).copy()
    for k in range(pred.size):
        if pred[k] != 0.0:
            e[k + 1:] -= pred[k] * x[: x.size - k - 1]
    return e


def robust_sigma(e):
    """1.4826 x median(|e|): the excitation's scale, robust by construction.

    This is the estimator the AR click detector needs (Godsill and Rayner). A leaky
    integrator over e^2 fails both ways and both ways were measured: 100 clicks in 6 s
    inflate it until they mask each other (32 of 100 caught), and clamping its update makes
    it so insensitive to programme that vocal onsets and snare hits cross the threshold (36
    false repairs). A median over the analysed window cannot be moved by a handful of
    outlying samples, and it rises with the programme, which is what a drum hit needs. In
    C++ it is one nth_element over a fixed scratch buffer - no allocation.
    """
    m = float(np.median(np.abs(e))) if e.size else 0.0
    return 1.4826 * m


class RunScanner:
    """Finds runs of threshold crossings **across segment boundaries**.

    A run truncated at the hop boundary looks short, and a short run is exactly what the
    detector takes for a click: measured, that turned 4 to 15 snare attacks per render into
    "repairs". The scanner therefore carries an open run from one segment into the next and
    only decides when the run actually ends (merge samples below threshold), which is what
    makes "a click is short, music is not" a real test.

    Positions are td indices and are shifted by -hop at each segment, so an open run whose
    start has fallen out of the buffer is marked unrepairable rather than guessed at.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.active = False
        self.start = 0
        self.length = 0
        self.gap = 0
        self.lost = False          # the run started before the buffer: cannot be repaired

    def shift(self, hop):
        if self.active:
            self.start -= hop
            if self.start < 0:
                self.lost = True

    def scan(self, hit, base, merge, on_run):
        """hit: bool array over the segment; base: td index of hit[0]. Calls on_run(start,
        length, lost) for every run that closes inside this segment."""
        for i in range(hit.size):
            if hit[i]:
                if not self.active:
                    self.active = True
                    self.start = base + i
                    self.length = 1
                    self.gap = 0
                    self.lost = False
                else:
                    self.length += self.gap + 1
                    self.gap = 0
            elif self.active:
                self.gap += 1
                if self.gap > merge:
                    on_run(self.start, self.length, self.lost)
                    self.reset()


class ClickRepair:
    """Detect by prediction error, repair by two-sided AR extrapolation with a crossfade.

    G1 departure: the sketch's exact least-squares AR interpolation is a dense solve the size
    of the gap and cannot run in processBlock (rules 1 and 20). Forward extrapolation from the
    left context, backward from the right, crossfaded, is O(span x order) and is still
    interpolation from both sides.

    Detection and repair use **different model orders**, which is the single biggest lever
    measured here. Detection wants a low order: the residual of a low-order model is large and
    click-like samples stand out (order 32 -> 14 false detections on the clean vocal, order 256
    -> 442, because an over-fitted model shrinks sigma along with the error). Repair wants a
    high order: extrapolating across 3 ms of a 180 Hz voice needs more history than 32 samples,
    and the median per-click residual goes from -31.5 dBFS at order 32 to -43.5 at order 256.
    The repair model is fitted lazily, at most once per hop, so a hop with no click costs
    nothing and a hop full of crackle costs one Burg.
    """

    def prepare(self, fs):
        self.fs = float(fs)
        self.burg_block = max(CLICK_AR_ORDER * 2, int(round(CLICK_BURG_BLOCK_S * fs)))
        self.repair_order = CLICK_REPAIR_AR_ORDER
        self.repair_block = max(self.repair_order * 4,
                                int(round(CLICK_REPAIR_BURG_BLOCK_S * fs)))
        self.history = max(self.burg_block, self.repair_block)
        self.context = max(CLICK_AR_ORDER, int(round(CLICK_CONTEXT_S * fs)))
        self.step_long = max(self.context, int(round(CLICK_STEP_LONG_S * fs)))
        self.xfade = max(1, int(round(CLICK_XFADE_S * fs)))
        self.merge = max(1, int(round(CLICK_MERGE_S * fs)))
        self.extend_max = max(1, int(round(CLICK_EXTEND_MAX_S * fs)))
        self.extend_gap = max(1, int(round(CLICK_EXTEND_GAP_S * fs)))
        self.lookahead = max(1, int(round(CLICK_LOOKAHEAD_S * fs)))
        self.scan_main = RunScanner()
        self.scan_crackle = RunScanner()
        self.scan_missed = RunScanner()
        self.reset()

    def reset(self):
        self.caught = 0
        self.missed = 0
        self.longest_samples = 0
        self.scan_main.reset()
        self.scan_crackle.reset()
        self.scan_missed.reset()
        # measurement instrumentation only (the port keeps the three counters as atomics and
        # no list): absolute (input sample, length) of every repair, for measure.py's
        # "every injected click was caught" assertion.
        self.log = []
        self.abs_base = 0

    @staticmethod
    def sigma_of(threshold_pct):
        t = min(max(float(threshold_pct), 0.0), 100.0) / 100.0
        return CLICK_SIGMA_AT_0 + t * (CLICK_SIGMA_AT_100 - CLICK_SIGMA_AT_0)

    def _is_level_step(self, mono, start, length):
        """True when the span is an edge in the music rather than a click: the context RMS
        on the two sides differs by more than CLICK_MAX_STEP_DB at the AR context's scale
        *and* at CLICK_STEP_LONG_S."""
        return (self._step_at(mono, start, length, self.context)
                and self._step_at(mono, start, length, self.step_long))

    @staticmethod
    def _step_at(mono, start, length, c):
        if start < c or start + length + c > mono.size:
            return True
        left = mono[start - c:start]
        right = mono[start + length:start + length + c]
        lr = float(np.sqrt(np.mean(left * left)))
        rr = float(np.sqrt(np.mean(right * right)))
        floor = undb(CLICK_ABS_FLOOR_DBFS)
        return abs(db(max(rr, floor)) - db(max(lr, floor))) > CLICK_MAX_STEP_DB

    def _extrapolate(self, buf, start, length, pred, w):
        """Forward from the left context, backward from the right, crossfaded by w. None when
        the result is not finite or exceeds CLICK_RUNAWAY_FACTOR x the local peak."""
        order = pred.size
        left = buf[start - order:start]
        right = buf[start + length:start + length + order]
        limit = CLICK_RUNAWAY_FACTOR * max(float(np.abs(left).max()),
                                           float(np.abs(right).max()), 1.0e-12)
        fwd = np.empty(length)
        hist = left[::-1].copy()                                      # hist[k] = buf[start-1-k]
        for i in range(length):
            v = float(np.dot(pred, hist))
            fwd[i] = v
            hist[1:] = hist[:-1]
            hist[0] = v
        bwd = np.empty(length)
        hist = right.copy()                                           # hist[k] = buf[end+k]
        for i in range(length):
            v = float(np.dot(pred, hist))
            bwd[length - 1 - i] = v
            hist[1:] = hist[:-1]
            hist[0] = v
        rep = w * fwd + (1.0 - w) * bwd
        if not np.isfinite(rep).all() or float(np.abs(rep).max()) > limit:
            return None
        return rep

    def _repair(self, buf, span_start, span_len, pred, fallback=None):
        """Replaces the span, plus `xfade` samples each side so the crossfade never sits on
        the click itself. (It did: for a 0.5 ms click, 16 of its 24 samples were inside the
        two seams and the worst repair residual measured -10.8 dBFS instead of -30.)

        A runaway extrapolation falls back to `fallback` (the low-order detection model)
        before the cosine bridge. The full AR(192) ran away at the note change of the test
        vocal (a 1-sample false detection at 0.75 s), and the bridge it fell to left -21.9 dBFS
        where the other false repairs leave -83 to -96."""
        order = pred.size
        xf = self.xfade
        start = span_start - xf
        length = span_len + 2 * xf
        if start < order or start + length + order > buf.size:
            return
        t = (np.arange(length) + 0.5) / length
        w = 0.5 * (1.0 + np.cos(math.pi * t))                         # raised cosine, 1 -> 0
        rep = self._extrapolate(buf, start, length, pred, w)
        if rep is None and fallback is not None:
            rep = self._extrapolate(buf, start, length, fallback, w)
        if rep is None:
            # the safety net: a cosine bridge between the two context ends, always bounded
            rep = buf[start - 1] * w + buf[start + length] * (1.0 - w)
        r = 0.5 * (1.0 - np.cos(math.pi * (np.arange(xf) + 0.5) / xf))
        rep[:xf] = buf[start:start + xf] * (1.0 - r) + rep[:xf] * r
        rep[length - xf:] = (buf[start + length - xf:start + length] * r
                             + rep[length - xf:] * (1.0 - r))
        buf[start:start + length] = rep

    def process_segment(self, td, seg_start, seg_len, p):
        """Repairs td[seg_start : seg_start+seg_len] (2 channels) in place.

        td must hold `history` samples before seg_start and `lookahead` samples after the
        segment; the caller's framing guarantees both.
        """
        for sc in (self.scan_main, self.scan_crackle, self.scan_missed):
            sc.shift(seg_len)
        mono = 0.5 * (td[:, 0] + td[:, 1])
        order = CLICK_CRACKLE_AR_ORDER if p.clickMode == MODE_CRACKLE else CLICK_AR_ORDER
        span_s = (CLICK_CRACKLE_LENGTH_S if p.clickMode == MODE_CRACKLE
                  else p.clickLength / 1000.0)
        max_span = max(1, min(int(round(span_s * self.fs)), self.lookahead - self.context))
        sigma = self.sigma_of(p.clickThreshold)
        reject_above = max_span + int(round(CLICK_RUN_SLACK_ORDER * order))

        fit_from = seg_start - self.burg_block
        # The detection model is fitted on history + segment + lookahead, not on clean history
        # alone. A new sound then gets modelled instead of flagged: measured on a clean vocal,
        # 9 false repairs and a -16.3 dBFS residual with a history-only fit against 3 and
        # -42.3 dBFS with this one (an onset and a sibilant burst are "surprising" to a model
        # that has not seen them). A 150-sample click inside a 1570-sample window barely moves
        # Burg, so the detector still sees it.
        pred = burg(mono[fit_from:seg_start + seg_len + self.lookahead], order)
        e = ar_error(mono[fit_from:seg_start + seg_len + self.lookahead], pred)
        off = self.burg_block                              # seg_start inside `e`
        thr = max(sigma * robust_sigma(e[:off + seg_len]), undb(CLICK_ABS_FLOOR_DBFS))
        hit = np.abs(e[off:off + seg_len]) > thr

        repair_pred = [None]                               # fitted lazily, at most once a hop

        thr_ext = max(CLICK_EXTEND_SIGMA * robust_sigma(e[:off + seg_len]),
                      undb(CLICK_ABS_FLOOR_DBFS))
        lo_lim = fit_from + order                            # e's first `order` have no history
        # the repair needs its own context right of the span, or _repair skips the click
        hi_lim = seg_start + seg_len + self.lookahead - self.repair_order - self.xfade - 1

        def do_repair(start, length, lost):
            if lost or length > reject_above:
                return
            length = int(min(length, max_span))
            # hysteresis: grow the run outwards to the furthest sample above thr_ext, crossing
            # dips of up to extend_gap samples
            new_start, gap = start, 0
            for k in range(1, self.extend_max + 1):
                i = start - k
                if i <= lo_lim or gap > self.extend_gap:
                    break
                if abs(e[i - fit_from]) > thr_ext:
                    new_start, gap = i, 0
                else:
                    gap += 1
            end, new_end, gap = start + length, start + length, 0
            for k in range(self.extend_max):
                i = end + k
                if i >= hi_lim or gap > self.extend_gap:
                    break
                if abs(e[i - fit_from]) > thr_ext:
                    new_end, gap = i + 1, 0
                else:
                    gap += 1
            start, length = new_start, new_end - new_start
            if self._is_level_step(mono, start, length):
                return
            if repair_pred[0] is None:
                src = mono[seg_start - self.repair_block:seg_start]
                rp = burg(src, self.repair_order)
                repair_pred[0] = rp if np.any(rp) else pred
            for ch in range(2):
                self._repair(td[:, ch], start, length, repair_pred[0],
                             pred if repair_pred[0] is not pred else None)
            self.caught += 1
            self.longest_samples = max(self.longest_samples, length)
            self.log.append((self.abs_base + start, length))

        self.scan_main.scan(hit, seg_start, self.merge, do_repair)

        # the crackle co-detector, switched in by Crackle % (0 % = the top sigma = nothing)
        if p.clickCrackle > 0.0 and p.clickMode == MODE_CLICKS:
            mono_c = 0.5 * (td[:, 0] + td[:, 1])
            pred_c = burg(mono_c[fit_from:seg_start], CLICK_CRACKLE_AR_ORDER)
            e_c = ar_error(mono_c[fit_from:seg_start + seg_len + self.lookahead], pred_c)
            span_c = max(1, int(round(CLICK_CRACKLE_LENGTH_S * self.fs)))
            thr_c = max(self.sigma_of(p.clickCrackle) * robust_sigma(e_c[:off + seg_len]),
                        undb(CLICK_ABS_FLOOR_DBFS))
            hit_c = np.abs(e_c[off:off + seg_len]) > thr_c
            reject_c = span_c + CLICK_CRACKLE_AR_ORDER

            def do_crackle(start, length, lost):
                if lost or length > reject_c:
                    return
                length = int(min(length, span_c))
                if self._is_level_step(mono_c, start, length):
                    return
                for ch in range(2):
                    self._repair(td[:, ch], start, length, pred_c)
                self.caught += 1
                self.log.append((self.abs_base + start, length))

            self.scan_crackle.scan(hit_c, seg_start, self.merge, do_crackle)

        # the honest counter: a second pass over the repaired signal, one sigma lower - what
        # the user would still hear. Same AR model, no second Burg (the C++ does the same).
        mono2 = 0.5 * (td[:, 0] + td[:, 1])
        e2 = ar_error(mono2[fit_from:seg_start + seg_len + self.lookahead], pred)
        sigma2 = max(1.0, sigma - CLICK_MISSED_SIGMA_MARGIN)
        thr2 = max(sigma2 * robust_sigma(e2[:off + seg_len]), undb(CLICK_ABS_FLOOR_DBFS))
        hit2 = np.abs(e2[off:off + seg_len]) > thr2
        counter = [0]

        def do_missed(start, length, lost):
            if (not lost and length <= reject_above
                    and not self._is_level_step(mono2, start, length)):
                counter[0] += 1

        self.scan_missed.scan(hit2, seg_start, self.merge, do_missed)
        self.missed += counter[0]



# --------------------------------------------------------------------------- Noise
class NoiseWiener:
    """Decision-directed Wiener gain, stereo-linked; Adaptive = minimum statistics."""

    def prepare(self, fs, frame, hop, win_energy):
        self.fs, self.frame, self.hop = float(fs), frame, hop
        self.bins = frame // 2 + 1
        self.win_energy = float(win_energy)
        self.sub_frames = max(1, int(round((NOISE_MINSTAT_WINDOW_S / NOISE_MINSTAT_SUBWINDOWS)
                                           / (hop / fs))))
        self.smooth_a = np.float32(math.exp(-(hop / fs) / NOISE_MINSTAT_SMOOTH_S))
        self.bias = np.float32(undb(NOISE_MINSTAT_BIAS_DB) ** 2)
        self.warm_frames = max(1, int(math.ceil(NOISE_MINSTAT_SMOOTH_S / (hop / fs))))
        self.profile = None
        self.reset()

    def reset(self):
        big = np.float32(1.0e30)
        self.sub_min = np.full(self.bins, big, dtype=np.float32)
        self.ring = np.full((NOISE_MINSTAT_SUBWINDOWS, self.bins), big, dtype=np.float32)
        self.ring_at = 0
        self.sub_count = 0
        self.lam = np.full(self.bins, np.float32(1.0e-20), dtype=np.float32)
        self.pow_smooth = np.zeros(self.bins, dtype=np.float32)
        self.smooth_primed = False
        self.warm_count = 0
        self.xi = np.zeros(self.bins, dtype=np.float32)
        self.gamma_prev = np.zeros(self.bins, dtype=np.float32)
        self.gain = np.ones(self.bins, dtype=np.float32)
        self.learn_left = 0
        self.learn_acc = np.zeros(self.bins, dtype=np.float64)
        self.learn_frames = 0
        self.learn_peak = 0.0

    def start_learn(self):
        self.learn_left = max(1, int(round(NOISE_LEARN_S * self.fs / self.hop)))
        self.learn_acc[:] = 0.0
        self.learn_frames = 0
        self.learn_peak = 0.0

    def implied_rms(self, lam):
        """The broadband RMS a one-sided power estimate implies (Parseval, windowed)."""
        s = float(lam[0]) + float(lam[-1]) + 2.0 * float(np.sum(lam[1:-1]))
        return math.sqrt(max(s / (self.frame * self.win_energy), 1.0e-300))

    def _minstat(self, power):
        # The engine's first `frame` samples of output are the priming zeros, and a zero frame
        # fed to a minimum tracker pins the estimate at zero for a whole window: measured, the
        # Adaptive profile read -300 dBFS for the first 1.5 s and reduced nothing, then -63.9
        # dBFS instead of -50 while the zeros were still in the ring (8.1 dB of reduction where
        # -12 was asked). The tracker therefore starts at the first frame that has any energy.
        # It does not prime the ring from that one frame: a single periodogram is exponentially
        # distributed per bin, so a ring primed from it sat far below the floor until it rolled
        # over - measured, 2.3 dB of reduction over the first 1.5 s where 11.8 was reached after
        # it. For NOISE_MINSTAT_SMOOTH_S the estimate is the running mean of the frames instead
        # (unbiased, its variance falling as 1/k), and the ring is primed from that mean, divided
        # by the bias so the estimate does not jump at the hand-over.
        if not self.smooth_primed:
            if self.warm_count == 0 and not np.any(power > 0.0):
                return
            self.warm_count += 1
            self.pow_smooth = (self.pow_smooth + (power - self.pow_smooth)
                               / np.float32(self.warm_count)).astype(np.float32)
            self.lam = np.minimum(self.pow_smooth, np.float32(1.0e29)).astype(np.float32)
            if self.warm_count < self.warm_frames:
                return
            self.ring[:] = self.pow_smooth / self.bias
            self.sub_min = (self.pow_smooth / self.bias).astype(np.float32)
            self.sub_count = 0
            self.smooth_primed = True
            return
        else:
            self.pow_smooth = (self.smooth_a * self.pow_smooth
                               + (np.float32(1.0) - self.smooth_a) * power).astype(np.float32)
        self.sub_min = np.minimum(self.sub_min, self.pow_smooth)
        self.sub_count += 1
        if self.sub_count >= self.sub_frames:
            self.ring[self.ring_at] = self.sub_min
            self.ring_at = (self.ring_at + 1) % NOISE_MINSTAT_SUBWINDOWS
            self.sub_min = np.full(self.bins, np.float32(1.0e30), dtype=np.float32)
            self.sub_count = 0
        m = np.minimum(np.min(self.ring, axis=0), self.sub_min)
        self.lam = np.minimum(m * self.bias, np.float32(1.0e29)).astype(np.float32)

    def gain_for(self, power, p):
        """power: the mean of the two channels' bin power, float32. Returns the gain."""
        if self.learn_left > 0:
            self.learn_acc += power
            self.learn_frames += 1
            self.learn_peak = max(self.learn_peak, self.implied_rms(power))
            self.learn_left -= 1
            if self.learn_left == 0 and self.learn_frames > 0:
                if db(self.learn_peak) <= NOISE_LEARN_MAX_DBFS:
                    self.profile = (self.learn_acc / self.learn_frames).astype(np.float32)
        self._minstat(power)                       # always tracking, so Adaptive is instant
        if not p.noiseOn:
            self.gain = np.ones(self.bins, dtype=np.float32)
            self.gamma_prev = np.zeros(self.bins, dtype=np.float32)
            return self.gain
        if p.noiseMode == PROFILE_LEARNED and self.profile is not None:
            lam = self.profile.copy()
        else:
            lam = self.lam.copy()
        # Floor is the broadband level the user asserts. The estimate supplies the shape; when
        # it finds less noise than Floor the user wins, scaled, so the shape is kept.
        est = self.implied_rms(lam)
        want = undb(p.noiseFloor)
        if est < want:
            # clamped so a silent start (est -> 0) cannot overflow the float32 estimate
            scale = min((want / max(est, 1.0e-12)) ** 2, 1.0e12)
            lam = (lam * np.float32(scale)).astype(np.float32)
        g_min = np.float32(undb(p.noiseReduction))
        tau = NOISE_DD_TAU_AT_0_S * (NOISE_DD_TAU_AT_100_S / NOISE_DD_TAU_AT_0_S) ** (
            p.noiseSmooth / 100.0)
        alpha = np.float32(math.exp(-(self.hop / self.fs) / tau))
        gamma = (power / np.maximum(lam, np.float32(1.0e-30))).astype(np.float32)
        # the previous frame's clean estimate over the noise, G(l-1)^2 gamma(l-1): the first
        # version used the *current* gamma here, which makes the a-priori SNR partly
        # a-posteriori and lets every high periodogram bin through
        xi = (alpha * (self.gain * self.gain * self.gamma_prev)
              + (np.float32(1.0) - alpha) * np.maximum(gamma - np.float32(1.0),
                                                       np.float32(0.0))).astype(np.float32)
        self.gamma_prev = gamma
        self.xi = xi
        g = (xi / (xi + np.float32(1.0))).astype(np.float32)
        self.gain = np.maximum(g, g_min).astype(np.float32)
        return self.gain


# --------------------------------------------------------------------------- Reverb
class ReverbSubtract:
    """Late-tail power subtraction per bin with a spectral-flux attack hold, stereo-linked."""

    def prepare(self, fs, frame, hop):
        self.fs, self.frame, self.hop = float(fs), frame, hop
        self.bins = frame // 2 + 1
        self.delay_frames = max(1, int(round(REVERB_PREDELAY_S / (hop / fs))))
        self.smooth = math.exp(-1.0 / REVERB_SMOOTH_FRAMES)
        self.flux_a = math.exp(-(hop / fs) / REVERB_FLUX_TAU_S)
        self.reset()

    def reset(self):
        self.hist = np.zeros((self.delay_frames + 1, self.bins), dtype=np.float32)
        self.hist_at = 0
        self.gain = np.ones(self.bins, dtype=np.float32)
        self.prev_mag = np.zeros(self.bins, dtype=np.float32)
        self.flux_mean = 0.0
        self.hold_frames = 0
        self.onsets = 0

    def gain_for(self, power, p):
        mag = np.sqrt(power).astype(np.float32)
        flux = float(np.sum(np.maximum(mag - self.prev_mag, np.float32(0.0))))
        self.prev_mag = mag
        onset = self.flux_mean > 0.0 and flux > REVERB_FLUX_FACTOR * self.flux_mean
        self.flux_mean = self.flux_a * self.flux_mean + (1.0 - self.flux_a) * flux
        if onset:
            self.onsets += 1
        if not p.reverbOn:
            self.hist[self.hist_at] = power
            self.hist_at = (self.hist_at + 1) % self.hist.shape[0]
            self.gain = np.ones(self.bins, dtype=np.float32)
            return self.gain
        if onset:
            self.hold_frames = int(round((p.reverbAttacks / 100.0) * REVERB_ATTACK_HOLD_S
                                         / (self.hop / self.fs)))
        past = self.hist[(self.hist_at - self.delay_frames) % self.hist.shape[0]]
        amount = p.reverbAmount / 100.0
        # power falls 60 dB in RT60, so 10^(-6 t / T) over the prediction gap
        decay = 10.0 ** (-6.0 * (self.delay_frames * self.hop / self.fs)
                         / max(p.reverbTail, 1.0e-3))
        floor_pow = np.float32(undb(REVERB_FLOOR_DB_AT_FULL * amount) ** 2)
        late = (np.float32(decay) * past).astype(np.float32)
        ratio = (late / np.maximum(power, np.float32(1.0e-30))).astype(np.float32)
        target = np.sqrt(np.maximum(np.float32(1.0) - np.float32(amount) * ratio,
                                    floor_pow)).astype(np.float32)
        if self.hold_frames > 0:
            target = np.ones(self.bins, dtype=np.float32)
            self.hold_frames -= 1
        self.gain = (np.float32(self.smooth) * self.gain
                     + np.float32(1.0 - self.smooth) * target).astype(np.float32)
        self.hist[self.hist_at] = power
        self.hist_at = (self.hist_at + 1) % self.hist.shape[0]
        return self.gain


# --------------------------------------------------------------------------- the plugin
class CleanUp:
    """The whole effect, with the lifecycle the AudioProcessor port has."""

    def __init__(self):
        self.hum = HumComb()
        self.click = ClickRepair()
        self.noise = NoiseWiener()
        self.reverb = ReverbSubtract()
        self.fs = 48000.0

    # ---- lifecycle
    def prepare(self, fs, max_block=512):
        self.fs = float(fs)
        self.frame = next_pow2(int(round(FRAME_SECONDS * fs)))
        self.hop = self.frame // OVERLAP
        self.window = np.hanning(self.frame + 1)[:-1].astype(np.float32)   # periodic Hann
        self.win_energy = float(np.sum(self.window.astype(np.float64) ** 2))
        self.wola_scale = np.float32(1.0 / WOLA_HANN_SUM)
        self.hum.prepare(fs)
        self.click.prepare(fs)
        self.noise.prepare(fs, self.frame, self.hop, self.win_energy)
        self.reverb.prepare(fs, self.frame, self.hop)
        self.lookahead = self.click.lookahead
        self.latency = self.frame + self.lookahead
        self.switch_len = max(1, int(round(SWITCH_XFADE_S * fs)))
        self.trim_steps = max(1, int(round(TRIM_RAMP_S * fs)))
        self.count_frames = max(1, int(round(CLICK_COUNT_WINDOW_S * fs / self.hop)))
        self.band_edges = self._band_edges()
        self.reset()

    def _band_edges(self):
        n = int(round(BANDS_PER_OCTAVE * math.log2(BAND_HIGH_HZ / BAND_LOW_HZ)))
        edges = BAND_LOW_HZ * 2.0 ** (np.arange(n + 1) / BANDS_PER_OCTAVE)
        k = np.round(edges * self.frame / self.fs).astype(int)
        return np.clip(k, 0, self.frame // 2)

    def reset(self):
        self.hum.reset()
        self.click.reset()
        self.noise.reset()
        self.reverb.reset()
        # the time-domain buffer the click stage repairs and the analysis frame is taken from:
        # [ burg history | frame | lookahead ], newest sample last
        self.td_len = self.click.history + self.frame + self.lookahead
        self.td = np.zeros((self.td_len, 2))
        self.acc = np.zeros((self.frame, 2), dtype=np.float32)
        self.in_buf = np.zeros((0, 2))
        self.out_buf = np.zeros((self.hop, 2))      # primed: a block is not a hop multiple
        self.dry = np.zeros((self.frame + self.lookahead + 2 * self.hop, 2))
        self.engine_on = False
        self.prime_left = 0
        self.fade = 0.0
        self.alignment = 0
        nb = self.band_edges.size - 1
        self.input_bands = np.zeros(nb)
        self.removed_bands = np.zeros(nb)
        self.frames_done = 0
        self.fed = 0
        # the switch crossfades and Trim snap to the parameters on the first block
        self.snap = True
        self.hum_mix = 0.0
        self.listen_mix = np.array([1.0, 0.0, 0.0])
        self.bypass_mix = 0.0
        self.trim_gain = self.trim_target = 1.0
        self.trim_left = 0
        self.trim_factor = 1.0

    def _start_engine(self):
        self.engine_on = True
        self.prime_left = self.latency
        self.fade = 0.0
        self.td[:] = 0.0
        self.acc[:] = 0.0
        self.in_buf = np.zeros((0, 2))
        self.out_buf = np.zeros((self.hop, 2))
        self.noise.reset()
        self.reverb.reset()
        self.click.reset()

    # ---- one hop of the spectral engine
    def _hop_step(self, chunk, p):
        hop, frame = self.hop, self.frame
        bb = self.click.history
        self.td[:-hop] = self.td[hop:]
        self.td[-hop:] = chunk
        self.fed += hop
        # the committed segment ends `lookahead` samples before the newest sample
        seg_start = bb + frame - hop
        if p.clickOn:
            self.click.abs_base = self.fed - self.td_len
            self.click.process_segment(self.td, seg_start, hop, p)
        src = self.td[bb:bb + frame]
        spec = np.fft.rfft((src.astype(np.float32) * self.window[:, None]).T,
                           axis=1).astype(np.complex64)
        power = (0.5 * ((spec.real * spec.real + spec.imag * spec.imag)
                        .sum(axis=0))).astype(np.float32)
        before = power.astype(np.float64)
        g = self.noise.gain_for(power, p)
        power = (power * g * g).astype(np.float32)
        g = (g * self.reverb.gain_for(power, p)).astype(np.float32)
        after = (before * (g.astype(np.float64) ** 2))
        self._publish_bands(before, np.maximum(before - after, 0.0))
        out = (spec * g[None, :]).astype(np.complex64)
        y = np.fft.irfft(out, n=frame, axis=1).astype(np.float32).T
        self.acc += y * self.window[:, None] * self.wola_scale
        emit = self.acc[:hop].astype(np.float64).copy()
        self.acc[:-hop] = self.acc[hop:]
        self.acc[-hop:] = 0.0
        self.frames_done += 1
        return emit

    def _publish_bands(self, in_power, removed_power):
        k = self.band_edges
        for i in range(k.size - 1):
            a, b = int(k[i]), max(int(k[i]) + 1, int(k[i + 1]))
            self.input_bands[i] = in_power[a:b].sum()
            self.removed_bands[i] = removed_power[a:b].sum()

    # ---- processBlock
    def process_block(self, x, p):
        """x: (n, 2) or (n,) -> (n, 2), the same length, the plugin's real output."""
        x = np.asarray(x, dtype=np.float64)
        if x.ndim == 1:
            x = np.stack([x, x], axis=1)
        n = x.shape[0]
        if n == 0:
            return x.copy()

        # The switches - Hum on/off, Listen, Bypass - are crossfaded over SWITCH_XFADE_S (rules 2
        # and 7). Hard, each read -2.6 dB on max_click_db against -43 dB steady, on a 50 Hz sine
        # on the first notch. Every crossfade state snaps to its parameter on the first block
        # after reset, so a render with static parameters is exactly what it was without them.
        step = 1.0 / self.switch_len
        listen_target = np.array([float(p.listen == i) for i in range(3)])
        if self.snap:
            self.hum_mix = 1.0 if p.humOn else 0.0
            self.listen_mix = listen_target.copy()
            self.bypass_mix = 1.0 if p.bypass else 0.0
            self.trim_gain = self.trim_target = undb(p.trim)
            self.trim_left = 0
            self.snap = False

        # Bypass does not move the reported latency (the host's compensation must not churn).
        # Once its crossfade has run, it stops the engine and hands out the aligned dry signal:
        # a wire, not trimmed.
        want = p.spectral
        bypassed = p.bypass and self.bypass_mix >= 1.0
        if bypassed:
            self.engine_on = False
            self.fade = 0.0
            running = False
            self.alignment = self.latency if want else 0
        else:
            if want and not self.engine_on:
                self._start_engine()
            elif not want and self.engine_on and self.fade <= 0.0:
                self.engine_on = False
            running = self.engine_on or self.fade > 0.0
            self.alignment = self.latency if running else 0

        # the dry delay line of the plugin input: Removed, Input, and bypass read from it
        self.dry = np.vstack([self.dry, x])
        end = self.dry.shape[0] - self.alignment
        dry_aligned = self.dry[end - n:end].copy()
        keep = self.frame + self.lookahead + 2 * self.hop + n
        if self.dry.shape[0] > keep:
            self.dry = self.dry[-keep:]
        wire = dry_aligned if self.alignment > 0 else x.copy()

        if bypassed:
            return wire

        # Hum, crossfaded on and off; the comb runs while its share is above zero
        h_target = 1.0 if p.humOn else 0.0
        if self.hum_mix > 0.0 or h_target > 0.0:
            proc = self.hum.process(x.copy(), p)
            hm = self._ramp(self.hum_mix, h_target, step, n)
            self.hum_mix = float(hm[-1])
            hum_out = x * (1.0 - hm)[:, None] + proc * hm[:, None]
        else:
            hum_out = x.copy()

        if running:
            self.in_buf = np.vstack([self.in_buf, hum_out])
            produced = []
            while self.in_buf.shape[0] >= self.hop:
                produced.append(self._hop_step(self.in_buf[:self.hop], p))
                self.in_buf = self.in_buf[self.hop:]
            if produced:
                self.out_buf = np.vstack([self.out_buf] + produced)
            engine = self.out_buf[:n].copy()
            self.out_buf = self.out_buf[n:]
            # the switch crossfade (rule 2). While the engine primes, the hum-only signal is
            # heard; that is the documented flam of a module switch.
            if self.prime_left > 0:
                self.prime_left = max(0, self.prime_left - n)
            target = 1.0 if (self.engine_on and self.prime_left == 0) else 0.0
            step = 1.0 / self.switch_len
            f = np.empty(n)
            v = self.fade
            for i in range(n):
                v = min(v + step, target) if target > v else max(v - step, target)
                f[i] = v
            self.fade = v
            unproc = dry_aligned if self.alignment > 0 else hum_out
            y = unproc * (1.0 - f)[:, None] + engine * f[:, None]
        else:
            y = hum_out

        # Listen, crossfaded: each of Output, Removed and Input has its own share
        g = np.empty((n, 3))
        for i in range(3):
            g[:, i] = self._ramp(float(self.listen_mix[i]), float(listen_target[i]), step, n)
        self.listen_mix = g[-1].copy()
        y = (g[:, 0:1] * y + g[:, 1:2] * (dry_aligned - y) + g[:, 2:3] * dry_aligned)

        # Trim: a multiplicative ramp over TRIM_RAMP_S, the same arithmetic as the C++
        y = y * self._trim_gains(undb(p.trim), n)[:, None]

        # Bypass, crossfaded into the wire
        b_target = 1.0 if p.bypass else 0.0
        if self.bypass_mix > 0.0 or b_target > 0.0:
            bm = self._ramp(self.bypass_mix, b_target, step, n)
            self.bypass_mix = float(bm[-1])
            y = y * (1.0 - bm)[:, None] + wire * bm[:, None]
        return y

    @staticmethod
    def _ramp(v, target, step, n):
        """v moving linearly towards target by step per sample: the n values after each step."""
        out = np.empty(n)
        for i in range(n):
            v = min(v + step, target) if target > v else max(v - step, target)
            out[i] = v
        return out

    def _trim_gains(self, target, n):
        if target != self.trim_target:
            self.trim_target = target
            self.trim_left = self.trim_steps
            self.trim_factor = math.exp((math.log(target) - math.log(self.trim_gain)) / self.trim_steps)
        out = np.empty(n)
        for i in range(n):
            if self.trim_left > 0:
                self.trim_gain *= self.trim_factor
                self.trim_left -= 1
                if self.trim_left == 0:
                    self.trim_gain = self.trim_target
            out[i] = self.trim_gain
        return out

    # ---- editor actions (brief: Find, Learn, Estimate write parameters as one host edit)
    def find_hum(self, x):
        """The strongest peak in 45-65 Hz, or half of the strongest in 100-130 Hz (sketch 4.2)."""
        x = np.asarray(x, dtype=np.float64)
        mono = x.mean(axis=1) if x.ndim > 1 else x
        n = min(mono.size, int(2.0 * self.fs))
        if n < 2048:
            return None
        w = np.hanning(n)
        mag = np.abs(np.fft.rfft(mono[:n] * w))
        f = np.fft.rfftfreq(n, 1.0 / self.fs)
        best = None
        for lo, hi, div in ((45.0, 65.0, 1.0), (100.0, 130.0, 2.0)):
            m = (f >= lo) & (f <= hi)
            if not np.any(m):
                continue
            i = int(np.argmax(mag[m]))
            hz, level = float(f[m][i]) / div, float(mag[m][i])
            if best is None or level > best[1]:
                best = (hz, level)
        return None if best is None else float(min(max(best[0], 40.0), 70.0))

    def estimate_tail(self, x):
        """RT60 from the decay after the last transient, over the last 4 s (sketch 4.5)."""
        x = np.asarray(x, dtype=np.float64)
        mono = x.mean(axis=1) if x.ndim > 1 else x
        n = min(mono.size, int(4.0 * self.fs))
        seg = mono[-n:]
        win = max(1, int(round(0.01 * self.fs)))
        env = np.sqrt(np.convolve(seg * seg, np.ones(win) / win, mode="same"))
        e = db(env, -120.0)
        peak = int(np.argmax(e))
        tail = e[peak:]
        if tail.size < 4 * win:
            return None
        ref = tail[0]
        below5 = np.flatnonzero(tail <= ref - 5.0)
        below25 = np.flatnonzero(tail <= ref - 25.0)
        if below5.size == 0 or below25.size == 0:
            return None
        lo_i, hi_i = int(below5[0]), int(below25[0])
        if hi_i <= lo_i + win:
            return None
        t = np.arange(lo_i, hi_i) / self.fs
        slope = float(np.polyfit(t, tail[lo_i:hi_i], 1)[0])
        if slope >= -1.0e-6:
            return None
        return float(min(max(-60.0 / slope, 0.2), 4.0))


# --------------------------------------------------------------------------- render helper
def render(x, p, fs=48000.0, block=512, learn_at=None):
    """Runs the plugin over x in blocks, the way the harness does. Returns (y, plugin)."""
    cu = CleanUp()
    cu.prepare(fs, block)
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    out = np.empty_like(x)
    learn_block = None if learn_at is None else int(round(learn_at * fs / block))
    i = b = 0
    while i < x.shape[0]:
        if learn_block is not None and b == learn_block:
            cu.noise.start_learn()
        n = min(block, x.shape[0] - i)
        out[i:i + n] = cu.process_block(x[i:i + n], p)
        i += n
        b += 1
    return out, cu


# --------------------------------------------------------------------------- self-test
def selftest():
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name + ((" - " + detail) if detail else ""))
        ok = ok and bool(cond)

    rng = np.random.default_rng(1)

    # 1. Burg recovers a known AR(2)
    a1, a2 = 1.6, -0.9
    n = 8000
    e = rng.standard_normal(n)
    y = np.zeros(n)
    for i in range(2, n):
        y[i] = a1 * y[i - 1] + a2 * y[i - 2] + e[i]
    pred = burg(y, 2)
    check("burg recovers AR(2)", abs(pred[0] - a1) < 0.05 and abs(pred[1] - a2) < 0.05,
          "got %.3f %.3f, want %.3f %.3f" % (pred[0], pred[1], a1, a2))

    # 2. the SVF bell is its transfer function, cuts Depth dB, and is a wire far away
    fs, hz, bw, g_db = 48000.0, 1000.0, 100.0, -12.0
    b = SvfBell()
    b.set(fs, hz, bw, g_db)
    imp = np.zeros(8192)
    imp[0] = 1.0
    yb = np.array([b.process(v) for v in imp])
    H = np.fft.rfft(yb)
    f = np.fft.rfftfreq(imp.size, 1.0 / fs)
    at = float(db(abs(H[int(np.argmin(abs(f - hz)))])))
    far = float(db(abs(H[int(np.argmin(abs(f - 100.0)))])))
    check("svf bell cuts Depth dB at the centre", abs(at - g_db) < 0.3, "%.2f dB" % at)
    check("svf bell is a wire far away", abs(far) < 0.2, "%.3f dB at 100 Hz" % far)
    bq, aq = b.coeffs()
    from scipy.signal import lfilter
    yr = lfilter(bq, aq, imp)
    check("svf bell == its documented biquad", float(db(np.abs(yb - yr).max())) < -120.0,
          "%.1f dBFS" % float(db(np.abs(yb - yr).max())))

    # A deep narrow notch has to stay narrow (Width is Hz, whatever Depth is) and still reach
    # Depth at its centre. The centre floor is only measurable with a sine *at* the centre: an
    # FFT bin 0.02 Hz away already reads -32 dB, because a 60 dB-deep 2 Hz notch recovers 3 dB
    # within about +/- 0.001 Hz of its floor (|H| = |A^2 + 2 eps / k|). That is also the honest
    # statement of what Depth buys: it needs the tracker to sit on the hum.
    def thru(hz_in, hz_notch, bw, gain_db, seconds=3.0):
        f = SvfBell()
        f.set(fs, hz_notch, bw, gain_db)
        t = np.arange(int(seconds * fs)) / fs
        sig = np.sin(2.0 * math.pi * hz_in * t)
        out = np.array([f.process(v) for v in sig])
        half = out.size // 2                        # after the ring-in
        return float(db(np.sqrt(np.mean(out[half:] ** 2))
                        / np.sqrt(np.mean(sig[half:] ** 2))))

    at_centre = thru(100.0, 100.0, 2.0, -60.0)
    check("deep notch reaches Depth on a sine at its centre", abs(at_centre + 60.0) < 1.0,
          "%.2f dB" % at_centre)
    off = thru(80.0, 100.0, 2.0, -60.0)
    check("deep notch is a wire 20 Hz away", abs(off) < 0.2, "%.3f dB at 80 Hz" % off)
    bw3 = thru(100.0 + 1.0, 100.0, 2.0, -60.0)      # +/- Width/2 is the -3 dB point
    check("Width is the -3 dB bandwidth", abs(bw3 + 3.0) < 0.6, "%.2f dB at +1 Hz" % bw3)

    # 3. all modules off: the output is the input, bit-exact, latency 0
    x = (rng.standard_normal((48000, 2)) * 0.1)
    y, cu = render(x, Params(), fs=48000.0, block=512)
    check("all off nulls bit-exact", np.array_equal(x, y),
          "peak residual %.1f dBFS" % float(db(np.abs(x - y).max())))
    check("all off reports alignment 0", cu.alignment == 0)

    # 4. the WOLA reconstructs when nothing is modified (E.11: null when unmodified)
    p = Params(noiseOn=True, noiseReduction=0.0, noiseSmooth=0.0)
    y, cu = render(x, p, fs=48000.0, block=512)
    lat = cu.latency
    res = y[lat:] - x[:x.shape[0] - lat]
    check("WOLA passthrough at Reduction 0 dB", float(db(np.abs(res).max())) < -70.0,
          "%.1f dBFS at latency %d" % (float(db(np.abs(res).max())), lat))
    check("latency == frame + lookahead", cu.latency == cu.frame + cu.lookahead,
          "%d == %d + %d" % (cu.latency, cu.frame, cu.lookahead))

    # 5. the reverb module at Amount 0 is also a null
    p = Params(reverbOn=True, reverbAmount=0.0)
    y, cu = render(x, p, fs=48000.0, block=512)
    res = y[cu.latency:] - x[:x.shape[0] - cu.latency]
    check("reverb at Amount 0 passes through", float(db(np.abs(res).max())) < -70.0,
          "%.1f dBFS" % float(db(np.abs(res).max())))

    # 6. bypass is a latency-compensated wire
    p = Params(noiseOn=True, bypass=True)
    y, cu = render(x, p, fs=48000.0, block=512)
    res = y[cu.latency:] - x[:x.shape[0] - cu.latency]
    check("bypass is a delayed wire", float(db(np.abs(res).max())) <= -300.0,
          "%.1f dBFS" % float(db(np.abs(res).max())))

    # 7. two runs from reset are bit-identical (rule 8)
    p = Params(humOn=True, clickOn=True, noiseOn=True, reverbOn=True)
    y1, _ = render(x[:24000], p, fs=48000.0, block=512)
    y2, _ = render(x[:24000], p, fs=48000.0, block=512)
    check("two runs are bit-identical", np.array_equal(y1, y2))

    # 8. block size does not change the output
    y3, _ = render(x[:24000], p, fs=48000.0, block=64)
    check("block size does not change the output",
          float(db(np.abs(y1 - y3).max())) < -200.0,
          "%.1f dBFS between block 512 and 64" % float(db(np.abs(y1 - y3).max())))

    # 9. finite at every supported rate
    bad = None
    for fs2 in (44100, 48000, 88200, 96000, 176400, 192000):
        xs = rng.standard_normal((int(0.3 * fs2), 2)) * 0.1
        ys, _ = render(xs, Params(noiseOn=True, reverbOn=True), fs=float(fs2), block=256)
        if not np.isfinite(ys).all():
            bad = fs2
            break
    check("finite at every supported rate", bad is None, "" if bad is None else "%d Hz" % bad)

    # 10. Listen Removed plus Listen Output equals Listen Input (the identity it promises)
    p0 = Params(humOn=True, noiseOn=True)
    yo, _ = render(x[:24000], p0, fs=48000.0, block=512)
    p0.listen = LISTEN_REMOVED
    yr, _ = render(x[:24000], p0, fs=48000.0, block=512)
    p0.listen = LISTEN_INPUT
    yi, _ = render(x[:24000], p0, fs=48000.0, block=512)
    d = float(db(np.abs(yo + yr - yi).max()))
    check("Output + Removed == Input", d < -120.0, "%.1f dBFS" % d)

    # 11. Noise defects found at G3 (docs/failures.md), on noise alone at -50 dBFS
    wn = rng.standard_normal(int(4.0 * 48000)) * undb(-50.0)
    xn = np.stack([wn, wn], axis=1)

    def reduction(p, a_s, b_s):
        y, cu = render(xn, p, fs=48000.0, block=512)
        y = y[cu.latency:]
        a, b = int(a_s * 48000), int(b_s * 48000)
        return float(db(np.sqrt(np.mean(xn[a:b] ** 2))) - db(np.sqrt(np.mean(y[a:b] ** 2))))

    # the minimum tracker primed from one periodogram sat below the floor for its whole window
    r0 = reduction(Params(noiseOn=True, noiseReduction=-12.0, noiseSmooth=40.0), 0.5, 1.5)
    check("noise reduces from the start (minimum-statistics warm-up)", r0 >= 11.0,
          "%.2f dB over 0.5-1.5 s at Reduction -12 dB" % r0)
    # a decision-directed gain whose a-priori SNR follows the periodogram stops short of its floor
    r1 = reduction(Params(noiseOn=True, noiseReduction=-18.0, noiseSmooth=40.0), 2.0, 4.0)
    check("noise reaches its gain floor (decision-directed gain law)", r1 >= 17.0,
          "%.2f dB at Reduction -18 dB, Smooth 40 %%" % r1)

    # 12. Click defect found at G3 (docs/failures.md): the repair covered only a click's core.
    # A tone in noise at a level where 21 sigma (Threshold 55 %) sits inside a 0.35 burst, so
    # the burst's Hann flanks are under the detection threshold.
    t = np.arange(48000) / 48000.0
    tone = 0.3 * np.sin(2 * math.pi * 220.0 * t) + 0.1 * np.sin(2 * math.pi * 660.0 * t)
    tone = tone + rng.standard_normal(t.size) * undb(-38.0)
    xc = np.stack([tone, tone], axis=1)
    c0, cl = 24000, 86                                     # 1.8 ms
    burst = rng.choice([-1.0, 1.0], size=cl) * 0.35 * np.hanning(cl)
    xc_click = xc.copy()
    xc_click[c0:c0 + cl] += burst[:, None]
    yc, cuc = render(xc_click, Params(clickOn=True), fs=48000.0, block=512)
    yc = yc[cuc.latency:]
    sl = slice(c0 - 16, c0 + cl + 16)
    resid = float(db(np.sqrt(np.mean((yc[sl] - xc[sl]) ** 2))))
    check("click repair covers the whole click (hysteresis)", resid <= -25.0,
          "residual %.1f dBFS over a 1.8 ms burst at 0.35" % resid)

    # 13. Click defect found at G3: the level-step test read pitch-pulse ripple as an edge. In
    # the vocal in a 1.0 s room, 0.75 % of positions read a > 12 dB step at 1.333 ms and none
    # at 5 ms; a click put on each of them (up to eight, 0.6 s apart) must be repaired.
    import material as _mat
    rv = _mat.convolve_room(_mat.vocal(48000.0, 6.0), _mat.reverb_ir(48000.0, rt60=1.0,
                                                                     drr_db=3.0, seed=7))
    mono_rv = rv.mean(axis=1)

    def rms_db(a):
        return float(db(max(float(np.sqrt(np.mean(a * a))), 1.0e-4)))

    def only_short(st, ln):
        d = [abs(rms_db(mono_rv[st + ln:st + ln + c]) - rms_db(mono_rv[st - c:st]))
             for c in (64, 240)]
        return d[0] > 12.0 and d[1] <= 12.0

    cl, spots, st = 57, [], int(0.6 * 48000)
    while st < int(5.8 * 48000) and len(spots) < 8:
        if only_short(st, cl):
            spots.append(st)
            st += int(0.6 * 48000)
        st += 3
    xs = rv.copy()
    for st in spots:
        xs[st:st + cl] += (rng.choice([-1.0, 1.0], size=cl) * 0.35 * np.hanning(cl))[:, None]
    _, cus = render(xs, Params(clickOn=True), fs=48000.0, block=512)
    got = sum(any(d < st + cl and d + dl > st for d, dl in cus.click.log) for st in spots)
    check("clicks in a sung note are not taken for edges (level step at two scales)",
          len(spots) >= 6 and got == len(spots), "%d of %d caught" % (got, len(spots)))

    # 14. Burg defect found at G5: the textbook recursion for the denominator lost the order
    # on a sung vowel. Every 40 ms window of the vocal must be fitted to the full repair order.
    vv = _mat.vocal(48000.0, 6.0).mean(axis=1)
    short = 0
    windows = 0
    for st in range(int(0.5 * 48000), int(5.5 * 48000), 960):
        w = vv[st:st + 1920]
        if np.abs(w).max() < 1.0e-3:
            continue
        windows += 1
        r = burg(w, CLICK_REPAIR_AR_ORDER)
        fitted = int(np.max(np.nonzero(r)[0]) + 1) if np.any(r) else 0
        short += fitted < CLICK_REPAIR_AR_ORDER
    check("burg keeps the full repair order on a sung vowel (direct denominator)", short == 0,
          "%d of %d windows fitted short" % (short, windows))

    # 15. Click defect found at G5: a runaway AR(192) repair fell straight to the cosine bridge.
    # The test vocal's first note change (0.75 s) draws a 1-sample false detection whose
    # full-order extrapolation runs away; the detection model must take over before the bridge.
    v12 = _mat.vocal(48000.0, 6.0)[: int(1.2 * 48000)]
    yv, cuv = render(v12, Params(clickOn=True, clickLength=3.5), fs=48000.0, block=512)
    yv = yv[cuv.latency:]
    rv12 = float(db(np.abs(yv - v12[:yv.shape[0]]).max()))
    check("a runaway repair falls back to the detection model before the bridge", rv12 <= -35.0,
          "%.1f dBFS on the clean vocal's first 1.2 s (%d repair)" % (rv12, cuv.click.caught))

    # 16. Switch defect found at G4: Hum off, Listen and Bypass were hard switches. A 50 Hz sine
    # on the first notch, the switch thrown at 1 s: the largest step stays a sine's, not a jump.
    ts = np.arange(int(2.0 * 48000)) / 48000.0
    sn = 0.25 * np.sin(2.0 * math.pi * 50.0 * ts)
    xs2 = np.stack([sn, sn], axis=1)

    def switched(before, after):
        cu = CleanUp()
        cu.prepare(48000.0, 512)
        out = []
        for i in range(0, xs2.shape[0], 512):
            out.append(cu.process_block(xs2[i:i + 512], before if i < 48000 else after))
        y = np.vstack(out)
        return float(db(np.abs(np.diff(y, axis=0)).max() / np.abs(y).max()))

    base = dict(humOn=True, humDepth=-60.0)
    for name, a, b in (("Hum off", Params(**base), Params(humDepth=-60.0)),
                       ("Listen to Removed", Params(**base), Params(listen=LISTEN_REMOVED, **base)),
                       ("Bypass on", Params(**base), Params(bypass=True, **base))):
        step_db = switched(a, b)
        check("switching %s is click-free" % name, step_db <= -20.0, "largest step %.1f dB" % step_db)

    print("\n" + ("selftest: all good" if ok else "selftest: FAILURES above"))
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    ap.print_help()
