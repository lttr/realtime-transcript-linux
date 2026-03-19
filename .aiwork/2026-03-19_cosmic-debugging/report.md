---
status: active
---

# Cosmic DE Migration - Debugging Report

## What's Fixed (committed)

1. **`pw-record --raw` flag** - Without `--raw`, pw-record outputs WAV-wrapped audio. ElevenLabs expects raw PCM s16le. This caused "no speech detected" on every session.

2. **`wtype -k` vs `-P`** - `-P` only sends keydown (key stuck), `-k` sends press+release. Was flooding "v" characters after paste.

3. **Status endpoint** - API key scoped without Models access. Changed from `/v1/models` to `/v1/speech-to-text` POST (returns 422 = authenticated).

4. **Visual indicator cairo -> CSS** - Cosmic DE doesn't render cairo drawing on layer-shell surfaces (`set_app_paintable` + DrawingArea is invisible). CSS-styled GTK widgets work. Each bar in its own fixed-height cell for independent movement.

5. **Debug log cleanup** - DEBUG level no longer written to log file. Notifications on completion/no-speech. Removed "Already recording" popup.

## Fix applied: npm:ws -> native Deno WebSocket (NEEDS TESTING)

### Problem
`npm:ws` WebSocket `.on("message")` events never fire when launched via Cosmic `Spawn()`.
TCP connects, audio sends, but no messages received. Works fine from terminal.

### Fix
Replaced `npm:ws` (Node.js compat layer) with native Deno `WebSocket`:
- `npm:ws` relies on Node.js event loop shims that break in Cosmic's non-standard process context
- Native Deno WebSocket is built into the runtime, no Node compat needed
- Auth changed from `xi-api-key` header to single-use token via `POST /v1/single-use-token/realtime_scribe` (native WS can't set custom headers)
- Event handlers: `.on("message")` -> `.onmessage`, `.once("open")` -> `.onopen`, etc.
- Message data: `data.toString()` -> `event.data` (native WS gives string directly)

### If this doesn't fix it
1. Dump env from Cosmic Spawn (`env > /tmp/debug.log`) and compare with terminal env
2. Try `setsid` in wrapper to create a new session
3. Check if `DBUS_SESSION_BUS_ADDRESS` is needed for networking stack

## Shortcuts configured

```
Super+Alt+K  →  /home/lukas/bin/voice-transcribe
Super+Alt+O  →  /home/lukas/bin/voice-transcribe stop
```

## Files changed outside repo
- `~/bin/voice-transcribe` - wrapper script
- `~/.config/environment.d/elevenlabs.conf` - API key for systemd session
- `~/.config/cosmic/.../custom` - keyboard shortcuts (synced to dotfiles)
