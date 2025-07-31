# Voice Transcription with Global Keyboard Shortcut

My own voice (@lttr):

> This is vibe coded, personal software. It was created only for me, with Claude Code and Claude Pro subscription.
> I used my keyboard for the first couple of the prompts, then used text generated from my voice using this software.

---

A real-time voice transcription system for Linux that transcribes speech and automatically types it into the currently active window. Features both cloud-based ElevenLabs API and local Whisper fallback for maximum reliability.

## Features

- **Multi-language support** - English and Czech with automatic system detection
- **Hybrid transcription engine** with ElevenLabs API primary and Whisper fallback
- **Lightning-fast cloud processing** via ElevenLabs with automatic local fallback
- **Global keyboard shortcut** integration with GNOME
- **Progressive text injection** - types text as you speak, not just at the end
- **Automatic speech detection** with natural pause boundaries
- **Smart engine selection** - uses best available transcription method
- **No audio event noise** - filters out typing, background sounds, etc.
- **Reliable fallback** - always works even without internet connection

## How It Works

### Hybrid Architecture (NEW)

The system now uses a smart hybrid approach:

1. **Primary Engine**: ElevenLabs API for fast, cloud-based transcription
2. **Fallback Engine**: Local Whisper model when API unavailable
3. **Smart Selection**: Automatically chooses best available engine
4. **Progressive Injection**: Types text as phrases complete during natural speech pauses
5. **User Notifications**: Informs when switching to slower local processing

### Transcription Flow

1. **Single script execution** (`voice_hybrid.py`) - no daemon required for ElevenLabs
2. **Engine selection**: Tests ElevenLabs API availability, falls back to Whisper if needed
3. **Audio capture**: Records with voice activity detection and natural pause boundaries
4. **Streaming processing**: Transcribes audio chunks on speech pauses (1.5s boundaries)
5. **Progressive injection**: Types transcribed phrases immediately via `xdotool`
6. **Fallback handling**: Seamlessly switches engines with user notification

## System Requirements

- **OS**: Ubuntu 20.04+ or similar Linux distribution with GNOME
- **Python**: 3.8+
- **Audio**: Working microphone
- **Internet**: Optional (for ElevenLabs API, falls back to local processing)
- **Memory**: 500MB-1GB RAM (depending on engine used)
- **CPU**: Any modern CPU (fallback Whisper is CPU-optimized)

## Performance

### ElevenLabs API (Primary)
- **Startup time**: ~0.1 seconds (no model loading)
- **Response time**: ~1.4-2.1 seconds per phrase
- **Memory usage**: ~100MB (no local model)
- **Internet required**: Yes
- **Accuracy**: Excellent with cloud processing power

### Whisper Fallback (Local)
- **Startup time**: ~5 seconds (first-time model loading)
- **Response time**: ~0.3-1.0 seconds per phrase
- **Memory usage**: ~600MB (preloaded model)
- **Internet required**: No
- **Accuracy**: Good for offline processing

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

# Install Python dependencies (ElevenLabs API, python-dotenv, Whisper, PyAudio, numpy)
pip install -r requirements.txt
```

### 3. Configure ElevenLabs API (Recommended)

For best performance, set up ElevenLabs API using a `.env` file:

```bash
# Copy the example file
cp .env.example .env

# Edit the .env file with your API key
nano .env
```

**Content of `.env` file:**
```bash
ELEVENLABS_API_KEY=your_api_key_here
```

**Get your API key:**
1. Visit https://elevenlabs.io/app/settings/api-keys
2. Create or copy your API key
3. Paste it in the `.env` file (replace `your_api_key_here`)

**Why use .env file?**
- ✅ Works with GNOME keyboard shortcuts (no shell environment needed)
- ✅ Secure (automatically ignored by git)
- ✅ Easy to manage and update
- ✅ Standard practice for API keys

**Alternative:** You can still use environment variables:
```bash
export ELEVENLABS_API_KEY="your_api_key_here"
echo 'export ELEVENLABS_API_KEY="your_api_key_here"' >> ~/.bashrc
```

**Note**: Without API key, system will automatically use local Whisper fallback.

### 4. Make Scripts Executable

```bash
chmod +x voice_hybrid.py
```

### 5. Optional: Legacy Daemon Setup

The old daemon-based system is still available but not required for the hybrid system:

```bash
# Only needed if you want to use the original voice_daemon.py + voice_trigger.py
chmod +x voice_daemon.py voice_trigger.py

