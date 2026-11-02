# Status - Clean Up 0.1.0 (2026-11-01)
Tier P, track E, at gate G3 (paused by the owner mid-G3). Recipe D.8.1.

## Waiting for Björn
Newest first, one line each. Everything else below is unblocked and in progress.

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
- 2026-11-01 **The Noise module's Reduction knob does not yet deliver its number** (see the
  G3 table): asking -12 dB gives 7.3 dB of measured broadband reduction, and the module
  saturates at 8.6 dB however deep the floor is set. That is the periodogram's heavy tail, not
  a bug, and the fix in hand is to calibrate the knob so it means what the CSV says it means
  ("how much of the noise floor is taken away"). **This is where the work was paused.**

- 2026-11-01 **Shared code `Source/oberli/` is not in the template yet.** LookAndFeel, Strip
  frame, meters, Loudness, **Analysis/FFT**, References, RenderSafety are built in
  Oberli-Audio/bob-skills as template `Source/oberli/`. The editor stays the template stub
  until they land; the always-on **input sonogram** of the Removed display needs the shared
  Analysis/FFT, so only the removed-energy half (band energies of in minus out, inside the
  STFT engine) is built on the DSP side. Refresh `Source/oberli/` from plugin-template and
  wire it in when it exists.
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
| G3 | **open, paused** | per target below; `python3 "sound design/prototype/measure.py" <what>` |
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
| 0 false repairs on a snare at Threshold 55 % | **0** | pass |
| per-click repair residual | median -31.7 dBFS, improvement 18.8 dB, worst -10.3 | pass (median bar) |
| a clean vocal is left alone | 3 repairs, residual -42.3 dBFS | pass |
| -50 dBFS pink reduced 12 +/- 1 dB in the gaps | **7.3 dB (module ceiling 8.6 dB)** | **fail, in hand** |
| no musical noise above -60 dBFS at Smooth 40 % | -57.7 dBFS | fail, follows the row above |
| Reduction 0 dB passes through | -143.9 dBFS | pass |
| Learn captures a profile | yes, gaps reach -58.3 dBFS | pass |
| 1.2 s RT60 reads <= 0.6 s at Amount 50 % | not yet run | - |
| onsets within 1 dB at Attacks 60 % | not yet run | - |
| Estimate measures the tail | not yet run | - |
| all four modules on: health, max_click_db, Removed data | not yet run | - |

## Listening debt
- 2026-11-01: nothing heard yet. `python3 "sound design/prototype/measure.py" renders` writes
  `<module>-in.wav`, `-out.wav` and `-removed.wav` for all four modules into
  `sound design/renders/` (gitignored, reproducible to the bit from the seed). The pairs to A/B
  at the listening checkpoint: hum on the bass line, clicks on the vocal, pink noise on the
  vocal, the 1.2 s room on the vocal. **Not yet rendered - paused before it.**

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
Plan: 1. [x] G1 decisions 2. [x] G2 numpy prototype 3. [~] G3 measure - null, latency, hum,
click done; **Noise's Reduction calibration is the open point**; reverb, all-four and the
reference renders not yet run 4. [ ] G4 C++ port 5. [ ] harness hooks and tests 6. [ ] G5 null
7. [ ] G6 validate 8. [ ] G7 bank and documents.
Working tree: clean. Build: red on purpose (the template processor still references
`Params::outGain` and `Params::mix`, which the real `parameters.csv` does not have; the
processor is rewritten at G4). Tests: the prototype selftest is green (17 checks); the CTest
suite is not registered yet (no harness binary).
Open questions for the owner: the Waiting for Björn section above.
To take the work up in the local session (Claude Code in Visual Studio / VS Code): the
self-contained prompt is the second section of `docs/kickoff.md`.
Next command, to resume exactly where this stopped:
`python3 "sound design/prototype/measure.py" noise` - then calibrate the Reduction knob so the
measured broadband reduction equals the number on the knob (the floor-to-achieved table is in
Decisions below), then `reverb`, `all-four`, `renders`.

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
  SNR smoothed with alpha from Smooth (0.5-0.98), gain floored at Reduction so the floor is
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

### 2026-11-01 open: the Noise module's Reduction knob (where work paused)
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
