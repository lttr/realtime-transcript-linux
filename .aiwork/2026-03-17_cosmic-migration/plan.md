---
status: complete
---

# Cosmic Desktop Migration - Deno Transcriber

Migrate `elevenlabs-transcriber/` from GNOME/X11 to Cosmic (Wayland-native).

## System State

- `wtype`: NOT installed (available: `apt install wtype`)
- `wl-copy`: NOT installed (available: `apt install wl-clipboard`)
- `pw-record`: installed at `/usr/bin/pw-record`
- `gjs`: NOT installed
- GTK4: installed (gir1.2-gtk-4.0), works with `/usr/bin/python3`
- GTK3 layer-shell: `gir1.2-gtklayershell-0.1` available but not installed
- GTK4 layer-shell: NOT packaged for this system
- System python: `/usr/bin/python3` has `gi` module; linuxbrew python3 does NOT

**Need to install:** `sudo apt install wtype wl-clipboard gir1.2-gtklayershell-0.1`

## What Changes

| Component | Current (X11/GNOME) | New (Cosmic/Wayland) |
|-----------|---------------------|----------------------|
| Clipboard | `xsel --clipboard --input` | `wl-copy` |
| Key simulation | `xdotool key` | `wtype` |
| Terminal detect | `xdotool getactivewindow` + `xprop WM_CLASS` | Removed (always Ctrl+Shift+V) |
| Visual indicator | GJS + GTK3 | `/usr/bin/python3` + GTK3 + gtk-layer-shell |
| Audio capture | `parecord` > `arecord` | `pw-record` > `parecord` > `arecord` |
| Notifications | `notify-send` | `notify-send` (unchanged) |

## Steps

### 0. Install deps
```bash
sudo apt install wtype wl-clipboard gir1.2-gtklayershell-0.1
```

### 1. Text injection: wl-copy + wtype

**`clipboardInject()`** → replace xsel/xdotool:
- `xsel --clipboard --input` → `wl-copy` (stdin piped)
- Always paste with Ctrl+Shift+V: `wtype -M ctrl -M shift -P v -m shift -m ctrl`

**`injectText()`** Enter key:
- `xdotool key Return` → `wtype -k Return`

Add startup check for `wl-copy` and `wtype`, fail fast.

### 2. Remove terminal detection

Delete `detectTerminal()`, `TERMINALS` const. Always Ctrl+Shift+V.

### 3. Audio capture: prefer pw-record

Priority: `pw-record` > `parecord` > `arecord`
```
pw-record --format=s16 --rate=16000 --channels=1 -
```

### 4. Visual indicator: Python GTK3 + layer-shell

Replace `visual_indicator_gtk.js` (GJS) with `visual_indicator.py` (Python GTK3 + layer-shell).

Why GTK3 not GTK4: `gtk4-layer-shell` not packaged; GTK3 layer-shell is available.

Key differences from current GJS version:
- Use `/usr/bin/python3` (system python with gi bindings)
- `GtkLayerShell.init_for_window(win)` → proper Wayland overlay
- `GtkLayerShell.set_layer(win, OVERLAY)`
- `GtkLayerShell.set_anchor(win, BOTTOM|RIGHT, True)`
- `GtkLayerShell.set_margin(win, RIGHT, 20)` / `set_margin(win, BOTTOM, 60)`
- Rest of drawing code (cairo bars, silence tracking) stays identical

Update `spawnIndicator()` in transcribe.ts:
- `/usr/bin/python3 visual_indicator.py` instead of `gjs visual_indicator_gtk.js`

### 5. Context prompt + cleanup

- CONTEXT_PROMPT: "GNOME" → "Cosmic", "Ubuntu" → "Pop!_OS"
- Delete `visual_indicator_gtk.js`
- Update file header comment

## Files

- **MODIFY** `elevenlabs-transcriber/transcribe.ts` - text injection, audio, indicator spawn, context
- **DELETE** `elevenlabs-transcriber/visual_indicator_gtk.js`
- **CREATE** `elevenlabs-transcriber/visual_indicator.py` - Python GTK3 + layer-shell

## Verification

1. Install deps: `sudo apt install wtype wl-clipboard gir1.2-gtklayershell-0.1`
2. `./transcribe status` - API ping works
3. `./transcribe` - full test: speak, verify text appears in active window, verify indicator overlay
