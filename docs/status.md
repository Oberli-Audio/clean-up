# Status - Clean Up 0.1.0 (2026-11-01)
Tier P, track E, at gate G2. Recipe D.8.1.

## Waiting for Björn
Newest first, one line each. Everything else below is unblocked and in progress.

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
| G2 | open | numpy prototype in the port's structure (`sound design/prototype/`) |
| G3 | - | |
| G4 | - | |
| G5 | - | |
| G6 | - | |
| G7 | - | |

## Listening debt
- 2026-11-01: nothing rendered yet; the G3 reference renders will be listed here as pairs
  (flawed / repaired) per module.

## Open exceptions
- none yet.

## Handoff
Task: build Clean Up from G1 to G7, Tier P, stopping before the release.
Plan: 1. [x] G1 decisions 2. [ ] G2 numpy prototype (next) 3. [ ] G3 measure
4. [ ] G4 C++ port 5. [ ] harness hooks and tests 6. [ ] G5 null 7. [ ] G6 validate
8. [ ] G7 bank and documents.
Working tree: clean. Build: red on purpose (the template processor still references
`Params::outGain` and `Params::mix`, which the real `parameters.csv` does not have; the
processor is rewritten at G4). Tests: not registered yet (no harness binary).
Open questions for the owner: the Waiting for Björn section above.
Next command: `python3 "sound design/prototype/measure.py" --all`

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
