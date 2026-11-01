# Sonic brief (owner-confirmed 2026-11-01 from the decided Tier S sketch, docs/sketch.md; amend below, never edit the YAML)

```yaml
name: Clean Up
track: effect
stages: [processing, analysis, output]
type: utility
musical_role: effect
tier: P
one_sentence: Four restoration modules in a fixed order (hum, clicks, noise, room tail), one knob each, with everything it removed drawn on the input sonogram.
references:
  - iZotope RX 12 (De-hum, De-click, Spectral De-noise, Dialogue De-reverb): the paid standard; Clean Up is free, real-time, four modules in one
  - Acon Restoration Suite: separate plugins; Clean Up shares one STFT so latency is paid once
  - Bertom Denoiser: free noise only
must_do:
  - Each module off is bypassed in code; all off nulls exactly
  - Hum alone is zero latency; any spectral module adds one fixed latency, reported
  - Removed listen (global only) plays everything taken away
  - Find (hum), Learn (noise profile), Estimate (room RT60) write parameters as one host edit
defining_features:
  - Removed overlay on the input sonogram (hum lines, click ticks, reverb patches, noise tint)
  - Honest click counter including "missed" from a second pass on the output
  - Attack hold in de-reverb keeps consonants sharp
out_of_scope: [spectral repair canvas, machine-learned speech model, per-module mix, per-module listen]
core_controls:
  - Depth: how deep the hum notches cut
  - Threshold: how unusual a sample must be to count as a click
  - Reduction: how much of the noise floor is taken away
  - Amount: how much of the room tail is removed
  - Listen: Output, Removed, Input
signal_flow: |
  in -> Hum (adaptive notch comb + PLL, time domain, 0 latency)
     -> STFT 2048/4x -> Click (AR(32) detect + AR interpolate) -> Noise (Wiener, decision-directed) -> Reverb (late-tail subtraction, attack hold)
     -> iSTFT -> Trim -> out;  Removed = in (delayed) - out
cpu_budget: { p999_pct: 25, max_pct: 50, idle_pct: 2, at: 48k/64, slice: x86_64-rosetta, preset: all four modules on }
cpu_reference_machine: Apple M3 Pro (Björn's Mac)
instances_expected: 1-4 per project on problem tracks; 1 in the live-stream rig (Hum and Noise only)
latency_budget: 0 with Hum only; 2048-frame STFT plus click lookahead (about 43 ms at 48 kHz) otherwise, reported
sample_rates: [44100, 48000, 88200, 96000, 176400, 192000]
channels: stereo
register: n/a (effect)
register_intent: n/a
presets:
  bank_size: 10
  categories: [Hum, Clicks, Noise, Room, Live]
  reference_chord: n/a; test material is a vocal and a bass line with injected hum, clicks, pink noise and a 1.2 s RT60 convolution
  loudness_window: n/a
  edge_presets: [All Four Heavy, Live Stream Vocal, Dry Out The Room]
  naming: English, by flaw and source ("Stage Box Hum", "Live Stream Vocal")
mix_context: early in the chain before compression; removes flaws, never adds colour
quality_targets:
  alias_floor_db:     { target: n/a, method: n/a }
  thd_n_db:           { target: null with all modules off, method: harness null after latency compensation }
  response_error_db:  { target: "a bass note on a hum harmonic loses at most Depth dB", method: 100 Hz sine through the comb at 50 Hz fundamental }
  loudness:           { target: n/a, method: n/a }
  keyboard_span_lu:   { target: n/a, method: n/a }
  low_register:       { target: "50 Hz + 8 harmonics at -40 dBFS below -90 dBFS", method: injected hum on the bass test }
  other:
    - "clicks: 100 synthetic 0.5-3 ms clicks all caught, 0 false repairs on a snare at Threshold 55 %"
    - "noise: -50 dBFS pink reduced 12 +/- 1 dB in gaps, no musical noise above -60 dBFS at Smooth 40 %"
    - "reverb: 1.2 s RT60 reads <= 0.6 s at Amount 50 %, onsets within 1 dB at Attacks 60 %"
    - "latency: reported equals measured in both states"
open_questions: []
```

## Amendments
- 2026-11-01: Owner decisions confirmed with the brief: four modules; Removed listen is global only at every tier; accent ember (coral belongs to Sunday Organ). LookAndFeel, meters and the FFT/analysis helpers come from the shared Source/oberli/ code (bob-skills).
