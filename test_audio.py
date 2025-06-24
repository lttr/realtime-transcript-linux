#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import sys
import os
import time

# Suppress ALSA warnings
os.environ['ALSA_PCM_CARD'] = '0'
os.environ['ALSA_PCM_DEVICE'] = '0'
import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning)

try:
    import pyaudio
    import numpy as np
except ImportError as e:
    print(f"Error: {e}")
    sys.exit(1)

def list_audio_devices():
    """List all available audio input devices"""
    print("Available audio input devices:")
    audio = pyaudio.PyAudio()
    
    for i in range(audio.get_device_count()):
        device_info = audio.get_device_info_by_index(i)
        if device_info['maxInputChannels'] > 0:
            print(f"  Device {i}: {device_info['name']} (channels: {device_info['maxInputChannels']})")
    
    audio.terminate()

def test_audio_capture():
    """Test audio capture functionality"""
    print("\nTesting audio capture...")
    
    audio = pyaudio.PyAudio()
    
    # Find default input device
    try:
        default_device = audio.get_default_input_device_info()
        device_index = default_device['index']
        print(f"Using device: {default_device['name']}")
        
        # Test opening stream
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=1024
        )
        
        print("Recording 2 seconds of audio...")
        frames = []
        for _ in range(int(16000 / 1024 * 2)):  # 2 seconds
            data = stream.read(1024)
            frames.append(data)
        
        stream.stop_stream()
        stream.close()
        audio.terminate()
        
        # Analyze captured audio
        audio_data = b''.join(frames)
        audio_np = np.frombuffer(audio_data, dtype=np.int16)
        
        volume = np.sqrt(np.mean(audio_np.astype(np.float64)**2))
        print(f"Audio captured successfully! Average volume: {volume:.1f}")
        
        if volume > 100:
            print("✓ Audio capture working - detected sound")
        else:
            print("⚠ Audio capture working but no sound detected")
        
        return True
        
    except Exception as e:
        print(f"✗ Audio capture failed: {e}")
        return False

def main():
    print("Audio System Test")
    print("=" * 50)
    
    list_audio_devices()
    success = test_audio_capture()
    
    print("\n" + "=" * 50)
    if success:
        print("✓ Audio system is working correctly!")
        print("The voice transcription daemon should work properly.")
    else:
        print("✗ Audio system has issues that need to be resolved.")

if __name__ == "__main__":
    main()