# Setup systemd service (optional)
mkdir -p ~/.config/systemd/user
cp voice-transcriber.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable voice-transcriber.service
systemctl --user start voice-transcriber.service
```

### 6. Configure GNOME Keyboard Shortcuts

#### Hybrid System (Recommended)
1. Open **Settings** → **Keyboard** → **Keyboard Shortcuts**
2. Click **"View and Customize Shortcuts"**
3. Scroll down and click **"Custom Shortcuts"**
4. Click the **"+"** button to add a new shortcut
5. Configure the shortcut:
   - **Name**: `Voice Transcription (Hybrid)`
   - **Command**: `/home/lukas/code/realtime-transcript-linux/voice_hybrid.py`
   - **Shortcut**: Press `Ctrl+Shift+Alt+K` (or your preferred combination)

#### Stop Recording Shortcut (Optional)
1. Click the **"+"** button to add another shortcut
2. Configure the stop shortcut:
   - **Name**: `Stop Voice Recording`
   - **Command**: `/home/lukas/code/realtime-transcript-linux/voice_hybrid.py stop`
   - **Shortcut**: Press `Ctrl+Shift+Alt+S` (or your preferred combination)

#### Legacy System (Optional)
If you prefer the daemon-based system:
   - **Name**: `Voice Transcription (Legacy)`
   - **Command**: `/home/lukas/code/realtime-transcript-linux/voice_trigger.py`
   - **Shortcut**: Press `Ctrl+Shift+Alt+L` (different key to avoid conflicts)

## Usage

### Hybrid System (Recommended)

1. **Press the keyboard shortcut**: `Ctrl+Shift+Alt+K`
2. **Speak clearly**: System shows notification - ElevenLabs API or local processing
3. **Progressive typing**: Text appears as you speak during natural pauses
4. **Automatic fallback**: If API fails, system notifies and switches to local Whisper
5. **Stop recording**: Wait for 4-second silence or press `Ctrl+Shift+Alt+S`

### Manual Operation

Test the hybrid system manually:

```bash
# Run hybrid transcription
./voice_hybrid.py

# Check system status  
./voice_hybrid.py ping

# View engine availability
./voice_hybrid.py status

# Stop active recording
./voice_hybrid.py stop

# Language management
./voice_hybrid.py lang          # Show current language
./voice_hybrid.py lang en       # Set to English  
./voice_hybrid.py lang cs       # Set to Czech

# Get help
./voice_hybrid.py help
```

### Legacy System Operation

If using the daemon-based system:

```bash
# Start daemon manually (in one terminal)
./voice_daemon.py

# Trigger transcription manually (in another terminal) 
./voice_trigger.py

# Check if daemon is running
./voice_trigger.py ping

# Stop active recording
./voice_trigger.py stop
```

### System Status

Check which engines are available:

```bash
# Shows ElevenLabs and Whisper availability
./voice_hybrid.py status

# Example output:
# Engine Status:
#   elevenlabs: {'available': True, 'api_key_configured': True}
#   whisper: {'available': True, 'model_loaded': False}
```

## Configuration

### Language Support

The system supports English and Czech transcription:

**Supported Languages:**
- **English (en)** - Default language, automatically detected from system locale
- **Czech (cs)** - Full support in both ElevenLabs API and Whisper fallback

**Language Management:**
```bash
# Show current language
./voice_hybrid.py lang

