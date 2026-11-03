#pragma once

/*  Clean Up - the DSP constants, ported by hand from the G2 prototype
    (`sound design/prototype/cleanup_proto.py`, the constants block). Every name and value is the
    prototype's; the reason for each value, and the measurement that set it, is written there
    beside it and is not repeated here. G5 nulls this port against that file, so a constant is
    changed in both places or in neither.

    Every length is in seconds and converted in prepare() (rule 12). */

namespace cleanup::k
{
inline constexpr double PI = 3.141592653589793238462643383279502884;   // Python's math.pi

// Framing
inline constexpr double FRAME_SECONDS = 2048.0 / 48000.0;   // 42.667 ms, rounded up to 2^n at the rate
inline constexpr int    OVERLAP = 4;                         // hop = frame / 4
inline constexpr double WOLA_HANN_SUM = 1.5;                 // sum of squared periodic Hann at hop = N/4

// Hum
inline constexpr double HUM_TRACK_TAU_S = 2.0;
inline constexpr double HUM_TRACK_RANGE_HZ = 0.5;
inline constexpr double HUM_TRACK_UPDATE_S = 32.0 / 48000.0;
inline constexpr double HUM_TRACK_LP_TAU_S = 0.200;
inline constexpr int    HUM_TRACK_LP_STAGES = 2;
inline constexpr double HUM_TRACK_PHASE_GAP_S = 0.100;
inline constexpr double HUM_TRACK_GATE = 1.0e-5;
inline constexpr double HUM_TRACK_WARMUP_S = 5.0 * HUM_TRACK_LP_TAU_S;
inline constexpr double HUM_TRACK_RECOEF_HZ = 0.001;
inline constexpr double HUM_BYPASS_DEPTH_DB = -0.01;
inline constexpr int    HUM_MAX_HARMONICS = 16;

// Click
inline constexpr int    CLICK_AR_ORDER = 32;
inline constexpr int    CLICK_CRACKLE_AR_ORDER = 8;
inline constexpr double CLICK_BURG_BLOCK_S = 0.010;
inline constexpr int    CLICK_REPAIR_AR_ORDER = 192;
inline constexpr double CLICK_REPAIR_BURG_BLOCK_S = 0.040;
inline constexpr double CLICK_SIGMA_AT_0 = 40.0;
inline constexpr double CLICK_SIGMA_AT_100 = 6.0;
inline constexpr double CLICK_MERGE_S = 0.001;
inline constexpr double CLICK_EXTEND_SIGMA = 6.0;
inline constexpr double CLICK_EXTEND_MAX_S = 0.001;
inline constexpr double CLICK_EXTEND_GAP_S = 0.00025;
inline constexpr double CLICK_RUN_SLACK_ORDER = 1.0;
inline constexpr double CLICK_ABS_FLOOR_DBFS = -80.0;
inline constexpr double CLICK_MAX_STEP_DB = 12.0;
inline constexpr double CLICK_RUNAWAY_FACTOR = 4.0;
inline constexpr double CLICK_CRACKLE_LENGTH_S = 0.0005;
inline constexpr double CLICK_CONTEXT_S = 64.0 / 48000.0;
inline constexpr double CLICK_STEP_LONG_S = 0.005;
inline constexpr double CLICK_XFADE_S = 8.0 / 48000.0;
inline constexpr double CLICK_LOOKAHEAD_S = 0.012;
inline constexpr double CLICK_MISSED_SIGMA_MARGIN = 1.0;
inline constexpr double CLICK_COUNT_WINDOW_S = 6.0;

// Noise
inline constexpr double NOISE_MINSTAT_WINDOW_S = 1.5;
inline constexpr int    NOISE_MINSTAT_SUBWINDOWS = 6;
inline constexpr double NOISE_MINSTAT_SMOOTH_S = 0.200;
inline constexpr double NOISE_MINSTAT_BIAS_DB = 1.8;
inline constexpr double NOISE_DD_TAU_AT_0_S = 0.25;
inline constexpr double NOISE_DD_TAU_AT_100_S = 4.0;
inline constexpr double NOISE_LEARN_S = 1.0;
inline constexpr double NOISE_LEARN_MAX_DBFS = -40.0;

// Reverb (the G3 decision on its gain law is open: docs/status.md, Waiting for Björn)
inline constexpr double REVERB_PREDELAY_S = 0.050;
inline constexpr double REVERB_SMOOTH_FRAMES = 2.0;
inline constexpr double REVERB_FLOOR_DB_AT_FULL = -24.0;
inline constexpr double REVERB_ATTACK_HOLD_S = 0.040;
inline constexpr double REVERB_FLUX_TAU_S = 0.200;
inline constexpr double REVERB_FLUX_FACTOR = 1.6;

// Switching between the two latency states, Hum on/off, Listen and Bypass (rule 2)
inline constexpr double SWITCH_XFADE_S = 0.015;
inline constexpr double TRIM_RAMP_S = 0.092;   // Trim's multiplicative ramp: 4.6 x the table's 20 ms tau

// The Removed display's bands: 1/6 octave, 50 Hz to 10 kHz (sketch 4.6)
inline constexpr double BAND_LOW_HZ = 50.0;
inline constexpr double BAND_HIGH_HZ = 10000.0;
inline constexpr int    BANDS_PER_OCTAVE = 6;
inline constexpr int    NUM_BANDS = 46;   // round(6 log2(200)); checked in Engine::prepare
} // namespace cleanup::k

namespace cleanup
{
enum Listen : int { LISTEN_OUTPUT = 0, LISTEN_REMOVED = 1, LISTEN_INPUT = 2 };
enum ClickMode : int { MODE_CLICKS = 0, MODE_CRACKLE = 1 };
enum Profile : int { PROFILE_LEARNED = 0, PROFILE_ADAPTIVE = 1 };

/** The plugin's parameters in plain units, exactly the rows of parameters.csv and the
    prototype's `Params` (same names, same defaults). */
struct EngineParams
{
    bool   humOn = false;
    double humDepth = -24.0;
    int    humHarmonics = 8;
    double humWidth = 2.0;
    double humFreq = 50.0;
    bool   clickOn = false;
    double clickThreshold = 55.0;
    double clickLength = 2.5;
    double clickCrackle = 0.0;
    int    clickMode = MODE_CLICKS;
    bool   noiseOn = false;
    double noiseReduction = -12.0;
    double noiseSmooth = 40.0;
    double noiseFloor = -60.0;
    int    noiseMode = PROFILE_ADAPTIVE;
    bool   reverbOn = false;
    double reverbAmount = 35.0;
    double reverbTail = 0.9;
    double reverbAttacks = 60.0;
    int    listen = LISTEN_OUTPUT;
    double trim = 0.0;
    bool   bypass = false;

    bool spectral() const noexcept { return clickOn || noiseOn || reverbOn; }
};
} // namespace cleanup
