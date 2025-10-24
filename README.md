# Voice Transcription with Global Keyboard Shortcut

My own voice (@lttr):

> This is vibe coded, personal software. It was created only for me, with Claude Code and Claude Pro subscription.
> I used my keyboard for the first couple of the prompts, then used text generated from my voice using this software.

---

A real-time voice transcription system for Linux that transcribes speech and automatically types it into the currently active window. Features AssemblyAI streaming (default) and ElevenLabs API for cloud-based transcription.

## Features

- **Real-time streaming transcription** - AssemblyAI streams results as you speak
- **Automatic language detection** - Seamlessly handles mixed Czech/English conversations
- **Dual cloud engines** - AssemblyAI (default) and ElevenLabs API
- **Progressive text injection** - types text as you speak, not just at the end
- **Global keyboard shortcut** integration with GNOME
- **Smart engine selection** - choose best engine for your needs
- **Automatic speech detection** with natural pause boundaries
- **Instance locking** - prevents overlapping sessions

## How It Works

### Dual-Engine Architecture

The system supports two cloud-based engines:

1. **AssemblyAI Streaming (Default)**: Real-time streaming transcription with progressive text injection
2. **ElevenLabs API (Alternative)**: Fast cloud-based transcription with chunk processing
3. **Progressive Injection**: Types text as phrases complete during natural speech pauses
4. **Smart Selection**: Choose engine via `--engine` flag

### Transcription Flow

1. **Single script execution** (`voice_transcription.py`) - no daemon required
2. **Instance locking**: Prevents multiple simultaneous sessions
3. **Audio capture**: Records with voice activity detection (AssemblyAI handles its own mic, ElevenLabs uses AudioCapture)
4. **Streaming processing**: Real-time transcription (AssemblyAI) or chunk-based (ElevenLabs)
5. **Progressive injection**: Types transcribed phrases immediately via `xdotool`

## System Requirements

- **OS**: Ubuntu 20.04+ or similar Linux distribution with GNOME
- **Python**: 3.8+
- **Audio**: Working microphone
- **Internet**: Required (cloud-based transcription)
- **Memory**: ~100-200MB RAM
- **CPU**: Any modern CPU (cloud processing)

## Performance

### AssemblyAI Streaming (Default)
- **Startup time**: ~0.2 seconds
- **Response time**: Real-time streaming (text appears as you speak)
- **Memory usage**: ~100MB
- **Internet required**: Yes
- **Accuracy**: Excellent with streaming API

### ElevenLabs API (Alternative)
- **Startup time**: ~0.1 seconds
- **Response time**: ~0.7-2.1 seconds per phrase
- **Memory usage**: ~100MB
- **Internet required**: Yes
- **Accuracy**: Excellent with cloud processing

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

# Install Python dependencies (AssemblyAI, ElevenLabs, python-dotenv, PyAudio, numpy)
pip install -r requirements.txt
```

### 3. Configure API Keys (Required)

Set up your API keys using a `.env` file:

```bash
# Copy the example file
cp .env.example .env

# Edit the .env file with your API key
nano .env
```

**Content of `.env` file:**
```bash
# AssemblyAI API key (default engine)
ASSEMBLYAI_API_KEY=your_assemblyai_key_here

