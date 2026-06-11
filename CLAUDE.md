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
| `audio_utils.py` | `is_wayland()`, `find_recorder()`, TextInjector, NotificationHelper |
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

## VAD Tuning (elevenlabs_transcriber.py)

- Silence threshold: 30 (RMS volume, local mic activity detection; matches the visual indicator's `0.12*250=30` so session silence and overlay fade agree)
- Silence timeout: 5.0s of mic silence (audio-only; chosen to coincide with the indicator's ~5s full fade-out so the session ends exactly when the overlay disappears, freeing up for the next session)
- Server VAD silence threshold: 1.0s (ElevenLabs server-side; API default is 1.5s. Lower values fragment slow speech into "trailing-off" turns the model punctuates with ellipses)
- `no_verbatim=true`: requested in the WS URL to remove filler words + disfluencies server-side, but the `scribe_v2_realtime` model currently IGNORES it (committed text still contains "uh"/"..."). The real fix is client-side: `_clean_filler_words` in `audio_utils.py` strips filler words, ellipses (anywhere - the model punctuates pauses with `...`), and orphan leading/trailing dashes (cut-off words). Also covers the AssemblyAI engine.
- Force commit interval: 10.0s (client-side fallback if server VAD stalls)
- Max duration: 300s

## Language guard (Czech/English only)

The user speaks ONLY Czech or English, switching whole sentences (not mid-sentence), mostly English. The realtime API has NO candidate-language whitelist - only a single `language_code` or full auto-detect - and forcing one language would butcher the other, so we run auto-detect with a recovery guard:

- WS params request `include_language_detection=true` + `include_timestamps=true` (the detected `language_code` is only surfaced on the `*_with_timestamps` committed message).
- `ALLOWED_LANGS = {cs, ces, cze, en, eng}` (module-level in `elevenlabs_transcriber.py`). A committed turn whose detected language is outside this set is an auto-detect drift (Czech mis-read as Russian/Ukrainian Cyrillic or Polish).
- Recovery, NOT drop: the send thread buffers raw PCM per turn (`audio_buffer` + `committed_offset` cursor advanced on every commit). A drifted turn's audio slice is re-transcribed via `_recover_as_czech` - the HTTP `POST /v1/speech-to-text` (`model_id=scribe_v2`, `language_code=cs`) endpoint, which is far less drift-prone - and that text is used instead. Adds ~1 HTTP roundtrip latency only on the rare drifted turn; turn is dropped only if recovery also fails.
- Backstop: `_clean_filler_words` in `audio_utils.py` returns `''` on any Cyrillic (`[Ѐ-ӿԀ-ԯ]`) that slips through (e.g. a `committed_transcript` without language_code), preventing wrong-script injection. Covers both engines. Polish drift is Latin so it can't be caught here - the per-turn `language_code` guard handles it.
