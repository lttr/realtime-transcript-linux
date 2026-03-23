# Architecture

## System Overview

The system is triggered by a keyboard shortcut (Cosmic DE) which launches the main orchestrator. After acquiring an instance lock, it selects a transcription engine and spawns a visual indicator. Both engines produce text callbacks that feed into the TextInjector, which pastes results into the active window.

**Current setup:** Cosmic DE (Wayland), ElevenLabs engine, PipeWire audio via `pw-record`, text injection via `wl-copy` + `wtype`.

```mermaid
graph TD
    KS[Keyboard Shortcut] --> VT[voice_transcription.py]
    VT --> LOCK[Instance Lock]
    VT --> ENGINE{Engine Selection}
    ENGINE -.->|available| AAI[assemblyai_transcriber.py]
    ENGINE ==>|primary| EL[elevenlabs_transcriber.py]

    AAI -.-> MIC1[pw-record]
    EL ==> MIC2[pw-record / PipeWire]

    AAI -.->|streaming events| CB[text callback]
    EL ==>|committed transcripts| CB
    CB ==> TI[TextInjector / wl-copy + wtype]
    TI ==> WIN[Active Window]

    VT ==> VI[visual_indicator.py]
    VI ==>|subprocess| GTK[visual_indicator_wayland.py]
    VI -.->|temp file IPC| GTK

    style EL fill:#2d5016,stroke:#4a8c2a,color:#fff
    style MIC2 fill:#2d5016,stroke:#4a8c2a,color:#fff
    style TI fill:#2d5016,stroke:#4a8c2a,color:#fff
    style GTK fill:#2d5016,stroke:#4a8c2a,color:#fff
```

## Engine Comparison

Both engines use WebSocket streaming with server-side speech detection. AssemblyAI uses its SDK's streaming client with turn-based events. ElevenLabs uses a direct WebSocket connection to Scribe v2 Realtime with server-side VAD.

```mermaid
graph LR
    subgraph AAI[AssemblyAI - available]
        A1[Direct mic subprocess] --> A2[WebSocket streaming]
        A2 --> A3[Server detects end_of_turn]
        A3 --> A4[Inject phrase]
    end

    subgraph EL[ElevenLabs - PRIMARY]
        E1[pw-record / PipeWire] ==> E2[WebSocket streaming]
        E2 ==> E3[Server VAD commits transcript]
        E3 ==> E4[Inject phrase]
    end

    style EL fill:#2d5016,stroke:#4a8c2a,color:#fff
```

| Aspect | AssemblyAI | ElevenLabs |
|--------|-----------|------------|
| Protocol | WebSocket (SDK) | WebSocket (direct) |
| Model | Streaming v3 | Scribe v2 Realtime |
| Audio handling | Own subprocess + threads | Own subprocess + threads |
| Phrase detection | Server-side turn events | Server-side VAD (0.7s silence) |
| Session end | Server TerminationEvent | Dual-signal: no commits AND no mic audio for 5s |
| Vocabulary priming | `keyterms_prompt` (list) | `previous_text` (context string) |
| Latency | ~150ms partials | ~150ms partials |

## Audio Pipeline

Audio is captured from the system microphone as raw 16kHz 16-bit mono frames via `pw-record`/`parecord`/`arecord`. Each engine handles VAD differently:

### AssemblyAI (server-side VAD)
Audio streams continuously to the server. AssemblyAI's server detects turn boundaries and emits `TurnEvent`s with finalized text. No client-side VAD or audio accumulation.

```mermaid
sequenceDiagram
    participant Mic as pw-record
    participant API as AssemblyAI WebSocket
    participant Win as Active Window

    Mic->>API: Stream all audio chunks continuously
    API->>API: Server-side turn detection
    API-->>Win: TurnEvent → inject transcribed text
    Note over API: Session ends on TerminationEvent
```

### ElevenLabs (server VAD + local audio activity)
Audio streams continuously to the server. ElevenLabs server VAD commits transcript at phrase boundaries (0.7s silence). The local monitor tracks two signals for session end: server commit timestamps AND mic audio activity (RMS volume). Session ends only when BOTH signals show 5s of inactivity, preventing premature stops when user pauses between sentences.

```mermaid
sequenceDiagram
    participant Mic as pw-record
    participant Send as Send Thread
    participant WS as ElevenLabs WebSocket
    participant Mon as Monitor Thread
    participant Win as Active Window

    Mic->>Send: Raw audio frames
    Send->>Send: Track audio activity (RMS > 50)
    Send->>WS: Stream base64 audio chunks
    WS-->>Win: Inject committed transcript
    WS-->>Mon: Update last_committed_time

    loop Every 0.5s
        Mon->>Mon: Check both signals
        alt No commits AND no mic audio > 5s
            Mon->>Mon: End session
        end
    end
```

## Visual Indicator

The visual indicator is a small GTK3 floating overlay showing 4 animated bars in the bottom-right corner. It runs as a separate process to avoid blocking the transcription pipeline. The main process writes volume levels to a temp file; the GTK process polls it every 50ms. Writing "stop" to the file triggers a brief animation before exit.

Uses `gtk-layer-shell` for Wayland overlay positioning (`visual_indicator_wayland.py`).

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
Uses `pw-record` (PipeWire, current), `parecord` (PulseAudio), or `arecord` (ALSA) via subprocess. Avoids PyAudio's device enumeration complexity and build issues. More reliable with modern PipeWire stacks.

### Dual-signal silence detection (ElevenLabs)
Session end requires two independent signals to both show inactivity:
- **Server commits** - no ElevenLabs VAD commit for 5s
- **Mic audio activity** - no audio above RMS threshold (50) for 5s

This prevents premature stops when the server hasn't committed yet but the user is still speaking (e.g., pausing between sentences).

### Subprocess Visual Indicator
GTK runs in a separate process because the GTK main loop would block transcription. Temp file IPC is simple and sufficient at 50ms polling. Clean lifecycle: kill subprocess = cleanup.

### Clipboard-based text injection
- **Wayland (current):** `wl-copy` + `wtype` keystroke
- **X11:** `xsel` + `xdotool` keystroke

Clipboard approach preferred over direct typing because `xdotool type` has issues with non-ASCII characters (Czech diacritics). Terminal detection switches paste key: `Ctrl+V` vs `Ctrl+Shift+V`.

### Instance Locking
PID-based lock file prevents overlapping sessions. Checks if PID is still alive before acquiring, auto-cleans stale locks from crashed sessions.

### Vocabulary Priming
Both engines support priming the model with domain-specific terms:
- **AssemblyAI**: `keyterms_prompt` - list of terms sent after connection
- **ElevenLabs**: `previous_text` field on first audio chunk - context string that primes the model for tech vocabulary
