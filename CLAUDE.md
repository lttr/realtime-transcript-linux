# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A real-time voice transcription system for Linux GNOME that captures speech via global keyboard shortcut and injects transcribed text directly into the active window. Supports both AssemblyAI (default) and ElevenLabs streaming APIs for high-quality transcription with instance locking for reliability.

## Architecture

**Dual-Engine Voice Transcription System**: Cloud-based speech-to-text using AssemblyAI (default) or ElevenLabs streaming APIs for optimal accuracy and real-time performance.

### Core Components

- **`voice_transcription.py`**: Main orchestrator supporting both AssemblyAI and ElevenLabs with progressive text injection
- **`assemblyai_transcriber.py`**: AssemblyAI streaming API client (default engine)
- **`elevenlabs_transcriber.py`**: ElevenLabs API client with .env file support and retry logic (alternative engine)
- **`audio_utils.py`**: Shared audio processing utilities (VAD, text injection, notifications)
- **`.env`**: API key configuration file (create from `.env.example`)

### Processing Flow

1. **Instance Locking**: Prevents multiple simultaneous sessions using PID-based locking
2. **API Check**: Verifies ElevenLabs API key and connectivity
3. **Audio Capture**: Records with voice activity detection and natural pause boundaries (1.5s phrase boundaries, 4s recording end)  
4. **Streaming Processing**: Transcribes audio chunks on natural speech pauses
5. **Progressive Injection**: Pastes transcribed phrases via clipboard (default) or xdotool type

### Key Technical Details

#### Performance Characteristics
- **AssemblyAI Streaming (default)**: Real-time streaming transcription, progressive text injection as you speak
- **ElevenLabs API (alternative)**: ~0.7-2.1s response time, ~100MB memory, chunk-based processing
- **Progressive injection**: Real-time text appearing as you speak (both engines)

#### Technical Features
- **Instance locking**: Prevents multiple overlapping sessions that cause delays
- **Automatic language detection**: Seamlessly handles mixed Czech/English conversations
- **Natural pause detection**: Dual-threshold VAD distinguishes phrase boundaries from recording end
- **Streaming transcription**: Processes 2+ second audio chunks on natural speech pauses
- **Progressive injection**: Injects text as phrases complete via clipboard+paste (or xdotool type with `--xdotool` flag)
- **High-accuracy API**: Cloud-based processing with scribe_v1 model

#### File Locations
- **System logs**: `/tmp/voice_transcription.log`
- **Configuration**: `.env` file in project root
- **Lock file**: `/tmp/voice_transcription.pid` (prevents multiple instances)
- **Stop signal**: `/tmp/voice_transcription_stop.flag` (external stop mechanism)

## Development Commands

### Voice Transcription Commands
```bash
# Run voice transcription (clipboard mode, AssemblyAI engine)
./voice_transcription.py

# Use xdotool type instead of clipboard for text injection
./voice_transcription.py --xdotool

# Run with specific engine
./voice_transcription.py --engine assemblyai  # Use AssemblyAI (default)
./voice_transcription.py --engine elevenlabs  # Use ElevenLabs

# Check system status and engine availability
./voice_transcription.py status

# Test connectivity (both engines)
./voice_transcription.py ping

# Stop active recording
./voice_transcription.py stop

# Language management
./voice_transcription.py lang          # Show current language
./voice_transcription.py lang auto     # Auto-detect language (default)
./voice_transcription.py lang en       # Set to English
./voice_transcription.py lang cs       # Set to Czech

# View system logs
tail -f /tmp/voice_transcription.log
```

### Testing
```bash
# Test audio system and microphone detection
./test_audio.py

# Verify system dependencies
./test_setup.py
```

### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# System dependencies (Ubuntu/Debian)
sudo apt install python3 python3-pip python3-dev portaudio19-dev xdotool xsel libnotify-bin
```

### GNOME Keyboard Shortcuts
Configure in **Settings** → **Keyboard** → **Keyboard Shortcuts** → **Custom Shortcuts**:

#### Voice Transcription
- **Name**: `Voice Transcription`
- **Command**: `/home/lukas/code/realtime-transcript-linux/voice_transcription.py`  
- **Shortcut**: `Ctrl+Shift+Alt+K`

#### Stop Recording (Optional)
- **Name**: `Stop Voice Recording`
- **Command**: `/home/lukas/code/realtime-transcript-linux/voice_transcription.py stop`
- **Shortcut**: `Ctrl+Shift+Alt+S`

## Configuration

### API Configuration
Configure using `.env` file in project root:
```bash
# Copy template and edit
cp .env.example .env
# Add your API keys (at least one required):
# ASSEMBLYAI_API_KEY=your_key_here  (default engine)
# ELEVENLABS_API_KEY=your_key_here  (alternative engine)
```

#### AssemblyAI Configuration (Default Engine)
Located in `assemblyai_transcriber.py`:
- Streaming API with real-time transcription
- Sample rate: 16kHz
- Auto-formatting: Enabled (`format_turns=True`)
- Language detection: Auto-detect or specified (en/cs)

#### ElevenLabs Configuration (Alternative Engine)
Located in `elevenlabs_transcriber.py`:
- API timeout: 8.0 seconds (transcription requests)
- Quick test timeout: 5.0 seconds (connectivity tests)
- Max retries: 2 attempts with 1.0s delay
- Model: `scribe_v1` (ElevenLabs speech-to-text model)

### Language Support
The system supports automatic and manual language selection:
- **Auto-detect (auto)**: Default mode, automatically detects language for each phrase (recommended)
- **English (en)**: Force English-only transcription
- **Czech (cs)**: Force Czech-only transcription
- **Mixed-language support**: Auto mode handles seamless Czech/English switching within conversations
- **Manual selection**: Use `./voice_transcription.py lang <code>` to set language mode

### Voice Activity Detection
Located in `audio_utils.py` AudioCapture class:
- Short pause: 1.5s (phrase boundary - transcribe and continue)
- Long pause: 4s (end recording session)
- Minimum phrase: 2s (avoid processing tiny fragments)
- Maximum duration: 45s (total recording time limit)
- Silence threshold: 50 (volume level for speech detection)

### Common Issues

#### API Issues
**API key not configured**: Ensure `.env` file exists with correct format:
- AssemblyAI: `ASSEMBLYAI_API_KEY=your_key_here`
- ElevenLabs: `ELEVENLABS_API_KEY=your_key_here`
(no quotes or extra spaces)

**API connectivity issues**: Check internet connection and API key validity. Use `./voice_transcription.py ping` to test connectivity for both engines.

**Engine selection**: Use `--engine assemblyai` or `--engine elevenlabs` to switch between engines. AssemblyAI is default.

#### Performance Issues
**Multiple instances**: System prevents overlapping sessions with instance locking. If you see "Voice transcription already in progress", wait for current session to complete.

**Audio device conflicts**: System uses OS default microphone - avoid complex device selection logic that can break with different audio setups.