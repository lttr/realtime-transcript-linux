# Voice Transcription with Global Keyboard Shortcut

My own voice (@lttr):

> This is vibe coded, personal software. It was created only for me, with Claude Code and Claude Pro subscription.
> I used my keyboard for the first couple of the prompts, then used text generated from my voice using this software.

---

A real-time voice transcription system for Linux that transcribes speech and automatically types it into the currently active window. Features AssemblyAI streaming (default) and ElevenLabs API for cloud-based transcription.

## Features

- **Real-time streaming transcription** - AssemblyAI streams results as you speak
- **Automatic language detection** - Seamlessly handles mixed Czech/English conversations
- **Dual cloud engines** - AssemblyAI (default) and ElevenLabs API
- **Progressive text injection** - types text as you speak, not just at the end
- **Global keyboard shortcut** integration with GNOME
- **Instance locking** - prevents overlapping sessions

## Installation

### 1. System Dependencies

```bash
sudo apt install python3 python3-pip python3-dev portaudio19-dev xdotool xsel libnotify-bin
```

### 2. Project Setup

```bash
cd ~/code/realtime-transcript-linux
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. API Keys

```bash
cp .env.example .env
nano .env
```

Add at least one API key (no quotes, no extra spaces):
```bash
ASSEMBLYAI_API_KEY=your_key_here
ELEVENLABS_API_KEY=your_key_here
```

### 4. GNOME Keyboard Shortcut

**Settings** > **Keyboard** > **Custom Shortcuts** > **+**

- **Name**: `Voice Transcription`
- **Command**: `/home/lukas/code/realtime-transcript-linux/voice_transcription.py`
- **Shortcut**: `Ctrl+Shift+Alt+K`

Optional stop shortcut:
- **Command**: `/home/lukas/code/realtime-transcript-linux/voice_transcription.py stop`
- **Shortcut**: `Ctrl+Shift+Alt+S`

## Usage

1. Press `Ctrl+Shift+Alt+K`
2. Speak - text appears progressively during natural pauses
3. Stop: wait for silence or press `Ctrl+Shift+Alt+S`

```bash
./voice_transcription.py                     # Default (AssemblyAI)
./voice_transcription.py --engine elevenlabs  # Use ElevenLabs
./voice_transcription.py status              # Engine availability
./voice_transcription.py ping                # Test connectivity
./voice_transcription.py lang [auto|en|cs]   # Language mode
```

## Troubleshooting

```bash
# Check logs
tail -f /tmp/voice_transcription.log

# Test connectivity
./voice_transcription.py ping

# Stale lock file (if "already in progress" after crash)
rm /tmp/voice_transcription.pid
```

- **Text not injecting**: Check `xdotool` is installed, target window is focused. Wayland has limited support.
- **Poor quality**: Check microphone, reduce background noise, try the other engine.

## Security

- Audio sent to cloud APIs (AssemblyAI/ElevenLabs) for transcription
- API keys stored in `.env` (gitignored)
- Runs with user privileges
