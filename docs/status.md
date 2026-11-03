# Status - Clean Up 0.1.0 (2026-11-03)
Tier P, track E, at gate G3 (open: every row measured, 37 of 38 pass; Reverb's T60 needs a
design decision, below; the reference renders are waiting to be heard). G4 runs meanwhile for
Hum, Click and Noise, whose rows pass. Recipe D.8.1.

## Waiting for Björn
Newest first, one line each. Everything else below is unblocked and in progress.

- 2026-11-03 **Listening checkpoint: the reference renders are written.** `python3 "sound
  design/prototype/measure.py" renders` -> `sound design/renders/` (gitignored, to the bit from
  the seeds). A/B `<module>-in.wav` against `-out.wav`, and listen to `-removed.wav` alone:
  hum on the bass line, clicks on the vocal, pink noise on the vocal, the 1.2 s room on the
  vocal. The reverb pair is the one the decision below is about.
- 2026-11-03 **Reverb does not shorten the room; the design needs your call.** At Amount 50 %
  a 1.2 s room still reads **1.26 s** (target <= 0.6). The G1 decision predicted a memoryless
  gain could not change a decay *rate*; it also cannot steepen the fit: in a free exponential
  tail the late estimate equals the current power every frame, so `1 - Amount * late /
  current` is a constant (-3 dB at 50 %) and the tail is lowered, not shortened. Plain
  subtraction takes only 5.5 dB off a pure tail even at 100 %, because a noise-like tail
  scatters per bin (Noise's heavy tail again). Tried and reverted: a decision-directed Wiener
  against the late power (up to 20 dB off the tail at 100 %, but Lebart counts a held note's
  own power 50 ms back as reverb, so a held vowel would sit ~14 dB down - a pencil estimate,
  not measured) and a second "shorter room" late model (right in principle - the gain falls
  through the tail - but fed by the scatter it never pulled away). Options: **(a)** carry on
  towards real decay shortening: the shorter-room model driven by a robust direct-sound
  estimate, inside structural decision 4 but a G1 re-open, held notes the risk to measure -
  my recommendation; **(b)** Amount lowers the tail instead of shortening it (a drier room,
  not a smaller one) and the brief's target becomes a late-energy drop - cheap, and audibly a
  different effect. Listen to `reverb-out.wav` (that is (b) at its mildest) before you choose.
- 2026-11-02 **`noiseSmooth` is a time constant of 0.25-4 s, not the sketch's alpha 0.5-0.98.**
  Measured: at the sketch's range the default (alpha 0.69) leaves the Wiener short of its own
  floor - 7.3 dB where -12 was asked, 8.6 dB at most however deep the floor. From 0.25 s up a
  noise-only bin reaches its floor; the default 40 % is now 0.76 s and delivers 11.6 dB at
  -12, musical noise -67.0 dBFS. What longer Smooth costs is onsets: the first 10 ms of a
  phrase lose 0.30 dB at Smooth 0 %, 0.56 dB at 40 %, 1.08 dB at 100 %. The tooltip's
  "at the cost of some noise between words" no longer describes the trade; say if it should
  read "at the cost of softer word onsets" and I change the CSV line.
- 2026-11-01 **Latency is 54.7 ms at 48 kHz, not the brief's ~43 ms.** The brief's
  `latency_budget` reads "2048-frame STFT plus click lookahead (about 43 ms)", but a 2048 frame
  at 4x overlap costs `frame - hop` = 1536 samples on its own, and the output FIFO needs one hop
  because a host block is not a multiple of the hop. The honest budget is `hop + (frame - hop) +
  lookahead` = `frame + lookahead` = 2048 + 576 = **2624 samples = 54.7 ms**, reported and
  verified by the impulse test. Options if that is too much: (a) accept 54.7 ms - my
  recommendation, the plugin is for recorded material and the live rig is a stream, not a
  monitor path; (b) cap Length at 5 ms and shorten the click lookahead to 6 ms -> 48.7 ms;
  (c) a 1024 frame -> 32.7 ms, at the cost of the frequency resolution the hum and noise
  estimators live on. Say which.
- 2026-11-01 **`clickThreshold`'s sigma range is 40-6, not the sketch's 12-3.** Measured: at
  the sketch's mapping the default 55 % is 7 sigma, and a voice's glottal pulses are the AR
  model's own excitation, so the detector fired once per pitch period - **721 repairs on a
  clean vocal**. At 40-6 (default 55 % = 21 sigma) that is 3, with 97 of 100 clicks still
  caught and 0 false repairs on a snare. The knob's direction is unchanged.
- 2026-11-01 **EX-1 below: 97 of 100 clicks caught, not all 100.** The brief asks for all.
- 2026-11-01 **`clickThreshold` reads backwards in two places.** The sketch's mapping (4.3,
  "0-100 % to 12-3 sigma") and the CSV's `meaning` ("only loud clicks / balanced /
  everything") say higher % catches more; `brief.md` `core_controls` ("how unusual a sample
  must be") and the CSV `tooltip` said the opposite. Implemented as the sketch and `meaning`
  say; the tooltip is corrected in `parameters.csv`. **If you prefer the other direction the
  name should become Sensitivity** - say which and I change the CSV (one line, no DSP work).
