#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import subprocess
import shutil
from audio_utils import is_wayland


def test_system_dependencies():
    print("=== System Dependencies ===")

    # Audio recorder
    for cmd in ['pw-record', 'parecord', 'arecord']:
        if shutil.which(cmd):
            print(f"✓ {cmd}: FOUND")
            break
    else:
        print("✗ No audio recorder found - install pipewire or pulseaudio-utils")

    # Display server tools
    if is_wayland():
        print(f"  Display: Wayland")
        for cmd, pkg in [('wl-copy', 'wl-clipboard'), ('wtype', 'wtype')]:
            if shutil.which(cmd):
                print(f"✓ {cmd}: FOUND")
            else:
                print(f"✗ {cmd}: NOT FOUND - install {pkg}")
    else:
        # X11 support
        print(f"  Display: X11")
        for cmd in ['xdotool', 'xsel']:
            if shutil.which(cmd):
                print(f"✓ {cmd}: FOUND")
            else:
                print(f"✗ {cmd}: NOT FOUND - sudo apt install {cmd}")

    # Notifications (optional)
    if shutil.which('notify-send'):
        print("✓ notify-send: FOUND")
    else:
        print("? notify-send: NOT FOUND (optional)")


def test_python_dependencies():
    print("\n=== Python Dependencies ===")
    ok = True

    deps = [
        ('numpy', 'numpy'),
        ('requests', 'requests'),
        ('dotenv', 'python-dotenv'),
        ('websockets', 'websockets'),
        ('assemblyai', 'assemblyai'),
    ]

    for module, package in deps:
        try:
            __import__(module)
            print(f"✓ {package}: OK")
        except ImportError:
            print(f"✗ {package}: NOT FOUND")
            ok = False

    return ok


def test_api_keys():
    print("\n=== API Keys ===")
    import os
    from pathlib import Path

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent / '.env')
    except ImportError:
        pass

    for key_name in ['ASSEMBLYAI_API_KEY', 'ELEVENLABS_API_KEY']:
        val = os.getenv(key_name)
        if val:
            print(f"✓ {key_name}: configured ({val[:8]}...)")
        else:
            print(f"? {key_name}: not set")


def main():
    print("Voice Transcription - Setup Test")
    print("=" * 50)

    test_system_dependencies()
    deps_ok = test_python_dependencies()
    test_api_keys()

    print("\n=== Summary ===")
    if deps_ok:
        print("✓ Setup looks good!")
    else:
        print("✗ Missing dependencies. Run: pip install -r requirements.txt")


if __name__ == "__main__":
    main()
