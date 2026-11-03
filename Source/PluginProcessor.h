#pragma once

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_dsp/juce_dsp.h>

#include <array>
#include <atomic>
#include <cstring>

#include "Params.h"
#include "dsp/Engine.h"

/*  Clean Up - the processor.

    Thread model (sound-design-bob rule 1, D.1): the audio thread reads parameters through cached
    atomics, never by string lookup; nothing on the audio thread allocates, locks or logs. The
    continuous parameters are smoothed at block rate with the table's tau (Params::smoothing),
    as linear ramps so a parameter that does not move is exactly its value (G5 nulls the
    engine against the prototype). The switches' crossfades and Trim's per-sample ramp are
    the engine's, so the prototype runs the same arithmetic.

    The DSP is cleanup::Engine (Source/dsp/), the hand port of the G2 prototype. Its latency
    (0, or frame + lookahead once Click, Noise or Reverb is on) is published from the message
    thread by a timer, never from processBlock (rule 1). */
class CleanUpAudioProcessor final : public juce::AudioProcessor,
                                    private juce::Timer
{
public:
    CleanUpAudioProcessor();
    ~CleanUpAudioProcessor() override;

    // AudioProcessor
    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
    bool isBusesLayoutSupported (const BusesLayout& layouts) const override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;
    void processBlockBypassed (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return JucePlugin_Name; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }
    juce::AudioProcessorParameter* getBypassParameter() const override;

    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return {}; }
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock& destData) override;
    void setStateInformation (const void* data, int sizeInBytes) override;

    /** setStateInformation's work, with a verdict: false when the bytes are not a state of this
        plugin (foreign, truncated, newer); the state is then unchanged. The harness reports it. */
    bool loadState (const void* data, int sizeInBytes);

    /** The parameter tree; the editor attaches to it, the harness sets values through it. */
    juce::AudioProcessorValueTreeState& parameters() { return apvts; }

    /** What the editor may read from the audio thread: the 20 ms RMS per channel (D.6.2). */
    float outputLevel (int channel) const noexcept { return channel == 0 ? rmsL.load (std::memory_order_relaxed) : rmsR.load (std::memory_order_relaxed); }

    /** Publishes the latency the parameters imply (message thread; the timer calls it, the
        harness calls it after applying its flags). */
    void refreshLatency();

    /** The engine, for the editor's readouts and actions and for the harness. */
    cleanup::Engine& engine() noexcept { return dsp; }

private:
    void timerCallback() override { refreshLatency(); }
    void render (juce::AudioBuffer<float>& buffer, bool forceBypass) noexcept;
    cleanup::EngineParams readParams (int numSamples) noexcept;

    juce::AudioProcessorValueTreeState apvts;

    struct Smoothed
    {
        const char* id = nullptr;
        std::atomic<float>* raw = nullptr;
        juce::SmoothedValue<float, juce::ValueSmoothingTypes::Linear> value;
    };
    enum SmoothedIndex { sHumDepth, sHumWidth, sHumFreq, sClickThreshold, sClickLength, sClickCrackle,
                         sNoiseReduction, sNoiseSmooth, sNoiseFloor, sReverbAmount, sReverbTail, sReverbAttacks,
                         kNumSmoothed };
    std::array<Smoothed, kNumSmoothed> smoothed;
    std::atomic<float>* humOnP = nullptr;
    std::atomic<float>* humHarmonicsP = nullptr;
    std::atomic<float>* clickOnP = nullptr;
    std::atomic<float>* clickModeP = nullptr;
    std::atomic<float>* noiseOnP = nullptr;
    std::atomic<float>* noiseModeP = nullptr;
    std::atomic<float>* reverbOnP = nullptr;
    std::atomic<float>* listenP = nullptr;
    std::atomic<float>* trimP = nullptr;
    std::atomic<float>* bypassP = nullptr;

    cleanup::Engine dsp;
    // the Learned noise profile as the last state load brought it (message thread): applied at
    // every prepare, and saved again until the engine has published one of its own
    std::vector<float> loadedProfile;
    double loadedProfileRate = 0.0;
    int loadedProfileFrame = 0;
    std::atomic<bool> snapSmoothers { true };
    double currentSampleRate = 48000.0;
    std::atomic<float> rmsL { 0.0f }, rmsR { 0.0f };
    juce::dsp::BallisticsFilter<float> rmsFilterL, rmsFilterR;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (CleanUpAudioProcessor)
};