- 2026-11-01 **Sketch 4.2 says "the comb is bypassed below -60 dB Depth".** -60 dB is the
  deepest cut in the table, so taken as a slip: the comb is bypassed in code at Depth = 0 dB
  (no cut). Confirm.
- 2026-11-01 **CPU numbers from this machine are not your machine.** The brief's budget is an
  Apple M3 Pro; this cloud container is x86_64 Linux, 4 cores. `perf.py` rows here are
  labelled with the machine and are a sanity check, not the budget row of the release gate.
- 2026-11-01 **The release gate needs your two machines.** pluginval L10, the Steinberg
  validator, the macOS/Windows bundles, the arm64 smoke test, Ableton Live 10.1 under Rosetta
  and Ableton Live on Windows cannot run in a Linux container. Everything else of the gate is
  run here and logged below.
- 2026-11-01 **Listening checkpoint, after G3.** Reference renders of the four modules on the
  test material are committed under `sound design/renders/`; the pairs to A/B are listed in
  Listening debt.

## Gates
| Gate | State | Evidence (command -> number, test name, log) |
|---|---|---|
| G0 | closed 2026-11-01 | `docs/brief.md` owner-confirmed, from `docs/sketch.md` |
| G1 | closed 2026-11-01 | see Decisions: four families, four departures, each with the measurement that rejects it |
| G2 | closed 2026-11-01 | `python3 "sound design/prototype/cleanup_proto.py" --selftest` -> 17 checks, all green (Burg against a known AR(2), the bell against its own biquad, all-off bit-exact, WOLA passthrough, latency = frame + lookahead, bypass a delayed wire, two runs bit-identical, block size irrelevant, finite at all six rates, Output + Removed = Input) |
| G3 | **open** | per target below; `python3 "sound design/prototype/measure.py" --all` -> 38 measurements, 1 fail (Reverb T60, 2026-11-03) |
| G4 | - | |
| G5 | - | |
| G6 | - | |
| G7 | - | |

### G3 metric table (as measured, 2026-11-01)
Every row is one `measure.py` subcommand; the seed and the material are in its own output.

