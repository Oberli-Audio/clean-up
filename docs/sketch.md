# Clean Up - declick, dehum, denoise, de-reverb (Tier S sketch)

Tier S, gate G0-G2 sketch. Oberli Audio effect, Bone theme, accent Sage #33B679 (mix tools, category scheme confirmed 2026-11-01). Static frame: `clean-up@1x.png` (1000 x 604 at 100 %), `clean-up@2x.png` for Retina viewing. Sound side: sound-design-bob is needed for four estimators (adaptive notch comb, AR click detector and interpolator, spectral noise gain, late-reverb envelope); this sketch states what each must do and the evidence that proves it.

## 1. G0 brief

**Users.** Björn cleaning church recordings and live-stream feeds: mains hum from a stage box, clicks from a bad cable or a clock mismatch, the hiss of a cheap wireless receiver, and a room that is too live for a close-miked vocal. Friends who get the build.

**Why it is a gap.** Free VST3 restoration ends at Bertom Denoiser (noise only). Declick, dehum and de-reverb are iZotope RX, Acon DeVerberate, Waves Clarity, all paid; Ableton has nothing in any edition. The paid references are RX 12 (De-click, De-hum, Spectral De-noise, Dialogue De-reverb), Acon Restoration Suite, Accentize dxRevive.

**Core jobs.**
1. Make a flawed take usable in two minutes: switch on the module that matches the flaw, turn one knob, done.
2. See what was taken, not only hear it: the removed energy drawn on the input sonogram, plus Removed listen.
3. Never damage what is fine: each module is nullable when off or at zero, attacks survive de-reverb, speech survives denoise.
4. Run on a live-stream vocal with acceptable latency (one STFT frame) and leave the rest of the chain alone.

**Context.** On a track, early in the chain (before compression, which would raise the flaws). Used on recorded material mostly, in the live mix for hum and noise only. Window open while dialing, then closed.

**Success.** A 50 Hz hum with 8 harmonics at -40 dBFS vanishes to below -90 dBFS with no audible notch on a bass guitar; 100 synthetic clicks of 0.5-3 ms are all caught with none missed and no false repair on a snare hit; -50 dBFS pink noise is reduced 12 dB on a vocal with no musical-noise warble; a 1.2 s RT60 vocal reads as a 0.5 s room at Amount 50 % with the consonants intact; every module nulls when off.

**The five core controls.** Depth (Hum), Threshold (Click), Reduction (Noise), Amount (Reverb), Listen. The 64 px knob of each module is its one knob.

**CPU and latency budget.** All four modules on: 2.5 % on an M1 at 48 kHz, 128 samples. Latency: one STFT hop plus the click lookahead, 43 ms at 48 kHz with the 2048 frame, reported; Hum alone (time domain) is zero latency, so a "Hum only" state reports 0 and the readme says so.

**Four structural decisions (sound side).**
1. Hum is time domain, the rest is one shared STFT. The hum comb is a bank of adaptive second-order notches (fundamental plus N harmonics, Width in Hz) with a frequency tracker (PLL on the fundamental, ±0.5 Hz, so mains drift is followed); zero latency, no spectral smearing. Click, Noise and Reverb share one STFT (2048, 4x overlap, Hann) so their latency is paid once.
2. Clicks are detected by prediction error, repaired by interpolation. A short-order AR model (order 32, updated every 10 ms) predicts each sample; where the error exceeds Threshold times the local error RMS for 1 to Length ms, the span is replaced by AR interpolation from both sides (the RX approach). Crackle mode lowers the order and shortens Length for dense vinyl-style crackle.
3. Noise is Wiener gain with a decision-directed a-priori SNR. Learned mode uses a captured profile (1 s of noise only); Adaptive tracks the floor with minimum statistics. Smooth sets the gain floor's time smoothing so musical noise does not appear; Floor shows the estimate and lets the user override it.
4. Reverb is late-tail suppression, attack-preserving. The late reverberation power is estimated from the past STFT frames with an exponential decay model whose time constant is Tail (RT60); a per-bin gain subtracts it (spectral subtraction with a floor), and the transient detector (spectral flux) holds the gain at 1 on attacks for the Attacks percentage of their length. Estimate sets Tail from the decay of the last 4 s.

