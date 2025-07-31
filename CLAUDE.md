# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A real-time voice transcription system for Linux GNOME that captures speech via global keyboard shortcut and injects transcribed text directly into the active window. Features hybrid architecture with ElevenLabs API primary and local Whisper fallback for maximum reliability.

## Architecture

**Hybrid Transcription System**: The current primary architecture combines cloud-based ElevenLabs API with local Whisper fallback. A legacy daemon-client system is also available.

### Core Components

#### Hybrid System (Primary)
- **`voice_hybrid.py`**: Main orchestrator with smart engine selection and progressive text injection
- **`elevenlabs_transcriber.py`**: ElevenLabs API client with .env file support and retry logic  
- **`whisper_fallback.py`**: Local Whisper integration with lazy model loading
- **`audio_utils.py`**: Shared audio processing utilities (VAD, text injection, notifications)
- **`.env`**: API key configuration file (create from `.env.example`)

#### Legacy Daemon System (Available)
- **`voice_daemon.py`**: Background service that preloads Whisper model and handles transcription requests. Runs continuously via systemd user service.
- **`voice_trigger.py`**: Lightweight client triggered by GNOME keyboard shortcut. Connects to daemon via Unix socket, handles streaming responses, and injects text using xdotool.
- **`voice-transcriber.service`**: Systemd user service configuration for automatic daemon startup.

### Processing Flow

#### Hybrid System Processing
1. **Engine Selection**: Tests ElevenLabs API availability, falls back to Whisper if needed
2. **Audio Capture**: Records with voice activity detection and natural pause boundaries (1.5s phrase boundaries, 4s recording end)  
3. **Streaming Processing**: Transcribes audio chunks on natural speech pauses
4. **Progressive Injection**: Types transcribed phrases immediately via xdotool during speech
5. **Smart Fallback**: Seamlessly switches engines with user notification if API fails

#### Legacy System Processing  
1. Daemon preloads `tiny.en` Whisper model with float32 precision for accuracy
2. Trigger script sends transcription request via Unix socket (`/tmp/voice_transcriber.sock`)
3. Daemon captures audio with natural pause detection (1.5s phrase boundaries, 4s recording end)
4. Audio processed in streaming chunks with progressive text injection
5. Each phrase transcribed with high-accuracy parameters (beam_size=5, best_of=5)
6. Text injected progressively into active window via xdotool

### Key Technical Details

#### Performance Characteristics
- **ElevenLabs API**: ~1.4-2.1s response time, ~100MB memory, requires internet
- **Whisper fallback**: ~0.3-1.0s response time, ~600MB memory, works offline
- **Model loading**: Whisper takes 5+ seconds on first load, then instant

#### Technical Features
- **Automatic language detection**: Seamlessly handles mixed Czech/English conversations
- **Natural pause detection**: Dual-threshold VAD distinguishes phrase boundaries from recording end
- **Streaming transcription**: Processes 2+ second audio chunks on natural speech pauses
- **Progressive injection**: Injects text as phrases complete, not just at recording end
- **Smart fallback**: Automatic engine switching with user notifications
- **High-accuracy parameters**: Uses float32 precision, beam search, and quality prompts

#### File Locations
- **Hybrid logs**: `/tmp/voice_hybrid.log`
- **Legacy daemon logs**: `/tmp/voice_daemon.log` and systemd journal
- **Configuration**: `.env` file in project root
- **Unix socket**: `/tmp/voice_transcriber.sock` (legacy system)

## Development Commands

### Hybrid System Commands (Primary)
```bash
# Run hybrid transcription manually
./voice_hybrid.py

# Check system status and engine availability  
./voice_hybrid.py status

# Test connectivity (both API and local)
./voice_hybrid.py ping

# Stop active recording
./voice_hybrid.py stop

# Language management
./voice_hybrid.py lang          # Show current language
./voice_hybrid.py lang auto     # Auto-detect language (default)
./voice_hybrid.py lang en       # Set to English
./voice_hybrid.py lang cs       # Set to Czech

# View hybrid system logs
tail -f /tmp/voice_hybrid.log
```