# ElevenLabs API key (alternative engine)
ELEVENLABS_API_KEY=your_elevenlabs_key_here
```

**Get your API keys:**
- **AssemblyAI**: Visit https://www.assemblyai.com/app/account
- **ElevenLabs**: Visit https://elevenlabs.io/app/settings/api-keys

**Why use .env file?**
- ✅ Works with GNOME keyboard shortcuts (no shell environment needed)
- ✅ Secure (automatically ignored by git)
- ✅ Easy to manage and update
- ✅ Standard practice for API keys

**Note**: At least one API key is required to use the system.

### 4. Make Scripts Executable

```bash
chmod +x voice_transcription.py
```

### 5. Configure GNOME Keyboard Shortcuts
1. Open **Settings** → **Keyboard** → **Keyboard Shortcuts**
2. Click **"View and Customize Shortcuts"**
3. Scroll down and click **"Custom Shortcuts"**
4. Click the **"+"** button to add a new shortcut
5. Configure the shortcut:
   - **Name**: `Voice Transcription`
   - **Command**: `/home/lukas/code/realtime-transcript-linux/voice_transcription.py`
   - **Shortcut**: Press `Ctrl+Shift+Alt+K` (or your preferred combination)

#### Stop Recording Shortcut (Optional)
1. Click the **"+"** button to add another shortcut
2. Configure the stop shortcut:
   - **Name**: `Stop Voice Recording`
   - **Command**: `/home/lukas/code/realtime-transcript-linux/voice_transcription.py stop`
   - **Shortcut**: Press `Ctrl+Shift+Alt+S` (or your preferred combination)

## Usage

### Basic Usage

1. **Press the keyboard shortcut**: `Ctrl+Shift+Alt+K`
2. **Speak clearly**: System shows notification with active engine
3. **Progressive typing**: Text appears as you speak during natural pauses
4. **Stop recording**: Wait for silence or press `Ctrl+Shift+Alt+S`

### Manual Operation

```bash
# Run with default engine (AssemblyAI)
./voice_transcription.py

# Run with specific engine
./voice_transcription.py --engine assemblyai
./voice_transcription.py --engine elevenlabs

# Check system status
./voice_transcription.py status

# Test connectivity
./voice_transcription.py ping

# Stop active recording
./voice_transcription.py stop

# Language management
./voice_transcription.py lang          # Show current language
./voice_transcription.py lang auto     # Auto-detect language (default)
./voice_transcription.py lang en       # Set to English
./voice_transcription.py lang cs       # Set to Czech
```

### System Status

Check which engines are available:

```bash
# Shows engine availability
./voice_transcription.py status

# Example output:
# Engine Status:
#   assemblyai: {'available': True, 'api_key_configured': True}
#   elevenlabs: {'available': True, 'api_key_configured': True}
```

## Configuration

### Language Support

The system provides seamless automatic language detection for mixed conversations:

**Language Modes:**
- **Auto-detect (auto)** - Default mode, automatically detects language for each phrase
- **English (en)** - Force English-only transcription
- **Czech (cs)** - Force Czech-only transcription

**Language Management:**
```bash
# Show current language mode
./voice_hybrid.py lang

# Set language mode
./voice_hybrid.py lang auto  # Automatic detection (default)
./voice_hybrid.py lang en    # Force English
./voice_hybrid.py lang cs    # Force Czech
```

**Mixed-Language Conversations:**
- **Seamless switching**: Auto mode handles Czech/English switching within single conversations
- **Perfect for bilingual users**: Speak naturally without manual language switching
- **Example**: "Tohle je česká věta, but then I switch to English" - both parts transcribed correctly
- **Works with both engines**: ElevenLabs API and Whisper fallback support automatic detection

### API Configuration

Configure API behavior using `.env` file:

**Primary Method - .env file:**
```bash
# AssemblyAI (default engine)
ASSEMBLYAI_API_KEY=your_assemblyai_key_here

# ElevenLabs (alternative engine)
ELEVENLABS_API_KEY=your_elevenlabs_key_here
```

**AssemblyAI Settings:**
Located in `assemblyai_transcriber.py`:
- Streaming API with real-time transcription
- Sample rate: 16kHz
- Auto-formatting: Enabled (`format_turns=True`)
- Language detection: Auto-detect or specified (en/cs)

**ElevenLabs Settings:**
Adjust timeout settings in `elevenlabs_transcriber.py`:
- `api_timeout`: 8.0 seconds (transcription request timeout)
- `quick_test_timeout`: 5.0 seconds (connectivity test timeout)
- `max_retries`: 2 attempts (retry count for failed requests)

### Audio Processing Settings

Adjust speech detection in `audio_utils.py`:

```python
# In AudioCapture.__init__() method
self.silence_threshold = 50              # Volume threshold for speech detection
self.short_pause_frames = 1.5 * sample_rate  # 1.5s = phrase boundary
self.long_pause_frames = 4.0 * sample_rate   # 4.0s = end recording
self.min_phrase_frames = 2.0 * sample_rate   # 2.0s minimum phrase length
```

### Engine Selection

Choose your engine using the `--engine` flag:

```bash
# Use AssemblyAI (default)
./voice_transcription.py --engine assemblyai

