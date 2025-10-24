#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import os
import time
import logging
import numpy as np
import threading
from typing import Optional, Callable, Type
from pathlib import Path

# Try to import dotenv, but don't fail if not available
try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False

try:
    import assemblyai as aai
    from assemblyai.streaming.v3 import (
        BeginEvent,
        StreamingClient,
        StreamingClientOptions,
        StreamingError,
        StreamingEvents,
        StreamingParameters,
        StreamingSessionParameters,
        TerminationEvent,
        TurnEvent,
    )
    ASSEMBLYAI_AVAILABLE = True
except ImportError:
    ASSEMBLYAI_AVAILABLE = False


class AssemblyAITranscriber:
    """AssemblyAI Speech-to-Text streaming client with real-time transcription"""

    def __init__(self, api_key: Optional[str] = None, skip_availability_check: bool = False):
        # Initialize logger first
        self.logger = logging.getLogger(__name__)

        self.api_key = api_key or self._load_api_key()
        self.skip_availability_check = skip_availability_check

        # Streaming settings
        self.sample_rate = 16000

        # State tracking for progressive transcription
        self.full_text = ""
        self.text_callback = None
        self.client = None
        self.mic_stream = None  # Store mic stream for cleanup
        self.is_streaming = False
        self.stop_streaming = None  # Threading event for stopping

        if not ASSEMBLYAI_AVAILABLE:
            self.logger.warning("AssemblyAI package not installed. Run: pip install assemblyai")
        elif not self.api_key:
            self.logger.warning("No AssemblyAI API key found. Create .env file or set ASSEMBLYAI_API_KEY environment variable.")

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
        api_key = os.getenv('ASSEMBLYAI_API_KEY')

        if api_key:
            return api_key

        # If no key found, log helpful message
        if DOTENV_AVAILABLE:
            self.logger.debug("No API key found in .env file or environment variables")
        else:
            self.logger.debug("No API key found in environment variables (python-dotenv not available)")

        return None

    def is_available(self) -> bool:
        """Quick connectivity test to AssemblyAI API"""
        if not ASSEMBLYAI_AVAILABLE:
            self.logger.debug("AssemblyAI package not installed")
            return False

        if not self.api_key:
            return False

        # If skip check is enabled, assume it's available (optimistic)
        if self.skip_availability_check:
            return True

        try:
            # Quick test by creating a client (doesn't make network call)
            # Real validation happens on first connection
            return True

        except Exception as e:
            self.logger.debug(f"API availability check error: {e}")
            return False

    def _create_event_handlers(self):
        """Create event handler functions that have access to self"""
        transcriber = self  # Capture self in closure

        def on_begin(client: Type[StreamingClient], event: BeginEvent):
            """Handle session start event"""
            transcriber.logger.info(f"AssemblyAI session started: {event.id}")
            transcriber.is_streaming = True
            transcriber.full_text = ""

        def on_turn(client: Type[StreamingClient], event: TurnEvent):
            """Handle turn event - this is where we get transcribed text"""
            # Update last turn time
            transcriber.last_turn_time = time.time()

            transcriber.logger.debug(f"Turn event: '{event.transcript}', end={event.end_of_turn}, formatted={event.turn_is_formatted}")

            transcript = event.transcript.strip()

            # Only inject when we have a FINAL, FORMATTED transcript
            if transcript and event.end_of_turn and event.turn_is_formatted:
                transcriber.logger.info(f"Final formatted transcript: '{transcript}'")

                # Add to full text
                if transcriber.full_text and not transcriber.full_text.endswith(" "):
                    transcriber.full_text += " "
                transcriber.full_text += transcript

                # Call text callback to inject the complete, finalized phrase
                if transcriber.text_callback:
                    try:
                        transcriber.text_callback(transcript, transcriber.full_text.strip())
                    except Exception as e:
                        transcriber.logger.error(f"Error in text callback: {e}")

        def on_terminated(client: Type[StreamingClient], event: TerminationEvent):
            """Handle session termination"""
            transcriber.logger.info(f"Session terminated: {event.audio_duration_seconds:.1f}s processed")
            transcriber.is_streaming = False
            if transcriber.stop_streaming:
                transcriber.stop_streaming.set()

        def on_error(client: Type[StreamingClient], error: StreamingError):
            """Handle streaming errors"""
            transcriber.logger.error(f"Streaming error: {error}")
            transcriber.is_streaming = False
            if transcriber.stop_streaming:
                transcriber.stop_streaming.set()

        return on_begin, on_turn, on_terminated, on_error

    def transcribe_streaming(self, audio_capture, text_callback=None, stop_flag=None, language: str = "en") -> str:
        """
        Perform streaming transcription with progressive results

        Args:
            audio_capture: AudioCapture instance (not used - AssemblyAI captures directly)
            text_callback: Function called with each transcribed phrase
            stop_flag: Shared dictionary to signal stop
            language: Language code for transcription (default: en, None for auto)

        Returns:
            Complete transcribed text
        """
        if not ASSEMBLYAI_AVAILABLE:
            self.logger.error("AssemblyAI package not installed")
            return ""

        if not self.api_key:
            self.logger.error("No AssemblyAI API key available")
            return ""

        # Store callback for use in event handlers
        self.text_callback = text_callback
        self.full_text = ""
        self.last_turn_time = time.time()
        self.silence_timeout = 5.0  # Stop after 5 seconds of silence

        try:
            # Create streaming client
            self.logger.info("Creating AssemblyAI streaming client...")
            client = StreamingClient(
                StreamingClientOptions(
                    api_key=self.api_key,
                    api_host="streaming.assemblyai.com",
                )
            )
            self.client = client

            # Create and register event handlers
            on_begin, on_turn, on_terminated, on_error = self._create_event_handlers()
            client.on(StreamingEvents.Begin, on_begin)
            client.on(StreamingEvents.Turn, on_turn)
            client.on(StreamingEvents.Termination, on_terminated)
            client.on(StreamingEvents.Error, on_error)

            # Prepare streaming parameters
            params = StreamingParameters(
                sample_rate=self.sample_rate,
                format_turns=True,  # Enable capitalization and punctuation
            )

            # Connect to streaming service
            self.logger.info("Connecting to AssemblyAI streaming service...")
            client.connect(params)

            # Create microphone stream
            self.logger.info("Starting microphone stream...")

            # Start a timeout monitor thread to stop after silence
            self.stop_streaming = threading.Event()

            def timeout_monitor():
                """Monitor for silence timeout"""
                max_duration = 45  # Maximum recording duration
                start_time = time.time()

                while not self.stop_streaming.is_set():
                    time.sleep(0.5)  # Check every 0.5 seconds

                    # Check max duration
                    if time.time() - start_time > max_duration:
                        self.logger.info("Maximum duration reached, stopping...")
                        self.stop_streaming.set()
                        break

                    # Check silence timeout
                    silence_duration = time.time() - self.last_turn_time
                    if silence_duration > self.silence_timeout and self.full_text.strip():
                        self.logger.info(f"Silence detected for {silence_duration:.1f}s, stopping...")
                        self.stop_streaming.set()
                        break

                    # Check stop flag
                    if stop_flag and stop_flag.get('stop', False):
                        self.logger.info("Stop flag set, stopping...")
                        self.stop_streaming.set()
                        break

                # Disconnect when stopped
                try:
                    # Close mic stream to unblock client.stream()
                    if transcriber.mic_stream:
                        transcriber.mic_stream.close()
                    client.disconnect(terminate=True)
                except Exception as e:
                    transcriber.logger.debug(f"Cleanup error in monitor: {e}")

            monitor_thread = threading.Thread(target=timeout_monitor, daemon=True)
            monitor_thread.start()

            # Start streaming with generator wrapper for proper cleanup
            try:
                self.mic_stream = aai.extras.MicrophoneStream(sample_rate=self.sample_rate)

                # Wrap mic stream to allow interruption
                def audio_generator():
                    """Generator that yields audio but can be stopped"""
                    try:
                        for chunk in self.mic_stream:
                            if self.stop_streaming.is_set():
                                self.logger.info("Stop signal received in audio generator")
                                break
                            yield chunk
                    finally:
                        if self.mic_stream:
                            self.mic_stream.close()

                client.stream(audio_generator())

            except KeyboardInterrupt:
                self.logger.info("Streaming interrupted by user")
            except Exception as e:
                self.logger.error(f"Streaming error: {e}")
            finally:
                # Signal monitor to stop
                self.stop_streaming.set()

                # Close microphone stream
                if self.mic_stream:
                    try:
                        self.mic_stream.close()
                        self.logger.info("Microphone stream closed")
                    except:
                        pass

                # Wait for monitor thread
                monitor_thread.join(timeout=2)

                # Cleanup client
                self.logger.info("Disconnecting from AssemblyAI...")
                try:
                    client.disconnect(terminate=True)
                except:
                    pass

                self.mic_stream = None

            return self.full_text.strip()

        except KeyboardInterrupt:
            self.logger.info("Streaming interrupted by user")
            if self.client:
                self.client.disconnect(terminate=True)
            return self.full_text.strip()

        except Exception as e:
            self.logger.error(f"Streaming error: {e}")
            if self.client:
                try:
                    self.client.disconnect(terminate=True)
                except:
                    pass
            return self.full_text.strip()

    def transcribe_audio(self, audio_data, language: str = "en") -> Optional[str]:
        """
        Transcribe audio (not implemented for streaming-only API)
        AssemblyAI streaming API requires real-time audio input

        This method exists for compatibility but is not used
        """
        self.logger.warning("AssemblyAI transcriber only supports streaming mode")
        return None


class AssemblyAIError(Exception):
    """Custom exception for AssemblyAI API errors"""
    pass
