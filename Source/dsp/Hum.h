#pragma once

#include "Constants.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <vector>

/*  Hum: the adaptive notch comb, time domain, zero latency (G1 decision; the prototype's
    `SvfBell`, `OnePole` and `HumComb`). Float64 throughout, as in the prototype: a Q of 400
    needs it. The parameters arrive with every process() call, as they do in the prototype, so
    the two run the same sequence of coefficient updates (G5). */

namespace cleanup
{
/** One TPT (Cytomic / Simper) state-variable filter in its bell form. k is the bandwidth
    (Width / f0), not 1 / (Q A): the prototype's docstring has the measurement behind it. */
struct SvfBell
{
    double g = 0.0, k = 0.0, a1 = 0.0, a2 = 0.0, a3 = 0.0, m1 = 0.0;
    double ic1 = 0.0, ic2 = 0.0;

    void reset() noexcept { ic1 = ic2 = 0.0; }

    void set (double fs, double hz, double bwHz, double gainDb) noexcept
    {
        hz = std::min (std::max (hz, 1.0), 0.45 * fs);
        const double a = std::pow (10.0, gainDb / 40.0);
        g = std::tan (k::PI * hz / fs);
        k = std::max (bwHz / hz, 1.0e-6);
        m1 = k * (a * a - 1.0);
        a1 = 1.0 / (1.0 + g * (g + k));
        a2 = g * a1;
        a3 = g * a2;
    }

    double process (double x) noexcept
    {
        const double v3 = x - ic2;
        const double v1 = a1 * ic1 + a2 * v3;
        const double v2 = ic2 + a2 * ic1 + a3 * v3;
        ic1 = 2.0 * v1 - ic1;
        ic2 = 2.0 * v2 - ic2;
        return x + m1 * v1;   // m0 = 1, m2 = 0
    }
};

struct OnePole
{
    double a = 0.0, z = 0.0;
    void set (double fs, double tauS) noexcept { a = std::exp (-1.0 / std::max (tauS * fs, 1.0)); }
    void reset (double v = 0.0) noexcept { z = v; }
    double process (double x) noexcept { z = a * z + (1.0 - a) * x; return z; }
};

class HumComb
{
public:
    void prepare (double sampleRate)
    {
        fs = sampleRate;
        updateSamples = std::max (1, (int) std::nearbyint (k::HUM_TRACK_UPDATE_S * fs));
        for (auto* s : { &iqI[0], &iqI[1], &iqQ[0], &iqQ[1] })
            s->set (fs, k::HUM_TRACK_LP_TAU_S);
        trackCoef = 1.0 - std::exp (-((double) updateSamples / fs) / k::HUM_TRACK_TAU_S);
        gap = std::max (1, (int) std::nearbyint (k::HUM_TRACK_PHASE_GAP_S * fs / updateSamples));
        warmup = std::max (gap + 1, (int) std::nearbyint (k::HUM_TRACK_WARMUP_S * fs / updateSamples));
        ringI.assign ((size_t) gap + 1, 0.0);
        ringQ.assign ((size_t) gap + 1, 0.0);
        reset();
    }

    void reset() noexcept
    {
        for (auto& ch : bells)
            for (auto& b : ch)
                b.reset();
        for (auto* s : { &iqI[0], &iqI[1], &iqQ[0], &iqQ[1] })
            s->reset();
        oscPhase = 0.0;
        hasTracked = false;
        tracked = 0.0;
        std::fill (ringI.begin(), ringI.end(), 0.0);
        std::fill (ringQ.begin(), ringQ.end(), 0.0);
        ringAt = 0;
        ringFilled = 0;
        counter = 0;
        activeHarmonics = 0;
        coefFreq = 0.0;
    }

    double trackedHz() const noexcept { return hasTracked ? tracked : 0.0; }

    /** l, r: n samples in place. */
    void process (double* l, double* r, int n, const EngineParams& p) noexcept
    {
        if (! hasTracked)
        {
            tracked = p.humFreq;
            hasTracked = true;
        }
        if (p.humDepth >= k::HUM_BYPASS_DEPTH_DB)
            return;                                   // bypassed in code, not a 0 dB filter
        setCoeffs (p);
        const int nh = activeHarmonics;
        const double dphi = 2.0 * k::PI / fs;
        const double lo = p.humFreq - k::HUM_TRACK_RANGE_HZ;
        const double hi = p.humFreq + k::HUM_TRACK_RANGE_HZ;
        for (int i = 0; i < n; ++i)
        {
            double xl = l[i];
            double xr = r[i];
            const double mid = 0.5 * (xl + xr);
            const double c = std::cos (oscPhase);
            const double s = std::sin (oscPhase);
            double vi = mid * c;
            double vq = -mid * s;
            for (auto& st : iqI) vi = st.process (vi);
            for (auto& st : iqQ) vq = st.process (vq);
            oscPhase += dphi * tracked;
            if (oscPhase > 2.0 * k::PI)
                oscPhase -= 2.0 * k::PI;
            if (++counter >= updateSamples)
            {
                counter = 0;
                const int old = (ringAt + 1) % (gap + 1);
                const double pi_ = ringI[(size_t) old], pq_ = ringQ[(size_t) old];
                ringAt = old;
                ringI[(size_t) old] = vi;
                ringQ[(size_t) old] = vq;
                if (ringFilled <= warmup)
                    ++ringFilled;
                else if (std::hypot (vi, vq) > k::HUM_TRACK_GATE)
                {
                    // phase advance of the complex envelope over HUM_TRACK_PHASE_GAP_S -> Hz
                    const double cr = vi * pi_ + vq * pq_;
                    const double ci = vq * pi_ - vi * pq_;
                    const double hz = std::atan2 (ci, cr) * fs / (2.0 * k::PI * updateSamples * gap);
                    const double target = std::min (std::max (tracked + hz, lo), hi);
                    tracked += trackCoef * (target - tracked);
                    if (std::abs (tracked - coefFreq) > k::HUM_TRACK_RECOEF_HZ)
                        setCoeffs (p);
                }
            }
            for (int h = 0; h < nh; ++h) xl = bells[0][(size_t) h].process (xl);
            for (int h = 0; h < nh; ++h) xr = bells[1][(size_t) h].process (xr);
            l[i] = xl;
            r[i] = xr;
        }
    }

private:
    void setCoeffs (const EngineParams& p) noexcept
    {
        const double f0 = tracked;
        coefFreq = f0;
        const int n = std::min (std::max (p.humHarmonics, 1), k::HUM_MAX_HARMONICS);
        const double bw = std::max (p.humWidth, 1.0e-3);
        for (int h = 0; h < n; ++h)
        {
            const double hz = f0 * (h + 1);
            bells[0][(size_t) h].set (fs, hz, bw, p.humDepth);
            bells[1][(size_t) h].set (fs, hz, bw, p.humDepth);
        }
        activeHarmonics = n;
    }

    std::array<std::array<SvfBell, k::HUM_MAX_HARMONICS>, 2> bells {};
    std::array<OnePole, k::HUM_TRACK_LP_STAGES> iqI {}, iqQ {};
    std::vector<double> ringI, ringQ;
    double fs = 48000.0, trackCoef = 0.0, oscPhase = 0.0, tracked = 0.0, coefFreq = 0.0;
    bool hasTracked = false;
    int updateSamples = 32, gap = 1, warmup = 2, ringAt = 0, ringFilled = 0, counter = 0, activeHarmonics = 0;
};
} // namespace cleanup