| Target (brief) | Measured | Verdict |
|---|---|---|
| all modules off null exactly | -300.0 dBFS (bit-exact) | pass |
| bypass is latency-compensated and nulls | -300.0 dBFS | pass |
| Output + Removed = Input | -300.0 dBFS | pass |
| latency reported = measured, Hum only | 0 samples | pass |
| latency reported = measured, any spectral module | 2624 samples = 54.7 ms | pass, but see Waiting |
| 50 Hz + 8 harmonics at -40 dBFS go below -90 dBFS | **-101.8 dBFS** | pass |
| a 100 Hz note loses at most Depth dB | 11.8 dB at Depth -60, 11.8 at -24 | pass |
| the tracker follows mains drift | 50.18 Hz on +/-0.3 Hz drift | pass |
| Depth 0 dB bypasses the comb | -300.0 dBFS | pass |
| Find measures the mains frequency | 50.00 Hz | pass |
| 100 clicks 0.5-3 ms all caught at Threshold 55 % | **97 of 100** | EX-1 |
| (2026-11-03) per-click repair: median residual / improvement | -35.5 dBFS / 23.6 dB (was -31.7 / 18.8) | pass |
| 0 false repairs on a snare at Threshold 55 % | **0** | pass |
| a clean vocal is left alone | 3 repairs, residual -42.3 dBFS | pass |
| -50 dBFS pink reduced 12 +/- 1 dB in the gaps | 11.56 dB (2026-11-02; was 7.3) | pass |
| no musical noise above -60 dBFS at Smooth 40 % | -67.0 dBFS (2026-11-02; was -57.7) | pass |
| Smooth buys less artefact (0 % -> 40 %) | 1.2 dB | pass |
| Reduction 0 dB passes through | -143.9 dBFS | pass |
| Learn captures a profile | yes, gaps reach -61.6 dBFS | pass |
| 1.2 s RT60 reads <= 0.6 s at Amount 50 % | **1.26 s** (input 1.30 s) | **fail, Waiting for Björn** |
| onsets within 1 dB at Attacks 60 % | 0.65 dB | pass |
| Amount 0 % passes through | -142.3 dBFS | pass |
| Estimate measures the tail | 1.60 s (1.2 +/- 0.4) | pass |
| all four: finite, no clip | -7.5 dBFS peak | pass |
| all four adds no step outside the clicks (vs the clean room) | -3.4 dB | pass |
| all four: clicks caught in a room with hum and noise | 29 of 30 (2026-11-03; was 28) | pass |
| Removed display has data / is empty when off | 33.7 dB / 0 | pass |

## Listening debt
- 2026-11-03: nothing heard yet. The renders are written (`measure.py renders` -> `sound
  design/renders/`, gitignored, reproducible to the bit from the seeds): hum on the bass line,
  clicks on the vocal, pink noise on the vocal, the 1.2 s room on the vocal, each as `-in`,
  `-out` and `-removed`. Noise and Click changed on 2026-11-02/03, so these are the first
  renders of what G4 will port.

## Open exceptions
- EX-1 2026-11-01: brief target "100 synthetic 0.5-3 ms clicks all caught"; measured **97 of
  100** by `python3 "sound design/prototype/measure.py" click` (vocal + 100 clicks at amplitude
  0.5, Threshold 55 %, Length 3.5 ms, seed 6). Shipping is acceptable because each of the three
  coincides with an edge in the music - one inside a sibilant burst, two straddling a phrase
  end into silence - where the level-step test has to choose between missing a click and
  repairing a transient, and a click masked by a sibilant is not audible. Threshold does not
  buy them back (40 %: 95, 70 %: 97, 100 %: 96 with 526 repairs on a clean vocal), so this is
  the design's ceiling, not a setting. **Unacceptable if** fewer than 95 of 100, as the test
  `clicks caught (of 100)` asserts, or if a snare gains a single false repair.
  Friends: a click sitting exactly on a consonant or on the last note of a phrase may survive.