# Use ElevenLabs
./voice_transcription.py --engine elevenlabs
```

Default engine is AssemblyAI. At least one API key must be configured.

## Troubleshooting

### Common Issues

1. **Check system status**:
   ```bash
   ./voice_transcription.py ping
   ./voice_transcription.py status
   ```

2. **API not working**:
   ```bash
   # Check API keys in .env file
   cat .env

   # Verify file permissions (should be readable)
   ls -la .env

   # Ensure no extra spaces or quotes in .env file
   # Correct format: ASSEMBLYAI_API_KEY=your_key_here
   # Incorrect: ASSEMBLYAI_API_KEY = "your_key_here"
   ```

3. **View logs**:
   ```bash
   tail -f /tmp/voice_transcription.log
   ```

4. **Multiple instances error**:
   ```bash
   # If you see "already in progress", wait for current session to complete
   # Or remove lock file manually (use with caution)
   rm /tmp/voice_transcription.pid
   ```

### Keyboard Shortcut Not Working

1. **Check shortcut configuration** in GNOME Settings
2. **Verify script path** is correct in the shortcut command
3. **Test manually**: `./voice_transcription.py`
4. **Check logs**: `tail -f /tmp/voice_transcription.log`

### Poor Transcription Quality

1. **Check microphone quality**: Test with other applications
2. **Reduce background noise**: Use in quiet environment
3. **Speak clearly**: Normal pace, clear pronunciation
4. **Try different engine**: Switch between AssemblyAI and ElevenLabs
5. **Check logs**: Look for errors in `/tmp/voice_transcription.log`

### Text Not Injecting

1. **Check xdotool installation**: `which xdotool`
2. **Test xdotool manually**: `xdotool type "test"`
3. **Window focus**: Ensure target window is active before speaking
4. **Wayland compatibility**: May have limited functionality under Wayland

### High CPU Usage

1. **Check for multiple instances**: `ps aux | grep voice_transcription`
2. **Remove stale lock files**: `rm /tmp/voice_transcription.pid`

## Performance Tips

1. **Use AssemblyAI** for real-time streaming transcription
2. **Use ElevenLabs** for fast chunk-based processing
3. **Use a good microphone** for better recognition accuracy
4. **Speak in quiet environments** to improve transcription quality
5. **Ensure stable internet** for cloud API reliability

## Security Notes

- Script runs with user privileges (not root)
- Audio data is sent to cloud APIs (AssemblyAI/ElevenLabs) for transcription
- API keys stored in `.env` file (automatically ignored by git)
- Instance locking prevents overlapping sessions

## Uninstall

To remove the system:

```bash
# Remove project directory
rm -rf ~/code/realtime-transcript-linux

# Remove temporary files
rm /tmp/voice_transcription.log
rm /tmp/voice_transcription.pid
rm /tmp/voice_transcription_stop.flag

# Remove GNOME keyboard shortcut through Settings GUI
```

## Contributing

Feel free to submit issues and pull requests to improve the system.

## Architecture Files

- **`voice_transcription.py`** - Main orchestrator with dual-engine support
- **`assemblyai_transcriber.py`** - AssemblyAI streaming API client (default)
- **`elevenlabs_transcriber.py`** - ElevenLabs API client (alternative)
- **`audio_utils.py`** - Shared audio processing utilities (VAD, text injection, notifications)
- **`.env`** - API key configuration file (create from `.env.example`)
- **`.env.example`** - Template file for API key setup
- **`requirements.txt`** - Python dependencies

## Recent Changes

### v3.0 - Dual Cloud Engine Architecture (Latest)
- ✅ **AssemblyAI streaming integration** - Real-time transcription as you speak
- ✅ **ElevenLabs API support** - Fast chunk-based processing
- ✅ **Progressive text injection** - Text appears during natural speech pauses
- ✅ **Engine selection** - Choose between AssemblyAI and ElevenLabs
- ✅ **Instance locking** - Prevents overlapping sessions
- ✅ **Modular architecture** - Separated concerns with clean interfaces
- ✅ **Single-script execution** - No daemon required

## License

This project uses AssemblyAI and ElevenLabs APIs, following their respective licensing terms.

