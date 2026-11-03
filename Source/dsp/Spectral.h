#pragma once

#include "Constants.h"

#include <algorithm>
#include <cmath>
#include <vector>

/*  The two gain stages inside the shared STFT, float32 as in the prototype: Noise (the
    decision-directed Wiener with minimum statistics, the prototype's `NoiseWiener`) and Reverb
    (late-tail subtraction with a flux attack hold, `ReverbSubtract`). Both take the mean of the
    two channels' bin power and return one gain per bin (stereo-linked). Every array is sized in
    prepare(); gainFor allocates nothing. */

namespace cleanup
{
class NoiseWiener
{
public:
    void prepare (double sampleRate, int frameSize, int hopSize, double windowEnergy)
    {
        fs = sampleRate;
        frame = frameSize;
        hop = hopSize;
        bins = frame / 2 + 1;
        winEnergy = windowEnergy;
        subFrames = std::max (1, (int) std::nearbyint ((k::NOISE_MINSTAT_WINDOW_S / k::NOISE_MINSTAT_SUBWINDOWS)
                                                        / ((double) hop / fs)));
        smoothA = (float) std::exp (-((double) hop / fs) / k::NOISE_MINSTAT_SMOOTH_S);
        bias = (float) std::pow (std::pow (10.0, k::NOISE_MINSTAT_BIAS_DB / 20.0), 2.0);
        warmFrames = std::max (1, (int) std::ceil (k::NOISE_MINSTAT_SMOOTH_S / ((double) hop / fs)));
        const auto b = (size_t) bins;
        subMin.assign (b, 0.0f);
        ring.assign (b * (size_t) k::NOISE_MINSTAT_SUBWINDOWS, 0.0f);
        lam.assign (b, 0.0f);
        lamWork.assign (b, 0.0f);
        powSmooth.assign (b, 0.0f);
        gammaPrev.assign (b, 0.0f);
        gain.assign (b, 1.0f);
        learnAcc.assign (b, 0.0);
        profile.assign (b, 0.0f);
        hasProfile = false;
        reset();
    }

    void reset() noexcept
    {
        std::fill (subMin.begin(), subMin.end(), 1.0e30f);
        std::fill (ring.begin(), ring.end(), 1.0e30f);
        ringAt = 0;
        subCount = 0;
        std::fill (lam.begin(), lam.end(), 1.0e-20f);
        std::fill (powSmooth.begin(), powSmooth.end(), 0.0f);
        smoothPrimed = false;
        warmCount = 0;
        std::fill (gammaPrev.begin(), gammaPrev.end(), 0.0f);
        std::fill (gain.begin(), gain.end(), 1.0f);
        learnLeft = 0;
        std::fill (learnAcc.begin(), learnAcc.end(), 0.0);
        learnFrames = 0;
        learnPeak = 0.0;
    }

    void startLearn() noexcept
    {
        learnLeft = std::max (1, (int) std::nearbyint (k::NOISE_LEARN_S * fs / hop));
        std::fill (learnAcc.begin(), learnAcc.end(), 0.0);
        learnFrames = 0;
        learnPeak = 0.0;
    }

    bool learning() const noexcept { return learnLeft > 0; }
    bool profileCaptured() const noexcept { return hasProfile; }
    const std::vector<float>& noiseEstimate() const noexcept { return lam; }

    /** The broadband RMS a one-sided power estimate implies (Parseval, windowed). */
    double impliedRms (const float* l) const noexcept
    {
        double s = (double) l[0] + (double) l[bins - 1];
        double mid = 0.0;
        for (int i = 1; i < bins - 1; ++i)
            mid += (double) l[i];
        s += 2.0 * mid;
        return std::sqrt (std::max (s / ((double) frame * winEnergy), 1.0e-300));
    }

