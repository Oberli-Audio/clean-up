#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "State.h"

#include <cmath>

namespace
{
std::atomic<float>* param (juce::AudioProcessorValueTreeState& apvts, const char* id)
{
    auto* p = apvts.getRawParameterValue (id);
    jassert (p != nullptr);   // the table and the code disagree: parameters.csv is the source
    return p;
}

float tauMsOf (const char* id)
{
    for (const auto& s : Params::smoothing)
        if (std::strcmp (s.id, id) == 0)
            return s.tauMs;
    return 0.0f;
}
} // namespace

CleanUpAudioProcessor::CleanUpAudioProcessor()
    : AudioProcessor (BusesProperties()
                          .withInput ("Input", juce::AudioChannelSet::stereo(), true)
                          .withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      apvts (*this, nullptr, "PARAMETERS", Params::createParameterLayout())
{
    const char* ids[kNumSmoothed] = { Params::humDepth, Params::humWidth, Params::humFreq,
                                      Params::clickThreshold, Params::clickLength, Params::clickCrackle,
                                      Params::noiseReduction, Params::noiseSmooth, Params::noiseFloor,
                                      Params::reverbAmount, Params::reverbTail, Params::reverbAttacks };
    for (int i = 0; i < kNumSmoothed; ++i)
    {
        smoothed[(size_t) i].id = ids[i];
        smoothed[(size_t) i].raw = param (apvts, ids[i]);
    }
    humOnP = param (apvts, Params::humOn);
    humHarmonicsP = param (apvts, Params::humHarmonics);
    clickOnP = param (apvts, Params::clickOn);
    clickModeP = param (apvts, Params::clickMode);
    noiseOnP = param (apvts, Params::noiseOn);
    noiseModeP = param (apvts, Params::noiseMode);
    reverbOnP = param (apvts, Params::reverbOn);
    listenP = param (apvts, Params::listen);
    trimP = param (apvts, Params::trim);
    bypassP = param (apvts, Params::bypassParameterId);
    startTimerHz (10);
}

CleanUpAudioProcessor::~CleanUpAudioProcessor()
{
    stopTimer();
}

void CleanUpAudioProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    currentSampleRate = sampleRate;
    dsp.prepare (sampleRate, juce::jmax (1, samplesPerBlock));
    for (auto& s : smoothed)
        s.value.reset (sampleRate, (double) tauMsOf (s.id) * 4.6 / 1000.0);
    snapSmoothers.store (true);
    juce::dsp::ProcessSpec spec { sampleRate, (juce::uint32) juce::jmax (1, samplesPerBlock), 1 };
    for (auto* f : { &rmsFilterL, &rmsFilterR })
    {
        f->prepare (spec);
        f->setLevelCalculationType (juce::dsp::BallisticsFilterLevelCalculationType::RMS);
        f->setAttackTime (20.0f);
        f->setReleaseTime (20.0f);
    }
    rmsL.store (0.0f);
    rmsR.store (0.0f);
    refreshLatency();
}

void CleanUpAudioProcessor::releaseResources() {}

void CleanUpAudioProcessor::refreshLatency()
{
    const bool spectral = clickOnP->load() >= 0.5f || noiseOnP->load() >= 0.5f || reverbOnP->load() >= 0.5f;
    const int want = spectral ? dsp.latencySamples() : 0;
    if (want != getLatencySamples())
        setLatencySamples (want);
}

bool CleanUpAudioProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    if (layouts.getMainOutputChannelSet() != juce::AudioChannelSet::stereo())
        return false;
    return layouts.getMainInputChannelSet() == juce::AudioChannelSet::stereo()
        || layouts.getMainInputChannelSet() == juce::AudioChannelSet::mono();
}

juce::AudioProcessorParameter* CleanUpAudioProcessor::getBypassParameter() const
{
    return apvts.getParameter (Params::bypassParameterId);
}

