---
status: complete
---

# ElevenLabs Realtime STT Research

## Problem

Current ElevenLabs implementation is chunk-based (HTTP POST per phrase). Flow:
1. AudioCapture records with VAD, detects phrase boundary (1.5s silence)
2. Sends entire phrase as WAV to `POST /v1/speech-to-text`
3. Waits for response, injects text

**Result:** ~3-5s delay per phrase (recording + API round-trip). AssemblyAI streams continuously with ~150ms partial results.

## Solution: Scribe v2 Realtime WebSocket API

ElevenLabs launched a realtime WebSocket STT API using model `scribe_v2_realtime`.

### Key specs

| Property | Value |
|----------|-------|
| Model ID | `scribe_v2_realtime` |
| Latency | ~150ms for partial transcripts |
| Languages | 90+ including **Czech (ces) with ≤5% WER** |
| Pricing | $0.28/hr audio |
| Endpoint | `wss://api.elevenlabs.io/v1/speech-to-text/realtime` |
| Auth | `xi-api-key` header or single-use token |
| Audio format | PCM 16kHz 16-bit mono (matches our existing capture) |

### How it works

1. Open WebSocket to `wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id=scribe_v2_realtime`
2. Send audio chunks as base64 in `input_audio_chunk` messages
3. Receive `partial_transcript` (interim) and `committed_transcript` (final) events
4. Two commit strategies:
   - **manual** - client sends `commit: true` to finalize
   - **vad** - server-side VAD auto-commits on silence (configurable threshold)

### VAD parameters (server-side)

- `commit_strategy=vad` - enable server VAD
- `vad_silence_threshold_secs=1.5` - silence before commit (default 1.5)
- `vad_threshold=0.4` - voice detection sensitivity
- `min_speech_duration_ms=100`
- `min_silence_duration_ms=100`

### Message types

**Client sends:**
```json
{
  "message_type": "input_audio_chunk",
  "audio_base_64": "<base64 PCM data>",
  "commit": false,
  "sample_rate": 16000
}
```

**Server sends:**
- `session_started` - connection confirmed
- `partial_transcript` - interim text (updates as you speak)
- `committed_transcript` - finalized text segment
- `committed_transcript_with_timestamps` - final + word timing
- Various error types

## Implementation approach

### Option A: Direct WebSocket (recommended)

Use `websockets` library directly (no `elevenlabs` SDK needed). Mirrors AssemblyAI approach:

1. Connect WebSocket with `xi-api-key` header
2. Use `parecord` subprocess for mic capture (same as AssemblyAI)
3. Send PCM chunks as base64 via WebSocket
4. Use `commit_strategy=vad` for automatic phrase detection
5. On `committed_transcript` events, call `text_callback` to inject text
6. On `partial_transcript`, optionally show preview

**Pros:** No new dependencies (websockets already common), full control, matches AssemblyAI pattern
**Cons:** Manual reconnection logic

### Option B: ElevenLabs Python SDK

Use `elevenlabs` package with `speech_to_text.realtime.connect()`:

```python
connection = await elevenlabs.speech_to_text.realtime.connect(RealtimeAudioOptions(
    model_id="scribe_v2_realtime",
    audio_format=AudioFormat.PCM_16000,
    sample_rate=16000,
    commit_strategy=CommitStrategy.VAD,
))
connection.on(RealtimeEvents.COMMITTED_TRANSCRIPT, on_committed)
```

**Pros:** Higher-level API, maintained by ElevenLabs
**Cons:** Adds large dependency, async-only (our codebase is sync/threaded)

### Recommendation: Option A

Direct WebSocket is simpler, no new deps, and matches the existing AssemblyAI pattern (subprocess + streaming). The async SDK would require restructuring the threaded architecture.

## Architecture sketch

```
parecord (subprocess)
  └─ stdout → read PCM chunks in thread
                └─ base64 encode → WebSocket send

WebSocket recv thread
  ├─ partial_transcript → volume_callback / optional preview
  └─ committed_transcript → text_callback(phrase, full_text)
```

Key changes to `elevenlabs_transcriber.py`:
- Replace `transcribe_streaming()` chunked approach with WebSocket streaming
- Remove dependency on `AudioCapture` VAD - use server-side VAD instead
- Add `parecord` subprocess management (copy pattern from AssemblyAI)
- Keep `transcribe_audio()` for backwards compat (single-shot HTTP API)

## Czech language advantage

This is a major win: ElevenLabs Scribe v2 supports Czech with ≤5% WER, while AssemblyAI has no Czech support. With the realtime API, ElevenLabs becomes the **best option for Czech transcription** - both accurate AND responsive.

## Sources

- [Realtime API reference](https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime)
- [Server-side streaming guide](https://elevenlabs.io/docs/eleven-api/guides/cookbooks/speech-to-text/realtime/server-side-streaming)
- [Scribe v2 Realtime announcement](https://elevenlabs.io/blog/introducing-scribe-v2-realtime)
- [Models overview](https://elevenlabs.io/docs/overview/models)
