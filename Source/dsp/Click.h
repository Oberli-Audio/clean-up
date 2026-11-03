#pragma once

#include "Constants.h"

#include <array>
#include <atomic>
#include <cstdint>
#include <vector>

/*  Click: AR(32) prediction error for detection, two-sided AR(192) extrapolation with a
    raised-cosine crossfade for the repair (G1 decision; the prototype's `burg`, `ar_error`,
    `robust_sigma`, `RunScanner` and `ClickRepair`). Float64, as in the prototype. Every buffer
    is sized in prepare(); process_segment allocates nothing (rule 1). */

namespace cleanup
{
/** Python's int(round(x)): ties to even (std::nearbyint in the default rounding mode). */
int pyRound (double x) noexcept;

/** Burg's method: pred with xhat[n] = sum_k pred[k] x[n-1-k]. f, b, a, at are scratch of at
    least n, n, order + 1, order + 1. Returns the order actually fitted into pred (zeros beyond). */
void burg (const double* x, int n, int order, double* pred,
           double* f, double* b, double* a, double* at) noexcept;

/** e[i] = x[i] - sum_k pred[k] x[i-1-k], the prototype's summation order. */
void arError (const double* x, int n, const double* pred, int order, double* e) noexcept;

/** 1.4826 x median(|e|) over n samples, numpy's median (the mean of the two middle values for
    even n). scratch holds at least n. */
double robustSigma (const double* e, int n, double* scratch) noexcept;

/** Runs of threshold crossings carried across segment boundaries (the prototype's docstring
    has the measurement that made this necessary). */
struct RunScanner
{
    bool active = false, lost = false;
    int start = 0, length = 0, gap = 0;

    void reset() noexcept { active = lost = false; start = length = gap = 0; }
    void shift (int hop) noexcept
    {
        if (active)
        {
            start -= hop;
            if (start < 0)
                lost = true;
        }
    }
    template <typename OnRun>
    void scan (const unsigned char* hit, int n, int base, int merge, OnRun&& onRun)
    {
        for (int i = 0; i < n; ++i)
        {
            if (hit[i] != 0)
            {
                if (! active)
                {
                    active = true;
                    start = base + i;
                    length = 1;
                    gap = 0;
                    lost = false;
                }
                else
                {
                    length += gap + 1;
                    gap = 0;
                }
            }
            else if (active)
            {
                if (++gap > merge)
                {
                    onRun (start, length, lost);
                    reset();
                }
            }
        }
    }
};

class ClickRepair
{
public:
    /** frame and hop: the engine's framing, which sizes the time-domain buffer this repairs. */
    void prepare (double sampleRate, int frame, int hop);
    void reset() noexcept;

    /** Repairs td[segStart, segStart + segLen) of the two channels in place. td holds `history`
        samples before segStart and `lookahead` after the segment (the engine's framing). */
    void processSegment (double* tdL, double* tdR, int tdLen, int segStart, int segLen,
                         const EngineParams& p) noexcept;

    int history = 0, lookahead = 0;

    // the readouts (sketch 4.3), read by the editor and the harness from any thread
    std::atomic<int> caught { 0 }, missed { 0 }, longestSamples { 0 };

    // measurement instrumentation (the harness only): absolute (input sample, length) of the
    // last kLogSize repairs. Written on the audio thread into preallocated storage.
    static constexpr int kLogSize = 8192;
    std::array<std::int64_t, kLogSize> logStart {};
    std::array<int, kLogSize> logLength {};
    std::atomic<int> logCount { 0 };
    std::int64_t absBase = 0;

private:
    double sigmaOf (double thresholdPct) const noexcept;
    bool isLevelStep (const double* mono, int monoSize, int start, int length) const noexcept;
    static bool stepAt (const double* mono, int monoSize, int start, int length, int c) noexcept;
    void repair (double* buf, int bufSize, int spanStart, int spanLen, const double* pred, int order,
                 const double* fallback, int fallbackOrder) noexcept;
    bool extrapolate (const double* buf, int start, int length, const double* pred, int order) noexcept;
    void logRepair (int start, int length) noexcept;

    double fs = 48000.0;
    int burgBlock = 0, repairOrder = 0, repairBlock = 0, context = 0, stepLong = 0, xfade = 0;
    int merge = 0, extendMax = 0, extendGap = 0, maxRepair = 0;
    RunScanner scanMain, scanCrackle, scanMissed;

    // scratch, sized in prepare
    std::vector<double> mono, mono2, e, e2, sortScratch, burgF, burgB, burgA, burgAt;
    std::vector<double> pred, predCrackle, predRepair, fwd, bwd, ext, rep, fadeW, edgeR;
    std::vector<unsigned char> hit;
};
} // namespace cleanup