### Legacy Service Management
```bash
# Restart daemon after code changes (includes model reload wait)
systemctl --user restart voice-transcriber.service && sleep 5 && ./voice_trigger.py ping

# Check daemon status and logs
systemctl --user status voice-transcriber.service
journalctl --user -u voice-transcriber.service -f

# Manual daemon testing
./voice_daemon.py
```

### Testing
```bash
# Test audio system and microphone detection
./test_audio.py

# Test daemon connectivity
./voice_trigger.py ping

# Manual transcription test
./voice_trigger.py

# Verify system dependencies
./test_setup.py
```

### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# System dependencies (Ubuntu/Debian)
sudo apt install python3 python3-pip python3-dev portaudio19-dev xdotool libnotify-bin

# Setup systemd service
mkdir -p ~/.config/systemd/user
cp voice-transcriber.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable voice-transcriber.service
```

### GNOME Keyboard Shortcuts
Configure in **Settings** → **Keyboard** → **Keyboard Shortcuts** → **Custom Shortcuts**:

#### Hybrid System (Recommended)
- **Name**: `Voice Transcription (Hybrid)`
- **Command**: `/home/lukas/code/realtime-transcript-linux/voice_hybrid.py`  
- **Shortcut**: `Ctrl+Shift+Alt+K`

#### Stop Recording (Optional)
- **Name**: `Stop Voice Recording`
- **Command**: `/home/lukas/code/realtime-transcript-linux/voice_hybrid.py stop`
- **Shortcut**: `Ctrl+Shift+Alt+S`

#### Legacy System (Alternative)
- **Name**: `Voice Transcription (Legacy)`
- **Command**: `/home/lukas/code/realtime-transcript-linux/voice_trigger.py`
- **Shortcut**: `Ctrl+Shift+Alt+L`

## Configuration

### ElevenLabs API Configuration
Configure using `.env` file in project root:
```bash
# Copy template and edit
cp .env.example .env
# Add your API key: ELEVENLABS_API_KEY=your_key_here
```

Located in `elevenlabs_transcriber.py`:
- API timeout: 8.0 seconds (transcription requests)
- Quick test timeout: 5.0 seconds (connectivity tests)  
- Max retries: 2 attempts with 1.0s delay
- Model: `scribe_v1` (ElevenLabs speech-to-text model)

### Whisper Fallback Parameters
Located in `whisper_fallback.py` initialization and `voice_daemon.py`:
- Model: `tiny` (multilingual model supporting English and Czech)
- Precision: `float32` (higher accuracy than int8)
- Search: `beam_size=5, best_of=5` (comprehensive search for quality)
- Context: `condition_on_previous_text=False` (prevents repetition loops)

### Language Support
The hybrid system supports automatic and manual language selection:
- **Auto-detect (auto)**: Default mode, automatically detects language for each phrase (recommended)
- **English (en)**: Force English-only transcription
- **Czech (cs)**: Force Czech-only transcription
- **Mixed-language support**: Auto mode handles seamless Czech/English switching within conversations
- **Manual selection**: Use `./voice_hybrid.py lang <code>` to set language mode

### Voice Activity Detection
Located in `audio_utils.py` AudioCapture class:
- Short pause: 1.5s (phrase boundary - transcribe and continue)
- Long pause: 4s (end recording session)
- Minimum phrase: 2s (avoid processing tiny fragments)
- Maximum duration: 45s (total recording time limit)
- Silence threshold: 50 (volume level for speech detection)

### Common Issues

#### Hybrid System Issues
**ElevenLabs API failures**: System automatically falls back to Whisper. Check API key in `.env` file and network connectivity.

**API key not loading**: Ensure `.env` file exists with correct format: `ELEVENLABS_API_KEY=your_key_here` (no quotes or extra spaces).

**Whisper lazy loading delays**: First-time Whisper model loading takes 5+ seconds. Subsequent uses are immediate.

#### Legacy System Issues  
**Model repetition loops**: Caused by `condition_on_previous_text=True` - always keep disabled for streaming transcription.

**Timing issues**: The daemon needs 5+ seconds to load the Whisper model on startup - always include delays in restart scripts.

**Audio device conflicts**: System uses OS default microphone - avoid complex device selection logic that can break with different audio setups.

**Systemd service errors**: User services don't need `User=` or `Group=` directives - these cause "bad-setting" errors.