    /** power: the mean of the two channels' bin power. Returns the gain (bins values). */
    const float* gainFor (const float* power, const EngineParams& p) noexcept
    {
        if (learnLeft > 0)
        {
            for (int i = 0; i < bins; ++i)
                learnAcc[(size_t) i] += (double) power[i];
            ++learnFrames;
            learnPeak = std::max (learnPeak, impliedRms (power));
            if (--learnLeft == 0 && learnFrames > 0
                && 20.0 * std::log10 (std::max (learnPeak, 1.0e-300)) <= k::NOISE_LEARN_MAX_DBFS)
            {
                for (int i = 0; i < bins; ++i)
                    profile[(size_t) i] = (float) (learnAcc[(size_t) i] / learnFrames);
                hasProfile = true;
                ++profileVersion;
            }
        }
        minstat (power);                      // always tracking, so Adaptive is instant
        if (! p.noiseOn)
        {
            std::fill (gain.begin(), gain.end(), 1.0f);
            std::fill (gammaPrev.begin(), gammaPrev.end(), 0.0f);
            return gain.data();
        }
        const auto& src = (p.noiseMode == PROFILE_LEARNED && hasProfile) ? profile : lam;
        std::copy (src.begin(), src.end(), lamWork.begin());
        // Floor is the broadband level the user asserts: the estimate supplies the shape
        const double est = impliedRms (lamWork.data());
        const double want = std::pow (10.0, p.noiseFloor / 20.0);
        if (est < want)
        {
            const float scale = (float) std::min (std::pow (want / std::max (est, 1.0e-12), 2.0), 1.0e12);
            for (auto& v : lamWork)
                v = v * scale;
        }
        const float gMin = (float) std::pow (10.0, p.noiseReduction / 20.0);
        const double tau = k::NOISE_DD_TAU_AT_0_S
                           * std::pow (k::NOISE_DD_TAU_AT_100_S / k::NOISE_DD_TAU_AT_0_S, p.noiseSmooth / 100.0);
        const float alpha = (float) std::exp (-((double) hop / fs) / tau);
        for (int i = 0; i < bins; ++i)
        {
            const float gamma = power[i] / std::max (lamWork[(size_t) i], 1.0e-30f);
            const float g0 = gain[(size_t) i];
            const float xi = alpha * (g0 * g0 * gammaPrev[(size_t) i])
                             + (1.0f - alpha) * std::max (gamma - 1.0f, 0.0f);
            gammaPrev[(size_t) i] = gamma;
            const float g = xi / (xi + 1.0f);
            gain[(size_t) i] = std::max (g, gMin);
        }
        return gain.data();
    }

    /** The captured profile is plugin state (parameters.csv, noiseMode notes). */
    void setProfile (const float* values, int n) noexcept
    {
        if (n != bins) return;
        std::copy (values, values + n, profile.begin());
        hasProfile = true;
        ++profileVersion;
    }
    /** Bumped whenever the profile changes (Learn, or a loaded state); the engine publishes it. */
    int profileVersionNow() const noexcept { return profileVersion; }
    int binCount() const noexcept { return bins; }
    const std::vector<float>& capturedProfile() const noexcept { return profile; }

private:
    void minstat (const float* power) noexcept
    {
        const int b = bins;
        const auto S = (size_t) k::NOISE_MINSTAT_SUBWINDOWS;
        if (! smoothPrimed)
        {
            if (warmCount == 0 && ! std::any_of (power, power + b, [] (float v) { return v > 0.0f; }))
                return;
            ++warmCount;
            const float wc = (float) warmCount;
            for (int i = 0; i < b; ++i)
            {
                powSmooth[(size_t) i] = powSmooth[(size_t) i] + (power[i] - powSmooth[(size_t) i]) / wc;
                lam[(size_t) i] = std::min (powSmooth[(size_t) i], 1.0e29f);
            }
            if (warmCount < warmFrames)
                return;
            for (int i = 0; i < b; ++i)
            {
                const float v = powSmooth[(size_t) i] / bias;
                for (size_t r = 0; r < S; ++r)
                    ring[r * (size_t) b + (size_t) i] = v;
                subMin[(size_t) i] = v;
            }
            subCount = 0;
            smoothPrimed = true;
            return;
        }
        for (int i = 0; i < b; ++i)
            powSmooth[(size_t) i] = smoothA * powSmooth[(size_t) i] + (1.0f - smoothA) * power[i];
        for (int i = 0; i < b; ++i)
            subMin[(size_t) i] = std::min (subMin[(size_t) i], powSmooth[(size_t) i]);
        if (++subCount >= subFrames)
        {
            std::copy (subMin.begin(), subMin.end(), ring.begin() + (std::ptrdiff_t) ((size_t) ringAt * (size_t) b));
            ringAt = (ringAt + 1) % k::NOISE_MINSTAT_SUBWINDOWS;
            std::fill (subMin.begin(), subMin.end(), 1.0e30f);
            subCount = 0;
        }
        for (int i = 0; i < b; ++i)
        {
            float m = subMin[(size_t) i];
            for (size_t r = 0; r < S; ++r)
                m = std::min (m, ring[r * (size_t) b + (size_t) i]);
            lam[(size_t) i] = std::min (m * bias, 1.0e29f);
        }
    }

