#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import sys
import subprocess
import numpy as np
from audio_utils import find_recorder


def test_audio_capture():
    """Test audio capture using system recorder (pw-record/parecord/arecord)"""
    print("Audio System Test")
    print("=" * 50)

    recorder_cmd = find_recorder()
    if not recorder_cmd:
        print("✗ No audio recorder found. Install pipewire, pulseaudio-utils, or alsa-utils.")
        return False

    print(f"Using recorder: {recorder_cmd[0]}")
    print("Recording 2 seconds of audio...")

    try:
        process = subprocess.Popen(
            recorder_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )

        sample_rate = 16000
        chunk_size = 1024
        bytes_per_sample = 2
        chunks_needed = int(sample_rate / chunk_size * 2)  # 2 seconds
        frames = []

        for _ in range(chunks_needed):
            data = process.stdout.read(chunk_size * bytes_per_sample)
            if not data:
                break
            frames.append(data)

        process.terminate()
        process.wait(timeout=1)

        if not frames:
            print("✗ No audio data captured")
            return False

        audio_data = b''.join(frames)
        audio_np = np.frombuffer(audio_data, dtype=np.int16)
        volume = np.sqrt(np.mean(audio_np.astype(np.float64) ** 2))

        print(f"Audio captured successfully! Average volume: {volume:.1f}")

        if volume > 100:
            print("✓ Audio capture working - detected sound")
        else:
            print("⚠ Audio capture working but no sound detected")

        return True

    except Exception as e:
        print(f"✗ Audio capture failed: {e}")
        return False


if __name__ == "__main__":
    success = test_audio_capture()
    print()
    if success:
        print("✓ Audio system is working correctly!")
    else:
        print("✗ Audio system has issues that need to be resolved.")
    sys.exit(0 if success else 1)