## Handoff
Task: build Clean Up from G1 to G7, Tier P, stopping before the release.
Plan: 1. [x] G1 decisions 2. [x] G2 numpy prototype 3. [~] G3 measure - every row run
(`measure.py --all`: 38 measurements, 1 fail); open: Reverb's T60 (Waiting for Björn) and the
listening checkpoint 4. [ ] G4 C++ port 5. [ ] harness hooks
and tests 6. [ ] G5 null 7. [ ] G6 validate 8. [ ] G7 bank and documents.
Machine: from 2026-11-02 Björn's Mac (Claude Code in VS Code), on `main`. `Source/oberli/` is
refreshed from plugin-template 0e7d4f4 (`refresh_oberli.py --accent "#33B679"`); the editor is
wired to it at G4, with plugin-ui-bob.
Build: `cmake --preset release && cmake --build --preset release` is red on purpose, only in
`Source/PluginProcessor.cpp` (the template processor still references `Params::outGain` and
`Params::mix`, which the real `parameters.csv` does not have; the processor is rewritten at G4).
Tests: the prototype selftest is green, 21 checks
(`python3 "sound design/prototype/cleanup_proto.py" --selftest`); `ctest --preset fast` runs the
four shared tests (oberli_build_tests, oberli_loudness, oberli_shared, oberli_copy), all pass;
the product suite registers once the harness builds. On this Mac CMake finds Homebrew's
python3.12 first, which has no numpy: configure with
`cmake --preset release -DPython3_EXECUTABLE=/usr/bin/python3` (the build cache keeps it).
Open questions for the owner: the Waiting for Björn section above.
Next command, to resume exactly where this stopped:
the listening checkpoint and the Reverb decision are Björn's. Unblocked meanwhile: why the
all-four click at 5.13 s is never caught (`measure.py all-four`; a lead in Decisions,
2026-11-03), then G4, the C++ port of Hum, Click and Noise, whose G3 rows pass.

## Decisions

### 2026-11-01 G1, the four families
The selection tables (`dsp-selection.md` S.2) carry **no restoration rows**: no de-hum,
de-click, de-noise or de-reverb. Per S.0 a row that is not there is not forbidden - pick the
family by the quality axes it has to win on, write the trade-off, and the row is added to the
table afterwards (that is skills-bob work on dsp-selection.md, not this repo). The axes that
decide every module here are, in order: **the flaw goes away**, **nothing else changes**
(the null when off, the bass note on a hum harmonic, the snare that is not a click, the
consonant that survives), and **real-time at Tier P's budget**. The rows that do apply are
the spectral family's verification line (E.11: null when unmodified, latency, musical noise,
transient smearing) and rule 6 (modulated filters TPT/ZDF), rule 7 (latency), rule 12
(seconds, never samples).

- **Hum - adaptive notch comb of TPT bell filters, time domain, zero latency.** One
  second-order Cytomic/Simper SVF bell per harmonic, gain = Depth dB, Q = f_k / Width, with
  an I/Q frequency tracker on the fundamental (phase advance of the complex envelope, one
  `atan2` per 32-sample sub-block, tau 2 s, clamped to +/-0.5 Hz of `humFreq`). Trade-off:
  a bell with finite gain instead of a true notch is what makes "a bass note on a harmonic
  loses at most Depth dB" an identity rather than a hope, and TPT keeps it stable while the
  tracker moves it (rule 6). Rejected if: the comb at Depth -60 dB leaves the 50 Hz hum
  stack above -90 dBFS, or a 100 Hz sine loses more than Depth dB
  (`measure.py hum`).
- **Click - AR(32) prediction error for detection, two-sided AR extrapolation with a
  raised-cosine crossfade for the repair.** Burg on 10 ms blocks, error normalised by its
  50 ms RMS, Threshold 0-100 % mapped to 12-3 sigma, spans merged below 1 ms and clamped to
  Length. **Departure** from the sketch's "least-squares AR interpolation": the exact
  interpolation is a dense solve the size of the gap (up to 1920 samples at 192 kHz) and
  cannot run in `processBlock` (rule 1, rule 20). Forward extrapolation from the left
  context, backward from the right, crossfaded, is O(span x order) and is interpolation from
  both sides as the sketch's structural decision 2 requires. Rejected if: of 100 synthetic
  0.5-3 ms clicks any is missed, the per-click repair residual against the clean reference is
  above -30 dBFS, or a snare at Threshold 55 % gets a single false repair
  (`measure.py click`).
