# CLAUDE.md

## Project Overview

Real-time voice transcription for Linux GNOME. Captures speech via global shortcut, injects text into active window. Dual-engine: AssemblyAI (default streaming) and ElevenLabs (chunk-based alternative).

## Key Rules

- When adding transcription features (callbacks, params), update BOTH `assemblyai_transcriber.py` AND `elevenlabs_transcriber.py` for feature parity
- Audio capture uses system `parecord`/`arecord` subprocess, NOT PyAudio
- AssemblyAI transcriber manages its own mic; ElevenLabs uses shared `AudioCapture`

## Module Map

| File | Role |
|------|------|
| `voice_transcription.py` | Orchestrator, CLI, instance locking, engine selection |
| `assemblyai_transcriber.py` | Streaming API client, own audio capture, event-driven |
| `elevenlabs_transcriber.py` | Chunk-based API client, uses AudioCapture, retry logic |
| `audio_utils.py` | AudioCapture (VAD), TextInjector, NotificationHelper |
| `visual_indicator.py` | Wrapper - spawns GTK subprocess, IPC via temp file |
| `visual_indicator_gtk.py` | GTK3 floating overlay, audio level bars |

## Runtime Files

- Log: `/tmp/voice_transcription.log`
- Lock: `/tmp/voice_transcription.pid`
- Stop signal: `/tmp/voice_transcription_stop.flag`
- Visual IPC: `/tmp/voice_indicator_level`

## Dev Commands

```bash
./voice_transcription.py                    # Run (AssemblyAI default)
./voice_transcription.py --engine elevenlabs # ElevenLabs engine
./voice_transcription.py --xdotool          # xdotool instead of clipboard
./voice_transcription.py status             # Engine availability
./voice_transcription.py ping               # Test API connectivity
./voice_transcription.py stop               # Stop active recording
./voice_transcription.py lang [auto|en|cs]  # Language mode
tail -f /tmp/voice_transcription.log        # View logs
./test_audio.py                             # Test microphone
./test_setup.py                             # Verify dependencies
```

## VAD Tuning (audio_utils.py AudioCapture)

- Silence threshold: 50 (RMS volume)
- Short pause: 1.5s (phrase boundary - transcribe & continue)
- Long pause: 5.0s (end recording)
- Min phrase: 2.0s (skip tiny fragments)
- Max duration: 180s