cleanup::EngineParams CleanUpAudioProcessor::readParams (int numSamples) noexcept
{
    const bool snap = snapSmoothers.exchange (false);
    for (auto& s : smoothed)
    {
        const float target = s.raw->load (std::memory_order_relaxed);
        if (snap)
            s.value.setCurrentAndTargetValue (target);
        else
        {
            s.value.setTargetValue (target);
            s.value.skip (numSamples);
        }
    }

    auto v = [this] (SmoothedIndex i) { return (double) smoothed[(size_t) i].value.getCurrentValue(); };
    cleanup::EngineParams p;
    p.humOn = humOnP->load() >= 0.5f;
    p.humDepth = v (sHumDepth);
    p.humHarmonics = juce::roundToInt (humHarmonicsP->load());
    p.humWidth = v (sHumWidth);
    p.humFreq = v (sHumFreq);
    p.clickOn = clickOnP->load() >= 0.5f;
    p.clickThreshold = v (sClickThreshold);
    p.clickLength = v (sClickLength);
    p.clickCrackle = v (sClickCrackle);
    p.clickMode = juce::roundToInt (clickModeP->load());
    p.noiseOn = noiseOnP->load() >= 0.5f;
    p.noiseReduction = v (sNoiseReduction);
    p.noiseSmooth = v (sNoiseSmooth);
    p.noiseFloor = v (sNoiseFloor);
    p.noiseMode = juce::roundToInt (noiseModeP->load());
    p.reverbOn = reverbOnP->load() >= 0.5f;
    p.reverbAmount = v (sReverbAmount);
    p.reverbTail = v (sReverbTail);
    p.reverbAttacks = v (sReverbAttacks);
    p.listen = juce::roundToInt (listenP->load());
    p.trim = trimP->load();                        // the engine ramps it per sample
    p.bypass = bypassP->load() >= 0.5f;
    return p;
}

void CleanUpAudioProcessor::render (juce::AudioBuffer<float>& buffer, bool forceBypass) noexcept
{
    juce::ScopedNoDenormals noDenormals;
    const int numSamples = buffer.getNumSamples();
    const int inputs = getTotalNumInputChannels();
    for (int ch = inputs; ch < getTotalNumOutputChannels(); ++ch)
        buffer.clear (ch, 0, numSamples);
    if (numSamples == 0)   // a zero-length block is legal (harness contract, D.5.1)
        return;
    if (inputs == 1 && buffer.getNumChannels() > 1)
        buffer.copyFrom (1, 0, buffer, 0, 0, numSamples);   // mono in, the engine is stereo-linked

    auto p = readParams (numSamples);
    p.bypass = p.bypass || forceBypass;
    auto* l = buffer.getWritePointer (0);
    auto* r = buffer.getNumChannels() > 1 ? buffer.getWritePointer (1) : l;
    dsp.process (l, r, numSamples, p);

    float lastL = 0.0f, lastR = 0.0f;
    for (int i = 0; i < numSamples; ++i)
    {
        lastL = rmsFilterL.processSample (0, l[i]);
        lastR = rmsFilterR.processSample (0, r[i]);
    }
    rmsL.store (lastL, std::memory_order_relaxed);
    rmsR.store (lastR, std::memory_order_relaxed);
}

void CleanUpAudioProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
{
    render (buffer, false);
}

void CleanUpAudioProcessor::processBlockBypassed (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
{
    render (buffer, true);   // latency-compensated, a wire (rule 7)
}

juce::AudioProcessorEditor* CleanUpAudioProcessor::createEditor()
{
    return new CleanUpAudioProcessorEditor (*this);
}

void CleanUpAudioProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    copyXmlToBinary (*cleanup::State::toXml (apvts), destData);
}

void CleanUpAudioProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    loadState (data, sizeInBytes);
}

bool CleanUpAudioProcessor::loadState (const void* data, int sizeInBytes)
{
    // arbitrary bytes are refused, never crashed on (D.5.3): a foreign or newer blob leaves the state as it is
    if (data == nullptr || sizeInBytes <= 0)
        return false;
    auto xml = getXmlFromBinary (data, sizeInBytes);
    if (xml == nullptr)
        return false;
    auto* state = cleanup::State::stateOf (*xml);
    const bool ok = state != nullptr && cleanup::State::fromXml (*state, apvts);
    if (ok)
        snapSmoothers.store (true);
    return ok;
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new CleanUpAudioProcessor();
}