## 2. G1 design plan (five lines)

1. **Window** 1000 x 604 at 100 %, Bone; four modules side by side in signal-flow order, each 196 px, one on/off pill in its title row; one sonogram well.
2. **Hero** is what the ear cannot judge: the input sonogram with everything Clean Up removed drawn over it in the accent (hum lines, click ticks, reverb-tail patches, the noise floor as a tint), with a Listen segment Output / Removed / Input above it, and the four activity readouts under it in words ("7 clicks in 6 s · longest 1.8 ms · 0 missed").
3. **Accent** Sage on the set and active only: value arcs and pointers, lit module LEDs, selected segments, and the removed energy on the sonogram, since that is the plugin's action. The meters are ink.
4. **Sections** from the table's groups: Hum, Click, Noise, Reverb, the Removed display (no parameters), Output (Trim 64 px, In and Out meters; no Mix knob, utility without a wet path, the A B see line for the brand sheet).
5. **States**: modified (pill dims), drawer, About (charcoal page), bypass, module off (its knobs dim to `ink-subtle` arcs, the pill LED unlit, its overlay disappears from the sonogram), Learn capturing (1 s hairline progress under the Learn button, then the pill reads Learned), Find and Estimate running (same hairline, 200 ms), Removed listen (header pill shows "Listening: Removed" in `ink-subtle`, the sonogram shows the removed energy alone), Hum only (header meta "0 ms" instead of 43 ms).

## 3. Parameter table (sketch, six columns)

| id | type | name | group | unit / choices | min / max / default |
|---|---|---|---|---|---|
| humOn | bool | Hum | Hum | - | 0 / 1 / 0 |
| humDepth | float | Depth | Hum | dB | -60 / 0 / -24 |
| humHarmonics | int | Harmonics | Hum | - | 1 / 16 / 8 |
| humWidth | float | Width | Hum | Hz | 0.5 / 10 / 2 |
| humFreq | float | Frequency | Hum | Hz, center 55 | 40 / 70 / 50 |
| clickOn | bool | Click | Click | - | 0 / 1 / 0 |
| clickThreshold | float | Threshold | Click | % | 0 / 100 / 55 |
| clickLength | float | Length | Click | ms | 0.2 / 10 / 2.5 |
| clickCrackle | float | Crackle | Click | % | 0 / 100 / 0 |
| clickMode | choice | Mode | Click | Clicks \| Crackle | 0 / 1 / 0 |
| noiseOn | bool | Noise | Noise | - | 0 / 1 / 0 |
| noiseReduction | float | Reduction | Noise | dB | -30 / 0 / -12 |
| noiseSmooth | float | Smooth | Noise | % | 0 / 100 / 40 |
| noiseFloor | float | Floor | Noise | dB | -90 / -20 / -60 |
| noiseMode | choice | Profile | Noise | Learned \| Adaptive | 0 / 1 / 1 |
| reverbOn | bool | Reverb | Reverb | - | 0 / 1 / 0 |
| reverbAmount | float | Amount | Reverb | % | 0 / 100 / 35 |
| reverbTail | float | Tail | Reverb | s, center 1.0 | 0.2 / 4 / 0.9 |
| reverbAttacks | float | Attacks | Reverb | % | 0 / 100 / 60 |
| listen | choice | Listen | Output | Output \| Removed \| Input | 0 / 2 / 0 |
| trim | float | Trim | Output | dB, bipolar | -24 / +24 / 0 |
| bypass | bool | Bypass | - | - | 0 / 1 / 0 |

22 parameters, all within Live 10.1's 32. Find, Learn and Estimate are editor actions that write parameters (humFreq; the noise profile is state, not a parameter; reverbTail) through begin/perform/end edit. Every module defaults to off so an inserted Clean Up is a wire.