- **Noise - decision-directed Wiener gain on the shared STFT, minimum statistics for the
  Adaptive profile.** a-posteriori SNR from the bin power over the noise estimate, a-priori
  SNR smoothed with alpha from Smooth (0.5-0.98; a time constant of 0.25-4 s since
  2026-11-02, see below), gain floored at Reduction so the floor is
  reduced and not removed. Trade-off against a spectral gate: the gain floor plus the
  a-priori smoothing is the only thing that keeps musical noise down, and it is what the
  brief measures. Rejected if: -50 dBFS pink noise is not reduced by 12 +/- 1 dB in the gaps,
  or musical noise rises above -60 dBFS at Smooth 40 % (`measure.py noise`).
- **Reverb - late-tail power subtraction per bin (Lebart-style) with a spectral-flux attack
  hold.** The late power is predicted from the frame 50 ms back scaled by the Tail decay;
  gain = sqrt(max(1 - Amount x late/current, floor)), one-pole smoothed over 2 frames; an
  onset holds the gain at 1 for Attacks % of 40 ms. **Stated honestly:** a memoryless
  per-bin gain cannot change the physical decay *rate* of a pure exponential tail - it
  lowers the late energy relative to the direct sound. The brief's "1.2 s RT60 reads
  <= 0.6 s at Amount 50 %" is therefore measured as the Schroeder T60 over the -5 to -25 dB
  window of the processed vocal's decay, where the step in late-to-direct ratio steepens the
  fit; that is also what the ear calls a drier room. Rejected if: that T60 stays above 0.6 s
  at Amount 50 %, or consonant onsets move by more than 1 dB at Attacks 60 %
  (`measure.py reverb`).

