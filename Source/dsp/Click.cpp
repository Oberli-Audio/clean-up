#include "Click.h"

#include <algorithm>
#include <cmath>

namespace cleanup
{
namespace
{
double undb (double d) noexcept { return std::pow (10.0, d / 20.0); }
double dbOf (double x) noexcept { return x > 0.0 ? std::max (20.0 * std::log10 (x), -300.0) : -300.0; }
} // namespace

int pyRound (double x) noexcept { return (int) std::nearbyint (x); }

void burg (const double* x, int n, int order, double* pred,
           double* f, double* b, double* a, double* at) noexcept
{
    std::fill (pred, pred + order, 0.0);
    if (n <= order + 1)
        return;
    std::copy (x, x + n, f);
    std::copy (x, x + n, b);
    std::fill (a, a + order + 1, 0.0);
    a[0] = 1.0;
    for (int m = 0; m < order; ++m)
    {
        // the denominator directly at every order, not by the textbook recursion: on a highly
        // predictable source it falls by nine orders of magnitude and the recursion's
        // subtraction is then all rounding (the prototype's `burg` docstring has the measurement)
        double fb = 0.0, d = 0.0;
        for (int j = 0; j < n - m - 1; ++j)
        {
            fb += f[m + 1 + j] * b[j];
            d += f[m + 1 + j] * f[m + 1 + j] + b[j] * b[j];
        }
        if (d <= 1.0e-300)
            break;
        const double mu = 2.0 * fb / d;
        if (! (std::abs (mu) < 0.999))
            break;        // |mu| >= 1 is what makes the model non-minimum-phase in float
        for (int j = 0; j <= m + 1; ++j)
            at[j] = a[j] - mu * a[m + 1 - j];
        std::copy (at, at + m + 2, a);
        for (int j = 0; j < n - m - 1; ++j)
        {
            const double ff = f[m + 1 + j], bb = b[j];
            f[m + 1 + j] = ff - mu * bb;
            b[j] = bb - mu * ff;
        }
    }
    for (int j = 0; j < order; ++j)
        pred[j] = -a[j + 1];
}

void arError (const double* x, int n, const double* pred, int order, double* e) noexcept
{
    for (int i = 0; i < n; ++i)
    {
        double v = x[i];
        const int kmax = std::min (order, i);
        for (int k = 0; k < kmax; ++k)
            if (pred[k] != 0.0)
                v -= pred[k] * x[i - 1 - k];
        e[i] = v;
    }
}

double robustSigma (const double* e, int n, double* scratch) noexcept
{
    if (n <= 0)
        return 0.0;
    for (int i = 0; i < n; ++i)
        scratch[i] = std::abs (e[i]);
    const int mid = n / 2;
    std::nth_element (scratch, scratch + mid, scratch + n);
    double med = scratch[mid];
    if ((n & 1) == 0)
    {
        const double lower = *std::max_element (scratch, scratch + mid);
        med = (lower + med) / 2.0;
    }
    return 1.4826 * med;
}

//==============================================================================
void ClickRepair::prepare (double sampleRate, int frame, int hop)
{
    fs = sampleRate;
    burgBlock = std::max (k::CLICK_AR_ORDER * 2, pyRound (k::CLICK_BURG_BLOCK_S * fs));
    repairOrder = k::CLICK_REPAIR_AR_ORDER;
    repairBlock = std::max (repairOrder * 4, pyRound (k::CLICK_REPAIR_BURG_BLOCK_S * fs));
    history = std::max (burgBlock, repairBlock);
    context = std::max (k::CLICK_AR_ORDER, pyRound (k::CLICK_CONTEXT_S * fs));
    stepLong = std::max (context, pyRound (k::CLICK_STEP_LONG_S * fs));
    xfade = std::max (1, pyRound (k::CLICK_XFADE_S * fs));
    merge = std::max (1, pyRound (k::CLICK_MERGE_S * fs));
    extendMax = std::max (1, pyRound (k::CLICK_EXTEND_MAX_S * fs));
    extendGap = std::max (1, pyRound (k::CLICK_EXTEND_GAP_S * fs));
    lookahead = std::max (1, pyRound (k::CLICK_LOOKAHEAD_S * fs));

    const int tdLen = history + frame + lookahead;
    const int window = burgBlock + hop + lookahead;
    const int burgN = std::max ({ window, repairBlock, burgBlock });
    maxRepair = lookahead + 2 * extendMax + 2 * xfade + 16;
    mono.assign ((size_t) tdLen, 0.0);
    mono2.assign ((size_t) tdLen, 0.0);
    e.assign ((size_t) window, 0.0);
    e2.assign ((size_t) window, 0.0);
    sortScratch.assign ((size_t) window, 0.0);
    burgF.assign ((size_t) burgN, 0.0);
    burgB.assign ((size_t) burgN, 0.0);
    burgA.assign ((size_t) repairOrder + 1, 0.0);
    burgAt.assign ((size_t) repairOrder + 1, 0.0);
    pred.assign ((size_t) k::CLICK_AR_ORDER, 0.0);
    predCrackle.assign ((size_t) k::CLICK_CRACKLE_AR_ORDER, 0.0);
    predRepair.assign ((size_t) repairOrder, 0.0);
    fwd.assign ((size_t) maxRepair, 0.0);
    bwd.assign ((size_t) maxRepair, 0.0);
    rep.assign ((size_t) maxRepair, 0.0);
    fadeW.assign ((size_t) maxRepair, 0.0);
    edgeR.assign ((size_t) xfade, 0.0);
    ext.assign ((size_t) (repairOrder + maxRepair), 0.0);
    hit.assign ((size_t) hop, 0);
    reset();
}

void ClickRepair::reset() noexcept
{
    caught.store (0);
    missed.store (0);
    longestSamples.store (0);
    scanMain.reset();
    scanCrackle.reset();
    scanMissed.reset();
    logCount.store (0);
    absBase = 0;
}

double ClickRepair::sigmaOf (double thresholdPct) const noexcept
{
    const double t = std::min (std::max (thresholdPct, 0.0), 100.0) / 100.0;
    return k::CLICK_SIGMA_AT_0 + t * (k::CLICK_SIGMA_AT_100 - k::CLICK_SIGMA_AT_0);
}

bool ClickRepair::stepAt (const double* m, int size, int start, int length, int c) noexcept
{
    if (start < c || start + length + c > size)
        return true;
    double l2 = 0.0, r2 = 0.0;
    for (int i = 0; i < c; ++i)
    {
        l2 += m[start - c + i] * m[start - c + i];
        r2 += m[start + length + i] * m[start + length + i];
    }
    const double lr = std::sqrt (l2 / c), rr = std::sqrt (r2 / c);
    const double floor = undb (k::CLICK_ABS_FLOOR_DBFS);
    return std::abs (dbOf (std::max (rr, floor)) - dbOf (std::max (lr, floor))) > k::CLICK_MAX_STEP_DB;
}

bool ClickRepair::isLevelStep (const double* m, int size, int start, int length) const noexcept
{
    // an edge in the music is a step at both scales (CLICK_STEP_LONG_S in the prototype)
    return stepAt (m, size, start, length, context) && stepAt (m, size, start, length, stepLong);
}

bool ClickRepair::extrapolate (const double* buf, int start, int length, const double* pr, int order) noexcept
{
    // forward from the left context, backward from the right, crossfaded by fadeW into rep;
    // false when the result is not finite or exceeds CLICK_RUNAWAY_FACTOR x the local peak
    const double* left = buf + start - order;
    const double* right = buf + start + length;
    double peak = 1.0e-12;
    for (int i = 0; i < order; ++i)
        peak = std::max ({ peak, std::abs (left[i]), std::abs (right[i]) });
    const double limit = k::CLICK_RUNAWAY_FACTOR * peak;
    std::copy (left, left + order, ext.begin());                       // ext[t] in time order
    for (int i = 0; i < length; ++i)
    {
        double v = 0.0;
        for (int kk = 0; kk < order; ++kk)
            v += pr[kk] * ext[(size_t) (order + i - 1 - kk)];
        ext[(size_t) (order + i)] = v;
        fwd[(size_t) i] = v;
    }
    for (int j = 0; j < order; ++j)                                    // the time-reversed right
        ext[(size_t) (order - 1 - j)] = right[j];
    for (int i = 0; i < length; ++i)
    {
        double v = 0.0;
        for (int kk = 0; kk < order; ++kk)
            v += pr[kk] * ext[(size_t) (order + i - 1 - kk)];
        ext[(size_t) (order + i)] = v;
        bwd[(size_t) (length - 1 - i)] = v;
    }
    bool ok = true;
    for (int i = 0; i < length; ++i)
    {
        const double w = fadeW[(size_t) i];
        const double v = w * fwd[(size_t) i] + (1.0 - w) * bwd[(size_t) i];
        rep[(size_t) i] = v;
        if (! std::isfinite (v) || std::abs (v) > limit)
            ok = false;
    }
    return ok;
}

void ClickRepair::repair (double* buf, int bufSize, int spanStart, int spanLen,
                          const double* pr, int order, const double* fallback, int fallbackOrder) noexcept
{
    // the span plus `xfade` samples each side, so the crossfade never sits on the click itself
    const int xf = xfade;
    const int start = spanStart - xf;
    const int length = spanLen + 2 * xf;
    if (start < order || start + length + order > bufSize || length > maxRepair)
        return;
    for (int i = 0; i < length; ++i)
        fadeW[(size_t) i] = 0.5 * (1.0 + std::cos (k::PI * (((double) i + 0.5) / length)));   // 1 -> 0
    // a runaway full-order extrapolation falls back to the detection model before the bridge
    bool ok = extrapolate (buf, start, length, pr, order);
    if (! ok && fallback != nullptr)
        ok = extrapolate (buf, start, length, fallback, fallbackOrder);
    if (! ok)   // the safety net: a cosine bridge between the two context ends, always bounded
        for (int i = 0; i < length; ++i)
            rep[(size_t) i] = buf[start - 1] * fadeW[(size_t) i] + buf[start + length] * (1.0 - fadeW[(size_t) i]);
    for (int j = 0; j < xf; ++j)
        edgeR[(size_t) j] = 0.5 * (1.0 - std::cos (k::PI * ((double) j + 0.5) / xf));
    for (int j = 0; j < xf; ++j)
    {
        const double r = edgeR[(size_t) j];
        rep[(size_t) j] = buf[start + j] * (1.0 - r) + rep[(size_t) j] * r;
        const int t = length - xf + j;
        rep[(size_t) t] = buf[start + t] * r + rep[(size_t) t] * (1.0 - r);
    }
    std::copy (rep.begin(), rep.begin() + length, buf + start);
}

void ClickRepair::logRepair (int start, int length) noexcept
{
    const int n = logCount.load (std::memory_order_relaxed);
    logStart[(size_t) (n % kLogSize)] = absBase + start;
    logLength[(size_t) (n % kLogSize)] = length;
    logCount.store (n + 1, std::memory_order_release);
}

void ClickRepair::processSegment (double* tdL, double* tdR, int tdLen, int segStart, int segLen,
                                  const EngineParams& p) noexcept
{
    scanMain.shift (segLen);
    scanCrackle.shift (segLen);
    scanMissed.shift (segLen);
    for (int i = 0; i < tdLen; ++i)
        mono[(size_t) i] = 0.5 * (tdL[i] + tdR[i]);
    const bool crackleMode = p.clickMode == MODE_CRACKLE;
    const int order = crackleMode ? k::CLICK_CRACKLE_AR_ORDER : k::CLICK_AR_ORDER;
    const double spanS = crackleMode ? k::CLICK_CRACKLE_LENGTH_S : p.clickLength / 1000.0;
    const int maxSpan = std::max (1, std::min (pyRound (spanS * fs), lookahead - context));
    const double sigma = sigmaOf (p.clickThreshold);
    const int rejectAbove = maxSpan + pyRound (k::CLICK_RUN_SLACK_ORDER * order);
    const double absFloor = undb (k::CLICK_ABS_FLOOR_DBFS);

    // the detection model is fitted on history + segment + lookahead (the prototype says why)
    const int fitFrom = segStart - burgBlock;
    const int win = segStart + segLen + lookahead - fitFrom;
    const int off = burgBlock;
    burg (mono.data() + fitFrom, win, order, pred.data(), burgF.data(), burgB.data(), burgA.data(), burgAt.data());
    arError (mono.data() + fitFrom, win, pred.data(), order, e.data());
    const double rs = robustSigma (e.data(), off + segLen, sortScratch.data());
    const double thr = std::max (sigma * rs, absFloor);
    for (int i = 0; i < segLen; ++i)
        hit[(size_t) i] = std::abs (e[(size_t) (off + i)]) > thr ? 1 : 0;
    const double thrExt = std::max (k::CLICK_EXTEND_SIGMA * rs, absFloor);
    const int loLim = fitFrom + order;                                // e's first `order` have no history
    const int hiLim = segStart + segLen + lookahead - repairOrder - xfade - 1;

    bool repairReady = false;
    const double* repairPred = pred.data();
    int repairPredOrder = order;

    auto doRepair = [&] (int start, int length, bool lost)
    {
        if (lost || length > rejectAbove)
            return;
        length = std::min (length, maxSpan);
        // hysteresis: grow the run outwards to the furthest sample above thrExt, crossing dips
        // of up to extendGap samples
        int newStart = start, gapCount = 0;
        for (int kk = 1; kk <= extendMax; ++kk)
        {
            const int i = start - kk;
            if (i <= loLim || gapCount > extendGap)
                break;
            if (std::abs (e[(size_t) (i - fitFrom)]) > thrExt) { newStart = i; gapCount = 0; }
            else ++gapCount;
        }
        const int end = start + length;
        int newEnd = end;
        gapCount = 0;
        for (int kk = 0; kk < extendMax; ++kk)
        {
            const int i = end + kk;
            if (i >= hiLim || gapCount > extendGap)
                break;
            if (std::abs (e[(size_t) (i - fitFrom)]) > thrExt) { newEnd = i + 1; gapCount = 0; }
            else ++gapCount;
        }
        start = newStart;
        length = newEnd - newStart;
        if (isLevelStep (mono.data(), tdLen, start, length))
            return;
        if (! repairReady)
        {
            burg (mono.data() + segStart - repairBlock, repairBlock, repairOrder, predRepair.data(),
                  burgF.data(), burgB.data(), burgA.data(), burgAt.data());
            const bool any = std::any_of (predRepair.begin(), predRepair.end(), [] (double v) { return v != 0.0; });
            repairPred = any ? predRepair.data() : pred.data();
            repairPredOrder = any ? repairOrder : order;
            repairReady = true;
        }
        const double* fb = repairPred != pred.data() ? pred.data() : nullptr;
        repair (tdL, tdLen, start, length, repairPred, repairPredOrder, fb, order);
        repair (tdR, tdLen, start, length, repairPred, repairPredOrder, fb, order);
        caught.store (caught.load (std::memory_order_relaxed) + 1, std::memory_order_relaxed);
        longestSamples.store (std::max (longestSamples.load (std::memory_order_relaxed), length), std::memory_order_relaxed);
        logRepair (start, length);
    };
    scanMain.scan (hit.data(), segLen, segStart, merge, doRepair);

    // the crackle co-detector, switched in by Crackle % (0 % = nothing)
    if (p.clickCrackle > 0.0 && p.clickMode == MODE_CLICKS)
    {
        for (int i = 0; i < tdLen; ++i)
            mono2[(size_t) i] = 0.5 * (tdL[i] + tdR[i]);
        const int oc = k::CLICK_CRACKLE_AR_ORDER;
        burg (mono2.data() + fitFrom, segStart - fitFrom, oc, predCrackle.data(),
              burgF.data(), burgB.data(), burgA.data(), burgAt.data());
        arError (mono2.data() + fitFrom, win, predCrackle.data(), oc, e2.data());
        const int spanC = std::max (1, pyRound (k::CLICK_CRACKLE_LENGTH_S * fs));
        const double thrC = std::max (sigmaOf (p.clickCrackle) * robustSigma (e2.data(), off + segLen, sortScratch.data()),
                                      absFloor);
        for (int i = 0; i < segLen; ++i)
            hit[(size_t) i] = std::abs (e2[(size_t) (off + i)]) > thrC ? 1 : 0;
        const int rejectC = spanC + oc;
        auto doCrackle = [&] (int start, int length, bool lost)
        {
            if (lost || length > rejectC)
                return;
            length = std::min (length, spanC);
            if (isLevelStep (mono2.data(), tdLen, start, length))
                return;
            repair (tdL, tdLen, start, length, predCrackle.data(), oc, nullptr, 0);
            repair (tdR, tdLen, start, length, predCrackle.data(), oc, nullptr, 0);
            caught.store (caught.load (std::memory_order_relaxed) + 1, std::memory_order_relaxed);
            logRepair (start, length);
        };
        scanCrackle.scan (hit.data(), segLen, segStart, merge, doCrackle);
    }

    // the honest counter: a second pass over the repaired signal, one sigma lower, same model
    for (int i = 0; i < tdLen; ++i)
        mono2[(size_t) i] = 0.5 * (tdL[i] + tdR[i]);
    arError (mono2.data() + fitFrom, win, pred.data(), order, e2.data());
    const double sigma2 = std::max (1.0, sigma - k::CLICK_MISSED_SIGMA_MARGIN);
    const double thr2 = std::max (sigma2 * robustSigma (e2.data(), off + segLen, sortScratch.data()), absFloor);
    for (int i = 0; i < segLen; ++i)
        hit[(size_t) i] = std::abs (e2[(size_t) (off + i)]) > thr2 ? 1 : 0;
    int counter = 0;
    auto doMissed = [&] (int start, int length, bool lost)
    {
        if (! lost && length <= rejectAbove && ! isLevelStep (mono2.data(), tdLen, start, length))
            ++counter;
    };
    scanMissed.scan (hit.data(), segLen, segStart, merge, doMissed);
    missed.store (missed.load (std::memory_order_relaxed) + counter, std::memory_order_relaxed);
}
} // namespace cleanup