Tooltips (one sentence; the generator appends range and default):
- Depth: "How deep the notches cut at the hum's fundamental and harmonics."
- Harmonics: "How many multiples of the mains frequency are notched; buzz needs more than hum."
- Width: "How wide each notch is; wider follows unstable mains, narrower spares the bass."
- Frequency: "The mains fundamental; Find measures it and tracking follows drift."
- Threshold: "How unusual a sample must be to count as a click; lower catches more, also drum hits."
- Length: "The longest span that is repaired as one click."
- Crackle: "Adds repair of dense tiny clicks, like a worn record."
- Reduction: "How much of the noise floor is taken away."
- Smooth: "Slower gain changes avoid watery artifacts at the cost of some noise between words."
- Floor: "The noise level Clean Up assumes; Learn or Adaptive set it, you can override."
- Amount: "How much of the room's tail is removed."
- Tail: "How long the room rings; Estimate measures it."
- Attacks: "How much of each attack is kept untouched so consonants and hits stay sharp."
- Listen: "Removed plays only what Clean Up took away."

## 4. Approach and best practice

### 4.1 Signal path
```
in ─► Hum (adaptive notch comb, time domain, 0 latency)
    ─► STFT 2048/4x ─► Click (AR detect + interpolate, in the time domain on the frame's hop with lookahead)
                    ─► Noise (Wiener gain per bin)
                    ─► Reverb (late-tail subtraction per bin, attack hold)
    ─► iSTFT ─► Trim ─► out
Listen Removed = in (delayed by the latency) minus out
```
- Module order is fixed and is the right order: hum first because it would bias the noise profile and the click detector; clicks before noise so the detector sees the raw error; reverb last because it works on what is left.
- Off modules are not "at zero", they are bypassed in code, so the null test is exact.
- When only Hum is on, the STFT is skipped and the plugin reports 0 latency; turning on any spectral module changes the reported latency once (`setLatencySamples`), and the header meta shows it.

### 4.2 Hum
- Find: 2 s FFT, picks the strongest peak in 45-65 Hz (and 100-130 Hz, halved) and sets Frequency; tracking then runs a PLL on the fundamental, ±0.5 Hz, time constant 2 s; harmonics follow the tracked fundamental exactly.
- Notches are second-order with Width as the -3 dB bandwidth; Depth limits the cut so a bass note on a harmonic loses at most Depth dB; the comb is bypassed below -60 dB Depth.

### 4.3 Click
- Detector: AR(32) by Burg on 10 ms blocks, prediction error normalized by its local RMS (50 ms); a click starts when the normalized error exceeds the threshold (Threshold maps 0-100 % to 12-3 sigma) and ends after at most Length ms; two clicks closer than 1 ms merge.
- Repair: least-squares AR interpolation across the span using 64 samples on each side; a crossfade of 8 samples at the edges.
- Crackle: blends in a second detector with AR(8) and Length clamped to 0.5 ms, weighted by the Crackle percentage.
- Counter: caught clicks in the last 6 s, the longest, and "missed" from a second pass on the output with a lower threshold (what the user would still hear), so the readout is honest.

### 4.4 Noise
- Learned: Learn captures 1 s, the profile is the mean power per bin; stored in plugin state (2048 floats).
- Adaptive: minimum statistics over 1.5 s windows, per bin; Floor shows the broadband estimate and an override shifts the profile.
- Gain: decision-directed Wiener with the a-priori SNR smoothing set by Smooth (0.5 to 0.98); gain floor from Reduction so the noise is reduced, not removed, which is what keeps it natural.

### 4.5 Reverb
- Estimate: the decay slope of the band energy after the last transient over 4 s, fitted to an exponential; Tail = the RT60 it implies, clamped 0.2-4 s.
- Late power estimate per bin: sum of past frames' power weighted by exp(-t / Tail) beyond 50 ms; gain = max(1 - Amount * late / current, floor), smoothed over 2 frames.
- Attacks: spectral flux above a running mean marks an onset; for Attacks percent of the following 40 ms the gain is held at 1 (0 % = no protection, 100 % = the whole 40 ms).

