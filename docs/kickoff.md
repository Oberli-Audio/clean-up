# Clean Up: kickoff

Build order 5 of 5. Effect, Bone theme, accent sage #33B679 (category accent for mix tools, decided 2026-11-01), plugin code `Clup`, Tier P. Repo created from the template and initialised on 2026-11-01; parameter table and sketch are in.

## Prompt for the cloud session (started on Oberli-Audio/clean-up, VST3 project attached)

```
Build Clean Up for Oberli Audio, Tier P.
G0 is closed: docs/brief.md is owner-confirmed (2026-11-01), from the decided
sketch docs/sketch.md; parameters.csv is in the repo. Start at G1. Use
sound-design-bob and plugin-ui-bob (ship-bob for CI and releases).

Working rules:
- Pass a gate on your own when its evidence is green (tests, paramgen,
  pluginval, null and latency tests); log it in docs/status.md and go on.
- Stop for me only for: listening checkpoints, Ableton host checks (Live
  10.1 under Rosetta, Live on Windows), a conflict with a structural
  decision in the sketch, and before any release (run the release gate).
- Everything that needs me goes in a section "Waiting for Björn" at the
  top of docs/status.md, one line each, newest first; keep working on
  whatever is not blocked.
- Shared code (LookAndFeel, Strip frame, meters, Loudness, Analysis/FFT,
  References, RenderSafety) is built in Oberli-Audio/bob-skills as
  template Source/oberli/. Never write your own version and never edit
  bob-skills. Until it lands, keep the editor as the template stub and
  work on the DSP, harness and tests; then refresh Source/oberli/ from
  plugin-template and wire it in. A missing shared piece is a "Waiting
  for Björn" line.
- Commit and push at every checkpoint.
```

## Prompt to take the work up in the local session (Claude Code in Visual Studio / VS Code)

The cloud session above closed G0, G1 and G2 and stopped part-way through G3, on
`claude/oberli-audio-cleanup-tier-p-kz4mgz` at commit `eb68a85`. Paste the block below into a
fresh Claude Code session opened on this repository on your own machine. It stands alone - it
does not assume the cloud conversation.

```
Take up Clean Up for Oberli Audio, Tier P, track E, at gate G3 (open, part-measured).

Where it stands
- Branch claude/oberli-audio-cleanup-tier-p-kz4mgz, which already contains origin/main
  (the sage accent). Work on that branch; do not start a new one.
- docs/status.md is the one page and is current: the gate table carries the command
  behind every measured number, the G3 metric table says which targets pass, EX-1 is
  the one open exception, the Decisions section says what measuring changed in the
  design and why, and the Handoff section names the next command.
- G0 closed (docs/brief.md, owner-confirmed, with two dated amendments beneath the
  YAML - never edit the YAML). G1 closed (four algorithm families, each with its
  trade-off, its departure from the sketch where there is one, and the measurement
  that would reject it). G2 closed (the numpy prototype; F.15.1's per-track table
  prescribes numpy, not Faust, for an STFT effect, and G5 nulls against it).
- G3: null, bypass, the Listen identity, both latency states, the whole hum battery
  and the whole click battery pass. Noise is short of its target, and reverb,
  all-four and the reference renders have not been run.

Read first: docs/status.md, then sound design/prototype/cleanup_proto.py (its module
docstring and the constants block - every constant carries the measurement that set
it). Use sound-design-bob and plugin-ui-bob; ship-bob from the release gate on.

Resume here
1. The Noise module's Reduction knob. noiseReduction is a per-bin gain floor, but the
   brief measures the broadband drop of the floor in the gaps, and the module
   saturates at 8.6 dB however deep the floor is set (the floor-to-achieved table is
   in docs/status.md Decisions). Smoothing the a-posteriori SNR moves the ceiling to
   8.3 dB and no further, and the vocal itself is untouched either way, so the
   ceiling is the gain law, not the estimator. The knob's own meaning in
   parameters.csv is "How much of the noise floor is taken away", so calibrate the
   knob to deliver that number against the table rather than re-labelling it.
   Re-measure with: python3 "sound design/prototype/measure.py" noise
2. Then: measure.py reverb, measure.py all-four, measure.py renders (the renders are
   the listening checkpoint - stop and let me hear them).
3. Then G4: port Source/ to C++ by structure, constants hand-matched and documented
   beside the code. The template processor is still the skeleton and references
   Params::outGain and Params::mix, which the real parameters.csv does not have, so
   the build is red on purpose until the port lands.
4. Then the harness product hooks (--solo per module, product metrics: the three
   click counters, the removed band energies, the latency state, and flags that drive
   Find / Learn / Estimate), then tools/tests/test_plugin.py with a presence test per
   defining feature, each shown failing first (rule 13, D.3.8).
5. Then G5 (null the port against the prototype, per module, F.8 thresholds or a
   characterisation), G6, G7. Stop before any release and run the release gate with me.

Your machine can do what the cloud container could not, so do these when you reach
them: the malloc trap (it is macOS-only in tools/harness/Main.cpp, so it never armed
in the Linux container), the rtsan preset, pluginval L10, the Steinberg validator,
auval, the arm64 smoke test, perf.py on the slice the host runs, and the two Ableton
checks. Machine paths come from ~/.config/oberli/tools.toml
(python3 scripts/dsp-kit/toolchain.py check). The CPU numbers in docs/status.md from
the cloud container are labelled as not being your machine - replace them.

Four open questions are in the "Waiting for Björn" section of docs/status.md and need
me, not you; none of them blocks the work above. Shortest form:
- Latency is 54.7 ms at 48 kHz, not the brief's ~43 ms (a 2048 frame at 4x overlap
  costs frame - hop on its own). Three options are written out there; accepting
  54.7 ms is the recommendation.
- clickThreshold's sigma range is 40-6, not the sketch's 12-3 (at 12-3 the detector
  fired once per pitch period: 721 repairs on a clean vocal).
- EX-1: 97 of 100 clicks caught, not all 100.
- The shared Source/oberli/ has not landed, so the editor is still the template stub
  and the always-on input sonogram of the Removed display waits on the shared
  Analysis/FFT.

Working rules, unchanged
- Pass a gate on your own when its evidence is green (tests, paramgen, pluginval,
  null and latency tests); log it in docs/status.md and go on.
- Stop for me only for: listening checkpoints, the Ableton host checks (Live 10.1
  under Rosetta, Live on Windows), a conflict with a structural decision in the
  sketch, and before any release (run the release gate).
- Everything that needs me goes in "Waiting for Björn" at the top of docs/status.md,
  one line each, newest first; keep working on whatever is not blocked.
- Shared code (LookAndFeel, Strip frame, meters, Loudness, Analysis/FFT, References,
  RenderSafety) is built in Oberli-Audio/bob-skills as template Source/oberli/. Never
  write your own version and never edit bob-skills. Until it lands, keep the editor as
  the template stub and work on the DSP, harness and tests; then refresh
  Source/oberli/ from plugin-template and wire it in.
- scripts/dsp-kit/ and scripts/ship/ are byte copies of the kits: refresh them from
  ~/bob-skills, never edit them here. parameters.csv is the single source for
  parameters; regenerate Source/Params.h and docs/parameters.md from it.
- Add a regression test whenever a DSP defect is fixed, show it failing on the build
  that has the defect, and add its row to docs/failures.md.
- Commit and push at every checkpoint.

Two practical notes on the prototype: the hum comb is a per-sample loop in Python, so
keep any render you add to 6 seconds or so; and cleanup_proto.py --selftest (17
checks) is the fast way to see you have not broken it.
```
