#!/usr/bin/env python3
"""G5: the C++ port (CleanUpHarness) nulled against this prototype, per module and all four.

Same material in, the same plain parameter values (the harness echoes what it applied, and
the prototype renders exactly those), the same block size; the residual's peak and RMS over
the whole render, absolute dBFS, **no alignment** (a latency difference must fail). The F.8
targets (dsp-foundations.md, the only statement of them):

    hum         double, recursive state                        peak < -120 dBFS
    spectral    the prototype's FFT is double, the port's float  peak < -90 dBFS ("different precision")
    click       a repair decision flipped by rounding is a local residual: characterised, not passed

    python3 "sound design/prototype/g5_null.py"                 # all cases
    python3 "sound design/prototype/g5_null.py" hum noise       # some
    HARNESS=build/.../CleanUpHarness python3 ...                # another build
"""
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "dsp-kit"))
import cleanup_proto as P  # noqa: E402
import dspkit as K  # noqa: E402
import material as M  # noqa: E402
import paramgen  # noqa: E402

TABLE = {r["id"]: r for r in paramgen.read_table(ROOT / "parameters.csv")}

HARNESS = os.environ.get("HARNESS", str(ROOT / "build/CleanUpHarness_artefacts/Release/CleanUpHarness"))
FS, BLOCK, SECONDS = 48000, 512, 6.0
SPECTRAL_PEAK_DB, HUM_PEAK_DB = -90.0, -120.0


def material(case):
    if case == "hum":
        x, _ = M.add_hum(M.bass(FS, SECONDS), FS, f0=50.0, harmonics=8, dbfs=-40.0)
        return x
    clean = M.vocal(FS, SECONDS)
    if case == "click-clean":
        return clean
    if case == "click":
        x, _ = M.add_clicks(clean, FS, count=100, min_ms=0.5, max_ms=3.0, amp=0.5, seed=6)
        return x
    if case == "noise":
        x, _ = M.add_pink(clean, FS, dbfs=-50.0, seed=4)
        return x
    if case == "reverb":
        return M.convolve_room(clean, M.reverb_ir(FS, rt60=1.2, predelay_s=0.008, drr_db=0.0, seed=7))
    # all four: the room, then the electrical flaws (measure.py all-four)
    ref = M.convolve_room(clean, M.reverb_ir(FS, rt60=1.0, drr_db=3.0, seed=7))
    x, _ = M.add_hum(ref, FS, f0=50.0, harmonics=8, dbfs=-45.0)
    x, _ = M.add_pink(x, FS, dbfs=-55.0, seed=4)
    x, _ = M.add_clicks(x, FS, count=30, min_ms=0.5, max_ms=2.0, amp=0.35, seed=12)
    return x


SWITCHES = {"hum": ["humOn"], "click": ["clickOn"], "click-clean": ["clickOn"], "noise": ["noiseOn"],
            "reverb": ["reverbOn"], "all-four": ["humOn", "clickOn", "noiseOn", "reverbOn"]}
# plain values beyond the switches; click-clean is the false detection at the note change whose
# AR(192) extrapolation runs away (the fallback ladder, docs/failures.md)
EXTRA = {"click-clean": {"clickLength": 3.5}}


def run_case(case):
    x = np.asarray(material(case), dtype=np.float64)
    x32 = x.astype(np.float32)                       # what a host hands the plugin
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "in.wav", Path(td) / "out.wav"
        K.write_wav(str(src), x32, FS)
        cmd = [HARNESS, "--sample-rate=%d" % FS, "--block=%d" % BLOCK, "--seconds=%g" % (x.shape[0] / FS),
               "--in=%s" % src, "--out=%s" % dst] + ["--param=%s=1" % s for s in SWITCHES[case]]
        cmd += ["--param=%s=%.9f" % (pid, paramgen.to_normalised(TABLE[pid], v)) for pid, v in EXTRA.get(case, {}).items()]
        out = subprocess.run(cmd, capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError("harness failed (%d): %s" % (out.returncode, out.stderr))
        res = json.loads(out.stdout)
        y_cpp, _ = K.read_wav(str(dst))
    plain = res["product"]["params_plain"]
    kw = {}
    for name in vars(P.Params()):
        if name in plain:
            v = plain[name]
            cur = getattr(P.Params(), name)
            kw[name] = bool(v >= 0.5) if isinstance(cur, bool) else (int(round(v)) if isinstance(cur, int) else float(v))
    p = P.Params(**kw)
    y_py, cu = P.render(x32.astype(np.float64), p, fs=float(FS), block=BLOCK)
    n = min(y_py.shape[0], y_cpp.shape[0])
    r = K.null_residual(y_py[:n], y_cpp[:n], align=False)
    d = y_py[:n] - y_cpp[:n]
    worst = int(np.argmax(np.max(np.abs(d), axis=1)))
    return dict(case=case, peak=r["peak_dbfs"], rms=r["residual_dbfs"], rel=r["relative_db"],
                worst_s=worst / FS, latency_cpp=res["applied"]["latency_samples"], latency_py=cu.latency if p.spectral else 0,
                clicks_cpp=res["product"]["clicks_caught"], clicks_py=cu.click.caught,
                residual=d, out=y_py[:n])


def main(argv):
    cases = argv or ["hum", "click", "click-clean", "noise", "reverb", "all-four"]
    bad = 0
    for case in cases:
        r = run_case(case)
        target = HUM_PEAK_DB if case == "hum" else SPECTRAL_PEAK_DB
        ok = r["peak"] < target and r["latency_cpp"] == r["latency_py"]
        bad += not ok
        print("%-9s peak %8.1f dBFS  rms %8.1f dBFS  (%.1f dB under the signal)  target peak < %d  %s"
              % (case, r["peak"], r["rms"], -r["rel"], target, "PASS" if ok else "FAIL"))
        print("          worst at %.4f s; latency port %d / prototype %d; clicks port %d / prototype %d"
              % (r["worst_s"], r["latency_cpp"], r["latency_py"], r["clicks_cpp"], r["clicks_py"]))
    print("\n%d cases, %d FAIL" % (len(cases), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
