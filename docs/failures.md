# Failures - the product's own rows (D.9.3)

| Symptom | Cause | Confirming measurement | Fixed in | Regression test |
|---|---|---|---|---|
| Noise reduced only ~2 dB for the first 1.5 s after reset | Minimum-statistics ring primed from one raw periodogram (exponential per bin), so the minimum sat below the floor until the ring rolled over | Reduction over time on -50 dBFS noise alone: 2.3 dB over 0-1.5 s, 11.8 dB after (`measure.py noise`, first gap) | 2026-11-02, running-mean warm-up over `NOISE_MINSTAT_SMOOTH_S` | selftest `noise reduces from the start (minimum-statistics warm-up)`: 0.97 dB before, 11.68 after |
| Reduction knob saturates at 8.6 dB however deep the floor | Decision-directed a-priori SNR used the current gamma, and the sketch's alpha 0.5-0.98 put the default (0.69) below where the Wiener reaches its floor | Exact-profile simulation and an alpha sweep on the material: 7.3 dB at -12, 8.6 dB at -42; 11.6 dB at tau 0.76 s | 2026-11-02, Ephraim-Malah `G(l-1)^2 gamma(l-1)`, Smooth as tau 0.25-4 s | selftest `noise reaches its gain floor (decision-directed gain law)`: 10.10 dB before, 17.94 after |