### 4.6 The Removed display
- Input sonogram of the last 6 s (1/6-octave bands, 50 Hz to 10 kHz log, 100 ms columns) in ink tints on the sunken well; the removed energy (in minus out, same analysis) drawn over it in the accent at opacity proportional to dB removed; hum shows as lines, clicks as ticks, reverb as patches after notes, noise as a faint tint.
- Listen switches what the output is; the sonogram always shows the input with the overlay, except in Removed listen where it shows the removed energy alone.
- Data from a lock-free FIFO; 30 Hz, stopped when the transport stands still.

### 4.7 Hosts and quirks
- Latency change when a spectral module is first turned on: the manual says to switch the modules on before recording automation.
- 22 parameters, visible in Live 10.1's panel; the four On switches are first in each group so they land in the panel's first rows.
- Learn captures from the input while the transport runs; if the input is above -40 dBFS during capture, the button reads "Too loud for a noise profile" for 3 s and nothing is stored.
- Live on Windows auto-scale note (ship-bob).

### 4.8 Deliberately not in it
- No spectral repair canvas (paint out a cough): that is an editor, not a plugin.
- No machine-learned speech model (dxRevive class): the four estimators are explainable and tunable by ear.
- No per-module Mix: Amount, Reduction and Depth are the amount.
- No per-module listen: Removed is global and plays everything Clean Up took away; to hear one module's removal, switch the others off (decided 2026-11-01).

## 5. Manual outline
1. One paragraph, the module order and the sentence "Hum alone is zero latency; any other module adds 43 ms, reported to Live."
2. Two-minute setup per flaw: hum (Find), clicks (watch the counter), noise (Learn or Adaptive), room (Estimate, then Amount).
3. Reading the Removed display and using Removed listen.
4. Keeping it natural: Smooth, Attacks, Depth.
5. Parameters (generated).
6. Troubleshooting: watery vocal (raise Smooth, lower Reduction), snare hits repaired as clicks (raise Threshold or shorten Length), hum returns after a minute (tracking lost it; press Find), dull consonants (raise Attacks).

## 6. Acceptance tests for promotion to P
1. Null: all modules off, any Listen Output: output nulls to the input after host compensation; Hum only reports 0 ms.
2. Hum: 50 Hz plus 8 harmonics at -40 dBFS on a bass line go below -90 dBFS; the bass note at 100 Hz loses at most Depth dB.
3. Clicks: 100 synthetic clicks of 0.5-3 ms in a vocal, all caught, 0 false repairs on a snare track at Threshold 55 %.
4. Noise: -50 dBFS pink noise reduced by 12 ± 1 dB in the gaps; no musical noise above -60 dBFS at Smooth 40 %.
5. Reverb: a 1.2 s RT60 convolution on a dry vocal reads as RT60 0.6 s or less at Amount 50 %; consonant onsets within 1 dB of the dry at Attacks 60 %.
6. Latency: reported equals measured in both states.
7. CPU: under 2.5 % all on, under 0.3 % Hum only.

## 7. Open decisions for Björn
- Decided 2026-11-01: name Clean Up (slug `clean-up`, plugin ID `CleanUp`); four modules (Hum, Click, Noise, Reverb); Removed listen is global only, at every tier, no per-module listen.
- Accent: Sage #33B679, by the category scheme (decided 2026-11-01): one accent per category, mix tools.

## 8. Report
```
Tier: S, gate: G0-G2 sketch
Hosts: n/a at S
Brand sheet: deviates: output column without Mix knob (utility without wet path, the A B see line); module on/off as a small pill in the section title row (a new placement for a toggle, line to add if kept); logo is a CSS stand-in
What works well: one knob per module is the whole job; the Removed overlay makes the plugin's action visible, not implied; fixed module order avoids the RX "which first" question; off is bypassed, so the null is exact
Findings: none at S
Open / recommended: none
Evidence: clean-up@1x.png at 100 %, clean-up@2x.png
```
