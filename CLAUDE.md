# CLAUDE.md

## Project Overview

Real-time voice transcription for Linux (GNOME + Cosmic DE). Captures speech via global shortcut, injects text into active window. Supports both X11 and Wayland. Dual-engine: AssemblyAI (default) and ElevenLabs Scribe v2 Realtime. Both use WebSocket streaming with ~150ms latency.

## Key Rules

- When adding transcription features (callbacks, params), update BOTH `assemblyai_transcriber.py` AND `elevenlabs_transcriber.py` for feature parity
- Audio capture uses system `pw-record`/`parecord`/`arecord` subprocess, NOT PyAudio
- Both transcribers manage their own mic subprocess directly
- ElevenLabs uses `previous_text` on first audio chunk for vocabulary priming (equivalent of AssemblyAI's `keyterms_prompt`)
- Wayland: text injection via `wl-copy` + `wtype`, X11: via `xsel` + `xdotool`

## Module Map

| File | Role |
|------|------|
| `voice_transcription.py` | Orchestrator, CLI, instance locking, engine selection |
| `assemblyai_transcriber.py` | WebSocket streaming via SDK, own audio capture, event-driven |
| `elevenlabs_transcriber.py` | WebSocket streaming (Scribe v2 Realtime), own audio capture, server VAD + local audio activity tracking |
| `audio_utils.py` | `is_wayland()`, `find_recorder()`, AudioCapture, TextInjector, NotificationHelper |
| `visual_indicator.py` | Wrapper - spawns GTK subprocess (Wayland or X11), IPC via temp file |
| `visual_indicator_gtk.py` | GTK3 floating overlay, audio level bars (X11) |
| `visual_indicator_wayland.py` | GTK3 + gtk-layer-shell overlay (Wayland/Cosmic DE) |

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

## VAD Tuning (elevenlabs_transcriber.py)

- Silence threshold: 50 (RMS volume, local mic activity detection)
- Silence timeout: 5.0s (requires BOTH no server commits AND no mic audio)
- Server VAD silence threshold: 0.7s (ElevenLabs server-side)
- Force commit interval: 10.0s (client-side fallback if server VAD stalls)
- Max duration: 300s