# Set language manually
./voice_hybrid.py lang en    # English
./voice_hybrid.py lang cs    # Czech
```

**Automatic Detection:**
- System automatically detects language from `LANG`, `LC_ALL`, or `LC_MESSAGES` environment variables
- Falls back to English if system language is not supported
- Both ElevenLabs API and Whisper fallback respect the selected language

### ElevenLabs API Settings

Configure API behavior using `.env` file or environment variables:

**Primary Method - .env file:**
```bash
# In your .env file
ELEVENLABS_API_KEY=your_api_key_here
```

**Alternative - Environment variables:**
```bash
export ELEVENLABS_API_KEY="your_api_key_here"
```

**Advanced Settings:**
Adjust timeout settings in `elevenlabs_transcriber.py`:
- `api_timeout`: 8.0 seconds (transcription request timeout)
- `quick_test_timeout`: 5.0 seconds (connectivity test timeout)  
- `max_retries`: 2 attempts (retry count for failed requests)

**API Key Priority:**
1. Explicit parameter (when creating transcriber instance)
2. `.env` file in project directory
3. Environment variable `ELEVENLABS_API_KEY`

### Whisper Fallback Settings

The fallback system uses the multilingual `tiny` model for English and Czech support. Modify in `whisper_fallback.py`:

```python
# In WhisperFallback.__init__() method
self.model_name = "tiny"        # Multilingual model supporting English and Czech
self.compute_type = "float32"   # Higher precision for better accuracy
```

**Model Trade-offs**:

- `tiny`: **Current** - Fastest multilingual model, supports English/Czech, ~39MB
- `base`: Better accuracy, slower, multilingual, ~74MB  
- `small`: Best accuracy, slowest, multilingual, ~244MB

**Language Support:**
- All multilingual models support both English (`en`) and Czech (`cs`)
- Language is automatically detected or set via command line
- Performance is consistent across supported languages

### Audio Processing Settings

Adjust speech detection in `audio_utils.py`:

```python
# In AudioCapture.__init__() method
self.silence_threshold = 50              # Volume threshold for speech detection
self.short_pause_frames = 1.5 * sample_rate  # 1.5s = phrase boundary
self.long_pause_frames = 4.0 * sample_rate   # 4.0s = end recording
self.min_phrase_frames = 2.0 * sample_rate   # 2.0s minimum phrase length
```

### Hybrid Engine Priority

The system prioritizes engines in this order:

1. **ElevenLabs API** (if API key available and API reachable)
2. **Whisper Fallback** (if ElevenLabs unavailable)
3. **Error** (if both engines fail)

Disable ElevenLabs by removing/unsetting the API key:
```bash
unset ELEVENLABS_API_KEY  # Forces Whisper-only mode
```

## Troubleshooting

### Hybrid System Issues

1. **Check system status**:
   ```bash
   ./voice_hybrid.py ping
   ./voice_hybrid.py status
   ```

2. **ElevenLabs API not working**:
   ```bash
   # Check API key
   echo $ELEVENLABS_API_KEY
   
   # Test API connectivity
   curl -H "xi-api-key: $ELEVENLABS_API_KEY" \
        https://api.elevenlabs.io/v1/models
   ```

3. **Whisper fallback not loading**:
   ```bash
   # Check dependencies
   pip list | grep faster-whisper
   
   # Run with verbose logging
   ./voice_hybrid.py 2>&1 | grep -i whisper
   ```

4. **View logs**:
   ```bash
   tail -f /tmp/voice_hybrid.log
   ```

5. **API key not loading from .env**:
   ```bash
   # Check if .env file exists and has correct content
   cat .env
   
   # Verify file permissions (should be readable)
   ls -la .env
   
   # Test API key manually
   grep ELEVENLABS_API_KEY .env
   
   # Ensure no extra spaces or quotes in .env file
   # Correct format: ELEVENLABS_API_KEY=sk_your_key_here
   # Incorrect: ELEVENLABS_API_KEY = "sk_your_key_here"
   ```

### Legacy Daemon Issues

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

## Architecture Files

### Hybrid System (NEW)
- **`voice_hybrid.py`** - Main orchestrator with smart engine selection
- **`elevenlabs_transcriber.py`** - ElevenLabs API client with .env file support
- **`whisper_fallback.py`** - Local Whisper integration with lazy loading  
- **`audio_utils.py`** - Shared audio processing utilities
- **`.env`** - API key configuration file (create from `.env.example`)
- **`.env.example`** - Template file for API key setup

### Legacy System
- **`voice_daemon.py`** - Background daemon with preloaded Whisper model
- **`voice_trigger.py`** - Lightweight client for daemon communication
- **`voice-transcriber.service`** - Systemd service configuration

### Shared
- **`requirements.txt`** - Combined dependencies for both systems
- **Test scripts** - `test_audio.py`, `test_setup.py` for system validation

## Recent Changes

### v2.0 - Hybrid Architecture (Latest)
- ✅ **ElevenLabs API integration** for cloud-based transcription
- ✅ **Smart fallback system** with automatic Whisper backup
- ✅ **Progressive text injection** during natural speech pauses
- ✅ **No audio event descriptions** (configurable via API)
- ✅ **Modular architecture** with separated concerns
- ✅ **Single-script execution** (no daemon required for API mode)
- ✅ **Enhanced error handling** with retry logic and user notifications

### v1.0 - Daemon-Based System (Legacy)
- ✅ **Local Whisper processing** with preloaded models
- ✅ **Unix socket IPC** for fast daemon communication
- ✅ **Systemd service integration** for automatic startup
- ✅ **Voice activity detection** with natural pause boundaries

## License

This project uses the faster-whisper library and ElevenLabs API, following their respective licensing terms.

