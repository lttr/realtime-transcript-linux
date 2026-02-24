# Architecture

## System Overview

The system is triggered by a GNOME keyboard shortcut which launches the main orchestrator. After acquiring an instance lock, it selects a transcription engine and spawns a visual indicator. Both engines produce text callbacks that feed into the TextInjector, which pastes results into the active window.

```mermaid
graph TD
    KS[GNOME Keyboard Shortcut] --> VT[voice_transcription.py]
    VT --> LOCK[Instance Lock]
    VT --> ENGINE{Engine Selection}
    ENGINE -->|default| AAI[assemblyai_transcriber.py]
    ENGINE -->|alternative| EL[elevenlabs_transcriber.py]

    AAI --> MIC1[parecord / arecord]
    EL --> AC[AudioCapture]
    AC --> MIC2[parecord / arecord]

    AAI -->|streaming events| CB[text callback]
    EL -->|phrase chunks| CB
    CB --> TI[TextInjector]
    TI --> WIN[Active Window]

    VT --> VI[visual_indicator.py]
    VI -->|subprocess| GTK[visual_indicator_gtk.py]
    VI -.->|temp file IPC| GTK
```

## Engine Comparison

The two engines differ fundamentally in how they handle audio and detect phrase boundaries. AssemblyAI uses a persistent WebSocket connection with server-side turn detection. ElevenLabs relies on client-side VAD to split audio into chunks sent as individual HTTP requests.

```mermaid
graph LR
    subgraph AAI[AssemblyAI - Default]
        A1[Direct mic subprocess] --> A2[WebSocket streaming]
        A2 --> A3[Server detects end_of_turn]
        A3 --> A4[Inject phrase]
    end

    subgraph EL[ElevenLabs - Alternative]
        E1[AudioCapture with VAD] --> E2[1.5s silence = phrase boundary]
        E2 --> E3[HTTP POST chunk]
        E3 --> E4[Inject phrase]
    end
```

| Aspect | AssemblyAI | ElevenLabs |
|--------|-----------|------------|
| Protocol | WebSocket streaming | HTTP POST per chunk |
| Audio handling | Own subprocess + timeout thread | Shared AudioCapture with VAD |
| Phrase detection | Server-side turn events | Client-side 1.5s silence threshold |
| Retry logic | Reconnect on error | 2 retries with exponential backoff |
| Latency | Real-time streaming | ~0.7-2.1s per phrase |

## Audio Pipeline

Audio is captured from the system microphone as raw 16kHz 16-bit mono frames. The VAD monitors volume levels continuously. When silence exceeds 1.5s, the accumulated audio is sent for transcription and the result is injected - but recording continues. Only after 5s of silence does the session end.

```mermaid
sequenceDiagram
    participant Mic as parecord
    participant VAD as VAD
    participant API as Cloud API
    participant Inj as TextInjector
    participant Win as Active Window

    Mic->>VAD: Raw audio frames
    loop Every frame
        VAD->>VAD: Calculate RMS volume
        alt Volume above threshold
            VAD->>VAD: Reset silence counter
        else Silence
            VAD->>VAD: Increment silence counter
        end
    end

    alt 1.5s silence - phrase boundary
        VAD->>API: Send accumulated audio
        API-->>Inj: Transcribed text
        Inj->>Win: Paste into active window
        Note over VAD: Continue recording
    else 5.0s silence - end session
        VAD->>VAD: Stop capture
    end
```

## Visual Indicator

The visual indicator is a small GTK3 floating overlay showing 4 animated bars in the bottom-right corner. It runs as a separate process to avoid blocking the transcription pipeline. The main process writes volume levels to a temp file; the GTK process polls it every 50ms. Writing "stop" to the file triggers a brief animation before exit.

```mermaid
graph LR
    VT[Main Process] -->|atomic write| TF[temp file]
    TF -->|poll 50ms| GTK[GTK Subprocess]
    GTK --> BARS[4 animated bars]
    GTK --> DECAY[Silence countdown]
    GTK --> STOP[Stop animation and exit]
```

## Design Decisions

### No PyAudio
Uses `parecord` (PulseAudio) or `arecord` (ALSA) via subprocess. Avoids PyAudio's device enumeration complexity and build issues. More reliable with modern PipeWire/GNOME stacks.

### Dual-threshold VAD
Two silence thresholds serve different purposes:
- **1.5s** = phrase boundary (transcribe accumulated audio, keep recording)
- **5.0s** = end of session (user stopped talking)

This enables progressive injection without premature session termination.

### Subprocess Visual Indicator
GTK runs in a separate process because the GTK main loop would block transcription. Temp file IPC is simple and sufficient at 50ms polling. Clean lifecycle: kill subprocess = cleanup.

### Clipboard over xdotool type
Default injection uses clipboard (`xsel`) + paste keystroke because `xdotool type` has issues with non-ASCII characters (Czech diacritics). Terminal detection switches paste key: `Ctrl+V` vs `Ctrl+Shift+V`.

### Instance Locking
PID-based lock file prevents overlapping sessions. Checks if PID is still alive before acquiring, auto-cleans stale locks from crashed sessions.

### Keyterms Boosting (AssemblyAI)
~50 tech vocabulary terms (Git, TypeScript, Docker, etc.) improve recognition accuracy for developer-focused dictation.
