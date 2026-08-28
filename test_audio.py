#!/home/lukas/code/realtime-transcript-linux/venv/bin/python
"""Microphone check and level calibration.

`./test_audio.py` verifies capture works at all. `./test_audio.py calibrate`
measures silence and speech SEPARATELY and checks the `audio_levels.py`
constants against what this mic actually produces.

Measuring the two phases separately is the whole point: a single recording of
someone talking has a "minimum" around 1000 RMS, which looks exactly like a noise
floor and is not one. Tuning SILENCE_RMS from that number would put the silence
threshold above normal speech and cut sessions off mid-sentence.
"""

import sys
import subprocess
import numpy as np
from audio_utils import find_recorder
from audio_levels import SILENCE_RMS, DISPLAY_FLOOR_RMS, LOUD_RMS, rms_to_level

SAMPLE_RATE = 16000
CHUNK_BYTES = 1024 * 2


def record_rms(seconds, recorder_cmd):
    """Record for `seconds` and return per-chunk int16 RMS values."""
    process = subprocess.Popen(
        recorder_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    try:
        values = []
        for _ in range(int(SAMPLE_RATE / 1024 * seconds)):
            data = process.stdout.read(CHUNK_BYTES)
            if len(data) < CHUNK_BYTES:
                break
            audio = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            values.append(float(np.sqrt(np.mean(audio ** 2))))
        return values
    finally:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()


def percentile(values, p):
    return sorted(values)[min(len(values) - 1, int(len(values) * p))]


def describe(label, values):
    print(f"  {label:8} min {min(values):7.0f}   median {percentile(values, 0.5):7.0f}"
          f"   p90 {percentile(values, 0.9):7.0f}   max {max(values):7.0f}")


def test_audio_capture():
    """Verify audio capture works using the system recorder."""
    print("Audio System Test")
    print("=" * 50)

    recorder_cmd = find_recorder()
    if not recorder_cmd:
        print("✗ No audio recorder found. Install pipewire, pulseaudio-utils, or alsa-utils.")
        return False

    print(f"Using recorder: {recorder_cmd[0]}")
    print("Recording 2 seconds of audio...")

    try:
        values = record_rms(2, recorder_cmd)
    except Exception as e:
        print(f"✗ Audio capture failed: {e}")
        return False

    if not values:
        print("✗ No audio data captured")
        return False

    describe("captured", values)
    # pw-record emits ~0.6s of full-scale samples at startup, so judge on the
    # median rather than the peak.
    if percentile(values, 0.5) > SILENCE_RMS:
        print("✓ Audio capture working - detected sound")
    else:
        print("⚠ Audio capture working but no sound detected (silent room?)")
    print("\nRun './test_audio.py calibrate' to check the level constants.")
    return True


def calibrate():
    """Measure silence and speech separately, then check the level constants."""
    print("Audio Level Calibration")
    print("=" * 50)

    recorder_cmd = find_recorder()
    if not recorder_cmd:
        print("✗ No audio recorder found.")
        return False

    print(f"Using recorder: {recorder_cmd[0]}")
    print(f"Current constants: SILENCE_RMS={SILENCE_RMS:.0f} "
          f"DISPLAY_FLOOR_RMS={DISPLAY_FLOOR_RMS:.0f} LOUD_RMS={LOUD_RMS:.0f}\n")

    input("Phase 1/2 - stay SILENT for 5s. Press Enter when ready...")
    silence = record_rms(5, recorder_cmd)
    describe("silence", silence)

    input("\nPhase 2/2 - SPEAK normally for 8s. Press Enter when ready...")
    # Skip the first second: pw-record emits full-scale samples at startup.
    speech = record_rms(8, recorder_cmd)[16:]
    describe("speech", speech)

    if not silence or not speech:
        print("\n✗ Not enough audio captured to calibrate.")
        return False

    # Median, not a high percentile: a "silent" room still has sparse keyboard
    # and mouse transients (measured up to ~270 RMS here) which are not the noise
    # floor. Judging the floor by p90 would reject perfectly good constants.
    noise_floor = percentile(silence, 0.5)
    # Compare against QUIET speech (p10), not median speech: the threshold must
    # sit below the softest thing the user says, or trailing-off sentence ends
    # get treated as silence and the session cuts out mid-sentence.
    quiet_speech = percentile(speech, 0.1)
    transient = sum(1 for v in silence if v > SILENCE_RMS) / len(silence)

    print("\nVerdict")
    print("-" * 50)
    ok = True

    if SILENCE_RMS <= noise_floor:
        print(f"✗ SILENCE_RMS ({SILENCE_RMS:.0f}) is at or below the noise floor "
              f"({noise_floor:.0f}) - silence will never be detected, so sessions "
              f"will run until the 300s cap. Raise it above {noise_floor:.0f}.")
        ok = False
    elif SILENCE_RMS >= quiet_speech:
        print(f"✗ SILENCE_RMS ({SILENCE_RMS:.0f}) is at or above quiet speech "
              f"({quiet_speech:.0f}) - sessions will cut off mid-sentence. "
              f"Lower it well below {quiet_speech:.0f}.")
        ok = False
    else:
        print(f"✓ SILENCE_RMS ({SILENCE_RMS:.0f}) sits between the noise floor "
              f"({noise_floor:.0f}) and quiet speech ({quiet_speech:.0f}).")

    # Sparse transients above the threshold are fine - they just briefly reset
    # the overlay fade. Constant ones would stop the silence timeout firing.
    print(f"\n  silent chunks above SILENCE_RMS: {transient * 100:.0f}% "
          f"(keyboard/mouse transients)")
    if transient > 0.5:
        print("✗ The mic is above the silence threshold most of the time - "
              "the silence timeout will rarely fire. Raise SILENCE_RMS or "
              "reduce background noise.")
        ok = False

    # The bars should neither sit flat nor peg at full height during speech.
    levels = [rms_to_level(v) for v in speech]
    low, high = percentile(levels, 0.1), percentile(levels, 0.9)
    clipped = sum(1 for l in levels if l >= 1.0) / len(levels)
    print(f"\n  bar levels during speech: p10 {low:.2f}  p90 {high:.2f}  "
          f"clipped {clipped * 100:.0f}%")
    if clipped > 0.25:
        print(f"✗ Bars clip at full height {clipped * 100:.0f}% of the time - "
              f"raise LOUD_RMS. This is what made the bars look frozen.")
        ok = False
    elif high - low < 0.25:
        print("✗ Bars barely move (p90 - p10 < 0.25) - narrow the gap between "
              "DISPLAY_FLOOR_RMS and LOUD_RMS.")
        ok = False
    else:
        print("✓ Bars use a healthy portion of their range.")

    print("\n" + ("✓ Level constants fit this microphone."
                  if ok else "✗ Update the constants in audio_levels.py."))
    return ok


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "calibrate":
        sys.exit(0 if calibrate() else 1)

    success = test_audio_capture()
    print()
    print("✓ Audio system is working correctly!" if success
          else "✗ Audio system has issues that need to be resolved.")
    sys.exit(0 if success else 1)
