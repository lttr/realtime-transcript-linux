#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import os
import time
import logging
import requests
from typing import Optional, Union
import numpy as np
from pathlib import Path
from audio_utils import AudioCapture

# Try to import dotenv, but don't fail if not available
try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False


class ElevenLabsTranscriber:
    """ElevenLabs Speech-to-Text API client with error handling and retries"""
    
    def __init__(self, api_key: Optional[str] = None, skip_availability_check: bool = False):
        # Initialize logger first
        self.logger = logging.getLogger(__name__)
        
        self.api_key = api_key or self._load_api_key()
        self.base_url = "https://api.elevenlabs.io/v1"
        self.model_id = "scribe_v1"
        self.skip_availability_check = skip_availability_check
        
        # Timeout and retry settings  
        self.quick_test_timeout = 5.0  # 5 seconds for connectivity test
        self.api_timeout = 8.0  # 8 seconds for transcription requests
        self.max_retries = 2
        self.retry_delay = 1.0
        
        if not self.api_key:
            self.logger.warning("No ElevenLabs API key found. Create .env file or set ELEVENLABS_API_KEY environment variable.")
    
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
            # Quick connectivity test using models endpoint (more permissive)
            response = requests.get(
                f"{self.base_url}/models", 
                headers={"xi-api-key": self.api_key},
                timeout=self.quick_test_timeout
            )
            # Accept wide range of status codes as "API is reachable"
            # 200: Success, 401: Auth issue but API works, 429: Rate limited but API works
            # 403: Permissions but API works, 422: Bad request but API works
            return response.status_code in [200, 401, 403, 422, 429]
            
        except requests.exceptions.Timeout:
            # Still consider timeout as unavailable since we need fast responses
            self.logger.debug(f"API timeout after {self.quick_test_timeout}s")
            return False
        except requests.exceptions.ConnectionError:
            # Network/DNS issues - definitely unavailable
            self.logger.debug("API connection error")
            return False
        except Exception as e:
            # For any other errors, be optimistic and assume API might work
            self.logger.debug(f"API availability check error (assuming available): {e}")
            return True  # Changed from False to True - be optimistic
    
    def transcribe_audio(self, audio_data: Union[np.ndarray, bytes], language: str = "en") -> Optional[str]:
        """
        Transcribe audio using ElevenLabs API
        
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
        
        # Check minimum audio length and quality (avoid API calls for tiny/silent clips)
        # WAV header is ~44 bytes + actual audio data
        # For 16kHz 16-bit audio: ~32KB per second
        audio_size_kb = len(wav_data) / 1024
        
        # Skip very small audio files (less than 0.5s)
        if len(wav_data) < 16000:  # ~0.5 seconds of audio + headers
            self.logger.info(f"Audio too short for transcription ({audio_size_kb:.1f}KB < ~16KB minimum)")
            return ""
        
        # For medium-sized segments, check if they're mostly silence
        if len(wav_data) < 64000:  # Less than ~2 seconds
            if self._is_mostly_silent(audio_data if isinstance(audio_data, np.ndarray) else wav_data):
                self.logger.info(f"Audio mostly silent ({audio_size_kb:.1f}KB) - skipping to avoid empty response")
                return ""
        
        return self._transcribe_with_retry(wav_data, language)
    
    def _is_mostly_silent(self, audio_data) -> bool:
        """Check if audio data is mostly silence by analyzing volume levels"""
        try:
            if isinstance(audio_data, bytes):
                # Skip WAV header (assume first 44 bytes) and convert to numpy
                audio_bytes = audio_data[44:] if len(audio_data) > 44 else audio_data
                audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            else:
                audio_np = audio_data
            
            if len(audio_np) == 0:
                return True
            
            # Calculate RMS volume and peak volume
            rms = np.sqrt(np.mean(audio_np**2))
            peak = np.max(np.abs(audio_np))
            
            # Threshold for silence detection (quite conservative)
            silence_threshold_rms = 0.01  # 1% of full scale
            silence_threshold_peak = 0.05  # 5% of full scale
            
            is_silent = rms < silence_threshold_rms and peak < silence_threshold_peak
            
            if is_silent:
                self.logger.debug(f"Audio silence check: RMS={rms:.4f}, Peak={peak:.4f} - considered silent")
            
            return is_silent
            
        except Exception as e:
            self.logger.debug(f"Silence detection error: {e}, assuming not silent")
            return False
    
    def _transcribe_with_retry(self, wav_data: bytes, language: str) -> Optional[str]:
        """Transcribe with retry logic and error handling"""
        
        for attempt in range(self.max_retries + 1):
            try:
                start_time = time.time()
                audio_size_kb = len(wav_data) / 1024
                self.logger.info(f"Sending {audio_size_kb:.1f}KB audio to ElevenLabs API (attempt {attempt + 1})")
                
                # Prepare request
                files = {
                    'file': ('audio.wav', wav_data, 'audio/wav')
                }
                
                data = {
                    'model_id': self.model_id,
                    'tag_audio_events': False  # Disable audio event descriptions
                }
                
                # Only add language_code if not in auto-detection mode
                if language is not None:
                    data['language_code'] = language
                
                headers = {
                    'xi-api-key': self.api_key
                }
                
                # Make API request
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
                
                elif response.status_code == 429:  # Rate limited
                    self.logger.warning(f"ElevenLabs API rate limited after {elapsed:.1f}s (attempt {attempt + 1})")
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay * (attempt + 1))
                        continue
                    return None
                
                elif response.status_code == 401:  # Authentication error
                    self.logger.error(f"ElevenLabs API authentication failed after {elapsed:.1f}s - check API key")
                    return None
                
                elif response.status_code >= 500:  # Server error
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
    
    def transcribe_streaming(self, audio_capture: AudioCapture, text_callback=None, stop_flag=None, language: str = "en") -> str:
        """
        Perform streaming transcription with progressive results
        
        Args:
            audio_capture: AudioCapture instance
            text_callback: Function called with each transcribed phrase
            stop_flag: Shared dictionary to signal stop
            language: Language code for transcription (default: en)
            
        Returns:
            Complete transcribed text
        """
        full_text = ""
        
        def process_audio_chunk(audio_chunk):
            nonlocal full_text
            
            # Allow shorter chunks for commands, but skip very tiny ones  
            min_duration = 0.8 * audio_capture.sample_rate
            if len(audio_chunk) < min_duration:
                duration_s = len(audio_chunk) / audio_capture.sample_rate
                self.logger.info(f"Skipping short audio chunk ({duration_s:.1f}s < 0.8s minimum)")
                return
            
            # Transcribe chunk
            phrase_text = self.transcribe_audio(audio_chunk, language)
            
            if phrase_text and phrase_text.strip():
                full_text += phrase_text + " "
                
                if text_callback:
                    text_callback(phrase_text.strip(), full_text.strip())
        
        # Capture audio with streaming processing
        audio_capture.capture_streaming_audio(
            callback=process_audio_chunk,
            stop_flag=stop_flag
        )
        
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
