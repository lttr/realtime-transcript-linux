#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import os
import re
import time
import json
import base64
import logging
import shutil
import subprocess
import threading
import requests
import numpy as np
from typing import Optional
from pathlib import Path
from audio_utils import find_recorder

# Try to import dotenv, but don't fail if not available
try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False

try:
    from websockets.sync.client import connect as ws_connect
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

# Languages the user actually speaks. Committed turns auto-detected as anything
# else (ru/uk/pl drift on Czech speech) are dropped. Covers both ISO 639-1 and
# 639-3 spellings ElevenLabs may return.
ALLOWED_LANGS = {"cs", "ces", "cze", "en", "eng"}


class ElevenLabsTranscriber:
    """ElevenLabs Speech-to-Text API client - WebSocket streaming + HTTP fallback"""

    def __init__(self, api_key: Optional[str] = None, skip_availability_check: bool = False):
        # Initialize logger first
        self.logger = logging.getLogger(__name__)

        self.api_key = api_key or self._load_api_key()
        self.base_url = "https://api.elevenlabs.io/v1"
        self.model_id = "scribe_v2_realtime"
        self.skip_availability_check = skip_availability_check

        # Audio settings (match AssemblyAI)
        self.sample_rate = 16000
        self.chunk_size = 1024
        self.bytes_per_sample = 2  # 16-bit audio
        self.chunk_bytes = self.chunk_size * self.bytes_per_sample

        # Timeout for availability check
        self.quick_test_timeout = 5.0

        # Streaming state
        self.recorder_process = None
        self.stop_streaming = None

        # Find audio recorder command
        self._recorder_cmd = self._find_recorder()

        if not self.api_key:
            self.logger.warning("No ElevenLabs API key found. Create .env file or set ELEVENLABS_API_KEY environment variable.")

    def _find_recorder(self):
        """Find available audio recorder command"""
        return find_recorder(self.sample_rate)

    def _load_api_key(self) -> Optional[str]:
        """Load API key from .env file, then environment variable"""

        # First try to load from .env file in the script's directory
        if DOTENV_AVAILABLE:
            try:
                script_dir = Path(__file__).parent
                env_file = script_dir / '.env'

                if env_file.exists():
                    load_dotenv(env_file)
                    self.logger.debug(f"Loaded .env file from {env_file}")

            except Exception as e:
                self.logger.debug(f"Could not load .env file: {e}")

        # Try environment variable (works with both .env loaded and system env)
        api_key = os.getenv('ELEVENLABS_API_KEY')

        if api_key:
            return api_key

        # If no key found, log helpful message
        if DOTENV_AVAILABLE:
            self.logger.debug("No API key found in .env file or environment variables")
        else:
            self.logger.debug("No API key found in environment variables (python-dotenv not available)")

        return None

    def is_available(self) -> bool:
        """Quick connectivity test to ElevenLabs API"""
        if not self.api_key:
            return False

        # Check if API key format is valid (starts with sk_)
        if not self.api_key.startswith('sk_'):
            return False

        # If skip check is enabled, assume it's available (optimistic)
        if self.skip_availability_check:
            return True

        try:
            response = requests.get(
                f"{self.base_url}/models",
                headers={"xi-api-key": self.api_key},
                timeout=self.quick_test_timeout
            )
            return response.status_code in [200, 401, 403, 422, 429]

        except requests.exceptions.Timeout:
            self.logger.debug(f"API timeout after {self.quick_test_timeout}s")
            return False
        except requests.exceptions.ConnectionError:
            self.logger.debug("API connection error")
            return False
        except Exception as e:
            self.logger.debug(f"API availability check error (assuming available): {e}")
            return True

    # Patterns for audio event annotations: complete "(smích)", trailing "(", leading "smích)"
    _AUDIO_EVENT_FULL_RE = re.compile(r'\s*\(\s*\w+\s*\)')
    _AUDIO_EVENT_OPEN_RE = re.compile(r'\s*\(\s*$')
    _AUDIO_EVENT_CLOSE_RE = re.compile(r'^\s*\w+\s*\)')

    def _strip_audio_events(self, text: str) -> str:
        """Remove audio event tags from transcript text.

        Handles complete tags "(smích)", trailing orphan "(" at end of a
        commit, and leading orphan "smích)" from split commits.
        """
        text = self._AUDIO_EVENT_FULL_RE.sub('', text)
        text = self._AUDIO_EVENT_OPEN_RE.sub('', text)
        text = self._AUDIO_EVENT_CLOSE_RE.sub('', text)
        return text.strip()

    def _recover_as_czech(self, pcm_bytes: bytes) -> str:
        """Re-transcribe a turn's raw PCM with Czech forced.

        Rescue path for turns the realtime auto-detect mis-identified as a
        foreign (usually Slavic) language. The file-based Scribe endpoint with an
        explicit language_code is far less drift-prone, so we wrap the buffered
        PCM as a WAV and POST it with language_code=cs. The user speaks only
        Czech/English and these drifts happen on Czech speech, so cs is the right
        forced language. Returns '' on any failure - the caller then drops the
        turn rather than blocking.
        """
        min_bytes = int(0.1 * self.sample_rate) * 2  # API requires >=100ms, 16-bit
        if not pcm_bytes or len(pcm_bytes) < min_bytes:
            return ""
        try:
            import io
            import wave
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)  # 16-bit
                wav.setframerate(self.sample_rate)
                wav.writeframes(pcm_bytes)

            t0 = time.time()
            resp = requests.post(
                f"{self.base_url}/speech-to-text",
                headers={"xi-api-key": self.api_key},
                files={"file": ("turn.wav", buf.getvalue(), "audio/wav")},
                data={"model_id": "scribe_v2", "language_code": "cs"},
                timeout=10.0,
            )
            if resp.status_code != 200:
                self.logger.error(f"Czech recovery failed: HTTP {resp.status_code}")
                return ""
            text = (resp.json() or {}).get("text", "").strip()
            self.logger.info(
                f"Czech recovery ({(time.time() - t0) * 1000:.0f}ms): '{text[:60]}'"
            )
            return text
        except Exception as e:
            self.logger.error(f"Czech recovery error: {e}")
            return ""

    def _get_context_prompt(self):
        """Tech vocabulary as context prompt for Scribe v2 Realtime.

        Uses previous_text field on first audio chunk to prime the model
        for domain-specific terms (realtime API equivalent of keyterms).
        """
        terms = [
            "Claude", "Claude Code", "Anthropic", "ChatGPT", "OpenAI",
            "Cursor", "Copilot", "LLM", "MCP", "API",
            "Vue", "Nuxt", "React", "Next.js", "Svelte",
            "TypeScript", "JavaScript", "Tailwind", "Vite",
            "pnpm", "npm", "npx", "Node.js", "ESLint", "Prettier",
            "Docker", "GitHub", "Git",
            "Linux", "GNOME", "Ubuntu", "PipeWire", "PulseAudio",
            "PostgreSQL", "Prisma", "Redis",
            "refactor", "deploy", "localhost", "webhook",
        ]
        return " ".join(terms)

    def transcribe_streaming(self, audio_capture, text_callback=None, stop_flag=None, language: str = "en", volume_callback=None) -> str:
        """
        Perform streaming transcription via Scribe v2 Realtime WebSocket.

        Args:
            audio_capture: Not used (kept for interface compatibility)
            text_callback: Function called with each transcribed phrase
            stop_flag: Shared dictionary to signal stop
            language: Language code for transcription (default: en, None for auto)
            volume_callback: Function called with audio volume level for visual indicator

        Returns:
            Complete transcribed text
        """
        if not WEBSOCKETS_AVAILABLE:
            self.logger.error("websockets package not installed. Run: pip install websockets")
            return ""

        if not self.api_key:
            self.logger.error("No ElevenLabs API key available")
            return ""

        if not self._recorder_cmd:
            self.logger.error("No audio recorder found. Install pulseaudio-utils or alsa-utils.")
            return ""

        full_text = ""
        self.stop_streaming = threading.Event()
        last_committed_time = time.time()
        last_audio_activity_time = time.time()

        # Per-turn raw PCM buffer for foreign-language recovery. The send thread
        # appends every chunk; on each commit we slice [committed_offset:end] to
        # get exactly that turn's audio, then advance the cursor. If the turn was
        # auto-detected as a non-cs/en language, that slice is re-transcribed with
        # Czech forced instead of being lost. (committed_offset is a 1-element list
        # so both nested threads mutate it without a nonlocal declaration.)
        audio_buffer = bytearray()
        audio_lock = threading.Lock()
        committed_offset = [0]
        silence_threshold = 30  # RMS volume threshold for speech detection
                                 # (matches visual indicator's 0.12*250=30, so
                                 # session silence and overlay fade-out agree)
        silence_timeout = 5.0
        max_duration = 300  # 5 minutes

        # Get single-use token (more reliable than xi-api-key header)
        try:
            self.logger.info("Requesting single-use token...")
            token_resp = requests.post(
                f"{self.base_url}/single-use-token/realtime_scribe",
                headers={"xi-api-key": self.api_key},
                timeout=5.0,
            )
            if token_resp.status_code != 200:
                self.logger.error(f"Failed to get single-use token: HTTP {token_resp.status_code}")
                return ""
            token = token_resp.json().get("token")
            if not token:
                self.logger.error("Empty token in response")
                return ""
            self.logger.info("Single-use token obtained")
        except Exception as e:
            self.logger.error(f"Failed to get single-use token: {e}")
            return ""

        # Build WebSocket URL with token auth (no headers needed)
        params = [
            f"model_id={self.model_id}",
            "commit_strategy=vad",
            # Modest raise from 0.7 (API default is 1.5): slow speech with short
            # pauses no longer fragments into many "trailing-off" turns, each of
            # which the model would otherwise punctuate with an ellipsis.
            "vad_silence_threshold_secs=1.0",
            # Strip filler words ("um"/"uh") and disfluencies/false-starts
            # server-side. This is what removes the spurious "..." and "-"
            # artifacts the model emits for hesitant/cut-off slow speech.
            "no_verbatim=true",
            # Report the detected language per committed turn so we can drop
            # auto-detect drifts. The user speaks ONLY Czech or English, but
            # ElevenLabs auto-detect (language_code omitted) sometimes mis-fires
            # to Russian/Ukrainian (Cyrillic) or Polish on Czech speech. The
            # detected language_code is only present on the *_with_timestamps
            # message, so include_timestamps is required to surface it.
            "include_language_detection=true",
            "include_timestamps=true",
            f"audio_format=pcm_{self.sample_rate}",
            f"token={token}",
        ]
        if language is not None:
            params.append(f"language_code={language}")
        ws_url = f"wss://api.elevenlabs.io/v1/speech-to-text/realtime?{'&'.join(params)}"

        try:
            self.logger.info("Connecting to ElevenLabs Scribe v2 Realtime WebSocket...")
            ws = ws_connect(ws_url)
            self.logger.info("WebSocket connected")

            # Wait for session_started to confirm auth
            first_msg = ws.recv(timeout=5)
            parsed = json.loads(first_msg)
            if parsed.get("message_type") == "session_started":
                self.logger.info(f"ElevenLabs session started: {parsed.get('session_id')}")
            elif "error" in parsed.get("message_type", ""):
                error_text = parsed.get("error", parsed.get("message_type"))
                self.logger.error(f"ElevenLabs WebSocket error: {error_text}")
                ws.close()
                return ""
        except Exception as e:
            self.logger.error(f"WebSocket connection failed: {e}")
            return ""

        # Start parecord
        try:
            self.recorder_process = subprocess.Popen(
                self._recorder_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self.logger.info("Audio recorder started")
        except Exception as e:
            self.logger.error(f"Failed to start audio recorder: {e}")
            ws.close()
            return ""

        # --- Send thread: read PCM from parecord, base64-encode, send ---
        def send_audio():
            nonlocal last_audio_activity_time
            first_chunk = True
            context_prompt = self._get_context_prompt()
            force_commit_interval = 10.0
            last_force_commit = time.time()
            try:
                while not self.stop_streaming.is_set():
                    data = self.recorder_process.stdout.read(self.chunk_bytes)
                    if not data or len(data) < self.chunk_bytes:
                        break

                    # Keep raw PCM so a mis-detected turn can be re-transcribed
                    with audio_lock:
                        audio_buffer.extend(data)

                    # Calculate volume for visual indicator + speech detection
                    try:
                        audio_array = np.frombuffer(data, dtype=np.int16)
                        volume = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
                        if volume > silence_threshold:
                            last_audio_activity_time = time.time()
                        if volume_callback:
                            volume_callback(volume)
                    except Exception:
                        pass

                    # Force commit if no VAD commit received in a while
                    now = time.time()
                    should_commit = (
                        (now - last_committed_time) > force_commit_interval and
                        (now - last_force_commit) > force_commit_interval
                    )

                    # Build message
                    msg = {
                        "message_type": "input_audio_chunk",
                        "audio_base_64": base64.b64encode(data).decode("ascii"),
                        "commit": should_commit,
                        "sample_rate": self.sample_rate,
                    }
                    if first_chunk and context_prompt:
                        msg["previous_text"] = context_prompt
                        first_chunk = False

                    if should_commit:
                        last_force_commit = now
                        self.logger.debug("Force commit (no VAD commit in 10s)")

                    try:
                        ws.send(json.dumps(msg))
                    except Exception as e:
                        self.logger.debug(f"WebSocket send error: {e}")
                        break
            except Exception as e:
                self.logger.debug(f"Send thread error: {e}")

        # --- Receive thread: process server messages ---
        # Does NOT control session lifecycle - only the monitor does.
        def receive_messages():
            nonlocal full_text, last_committed_time
            try:
                for raw_msg in ws:
                    if self.stop_streaming.is_set():
                        break
                    try:
                        msg = json.loads(raw_msg)
                    except json.JSONDecodeError:
                        continue

                    msg_type = msg.get("message_type", "")

                    if msg_type == "session_started":
                        pass  # Already handled during connection

                    elif msg_type == "partial_transcript":
                        text = msg.get("text", "").strip()
                        if text:
                            self.logger.debug(f"Partial: '{text[:60]}'")

                    elif msg_type in ("committed_transcript", "committed_transcript_with_timestamps"):
                        last_committed_time = time.time()

                        # Advance the per-turn audio cursor for EVERY commit so the
                        # next turn's slice starts in the right place, kept or not.
                        with audio_lock:
                            turn_start = committed_offset[0]
                            turn_end = len(audio_buffer)
                            committed_offset[0] = turn_end

                        # Language guard: the user speaks ONLY Czech or English. In
                        # auto-detect mode (language_code omitted) ElevenLabs
                        # occasionally drifts to another (usually Slavic) language on
                        # Czech speech, emitting Cyrillic (ru/uk) or Polish text. The
                        # realtime API has no candidate-whitelist, so instead of
                        # losing the turn we re-transcribe its raw audio via the HTTP
                        # Scribe endpoint with Czech forced - far less drift-prone -
                        # and use that text. (No-op when a language is forced: the
                        # echoed language_code is always the forced cs/en.)
                        detected_lang = (msg.get("language_code") or "").lower()
                        if detected_lang and detected_lang not in ALLOWED_LANGS:
                            with audio_lock:
                                turn_audio = bytes(audio_buffer[turn_start:turn_end])
                            self.logger.warning(
                                f"Auto-detect drift to '{detected_lang}'; recovering "
                                f"turn as Czech (was: '{msg.get('text', '')[:60]}')"
                            )
                            text = self._strip_audio_events(self._recover_as_czech(turn_audio))
                            if not text:
                                self.logger.warning("Czech recovery produced no text; turn lost")
                        else:
                            text = self._strip_audio_events(msg.get("text", ""))

                        if text:
                            self.logger.info(f"Committed: '{text}'")
                            if full_text and not full_text.endswith(" "):
                                full_text += " "
                            full_text += text
                            if text_callback:
                                try:
                                    text_callback(text, full_text.strip())
                                except Exception as e:
                                    self.logger.error(f"Error in text callback: {e}")

                    elif "error" in msg_type:
                        error_text = msg.get("error", msg_type)
                        self.logger.error(f"ElevenLabs WebSocket error: {error_text}")
                        self.stop_streaming.set()
                        break
            except Exception as e:
                if not self.stop_streaming.is_set():
                    self.logger.debug(f"WebSocket closed: {e}")

        # --- Monitor thread: stop conditions + cleanup ---
        # Mirrors AssemblyAI pattern: monitor owns the lifecycle,
        # terminates recorder and closes WS to unblock other threads.
        def monitor():
            start_time = time.time()
            stop_file = "/tmp/voice_transcription_stop.flag"

            while not self.stop_streaming.is_set():
                time.sleep(0.5)

                # Max duration
                if time.time() - start_time > max_duration:
                    self.logger.info("Maximum duration reached, stopping...")
                    break

                # Silence timeout: stop after silence_timeout seconds of mic
                # silence. Uses the same silence threshold as the visual
                # indicator, so the session ends at the moment the overlay fully
                # fades out - giving the user a clear "it's done, start a new
                # one" signal instead of lingering ~1.5s longer waiting on the
                # trailing VAD commit.
                now = time.time()
                since_audio = now - last_audio_activity_time
                if since_audio > silence_timeout and full_text.strip():
                    self.logger.info(f"Silence detected for {since_audio:.1f}s, stopping...")
                    break

                # Stop flag (in-memory)
                if stop_flag and stop_flag.get('stop', False):
                    self.logger.info("Stop flag set, stopping...")
                    break

                # Stop file (inter-process)
                if os.path.exists(stop_file):
                    self.logger.info("Stop file detected, stopping...")
                    break

            # Cleanup: terminate recorder + close WS to unblock send/receive threads
            self.stop_streaming.set()
            try:
                if self.recorder_process:
                    self.recorder_process.terminate()
            except Exception:
                pass
            try:
                ws.close()
            except Exception:
                pass

        # Launch threads
        send_thread = threading.Thread(target=send_audio, daemon=True)
        recv_thread = threading.Thread(target=receive_messages, daemon=True)
        monitor_thread = threading.Thread(target=monitor, daemon=True)

        send_thread.start()
        recv_thread.start()
        monitor_thread.start()

        # Block on audio streaming (like AssemblyAI's client.stream())
        # Send thread exits when recorder is terminated by monitor
        try:
            send_thread.join()
        except KeyboardInterrupt:
            self.logger.info("Streaming interrupted by user")
            self.stop_streaming.set()

        # Signal stop and wait for cleanup
        self.stop_streaming.set()
        monitor_thread.join(timeout=2)

        # Ensure recorder is stopped
        if self.recorder_process:
            try:
                self.recorder_process.terminate()
                self.recorder_process.wait(timeout=1)
                self.logger.info("Audio recorder stopped")
            except subprocess.TimeoutExpired:
                self.recorder_process.kill()
            except Exception:
                pass
            self.recorder_process = None

        # Close WS (may already be closed by monitor)
        try:
            ws.close()
        except Exception:
            pass

        recv_thread.join(timeout=1)

        self.logger.info(f"ElevenLabs session ended, total text: '{full_text.strip()[:80]}'")
        return full_text.strip()

class ElevenLabsError(Exception):
    """Custom exception for ElevenLabs API errors"""
    pass
