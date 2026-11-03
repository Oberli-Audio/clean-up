#!/usr/bin/env python3
"""Clean Up's test suite - the project's copy of the dsp-kit scaffold (test_template.py), filled in.

Drives the offline renderer (harness-contract.md v3, `CleanUpHarness`) and asserts on its JSON
and WAVs with dspkit. The test material is the prototype's (`sound design/prototype/material.py`:
a vocal and a bass line with injected hum, clicks, pink noise and a room), written to WAV and
fed with --in, so the port is judged on what G3 measured.

    HARNESS=build/CleanUpHarness_artefacts/Release/CleanUpHarness python3 tools/tests/test_plugin.py --label fast
    ... --label render

Labels (D.3.1): fast = contract, rate/block matrix, health, properties, the brief's must-dos
(every build, < 60 s); render = the defining features and the brief's quality targets on the
port (every commit). Every test is a rule, a must-do or a defining feature; the name says which.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("DSPKIT", str(ROOT / "scripts" / "dsp-kit")))
sys.path.insert(0, str(ROOT / "sound design" / "prototype"))
import dspkit as K  # noqa: E402
import material as M  # noqa: E402
import paramgen  # noqa: E402

HARNESS = os.environ.get("HARNESS", str(ROOT / "build/CleanUpHarness_artefacts/Release/CleanUpHarness"))
GOLDEN_DIR = Path(os.environ.get("GOLDEN_DIR", str(ROOT / "tools/tests/golden")))
DEFAULT = dict(seed=1, sample_rate=48000, block=512, seconds=2.0)
SOURCE = dict(signal="noise:pink:-30")
RATES = (44100, 48000, 88200, 96000, 176400, 192000)
BLOCKS = (1, 13, 32, 64, 512, 4096)   # zero-length blocks: test_random_block_sizes_from_zero (a render of only 0s never advances)
FAST_BUDGET_S = float(os.environ.get("FAST_BUDGET_S", "20"))
GOLDEN_PEAK_DB = {"same": -140.0, "cross-feedforward": -100.0, "cross-feedback": -80.0}
FS = 48000
TABLE = {r["id"]: r for r in paramgen.read_table(ROOT / "parameters.csv")}


def norm(pid, plain):
    """Plain units -> the normalised value --param takes (the table's range and centre)."""
    r = TABLE[pid]
    if r["choices"]:
        return plain / (len(r["choices"].split("|")) - 1)
    return paramgen.to_normalised(r, plain)


ALL_FOUR = {"humOn": 1, "clickOn": 1, "noiseOn": 1, "reverbOn": 1}   # the brief's CPU preset
PARAM = ("trim", round(norm("trim", 4.8), 6))                          # a real ID, not the default


def run(params=None, **flags):
    f = dict(DEFAULT, **SOURCE)
    f.update(flags)
    if "in_" in f:
        f.pop("signal", None)
        f["in"] = f.pop("in_")
    res = K.render(HARNESS, params, **f)
    echo = {k: v for k, v in f.items() if k in ("seed", "sample_rate", "block", "seconds", "preset")
            and not (k == "block" and str(v).startswith("random:"))}
    K.assert_echo(res, params, **echo)                                     # rule 13
    return res


_TMP = tempfile.TemporaryDirectory()


@lru_cache(maxsize=None)
def wav(name):
    """The prototype's test material, written once per run."""
    seconds = 6.0
    clean = M.vocal(FS, seconds)
    if name == "vocal":
        x = clean
    elif name == "hum-bass":
        x, _ = M.add_hum(M.bass(FS, seconds), FS, f0=50.0, harmonics=8, dbfs=-40.0)
    elif name == "clicks":
        x, _ = M.add_clicks(clean, FS, count=100, min_ms=0.5, max_ms=3.0, amp=0.5, seed=6)
    elif name == "pink-vocal":
        x, _ = M.add_pink(clean, FS, dbfs=-50.0, seed=4)
    elif name == "room":
        x = M.convolve_room(np.vstack([clean, np.zeros((2 * FS, 2))]),
                            M.reverb_ir(FS, rt60=1.2, predelay_s=0.008, drr_db=0.0, seed=7))
    elif name == "snare":
        x = M.snare(FS, seconds)
    elif name == "noise-lead":
        lead = np.stack([M.pink(FS, int(1.5 * FS), -50.0, seed=4)] * 2, axis=1)
        pv, _ = M.add_pink(clean, FS, dbfs=-50.0, seed=4)
        x = np.vstack([lead, pv])
    else:
        raise KeyError(name)
    path = Path(_TMP.name) / (name + ".wav")
    K.write_wav(str(path), np.asarray(x, dtype=np.float32), FS)
    return str(path)


def seconds_of(path):
    x, fs = K.read_wav(path)
    return x.shape[0] / fs


def render_file(name, params, **flags):
    """Renders a material file; returns (input, output, result)."""
    src = wav(name)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.wav"
        res = run(params, in_=src, out=out, seconds=seconds_of(src), **flags)
        y, _ = K.read_wav(str(out))
    x, _ = K.read_wav(src)
    return x, y, res


class Timed(unittest.TestCase):
    label = "fast"

    def setUp(self):
        self._t0 = time.time()

    def tearDown(self):
        dt = time.time() - self._t0
        print("  [%s %.1f s]" % (self.label, dt), end="", flush=True)
        if self.label == "fast" and dt > FAST_BUDGET_S:
            self.fail("fast test took %.0f s; budget %.0f s (D.3.6: move it to a slower tier, do not delete it)" % (dt, FAST_BUDGET_S))


class Contract(Timed):
    def test_harness_echoes_params(self):                                  # rule 13
        pid, val = PARAM
        res = run({pid: val})
        self.assertAlmostEqual(res["applied"]["params"][pid], val, places=6)

    def test_seeded_runs_are_bit_identical(self):                          # rule 8
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.wav", Path(d) / "b.wav"
            run(ALL_FOUR, out=a)
            run(ALL_FOUR, out=b)
            xa, _ = K.read_wav(a)
            xb, _ = K.read_wav(b)
            self.assertTrue((xa == xb).all(), "two seeded renders differ")


class RateAndBlock(Timed):
    def test_rate_block_matrix_is_clean(self):                             # DoD: 42 combinations, all four on
        for fs in RATES:
            for blk in BLOCKS:
                with self.subTest(fs=fs, block=blk):
                    res = run(ALL_FOUR, sample_rate=fs, block=blk, seconds=0.25)
                    self.assertEqual(res["health"]["nan"] + res["health"]["inf"], 0)
                    self.assertLess(res["levels"]["peak_dbfs"], 0.0)

    def test_random_block_sizes_from_zero(self):                           # D.5.1, fuzz
        res = run(ALL_FOUR, block="random:7", max_block=1024, seconds=0.5)
        self.assertEqual(res["health"]["nan"], 0)

    def test_block_larger_than_announced(self):                            # D.5.1
        # chunked inside the engine: the oversized render must equal the announced-size one
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "ref.wav", Path(d) / "big.wav"
            run(ALL_FOUR, block=256, max_block=256, seconds=0.5, out=a)
            res = run(ALL_FOUR, block=1024, max_block=256, seconds=0.5, out=b)
            self.assertEqual(res["health"]["nan"], 0)
            xa, fs = K.read_wav(a)
            xb, _ = K.read_wav(b)
            self.assertLess(K.dropout_db(xa, xb, fs), 3.0, "an oversized block rendered quieter than its announced-size twin")


class Health(Timed):
    def test_silence_has_no_denormal_storm_or_dc(self):                    # DoD: 60 s of silence, all four on
        res = run(ALL_FOUR, signal="silence", seconds=10.0, profile=1, block=64, warmup=200)
        self.assertEqual(res["health"]["nan"] + res["health"]["inf"], 0)
        self.assertLess(res["levels"]["dc_dbfs"], -80.0)
        self.assertLess(res["profile"]["p999_pct"], 25.0)                  # rule 20: p99.9 judged
        print("over_deadline (reported, not judged, rule 20):", res["profile"]["over_deadline"], end=" ")

    def test_latency_matches_impulse(self):                                # rule 7, must-do: one fixed latency
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "imp.wav"
            # Click and Noise at Reduction 0 dB: the engine runs and passes the impulse through
            res = run({"clickOn": 1, "noiseOn": 1, "noiseReduction": norm("noiseReduction", 0.0)},
                      signal="impulse", out=out)
            x, fs = K.read_wav(out)
            ref = x[:, :1] * 0.0
            ref[0, 0] = 0.5
            self.assertEqual(K.latency_samples(ref, x[:, :1]), res["applied"]["latency_samples"])
            self.assertEqual(res["applied"]["latency_samples"], 2624)      # frame + lookahead at 48 kHz

    def test_hum_alone_is_zero_latency(self):                              # must-do
        res = run({"humOn": 1}, signal="impulse")
        self.assertEqual(res["applied"]["latency_samples"], 0)
        self.assertEqual(res["product"]["latency_state"], 0)


class Properties(Timed):
    def test_state_round_trip_is_bytewise(self):                           # D.5.3
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pid, val = PARAM
            run({pid: val}, state_out=d / "a.state", out=d / "a.wav", seconds=0.5)
            rb = run(state_in=d / "a.state", state_out=d / "b.state", out=d / "b.wav", seconds=0.5)
            self.assertEqual((d / "a.state").read_bytes(), (d / "b.state").read_bytes())
            self.assertAlmostEqual(rb["applied"]["params"][pid], val, places=6)
            xa, _ = K.read_wav(d / "a.wav")
            xb, _ = K.read_wav(d / "b.wav")
            self.assertTrue((xa == xb).all())

    def test_learned_profile_is_plugin_state(self):                        # parameters.csv: "Profile is plugin state"
        learned = {"noiseOn": 1, "noiseMode": norm("noiseMode", 0)}
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src = wav("noise-lead")
            run(learned, in_=src, seconds=seconds_of(src), learn_at=0.1, state_out=d / "a.state")
            self.assertIn(b"NoiseProfile", (d / "a.state").read_bytes(), "the Learned profile is not saved")
            # a new instance, the state loaded, no Learn: the profile is there and does its work
            res = run(learned, in_=wav("pink-vocal"), seconds=6.0, state_in=d / "a.state", state_out=d / "b.state")
            self.assertTrue(res["product"]["noise_profile_captured"], "the saved profile did not load")
            self.assertEqual((d / "a.state").read_bytes(), (d / "b.state").read_bytes(), "load and save changed it")
            # at another rate it is mapped onto that rate's bins
            res96 = run(learned, signal="noise:pink:-50", sample_rate=96000, seconds=1.0, state_in=d / "a.state")
            self.assertTrue(res96["product"]["noise_profile_captured"])
            self.assertEqual(res96["health"]["nan"] + res96["health"]["inf"], 0)

    def test_corrupted_state_does_not_crash(self):                         # D.5.3, fuzz
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            run(state_out=d / "good.state", seconds=0.25)
            good = (d / "good.state").read_bytes()
            cases = {"empty": b"", "truncated": good[: len(good) // 2], "garbage": bytes(range(256)) * 4,
                     "flipped": bytes(b ^ 0x55 for b in good)}
            for name, blob in cases.items():
                with self.subTest(case=name):
                    (d / "bad.state").write_bytes(blob)
                    try:
                        res = K.render(HARNESS, state_in=d / "bad.state", seconds=0.25,
                                       **{k: v for k, v in DEFAULT.items() if k != "seconds"}, **SOURCE)
                    except RuntimeError as e:
                        self.assertNotIn("Segmentation", str(e))
                        self.assertNotIn("-11", str(e).split(")")[0])
                        continue
                    self.assertEqual(res["health"]["nan"], 0)


class Switches(Timed):
    def test_switches_are_click_free(self):                                # rules 2 and 7
        # a 50 Hz sine on the first notch: thrown hard, each switch read -2.6 dB, crossfaded
        # it reads the sine's own largest step (-43.7 dB)
        hum = {"humDepth": norm("humDepth", -60.0)}
        cases = {"Hum off": dict(hum, automate="humOn:0=1,1.0=1,1.0001=0"),
                 "Listen to Removed": dict(hum, humOn=1, automate="listen:0=0,1.0=0,1.0001=%g" % norm("listen", 1)),
                 "Bypass on": dict(hum, humOn=1, automate="bypass:0=0,1.0=0,1.0001=1")}
        for name, spec in cases.items():
            with self.subTest(switch=name):
                spec = dict(spec)
                automate = spec.pop("automate")
                res = run(spec, signal="sine:50:-12", seconds=2.0, automate=automate)
                self.assertLess(res["health"]["max_click_db"], -20.0, "%s clicks" % name)


class MustDo(Timed):
    """The brief's must_do lines, on the port."""

    def test_all_modules_off_nulls_exactly(self):
        x, y, res = render_file("vocal", None)
        self.assertEqual(res["applied"]["latency_samples"], 0)
        self.assertTrue((x.astype(np.float32) == y.astype(np.float32)).all(), "all off is not a wire")

    def test_bypass_is_a_latency_compensated_wire(self):                   # rule 7
        x, y, res = render_file("vocal", dict(ALL_FOUR, bypass=1))
        lat = res["applied"]["latency_samples"]
        self.assertEqual(lat, 2624)
        self.assertTrue((y[lat:] == x[: x.shape[0] - lat]).all(), "bypass is not the delayed input")

    def test_removed_listen_plus_output_is_input(self):                    # must-do: Removed listen
        _, yo, res = render_file("pink-vocal", ALL_FOUR)
        _, yr, _ = render_file("pink-vocal", dict(ALL_FOUR, listen=norm("listen", 1)))
        _, yi, _ = render_file("pink-vocal", dict(ALL_FOUR, listen=norm("listen", 2)))
        self.assertLess(K.peak_dbfs(yo + yr - yi), -120.0)
        self.assertGreater(K.rms_dbfs(yr), -80.0, "Removed is silent")

    def test_find_measures_the_mains(self):                                # must-do: Find
        _, _, res = render_file("hum-bass", {"humOn": 1}, find=1)
        self.assertAlmostEqual(res["product"]["find_hz"], 50.0, delta=0.3)

    def test_learn_captures_a_profile(self):                               # must-do: Learn
        _, _, res = render_file("noise-lead", {"noiseOn": 1, "noiseMode": norm("noiseMode", 0)}, learn_at=0.1)
        self.assertTrue(res["product"]["noise_profile_captured"])

    def test_estimate_measures_the_tail(self):                             # must-do: Estimate
        _, _, res = render_file("room", {"reverbOn": 1}, estimate=1)
        self.assertAlmostEqual(res["product"]["estimate_s"], 1.2, delta=0.4)


class Goldens(Timed):
    """F.13.6: Tier P keeps one native golden at a stated tolerance."""
    label = "render"

    def test_goldens_match(self):
        sidecars = sorted(GOLDEN_DIR.glob("*.json")) if GOLDEN_DIR.exists() else []
        if not sidecars:
            self.skipTest("no goldens in %s yet (rendered at G6, after the Reverb decision)" % GOLDEN_DIR)
        for sc in sidecars:
            meta = json.loads(sc.read_text())
            with self.subTest(golden=sc.stem), tempfile.TemporaryDirectory() as d:
                out = Path(d) / "now.wav"
                flags = dict(meta["flags"])
                flags["out"] = out
                res = K.render(HARNESS, meta.get("params"), **flags)
                arch = res["applied"].get("build", {}).get("arch")
                kind = "same" if arch == meta.get("arch") else ("cross-feedback" if meta.get("feedback") else "cross-feedforward")
                now, fs = K.read_wav(out)
                gold, _ = K.read_wav(sc.with_suffix(".wav"))
                r = K.null_residual(gold, now, align=False)
                self.assertLess(r["peak_dbfs"], GOLDEN_PEAK_DB[kind],
                                "%s: residual against the golden (%s) - regenerate only with a changelog line (D.3.5)" % (sc.stem, kind))


class DefiningFeatures(Timed):
    """Rule 13: one presence test per defining feature in the brief, each shown failing on a
    build without the feature (D.3.8; docs/status.md names the build)."""
    label = "render"

    def test_removed_display_has_data_and_is_empty_when_off(self):
        _, _, on = render_file("pink-vocal", {"noiseOn": 1})
        _, _, off = render_file("pink-vocal", None)
        self.assertGreater(on["product"]["removed_total"], 0.0)
        self.assertEqual(off["product"]["removed_total"], 0.0)
        bands = np.array(on["product"]["removed_bands"])
        self.assertGreater(int((bands > 0).sum()), 40, "the noise tint covers the whole display")

    def test_click_counter_reports_missed_from_a_second_pass(self):
        # at Threshold 0 % (40 sigma) the quieter clicks pass the first pass and the honest
        # second pass, one sigma lower over the output, still finds some of them
        _, _, res = render_file("clicks", {"clickOn": 1, "clickThreshold": norm("clickThreshold", 0.0)})
        self.assertGreater(res["product"]["clicks_missed"], 0)
        self.assertGreater(res["product"]["clicks_caught"], 0)

    def test_attack_hold_keeps_consonants(self):
        def onset_change(attacks):
            x, y, res = render_file("room", {"reverbOn": 1, "reverbAmount": norm("reverbAmount", 50.0),
                                             "reverbTail": norm("reverbTail", 1.2),
                                             "reverbAttacks": norm("reverbAttacks", attacks)})
            lat = res["applied"]["latency_samples"]
            out = y[lat:]
            worst = 0.0
            for i in range(4):
                a = int((0.08 + i * 0.25) * 6.0 * FS)
                b = a + int(0.020 * FS)
                worst = max(worst, abs(K.peak_dbfs(x[a:b]) - K.peak_dbfs(out[a:b])))
            return worst
        held, unheld = onset_change(60.0), onset_change(0.0)
        self.assertLessEqual(held, 1.0, "onsets move more than 1 dB at Attacks 60 %")
        self.assertLess(held, unheld, "Attacks does not protect the onsets")


class Targets(Timed):
    """The brief's quality targets, measured on the port (G3 measured them on the prototype)."""
    label = "render"

    def test_hum_stack_goes_below_minus_90(self):
        # the brief's 50 Hz + 8 harmonics at -40 dBFS, alone through the comb at Depth -60 dB;
        # judged after the tracker's 1 s warm-up and the 2 s lock
        hum_only, _ = M.add_hum(np.zeros((6 * FS, 2)), FS, f0=50.0, harmonics=8, dbfs=-40.0)
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "hum.wav", Path(d) / "out.wav"
            K.write_wav(str(src), hum_only.astype(np.float32), FS)
            run({"humOn": 1, "humDepth": norm("humDepth", -60.0)}, in_=str(src), out=out, seconds=6.0)
            yh, _ = K.read_wav(str(out))
        self.assertLess(K.rms_dbfs(yh[3 * FS:]), -90.0)

    def test_clicks_caught_and_snare_left_alone(self):
        _, _, res = render_file("clicks", {"clickOn": 1, "clickLength": norm("clickLength", 3.5)})
        self.assertGreaterEqual(res["product"]["clicks_caught"], 95)    # EX-1: 97 on the prototype
        _, _, sn = render_file("snare", {"clickOn": 1})
        self.assertEqual(sn["product"]["clicks_caught"], 0)

    def test_noise_reduced_12_db_in_the_gaps(self):
        x, y, res = render_file("pink-vocal", {"noiseOn": 1})
        lat = res["applied"]["latency_samples"]
        out = y[lat:]
        m = np.zeros(out.shape[0], dtype=bool)
        for i in range(4):
            a = int((0.08 + i * 0.25) * 6.0 * FS) + int(0.19 * 6.0 * FS)
            b = int(min(out.shape[0], (0.08 + (i + 1) * 0.25) * 6.0 * FS) - 0.02 * FS)
            if b > a:
                m[a:b] = True
        red = K.rms_dbfs(x[: out.shape[0]][m]) - K.rms_dbfs(out[m])
        self.assertAlmostEqual(red, 12.0, delta=1.0)


if __name__ == "__main__":
    label = None
    if "--label" in sys.argv:
        i = sys.argv.index("--label")
        label = sys.argv[i + 1]
        del sys.argv[i:i + 2]
    if label:
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for cls in (Contract, RateAndBlock, Health, Properties, Switches, MustDo, Goldens, DefiningFeatures, Targets):
            if cls.label == label:
                suite.addTests(loader.loadTestsFromTestCase(cls))
        t0 = time.time()
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        dt = time.time() - t0
        print("label %s: %.0f s" % (label, dt))
        sys.exit(0 if result.wasSuccessful() and (label != "fast" or dt < 3.0 * FAST_BUDGET_S) else 1)
    unittest.main(verbosity=2)
