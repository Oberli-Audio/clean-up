#include "Engine.h"

#include <algorithm>
#include <cmath>
#include <cstring>

namespace cleanup
{
namespace
{
int nextPow2 (int n) noexcept
{
    int p = 1;
    while (p < n)
        p *= 2;
    return p;
}
} // namespace

void Engine::prepare (double sampleRate, int maxBlock)
{
    fs = sampleRate;
    frame = nextPow2 (pyRound (k::FRAME_SECONDS * fs));
    hop = frame / k::OVERLAP;
    bins = frame / 2 + 1;
    window.assign ((size_t) frame, 0.0f);
    winEnergy = 0.0;
    for (int i = 0; i < frame; ++i)
    {
        // periodic Hann: np.hanning(frame + 1)[:-1], computed in double and stored as float32
        const double w = 0.5 - 0.5 * std::cos (2.0 * k::PI * i / frame);
        window[(size_t) i] = (float) w;
        winEnergy += (double) window[(size_t) i] * (double) window[(size_t) i];
    }
    wolaScale = (float) (1.0 / k::WOLA_HANN_SUM);
    hum.prepare (fs);
    click.prepare (fs, frame, hop);
    noise.prepare (fs, frame, hop, winEnergy);
    reverb.prepare (fs, frame, hop);
    lookahead = click.lookahead;
    latency = frame + lookahead;
    switchLen = std::max (1, pyRound (k::SWITCH_XFADE_S * fs));

    // the Removed display's bands
    jassert (pyRound (k::BANDS_PER_OCTAVE * std::log2 (k::BAND_HIGH_HZ / k::BAND_LOW_HZ)) == k::NUM_BANDS);
    for (int i = 0; i <= k::NUM_BANDS; ++i)
    {
        const double edge = k::BAND_LOW_HZ * std::pow (2.0, (double) i / k::BANDS_PER_OCTAVE);
        bandEdges[(size_t) i] = std::min (std::max ((int) std::nearbyint (edge * frame / fs), 0), frame / 2);
    }

    int order = 0;
    while ((1 << order) < frame)
        ++order;
    fft = std::make_unique<juce::dsp::FFT> (order);
    fftL.assign ((size_t) frame * 2, 0.0f);
    fftR.assign ((size_t) frame * 2, 0.0f);
    power.assign ((size_t) bins, 0.0f);
    power2.assign ((size_t) bins, 0.0f);
    gTotal.assign ((size_t) bins, 0.0f);
    before.assign ((size_t) bins, 0.0);
    accL.assign ((size_t) frame, 0.0f);
    accR.assign ((size_t) frame, 0.0f);

    maxChunk = std::max (std::max (1, maxBlock), hop);
    tdLen = click.history + frame + lookahead;
    tdL.assign ((size_t) tdLen, 0.0);
    tdR.assign ((size_t) tdLen, 0.0);
    inL.assign ((size_t) (hop + maxChunk), 0.0);
    inR.assign ((size_t) (hop + maxChunk), 0.0);
    outL.assign ((size_t) (2 * hop + maxChunk), 0.0);
    outR.assign ((size_t) (2 * hop + maxChunk), 0.0);
    dryCap = latency + 2 * hop + maxChunk;
    dryL.assign ((size_t) dryCap, 0.0);
    dryR.assign ((size_t) dryCap, 0.0);
    for (auto* v : { &xL, &xR, &humL, &humR, &alignedL, &alignedR })
        v->assign ((size_t) maxChunk, 0.0);
    reset();
}

void Engine::reset() noexcept
{
    hum.reset();
    click.reset();
    noise.reset();
    reverb.reset();
    std::fill (tdL.begin(), tdL.end(), 0.0);
    std::fill (tdR.begin(), tdR.end(), 0.0);
    std::fill (accL.begin(), accL.end(), 0.0f);
    std::fill (accR.begin(), accR.end(), 0.0f);
    inCount = 0;
    std::fill (outL.begin(), outL.end(), 0.0);
    std::fill (outR.begin(), outR.end(), 0.0);
    outCount = hop;                               // primed: a block is not a hop multiple
    std::fill (dryL.begin(), dryL.end(), 0.0);
    std::fill (dryR.begin(), dryR.end(), 0.0);
    dryWrite = 0;
    engineOn = false;
    primeLeft = 0;
    fade = 0.0;
    currentAlignment = 0;
    for (auto& b : inputBands) b.store (0.0f, std::memory_order_relaxed);
    for (auto& b : removedBands) b.store (0.0f, std::memory_order_relaxed);
    inputTotal.fill (0.0);
    removedTotal.fill (0.0);
    hopsDone = 0;
    fed = 0;
}

void Engine::startEngine() noexcept
{
    engineOn = true;
    primeLeft = latency;
    fade = 0.0;
    std::fill (tdL.begin(), tdL.end(), 0.0);
    std::fill (tdR.begin(), tdR.end(), 0.0);
    std::fill (accL.begin(), accL.end(), 0.0f);
    std::fill (accR.begin(), accR.end(), 0.0f);
    inCount = 0;
    std::fill (outL.begin(), outL.end(), 0.0);
    std::fill (outR.begin(), outR.end(), 0.0);
    outCount = hop;
    noise.reset();
    reverb.reset();
    click.reset();
}

void Engine::hopStep (const double* chunkL, const double* chunkR, double* emitL, double* emitR,
                      const EngineParams& p) noexcept
{
    const int bb = click.history;
    std::memmove (tdL.data(), tdL.data() + hop, sizeof (double) * (size_t) (tdLen - hop));
    std::memmove (tdR.data(), tdR.data() + hop, sizeof (double) * (size_t) (tdLen - hop));
    std::copy (chunkL, chunkL + hop, tdL.data() + tdLen - hop);
    std::copy (chunkR, chunkR + hop, tdR.data() + tdLen - hop);
    fed += hop;
    // the committed segment ends `lookahead` samples before the newest sample
    const int segStart = bb + frame - hop;
    if (p.clickOn)
    {
        click.absBase = fed - tdLen;
        click.processSegment (tdL.data(), tdR.data(), tdLen, segStart, hop, p);
    }
    if (learnRequested.exchange (false, std::memory_order_acq_rel))
        noise.startLearn();

    for (int i = 0; i < frame; ++i)
    {
        fftL[(size_t) i] = (float) tdL[(size_t) (bb + i)] * window[(size_t) i];
        fftR[(size_t) i] = (float) tdR[(size_t) (bb + i)] * window[(size_t) i];
    }
    std::fill (fftL.begin() + frame, fftL.end(), 0.0f);
    std::fill (fftR.begin() + frame, fftR.end(), 0.0f);
    fft->performRealOnlyForwardTransform (fftL.data(), true);
    fft->performRealOnlyForwardTransform (fftR.data(), true);
    for (int kk = 0; kk < bins; ++kk)
    {
        const float rl = fftL[(size_t) (2 * kk)], il = fftL[(size_t) (2 * kk + 1)];
        const float rr = fftR[(size_t) (2 * kk)], ir = fftR[(size_t) (2 * kk + 1)];
        power[(size_t) kk] = 0.5f * ((rl * rl + il * il) + (rr * rr + ir * ir));
        before[(size_t) kk] = (double) power[(size_t) kk];
    }
    const float* gn = noise.gainFor (power.data(), p);
    for (int kk = 0; kk < bins; ++kk)
        power2[(size_t) kk] = power[(size_t) kk] * gn[kk] * gn[kk];
    const float* gr = reverb.gainFor (power2.data(), p);
    for (int kk = 0; kk < bins; ++kk)
        gTotal[(size_t) kk] = gn[kk] * gr[kk];

    // the Removed display: input and removed energy per band
    for (int b = 0; b < k::NUM_BANDS; ++b)
    {
        const int a = bandEdges[(size_t) b];
        const int e = std::max (a + 1, bandEdges[(size_t) b + 1]);
        double in = 0.0, rem = 0.0;
        for (int kk = a; kk < e && kk < bins; ++kk)
        {
            const double g = (double) gTotal[(size_t) kk];
            const double after = before[(size_t) kk] * (g * g);
            in += before[(size_t) kk];
            rem += std::max (before[(size_t) kk] - after, 0.0);
        }
        inputBands[(size_t) b].store ((float) in, std::memory_order_relaxed);
        removedBands[(size_t) b].store ((float) rem, std::memory_order_relaxed);
        inputTotal[(size_t) b] += in;
        removedTotal[(size_t) b] += rem;
    }

    for (int kk = 0; kk < bins; ++kk)
    {
        const float g = gTotal[(size_t) kk];
        fftL[(size_t) (2 * kk)] *= g;
        fftL[(size_t) (2 * kk + 1)] *= g;
        fftR[(size_t) (2 * kk)] *= g;
        fftR[(size_t) (2 * kk + 1)] *= g;
    }
    fft->performRealOnlyInverseTransform (fftL.data());
    fft->performRealOnlyInverseTransform (fftR.data());
    for (int i = 0; i < frame; ++i)
    {
        accL[(size_t) i] += fftL[(size_t) i] * window[(size_t) i] * wolaScale;
        accR[(size_t) i] += fftR[(size_t) i] * window[(size_t) i] * wolaScale;
    }
    for (int i = 0; i < hop; ++i)
    {
        emitL[i] = (double) accL[(size_t) i];
        emitR[i] = (double) accR[(size_t) i];
    }
    std::memmove (accL.data(), accL.data() + hop, sizeof (float) * (size_t) (frame - hop));
    std::memmove (accR.data(), accR.data() + hop, sizeof (float) * (size_t) (frame - hop));
    std::fill (accL.begin() + (frame - hop), accL.end(), 0.0f);
    std::fill (accR.begin() + (frame - hop), accR.end(), 0.0f);
    ++hopsDone;
}

void Engine::process (float* l, float* r, int n, const EngineParams& p) noexcept
{
    for (int pos = 0; pos < n;)
    {
        const int c = std::min (maxChunk, n - pos);
        processChunk (l + pos, r + pos, c, p);
        pos += c;
    }
}

void Engine::processChunk (float* l, float* r, int n, const EngineParams& p) noexcept
{
    if (n <= 0)
        return;
    for (int i = 0; i < n; ++i)
    {
        xL[(size_t) i] = (double) l[i];
        xR[(size_t) i] = (double) r[i];
    }

    // Bypass does not move the reported latency; it stops the engine and hands out the
    // aligned dry signal, so bypass is a wire.
    const bool want = p.spectral();
    bool running = false;
    if (p.bypass)
    {
        engineOn = false;
        fade = 0.0;
        currentAlignment = want ? latency : 0;
    }
    else
    {
        if (want && ! engineOn)
            startEngine();
        else if (! want && engineOn && fade <= 0.0)
            engineOn = false;
        running = engineOn || fade > 0.0;
        currentAlignment = running ? latency : 0;
    }

    // the dry delay line of the plugin input: Removed, Input and bypass read from it
    for (int i = 0; i < n; ++i)
    {
        dryL[(size_t) dryWrite] = xL[(size_t) i];
        dryR[(size_t) dryWrite] = xR[(size_t) i];
        dryWrite = (dryWrite + 1) % dryCap;
    }
    for (int i = 0; i < n; ++i)
    {
        const int at = ((dryWrite - currentAlignment - n + i) % dryCap + dryCap) % dryCap;
        alignedL[(size_t) i] = dryL[(size_t) at];
        alignedR[(size_t) i] = dryR[(size_t) at];
    }

    if (p.bypass)
    {
        const auto& srcL = currentAlignment > 0 ? alignedL : xL;
        const auto& srcR = currentAlignment > 0 ? alignedR : xR;
        for (int i = 0; i < n; ++i)
        {
            l[i] = (float) srcL[(size_t) i];
            r[i] = (float) srcR[(size_t) i];
        }
        return;
    }

    std::copy (xL.begin(), xL.begin() + n, humL.begin());
    std::copy (xR.begin(), xR.begin() + n, humR.begin());
    if (p.humOn)
        hum.process (humL.data(), humR.data(), n, p);

    if (running)
    {
        std::copy (humL.begin(), humL.begin() + n, inL.begin() + inCount);
        std::copy (humR.begin(), humR.begin() + n, inR.begin() + inCount);
        inCount += n;
        int used = 0;
        while (inCount - used >= hop)
        {
            hopStep (inL.data() + used, inR.data() + used, outL.data() + outCount, outR.data() + outCount, p);
            outCount += hop;
            used += hop;
        }
        if (used > 0)
        {
            std::memmove (inL.data(), inL.data() + used, sizeof (double) * (size_t) (inCount - used));
            std::memmove (inR.data(), inR.data() + used, sizeof (double) * (size_t) (inCount - used));
            inCount -= used;
        }
        // the switch crossfade (rule 2); while the engine primes the hum-only signal is heard
        if (primeLeft > 0)
            primeLeft = std::max (0, primeLeft - n);
        const double target = (engineOn && primeLeft == 0) ? 1.0 : 0.0;
        const double step = 1.0 / switchLen;
        double v = fade;
        const auto& unL = currentAlignment > 0 ? alignedL : humL;
        const auto& unR = currentAlignment > 0 ? alignedR : humR;
        for (int i = 0; i < n; ++i)
        {
            v = target > v ? std::min (v + step, target) : std::max (v - step, target);
            humL[(size_t) i] = unL[(size_t) i] * (1.0 - v) + outL[(size_t) i] * v;
            humR[(size_t) i] = unR[(size_t) i] * (1.0 - v) + outR[(size_t) i] * v;
        }
        fade = v;
        std::memmove (outL.data(), outL.data() + n, sizeof (double) * (size_t) (outCount - n));
        std::memmove (outR.data(), outR.data() + n, sizeof (double) * (size_t) (outCount - n));
        outCount -= n;
    }

    // humL/R is now the output y
    for (int i = 0; i < n; ++i)
    {
        double yl = humL[(size_t) i], yr = humR[(size_t) i];
        if (p.listen == LISTEN_INPUT)
        {
            yl = alignedL[(size_t) i];
            yr = alignedR[(size_t) i];
        }
        else if (p.listen == LISTEN_REMOVED)
        {
            yl = alignedL[(size_t) i] - yl;
            yr = alignedR[(size_t) i] - yr;
        }
        l[i] = (float) yl;
        r[i] = (float) yr;
    }
}

//==============================================================================
std::optional<double> Engine::findHum (const float* mono, int size, double sampleRate)
{
    // the strongest peak in 45-65 Hz, or half of the strongest in 100-130 Hz (sketch 4.2)
    const int n = std::min (size, (int) (2.0 * sampleRate));
    if (n < 2048)
        return std::nullopt;
    std::vector<double> xw ((size_t) n);
    for (int i = 0; i < n; ++i)   // np.hanning(n): the symmetric window
        xw[(size_t) i] = (double) mono[i] * (n > 1 ? 0.5 - 0.5 * std::cos (2.0 * k::PI * i / (n - 1)) : 1.0);
    const double binHz = sampleRate / n;
    struct Best { double hz = 0.0, level = -1.0; } best;
    for (const auto band : { std::array<double, 3> { 45.0, 65.0, 1.0 }, std::array<double, 3> { 100.0, 130.0, 2.0 } })
    {
        const int k0 = (int) std::ceil (band[0] / binHz), k1 = (int) std::floor (band[1] / binHz);
        double bandHz = 0.0, bandLevel = -1.0;
        for (int kk = k0; kk <= k1; ++kk)
        {
            const double w = 2.0 * k::PI * kk / n;
            double re = 0.0, im = 0.0;
            for (int i = 0; i < n; ++i)   // one bin of numpy's rfft, by direct evaluation
            {
                re += xw[(size_t) i] * std::cos (w * i);
                im -= xw[(size_t) i] * std::sin (w * i);
            }
            const double mag = std::hypot (re, im);
            if (mag > bandLevel)
            {
                bandLevel = mag;
                bandHz = kk * binHz / band[2];
            }
        }
        if (bandLevel >= 0.0 && bandLevel > best.level)
            best = { bandHz, bandLevel };
    }
    if (best.level < 0.0)
        return std::nullopt;
    return std::min (std::max (best.hz, 40.0), 70.0);
}

std::optional<double> Engine::estimateTail (const float* mono, int size, double sampleRate)
{
    // RT60 from the decay after the last transient, over the last 4 s (sketch 4.5)
    const int n = std::min (size, (int) (4.0 * sampleRate));
    const float* seg = mono + (size - n);
    const int win = std::max (1, pyRound (0.01 * sampleRate));
    std::vector<double> prefix ((size_t) n + 1, 0.0);
    for (int i = 0; i < n; ++i)
        prefix[(size_t) i + 1] = prefix[(size_t) i] + (double) seg[i] * (double) seg[i];
    std::vector<double> e ((size_t) n);
    const int shift = (win - 1) / 2;   // np.convolve(..., mode="same")
    for (int i = 0; i < n; ++i)
    {
        const int hi = std::min (n - 1, i + shift), lo = std::max (0, i + shift - (win - 1));
        const double ms = (prefix[(size_t) hi + 1] - prefix[(size_t) lo]) / win;
        const double env = std::sqrt (std::max (ms, 0.0));
        e[(size_t) i] = std::max (env > 0.0 ? 20.0 * std::log10 (env) : -6000.0, -120.0);
    }
    const int peak = (int) (std::max_element (e.begin(), e.end()) - e.begin());
    const int tailN = n - peak;
    if (tailN < 4 * win)
        return std::nullopt;
    const double ref = e[(size_t) peak];
    int lo = -1, hi = -1;
    for (int i = 0; i < tailN; ++i)
    {
        if (lo < 0 && e[(size_t) (peak + i)] <= ref - 5.0) lo = i;
        if (hi < 0 && e[(size_t) (peak + i)] <= ref - 25.0) { hi = i; break; }
    }
    if (lo < 0 || hi < 0 || hi <= lo + win)
        return std::nullopt;
    double st = 0.0, sy = 0.0;
    const int m = hi - lo;
    for (int i = lo; i < hi; ++i) { st += i / sampleRate; sy += e[(size_t) (peak + i)]; }
    const double tm = st / m, ym = sy / m;
    double num = 0.0, den = 0.0;
    for (int i = lo; i < hi; ++i)
    {
        const double dt = i / sampleRate - tm;
        num += dt * (e[(size_t) (peak + i)] - ym);
        den += dt * dt;
    }
    const double slope = den > 0.0 ? num / den : 0.0;
    if (slope >= -1.0e-6)
        return std::nullopt;
    return std::min (std::max (-60.0 / slope, 0.2), 4.0);
}
} // namespace cleanup