### 2026-11-01 G1, the structure the three spectral modules share
One WOLA STFT, periodic Hann, 4x overlap, **frame length specified in seconds** (42.667 ms,
the sketch's 2048 at 48 kHz) and rounded up to a power of two at the prepared rate in
`prepare` (rule 12): 2048 at 44.1 and 48 kHz, 4096 at 88.2 and 96, 8192 at 176.4 and 192, so
the time resolution is the same at every rate. The click stage sits inside the same framing
and takes its lookahead from it, which is what makes the brief's single latency figure exact:

    latency = clickLookahead (1 hop) + (frame - hop) = frame = 42.667 ms

Two latency states only, as the sketch decided: **0 samples** with Hum alone or nothing on,
**frame samples** as soon as Click, Noise or Reverb is on. Switching a spectral module on
primes the engine for one frame (the dry, hum-only signal is heard during it) and then
crossfades 15 ms into the delayed engine output (rule 2); `setLatencySamples` is published
off the audio thread, never from `processBlock` (rule 1). Off is bypassed in code, not zeroed,
so all-off is bit-exact against the input (`must_do`) and bypass is a latency-compensated
wire (rule 7). Removed = the plugin input delayed by the current latency minus the output, so
it carries what Hum took away too; Listen Input is the same delayed input, so every Listen
mode is latency-matched.

### 2026-11-01 G2 prototype tool: numpy, not Faust
`F.15.1`'s per-track table says it outright for this case: effect, STFT - "Faust; **a numpy
model for STFT/spectral effects**". Burg's method, a dense STFT with per-bin decision-directed
state and an AR extrapolator are not Faust's shape, and G5 nulls against the numpy model
(same table, G5 row). Faust is also not installed on this machine. No Faust library function
is used anywhere, so `notices.toml` gains no `kind = "faust"` entry.

### 2026-11-01 G2/G3, what measuring changed in the design
Each of these was found by a measurement, not by reading the code; each constant is named and
commented at its definition in `sound design/prototype/cleanup_proto.py`.

- **The notch Width was scaling with Depth.** Simper's published bell uses `k = 1/(Q A)`, so at
  Depth -60 dB (A = 0.0316) a 2 Hz Width came out 63 Hz wide and the comb ate the bass: a
  100 Hz note lost 61.5 dB where the target is at most Depth. The bell's centre gain is `A^2`
  for *any* k, so k is now the bandwidth outright (`k = Width / f0`) and Width is the -3 dB
  bandwidth, measured: -59.9 dB at the centre, -3.03 dB at +1 Hz, -0.009 dB at 20 Hz away.
- **The hum tracker needed a warm-up gate.** Its first, meaningless estimates pushed the track
  17 mHz off and the 2 s loop then took 8 s to creep back: -80 dBFS of hum over 1-2 s against
  -91 over 3-4 s. With the loop held open for 5 I/Q time constants (1 s) the track holds 50 Hz
  to 80 microhertz and the comb reaches -101.8 dBFS. A frozen comb reaches the same, which is
  how the residual was attributed to tracking error rather than to coefficient modulation.
  `|H(f0+d)| = max(A^2, 2 d / Width)` is why: at 2 Hz Width a 10 mHz error is -40 dB, not -60.
- **The click detector was rebuilt four times, each time on a number.** A leaky integrator over
  e^2 let 100 clicks in 6 s mask each other (32 of 100 caught); clamping its update made vocal
  onsets and snare hits cross the threshold (36 false repairs); a robust per-block MAD sigma
  fixed both but collapses to zero in digital silence (863 detections for 100 clicks), so the
  threshold has an absolute floor at -80 dBFS. Runs truncated at the hop boundary looked short,
  and a short run is what the detector takes for a click, so the scanner now carries an open
  run across segments. A snare attack still settles into a well-predicted noise burst after
  ~95 samples, so run length alone cannot tell an attack from a click: the level-step test
  (context RMS either side, 12 dB) does, and took the snare to 0. Detection and repair now use
  different orders - 32 to detect (14 false detections on a clean vocal against 442 at order
  256, because an over-fitted model shrinks sigma with the error), 192 to repair (median
  per-click residual -31.5 dBFS at 32, -42.0 at 192, -43.5 at 256), the repair model fitted
  lazily at most once per hop. The detection model is fitted on history + segment + lookahead,
  not on clean history alone: 3 false repairs and -42.3 dBFS on a clean vocal against 9 and
  -16.3 dBFS. And the edge crossfade was sitting on the click itself - for a 0.5 ms click, 16
  of its 24 samples were inside the two seams - so the repair now extends by the crossfade on
  each side.
- **Minimum statistics was taking the minimum of the raw periodogram** and read 21.8 dB low
  (the minimum of N exponential samples has mean 1/N of their mean; a 1.5 s window at a 10.7 ms
  hop is N = 140). Martin's method smooths first; with a 200 ms per-bin smoother the bias is
  1.8 dB, calibrated by `measure.py noise --calibrate`. The engine's priming zeros also pinned
  the estimate at zero for the first 1.5 s, so the tracker starts at the first frame with any
  energy, with the whole ring primed from it.

### 2026-11-01 the Noise module's Reduction knob (resolved 2026-11-02, next section)
`noiseReduction` is a **per-bin gain floor**, but the brief measures the **broadband** drop of
the floor in the gaps, and a decision-directed Wiener deliberately keeps bins that look like
signal. The periodogram of stationary noise is exponential, its tail is heavy, and the bins
with large gamma carry most of the energy, so the achieved reduction saturates far short of the
floor. Measured on the vocal + -50 dBFS pink, Smooth 40 %, Adaptive:

| `noiseReduction` (floor) | measured broadband reduction | deficit |
|---|---|---|
| -3 dB | 2.69 dB | 0.31 dB |
| -6 dB | 4.81 dB | 1.19 dB |
| -12 dB | 7.33 dB | 4.67 dB |
| -18 dB | 8.21 dB | 9.79 dB |
| -24 dB | 8.48 dB | 15.52 dB |
| -30 dB | 8.56 dB | 21.44 dB |
| -42 dB | 8.60 dB | 33.40 dB |

Smoothing the a-posteriori SNR (the standard musical-noise fix) moves the ceiling to 8.3 dB at
30 ms and no further, and the vocal itself is untouched either way (0.00 dB change over a
phrase), so the ceiling is the gain law, not the estimator. The knob's own meaning in
`parameters.csv` is "How much of the noise floor is taken away", so the fix in hand is to make
the knob deliver that number - the floor becomes a function of Reduction calibrated against
this table - rather than to re-label the knob as a per-bin floor. **Not yet implemented.**

### 2026-11-02 G3, Noise: two defects, not a calibration
The table above was read as the gain law's ceiling and the plan was to calibrate the knob
against it. Measuring before calibrating showed two defects instead, and with both fixed the
knob delivers its number without a calibration table. Each is a row in `docs/failures.md` and a
selftest check that fails on the commit before.

- **The minimum tracker started from one periodogram.** On noise alone the module reduced
  2.3 dB over its first 1.5 s and 11.8 dB after it; the brief's first gap (1.14-1.48 s) sits
  in that window. A single frame is exponentially distributed per bin, and the ring primed from
  it held the minimum far below the floor until it rolled over. Now the estimate is the running
  mean of the frames for `NOISE_MINSTAT_SMOOTH_S` (200 ms) and the ring is primed from that:
  10.7 dB over the first 0.5 s, 11.8 dB over 1.0-1.5 s.
- **The decision-directed gain stopped short of its floor.** Two parts. The a-priori SNR used
  the *current* gamma with the previous gain instead of Ephraim-Malah's `G(l-1)^2 gamma(l-1)`,
  which makes it partly a-posteriori (measured, it alone changes little: 7.2 against 7.3 dB).
  And the sketch's alpha range put the default at 0.69, where a Wiener cannot reach a
  -12 dB floor in pure noise even with an exact noise estimate (simulated: 9.3 dB, 10.5 dB at
  a -40 floor; 12.0 dB at alpha 0.98). The smoothing is now a time constant (rule 12),
  `alpha = exp(-hop / tau)`, tau log-spaced from 0.25 s (Smooth 0 %) to 4 s (100 %). Sweep on
  the vocal + pink, Reduction -12 (`tau_sweep`, seed 4):

  | tau | -6 | -12 | -18 | -24 | -30 | musical noise at -12 | onset, first 10 ms |
  |---|---|---|---|---|---|---|---|
  | 0.03 s | 5.5 | 8.7 | 9.9 | 10.3 | 10.4 | -60.5 dBFS | -0.06 dB |
  | 0.10 s | 5.7 | 10.5 | 13.2 | 14.1 | 14.4 | -63.6 | -0.16 |
  | 0.25 s | 5.8 | 11.2 | 15.7 | 18.0 | 18.7 | -65.8 | -0.30 |
  | 0.50 s | 5.8 | 11.5 | 17.1 | 21.4 | 23.5 | -66.8 | -0.46 |
  | 1.00 s | 5.8 | 11.6 | 17.8 | 23.5 | 28.2 | -67.2 | -0.64 |
  | 4.00 s | 5.8 | 11.7 | 18.0 | 24.0 | 30.0 | -67.5 | -1.08 |

  The knob as shipped, measured in the gaps (asked -> delivered, dB):

  | Smooth | -3 | -6 | -12 | -18 | -24 | -30 |
  |---|---|---|---|---|---|---|
  | 0 % (0.25 s) | 2.95 | 5.77 | 11.21 | 15.71 | 18.02 | 18.73 |
  | 40 % (0.76 s) | 2.95 | 5.79 | 11.56 | 17.55 | 22.99 | 26.66 |
  | 100 % (4 s) | 2.95 | 5.80 | 11.74 | 17.99 | 24.00 | 29.99 |

  At the default the knob is within 1 dB of its number to -24 dB; deeper settings need more
  Smooth, which is the trade the knob is for. Rejected if: `measure.py noise` misses 12 +/- 1 dB
  or musical noise rises above -60 dBFS at Smooth 40 %, or the first 10 ms of a phrase lose
  more than 1 dB at Smooth 40 %. `NOISE_MINSTAT_BIAS_DB` is unchanged (1.8 dB, re-measured by
  `measure.py noise --calibrate`).

### 2026-11-03 G3, Click: repairs covered only the click's core
The all-four run showed it: in a room with hum and noise, clicks were caught but repaired
from 13-46 samples after their start to 17-45 before their end, leaving -13.8 dBFS where the
input had -14.9. The detection threshold (21 sigma at the default 55 %) finds a click's core
only; its flanks were left in. Now a detected run grows outwards to the furthest sample whose
prediction error is above `CLICK_EXTEND_SIGMA` (6 sigma), up to `CLICK_EXTEND_MAX_S` (1 ms) a
side, crossing dips of up to `CLICK_EXTEND_GAP_S` (0.25 ms): a random-signed burst's error dips
below any threshold every few samples, and a sample-by-sample walk stopped at the first dip.
The click battery: 97 of 100 still caught (EX-1 unchanged), median residual -35.5 dBFS (was
-31.7), median improvement 23.6 dB (was 18.8), 0 snare repairs, 3 on the clean vocal as before.
Regression: selftest `click repair covers the whole click (hysteresis)` (-16.5 dBFS on the
commit before, -38.5 after); `docs/failures.md`.

**The level-step test read pitch-pulse ripple as an edge** (fixed 2026-11-03, the same day).
Its 1.333 ms windows are shorter than a sung pitch period (3.7-5.5 ms here), so in the vocal in
a 1.0 s room 0.75 % of positions read a > 12 dB step at 1.333 ms and none at 5 ms; the click at
5.44 s of the all-four run sat on one (-31.0 against -18.6 dBFS). 5 ms windows alone caught it
and missed a click 4 ms before a phrase onset instead, because the right window reached into
the onset. An edge in the music is a step at every scale, a pulse ripple only at the short one
and a nearby onset only at the long one, so the test now calls it an edge only when both
1.333 ms and `CLICK_STEP_LONG_S` (5 ms) agree. All-four: 29 of 30 (was 28); the battery, the
snare (0) and the clean vocal (3) are unchanged. Regression: selftest `clicks in a sung note
are not taken for edges (level step at two scales)` (5 of 7 on the commit before, 7 of 7).

**The one left, at 5.13 s, is below the default sensitivity, not a defect.** It sits in a loud
passage (local peak 0.28): the prediction error's sigma there is 0.0215, 21 sigma is 0.457, and
the click's own largest error is 0.384. Threshold 70 % (16 sigma) catches it - all 30, with one
repair on the clean room vocal (`clk3` sweep, 2026-11-03) - which is what the knob is for.

### 2026-11-03 G3, the all-four measurement was measuring the wrong thing
Two measurement defects, fixed in `measure.py all-four`, not in the plugin:
- **The flaws were in the room.** Hum, pink and the clicks were added before the room
  convolution, so each click carried a 1 s tail of its own and the level-step test (rightly)
  read it as a transient. Hum, noise and clicks are electrical; they now arrive after the room.
- **presetlint's absolute -6 dB `max_click_db` cannot be met by this material**: the clean
  vocal's sibilants alone read -3.8 dB. The health row now asks what it is for - whether the
  chain adds a step - outside the injected clicks (+/- 2 ms) and against the clean vocal in the
  same room (+1 dB allowed). Whether the clicks went is a separate row at EX-1's 95 %.
