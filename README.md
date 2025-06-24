# Voice Transcription with Global Keyboard Shortcut

A real-time voice transcription system for Linux that transcribes speech and automatically types it into the currently active window. Triggered by a global keyboard shortcut (Ctrl+Shift+Alt+K).

## Features

- **Real-time transcription** using OpenAI's Whisper model (CPU-optimized)
- **Global keyboard shortcut** integration with GNOME
- **Automatic speech detection** - detects when you start and stop speaking
- **Lightning-fast responses** - sub-second transcription with preloaded model
- **Text injection** - automatically types transcribed text into active window
- **CPU-only operation** - no GPU required
- **English language optimized** for best performance

## How It Works

1. **Background daemon** (`voice_daemon.py`) preloads Whisper model for instant responses
2. **Trigger script** (`voice_trigger.py`) is called by GNOME keyboard shortcut
3. Scripts communicate via Unix socket for fast IPC
4. **Brief microphone access** - only during actual recording (1-10 seconds)
5. **Preloaded model transcription** - sub-second processing of captured audio
6. Transcribed text is injected into the active window using `xdotool`

## System Requirements

- **OS**: Ubuntu 20.04+ or similar Linux distribution with GNOME
- **Python**: 3.8+
- **Audio**: Working microphone
- **Memory**: At least 1GB RAM available
- **CPU**: Any modern CPU (optimized for CPU-only operation)

## Performance

- **Startup time**: ~0.4 seconds (model preloading)
- **Response time**: ~0.3 seconds (after recording completes)
- **Microphone usage**: Only during 1-10 second recording periods
- **Memory usage**: ~200MB for preloaded model
- **CPU usage**: Minimal when idle, brief spike during transcription

## Installation

### 1. Install System Dependencies

```bash
# Update package list
sudo apt update

# Install required system packages
sudo apt install python3 python3-pip python3-dev portaudio19-dev xdotool

# Optional: Install notification support
sudo apt install libnotify-bin
```

### 2. Clone and Setup Project

```bash
# Navigate to the project directory
cd ~/code/realtime-transcript-linux

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies (faster-whisper, PyAudio, numpy)
pip install -r requirements.txt
```

### 3. Make Scripts Executable

```bash
chmod +x voice_daemon.py voice_trigger.py
```

### 4. Setup Systemd Service (Recommended)

The daemon should run automatically on login:

```bash
# Copy service file to user systemd directory
mkdir -p ~/.config/systemd/user
cp voice-transcriber.service ~/.config/systemd/user/

# Enable and start the service
systemctl --user daemon-reload
systemctl --user enable voice-transcriber.service
systemctl --user start voice-transcriber.service

# Check service status
systemctl --user status voice-transcriber.service
```

### 5. Configure GNOME Keyboard Shortcut

1. Open **Settings** → **Keyboard** → **Keyboard Shortcuts**
2. Click **"View and Customize Shortcuts"**
3. Scroll down and click **"Custom Shortcuts"**
4. Click the **"+"** button to add a new shortcut
5. Configure the shortcut:
   - **Name**: `Voice Transcription`
   - **Command**: `/home/lukas/code/realtime-transcript-linux/voice_trigger.py`
   - **Shortcut**: Press `Ctrl+Shift+Alt+K` (or your preferred combination)

## Usage

1. **Start the system**: The daemon should start automatically on login (if using systemd service)
2. **Press the keyboard shortcut**: `Ctrl+Shift+Alt+K`
3. **Speak clearly**: The system will show a notification that it's recording
4. **Stop speaking**: The system automatically detects when you stop talking
5. **Text appears**: Transcribed text is automatically typed into the active window

### Manual Operation

You can also run the components manually for testing:

```bash
# Start daemon manually (in one terminal)
./voice_daemon.py

# Trigger transcription manually (in another terminal)
./voice_trigger.py

# Check if daemon is running
./voice_trigger.py ping
```

## Configuration

### Whisper Model Selection

The system uses the `tiny.en` model by default for fastest performance. You can change this in `voice_daemon.py`:

```python
# In _init_recorder() method
self.recorder = AudioToTextRecorder(
    model="tiny.en",    # Options: tiny.en, base.en, small.en
    # ... other settings
)
```

**Model Trade-offs**:
- `tiny.en`: Fastest, least accurate, ~39MB
- `base.en`: Good balance, ~74MB  
- `small.en`: Better accuracy, slower, ~244MB

### Voice Activity Detection

Adjust speech detection sensitivity in `voice_daemon.py`:

```python
# In _init_recorder() method
vad_filter_min_silence_duration=500,  # ms of silence to stop (default: 500)
post_speech_silence_duration=0.2,     # seconds (default: 0.2)
```

## Troubleshooting

### Daemon Won't Start

1. **Check logs**:
   ```bash
   # View daemon logs
   journalctl --user -u voice-transcriber.service -f
   
   # Or check log file
   tail -f /tmp/voice_daemon.log
   ```

2. **Test manually**:
   ```bash
   # Run daemon in foreground to see errors
   ./voice_daemon.py
   ```

3. **Common issues**:
   - **Missing dependencies**: `pip3 install -r requirements.txt`
   - **Permission errors**: Check file permissions with `ls -la`
   - **Audio access**: Ensure microphone is working: `arecord -l`

### Keyboard Shortcut Not Working

1. **Check shortcut configuration** in GNOME Settings
2. **Verify script path** is correct in the shortcut command
3. **Test trigger manually**: `./voice_trigger.py`
4. **Check if daemon is running**: `./voice_trigger.py ping`

### Poor Transcription Quality

1. **Check microphone quality**: Test with other applications
2. **Reduce background noise**: Use in quiet environment
3. **Speak clearly**: Normal pace, clear pronunciation
4. **Try different model**: Switch to `base.en` or `small.en` in daemon code
5. **Check logs**: Look for errors in `/tmp/voice_daemon.log`

### Text Not Injecting

1. **Check xdotool installation**: `which xdotool`
2. **Test xdotool manually**: `xdotool type "test"`
3. **Window focus**: Ensure target window is active before speaking
4. **Wayland compatibility**: May have limited functionality under Wayland

### High CPU Usage

1. **Use smaller model**: Switch to `tiny.en` model
2. **Check for multiple instances**: `ps aux | grep voice_daemon`
3. **Restart daemon**: `systemctl --user restart voice-transcriber.service`

## Performance Tips

1. **Use smaller models** (`tiny.en`) for speed
2. **Close unnecessary applications** to free up CPU
3. **Use a good microphone** for better recognition accuracy
4. **Speak in quiet environments** to improve transcription quality
5. **Keep sentences short** for faster processing

## Security Notes

- The daemon runs with user privileges (not root)
- Audio data is processed locally (not sent to external servers)
- Unix socket permissions are set to 0666 for accessibility
- Service is sandboxed with systemd security settings

## Uninstall

To remove the system:

```bash
# Stop and disable service
systemctl --user stop voice-transcriber.service
systemctl --user disable voice-transcriber.service

# Remove service file
rm ~/.config/systemd/user/voice-transcriber.service
systemctl --user daemon-reload

# Remove project directory
rm -rf ~/realtime-transcript-linux

# Remove GNOME keyboard shortcut through Settings GUI
```

## Contributing

Feel free to submit issues and pull requests to improve the system.

## License

This project uses the RealtimeSTT library and follows its licensing terms.