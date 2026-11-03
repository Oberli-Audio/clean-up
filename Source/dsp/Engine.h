#pragma once

#include "Click.h"
#include "Constants.h"
#include "Hum.h"
#include "Spectral.h"

#include <juce_dsp/juce_dsp.h>

#include <array>
#include <atomic>
#include <cstdint>
#include <memory>
#include <optional>
#include <vector>

/*  Clean Up's whole signal path, the prototype's `CleanUp` class with the same lifecycle:
    Hum in the time domain (zero latency), then one WOLA STFT (periodic Hann, 4x overlap, frame
    in seconds rounded up to 2^n) that Click, Noise and Reverb share, the switch crossfade
    between the two latency states, the dry delay line Listen and bypass read from, and the
    Removed display's band energies.

    prepare() allocates; reset() and process() do not (rule 1). A host block larger than the one
    announced is processed in chunks of at most max(maxBlock, hop), so the buffers never grow;
    a block up to that size runs exactly as one prototype `process_block` call (G5).

    The switches (Hum on/off, Listen, Bypass) are crossfaded and Trim is a multiplicative ramp
    here, in the engine, so the prototype runs the same arithmetic (rules 2 and 7). */

namespace cleanup
{
class Engine
{
public:
    void prepare (double sampleRate, int maxBlock);
    void reset() noexcept;

    /** In place, two channels, any n >= 0. */
    void process (float* l, float* r, int n, const EngineParams& p) noexcept;

    int latencySamples() const noexcept { return latency; }   // frame + lookahead, the spectral state
    int alignment() const noexcept { return currentAlignment; }
    int frameSize() const noexcept { return frame; }
    int hopSize() const noexcept { return hop; }

    /** Learn starts at the next hop (an editor action; brief: one second of noise only). */
    void requestLearn() noexcept { learnRequested.store (true, std::memory_order_release); }

    // the readouts
    const ClickRepair& clickStage() const noexcept { return click; }
    const NoiseWiener& noiseStage() const noexcept { return noise; }
    const ReverbSubtract& reverbStage() const noexcept { return reverb; }
    NoiseWiener& noiseStage() noexcept { return noise; }
    double trackedHumHz() const noexcept { return hum.trackedHz(); }
    std::array<std::atomic<float>, k::NUM_BANDS> inputBands {}, removedBands {};
    // the harness's totals over a render (not read by the editor)
    std::array<double, k::NUM_BANDS> inputTotal {}, removedTotal {};
    std::int64_t hopsDone = 0;

    // editor actions on captured audio, message thread (sketch 4.2, 4.5)
    static std::optional<double> findHum (const float* mono, int n, double sampleRate);
    static std::optional<double> estimateTail (const float* mono, int n, double sampleRate);

private:
    void processChunk (float* l, float* r, int n, const EngineParams& p) noexcept;
    void startEngine() noexcept;
    void hopStep (const double* inL, const double* inR, double* outL, double* outR, const EngineParams& p) noexcept;

    HumComb hum;
    ClickRepair click;
    NoiseWiener noise;
    ReverbSubtract reverb;

    double fs = 48000.0;
    int frame = 2048, hop = 512, bins = 1025, lookahead = 0, latency = 0, switchLen = 1;
    int maxChunk = 512, tdLen = 0, dryCap = 0;
    double winEnergy = 1.0;
    float wolaScale = 1.0f;
    std::vector<float> window;
    std::array<int, k::NUM_BANDS + 1> bandEdges {};

    std::unique_ptr<juce::dsp::FFT> fft;
    std::vector<float> fftL, fftR, power, power2, gTotal, accL, accR;
    std::vector<double> before;

    std::vector<double> tdL, tdR;                  // [ click history | frame | lookahead ]
    std::vector<double> inL, inR, outL, outR;      // the hop FIFOs
    int inCount = 0, outCount = 0;
    std::vector<double> dryL, dryR;                // the dry delay line (a ring)
    int dryWrite = 0;
    std::vector<double> xL, xR, humL, humR, alignedL, alignedR;   // per-chunk work

    bool engineOn = false;
    int primeLeft = 0, currentAlignment = 0;
    double fade = 0.0;
    // the switch crossfades and Trim, snapped on the first chunk after reset
    bool snap = true;
    double humMix = 0.0, bypassMix = 0.0;
    std::array<double, 3> listenMix { 1.0, 0.0, 0.0 };
    double trimGain = 1.0, trimTarget = 1.0, trimFactor = 1.0;
    int trimLeft = 0, trimSteps = 1;
    std::int64_t fed = 0;
    std::atomic<bool> learnRequested { false };
};
} // namespace cleanup
