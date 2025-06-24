# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A real-time voice transcription system for Linux GNOME that captures speech via global keyboard shortcut (Ctrl+Shift+Alt+K) and injects transcribed text directly into the active window. Uses OpenAI's Whisper model with CPU-only operation for universal compatibility.

## Architecture

**Daemon-Client Pattern**: Two-process architecture with Unix socket IPC for fast communication and persistent model loading.

### Core Components

- **`voice_daemon.py`**: Background service that preloads Whisper model and handles transcription requests. Runs continuously via systemd user service.
- **`voice_trigger.py`**: Lightweight client triggered by GNOME keyboard shortcut. Connects to daemon via Unix socket, handles streaming responses, and injects text using xdotool.
- **`voice-transcriber.service`**: Systemd user service configuration for automatic daemon startup.

### Processing Flow

1. Daemon preloads `tiny.en` Whisper model with float32 precision for accuracy
2. Trigger script sends transcription request via Unix socket (`/tmp/voice_transcriber.sock`)
3. Daemon captures audio with natural pause detection (1.5s phrase boundaries, 4s recording end)
4. Audio processed in streaming chunks with progressive text injection
5. Each phrase transcribed with high-accuracy parameters (beam_size=5, best_of=5)
6. Text injected progressively into active window via xdotool

### Key Technical Details

- **Natural pause detection**: Dual-threshold VAD distinguishes phrase boundaries from recording end
- **Streaming transcription**: Processes 2+ second audio chunks on natural speech pauses
- **Progressive injection**: Injects text as phrases complete, not just at recording end
- **High-accuracy parameters**: Uses float32 precision, beam search, and quality prompts
- **Memory optimization**: ~400-600MB total with preloaded model

## Development Commands

### Service Management
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

## Configuration

### Whisper Model Parameters
Located in `voice_daemon.py` `_init_whisper_model()` and transcription methods:
- Model: `tiny.en` (fastest, most reliable for streaming)
- Precision: `float32` (higher accuracy than int8)
- Search: `beam_size=5, best_of=5` (comprehensive search for quality)
- Context: `condition_on_previous_text=False` (prevents repetition loops)

### Voice Activity Detection
In `_capture_and_transcribe_streaming()`:
- Short pause: 1.5s (phrase boundary - transcribe and continue)
- Long pause: 4s (end recording session)
- Minimum phrase: 2s (avoid processing tiny fragments)
- Maximum duration: 45s (total recording time limit)
- Silence threshold: 50 (volume level for speech detection)

### Common Issues

**Model repetition loops**: Caused by `condition_on_previous_text=True` - always keep disabled for streaming transcription.

**Timing issues**: The daemon needs 5+ seconds to load the Whisper model on startup - always include delays in restart scripts.

**Audio device conflicts**: System uses OS default microphone - avoid complex device selection logic that can break with different audio setups.

**Systemd service errors**: User services don't need `User=` or `Group=` directives - these cause "bad-setting" errors.