    double fs = 48000.0, winEnergy = 1.0, learnPeak = 0.0;
    int frame = 2048, hop = 512, bins = 1025, subFrames = 1, warmFrames = 1, warmCount = 0;
    int ringAt = 0, subCount = 0, learnLeft = 0, learnFrames = 0, profileVersion = 0;
    float smoothA = 0.0f, bias = 1.0f;
    bool smoothPrimed = false, hasProfile = false;
    std::vector<float> subMin, ring, lam, lamWork, powSmooth, gammaPrev, gain, profile;
    std::vector<double> learnAcc;
};

//==============================================================================
/** Lebart-style late-tail subtraction as the prototype has it today. Its gain law fails the
    G3 T60 target and is waiting for the owner's decision (docs/status.md); the port carries it
    unchanged so the module exists end to end, and is redone with the prototype. */
class ReverbSubtract
{
public:
    void prepare (double sampleRate, int frameSize, int hopSize)
    {
        fs = sampleRate;
        hop = hopSize;
        bins = frameSize / 2 + 1;
        delayFrames = std::max (1, (int) std::nearbyint (k::REVERB_PREDELAY_S / ((double) hop / fs)));
        smooth = std::exp (-1.0 / k::REVERB_SMOOTH_FRAMES);
        fluxA = std::exp (-((double) hop / fs) / k::REVERB_FLUX_TAU_S);
        hist.assign ((size_t) (delayFrames + 1) * (size_t) bins, 0.0f);
        gain.assign ((size_t) bins, 1.0f);
        prevMag.assign ((size_t) bins, 0.0f);
        reset();
    }

    void reset() noexcept
    {
        std::fill (hist.begin(), hist.end(), 0.0f);
        histAt = 0;
        std::fill (gain.begin(), gain.end(), 1.0f);
        std::fill (prevMag.begin(), prevMag.end(), 0.0f);
        fluxMean = 0.0;
        holdFrames = 0;
        onsets = 0;
    }

    int onsetCount() const noexcept { return onsets; }

    const float* gainFor (const float* power, const EngineParams& p) noexcept
    {
        double flux = 0.0;
        {
            float acc = 0.0f;   // numpy sums the float32 array; the total is read as a double
            for (int i = 0; i < bins; ++i)
            {
                const float mag = std::sqrt (power[i]);
                acc += std::max (mag - prevMag[(size_t) i], 0.0f);
                prevMag[(size_t) i] = mag;
            }
            flux = (double) acc;
        }
        const bool onset = fluxMean > 0.0 && flux > k::REVERB_FLUX_FACTOR * fluxMean;
        fluxMean = fluxA * fluxMean + (1.0 - fluxA) * flux;
        if (onset)
            ++onsets;
        const int rows = delayFrames + 1;
        float* histRow = hist.data() + (size_t) histAt * (size_t) bins;
        if (! p.reverbOn)
        {
            std::copy (power, power + bins, histRow);
            histAt = (histAt + 1) % rows;
            std::fill (gain.begin(), gain.end(), 1.0f);
            return gain.data();
        }
        if (onset)
            holdFrames = (int) std::nearbyint ((p.reverbAttacks / 100.0) * k::REVERB_ATTACK_HOLD_S / ((double) hop / fs));
        const float* past = hist.data() + (size_t) (((histAt - delayFrames) % rows + rows) % rows) * (size_t) bins;
        const double amount = p.reverbAmount / 100.0;
        const double decay = std::pow (10.0, -6.0 * (delayFrames * (double) hop / fs) / std::max (p.reverbTail, 1.0e-3));
        const float floorPow = (float) std::pow (std::pow (10.0, k::REVERB_FLOOR_DB_AT_FULL * amount / 20.0), 2.0);
        const bool hold = holdFrames > 0;
        if (hold)
            --holdFrames;
        const float sm = (float) smooth;
        for (int i = 0; i < bins; ++i)
        {
            float target = 1.0f;
            if (! hold)
            {
                const float late = (float) decay * past[i];
                const float ratio = late / std::max (power[i], 1.0e-30f);
                target = std::sqrt (std::max (1.0f - (float) amount * ratio, floorPow));
            }
            gain[(size_t) i] = sm * gain[(size_t) i] + (1.0f - sm) * target;
        }
        std::copy (power, power + bins, histRow);
        histAt = (histAt + 1) % rows;
        return gain.data();
    }

private:
    double fs = 48000.0, smooth = 0.0, fluxA = 0.0, fluxMean = 0.0;
    int hop = 512, bins = 1025, delayFrames = 1, histAt = 0, holdFrames = 0, onsets = 0;
    std::vector<float> hist, gain, prevMag;
};
} // namespace cleanup
