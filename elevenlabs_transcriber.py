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
from typing import Optional, Union
from pathlib import Path
from audio_utils import AudioCapture, find_recorder

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


class ElevenLabsTranscriber:
    """ElevenLabs Speech-to-Text API client - WebSocket streaming + HTTP fallback"""

    def __init__(self, api_key: Optional[str] = None, skip_availability_check: bool = False):
        # Initialize logger first
        self.logger = logging.getLogger(__name__)

        self.api_key = api_key or self._load_api_key()
        self.base_url = "https://api.elevenlabs.io/v1"
        self.model_id = "scribe_v2_realtime"
        self.batch_model_id = "scribe_v1"
        self.skip_availability_check = skip_availability_check

        # Audio settings (match AssemblyAI)
        self.sample_rate = 16000
        self.chunk_size = 1024
        self.bytes_per_sample = 2  # 16-bit audio
        self.chunk_bytes = self.chunk_size * self.bytes_per_sample

        # Timeout and retry settings (for HTTP fallback)
        self.quick_test_timeout = 5.0
        self.api_timeout = 8.0
        self.max_retries = 2
        self.retry_delay = 1.0

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

    def transcribe_audio(self, audio_data: Union[np.ndarray, bytes], language: str = "en") -> Optional[str]:
        """
        Transcribe audio using ElevenLabs HTTP API (single-shot, scribe_v1)

        Args:
            audio_data: Audio as numpy array or WAV bytes
            language: Language code (default: en)

        Returns:
            Transcribed text or None if failed
        """
        if not self.api_key:
            self.logger.error("No API key available")
            return None

        # Convert audio to WAV bytes if needed
        if isinstance(audio_data, np.ndarray):
            audio_capture = AudioCapture()
            wav_data = audio_capture.frames_to_wav_bytes(audio_data)
            if not wav_data:
                self.logger.error("Failed to convert audio to WAV format")
                return None
        else:
            wav_data = audio_data

        # Skip very small audio files (less than 0.5s)
        if len(wav_data) < 16000:
            audio_size_kb = len(wav_data) / 1024
            self.logger.info(f"Audio too short for transcription ({audio_size_kb:.1f}KB < ~16KB minimum)")
            return ""

        return self._transcribe_with_retry(wav_data, language)

    def _transcribe_with_retry(self, wav_data: bytes, language: str) -> Optional[str]:
        """Transcribe with retry logic and error handling (HTTP API)"""

        for attempt in range(self.max_retries + 1):
            try:
                start_time = time.time()
                audio_size_kb = len(wav_data) / 1024
                self.logger.info(f"Sending {audio_size_kb:.1f}KB audio to ElevenLabs API (attempt {attempt + 1})")

                files = {
                    'file': ('audio.wav', wav_data, 'audio/wav')
                }

                data = {
                    'model_id': self.batch_model_id,
                    'tag_audio_events': False
                }

                if language is not None:
                    data['language_code'] = language

                headers = {
                    'xi-api-key': self.api_key
                }

                response = requests.post(
                    f"{self.base_url}/speech-to-text",
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=self.api_timeout
                )

                elapsed = time.time() - start_time

                if response.status_code == 200:
                    result = response.json()
                    text = result.get('text', '').strip()
                    self.logger.info(f"ElevenLabs API response received ({elapsed:.1f}s): '{text[:50]}{'...' if len(text) > 50 else ''}'")
                    return text

                elif response.status_code == 429:
                    self.logger.warning(f"ElevenLabs API rate limited after {elapsed:.1f}s (attempt {attempt + 1})")
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay * (attempt + 1))
                        continue
                    return None

                elif response.status_code == 401:
                    self.logger.error(f"ElevenLabs API authentication failed after {elapsed:.1f}s - check API key")
                    return None

                elif response.status_code >= 500:
                    self.logger.warning(f"ElevenLabs API server error {response.status_code} after {elapsed:.1f}s (attempt {attempt + 1})")
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay)
                        continue
                    return None

                else:
                    self.logger.error(f"ElevenLabs API error {response.status_code} after {elapsed:.1f}s: {response.text}")
                    return None

            except requests.exceptions.Timeout:
                self.logger.warning(f"ElevenLabs API timeout ({self.api_timeout}s) on attempt {attempt + 1}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                    continue
                return None

            except requests.exceptions.ConnectionError:
                self.logger.warning(f"ElevenLabs API connection error on attempt {attempt + 1}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                    continue
                return None

            except Exception as e:
                self.logger.error(f"Unexpected error during transcription: {e}")
                return None

        self.logger.error("All retry attempts failed")
        return None

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
            "vad_silence_threshold_secs=0.7",
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
            first_chunk = True
            context_prompt = self._get_context_prompt()
            force_commit_interval = 10.0
            last_force_commit = time.time()
            try:
                while not self.stop_streaming.is_set():
                    data = self.recorder_process.stdout.read(self.chunk_bytes)
                    if not data or len(data) < self.chunk_bytes:
                        break

                    # Calculate volume for visual indicator
                    if volume_callback:
                        try:
                            audio_array = np.frombuffer(data, dtype=np.int16)
                            volume = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
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
                        text = self._strip_audio_events(msg.get("text", ""))
                        if text:
                            last_committed_time = time.time()
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
            nonlocal last_committed_time
            start_time = time.time()
            stop_file = "/tmp/voice_transcription_stop.flag"

            while not self.stop_streaming.is_set():
                time.sleep(0.5)

                # Max duration
                if time.time() - start_time > max_duration:
                    self.logger.info("Maximum duration reached, stopping...")
                    break

                # Silence timeout (only if we have text already)
                silence_duration = time.time() - last_committed_time
                if silence_duration > silence_timeout and full_text.strip():
                    self.logger.info(f"Silence detected for {silence_duration:.1f}s, stopping...")
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

    def get_usage_info(self) -> Optional[dict]:
        """Get API usage information (optional, for monitoring)"""
        if not self.api_key:
            return None

        try:
            response = requests.get(
                f"{self.base_url}/user",
                headers={"xi-api-key": self.api_key},
                timeout=5.0
            )

            if response.status_code == 200:
                return response.json()

        except Exception as e:
            self.logger.debug(f"Failed to get usage info: {e}")

        return None


class ElevenLabsError(Exception):
    """Custom exception for ElevenLabs API errors"""
    pass
