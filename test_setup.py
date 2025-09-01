#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import sys
import subprocess

def test_system_dependencies():
    print("=== Testing System Dependencies ===")
    
    # Test xdotool
    try:
        result = subprocess.run(['which', 'xdotool'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✓ xdotool: FOUND")
        else:
            print("✗ xdotool: NOT FOUND - Install with: sudo apt install xdotool")
    except Exception as e:
        print(f"✗ xdotool: ERROR - {e}")
    
    # Test notify-send (optional)
    try:
        result = subprocess.run(['which', 'notify-send'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✓ notify-send: FOUND")
        else:
            print("? notify-send: NOT FOUND (optional) - Install with: sudo apt install libnotify-bin")
    except Exception as e:
        print(f"? notify-send: ERROR - {e}")

def test_python_dependencies():
    print("\n=== Testing Python Dependencies ===")
    
    # Test RealtimeSTT
    try:
        import RealtimeSTT
        print("✓ RealtimeSTT: IMPORTED")
    except ImportError:
        print("✗ RealtimeSTT: NOT FOUND - Run: pip install -r requirements.txt")
        return False
    
    return True

def test_basic_functionality():
    print("\n=== Testing Basic Audio Setup ===")
    
    try:
        # Test pyaudio import
        import pyaudio
        print("✓ PyAudio: WORKING")
        
        # Test numpy import  
        import numpy
        print("✓ NumPy: WORKING")
        
        return True
        
    except Exception as e:
        print(f"✗ Basic functionality: ERROR - {e}")
        return False

def main():
    print("Voice Transcription System - Setup Test")
    print("=" * 50)
    
    test_system_dependencies()
    deps_ok = test_python_dependencies()
    basic_ok = test_basic_functionality()
    
    print("\n=== Summary ===")
    if deps_ok and basic_ok:
        print("✓ Basic setup looks good!")
        print("Next steps:")
        print("1. Configure API key: cp .env.example .env && edit .env")
        print("2. Test the system: ./voice_transcription.py status")
        print("3. Test transcription: ./voice_transcription.py")
    else:
        print("✗ Some issues found. Please resolve them before proceeding.")

if __name__ == "__main__":
    main()