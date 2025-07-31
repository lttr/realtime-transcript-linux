#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import logging
import time
import threading
from typing import Optional, Union
import numpy as np
from audio_utils import AudioCapture


class WhisperFallback:
    """Local Whisper transcription fallback with lazy loading"""
    
    def __init__(self):
        self.whisper_model = None
        self.model_lock = threading.Lock()
        self.model_loaded = False
        self.load_start_time = None
        
        # Model configuration (same as original daemon)
        self.model_name = "tiny.en"
        self.device = "cpu"
        self.compute_type = "float32"
        
        self.logger = logging.getLogger(__name__)
    
    def is_available(self) -> bool:
        """Check if Whisper fallback can be used (always true if dependencies available)"""
        try:
            from faster_whisper import WhisperModel
            return True
        except ImportError:
            self.logger.error("faster-whisper not available - install requirements")
            return False
    
    def _load_model(self) -> bool:
        """Load Whisper model with lazy initialization"""
        if self.model_loaded and self.whisper_model:
            return True
        
        with self.model_lock:
            # Double-check after acquiring lock
            if self.model_loaded and self.whisper_model:
                return True
            
            try:
                from faster_whisper import WhisperModel
                
                self.logger.info("🔄 Loading Whisper model (first-time may take 5+ seconds)...")
                self.load_start_time = time.time()
                
                self.whisper_model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=None  # Use default cache
                )
                
                load_time = time.time() - self.load_start_time
                self.model_loaded = True
                
                self.logger.info(f"✅ Whisper model loaded successfully ({load_time:.1f}s)")
                return True
                
            except Exception as e:
                self.logger.error(f"Failed to load Whisper model: {e}")
                self.whisper_model = None
                self.model_loaded = False
                return False
    
    def transcribe_audio(self, audio_data: np.ndarray, language: str = "en") -> Optional[str]:
        """
        Transcribe audio using local Whisper model
        
        Args:
            audio_data: Audio as numpy array (float32, normalized)
            language: Language code (default: en)
            
        Returns:
            Transcribed text or None if failed
        """
        if not self._load_model():
            return None
        
        if len(audio_data) < 0.5 * 16000:  # Less than 0.5 seconds at 16kHz
            self.logger.info("Audio too short for transcription")
            return ""
        
        try:
            start_time = time.time()
            
            # Transcribe with anti-repetition parameters (same as original)
            segments, info = self.whisper_model.transcribe(
                audio_data,
                language=language,
                beam_size=1,        # Reduced to prevent repetition
                temperature=0.3,    # Add randomness to break repetition
                condition_on_previous_text=False  # Disable to prevent loops
            )
            
            # Combine segments
            text = " ".join([segment.text for segment in segments]).strip()
            
            elapsed = time.time() - start_time
            self.logger.info(f"Whisper transcription complete ({elapsed:.1f}s): '{text[:50]}{'...' if len(text) > 50 else ''}'")
            
            return text
            
        except Exception as e:
            self.logger.error(f"Whisper transcription error: {e}")
            return None
    
    def transcribe_streaming(self, audio_capture: AudioCapture, text_callback=None, stop_flag=None) -> str:
        """
        Perform streaming transcription with progressive results
        
        Args:
            audio_capture: AudioCapture instance
            text_callback: Function called with each transcribed phrase
            stop_flag: Shared dictionary to signal stop
            
        Returns:
            Complete transcribed text
        """
        # Ensure model is loaded before starting
        if not self._load_model():
            self.logger.error("Cannot load Whisper model for streaming")
            return ""
        
        full_text = ""
        
        def process_audio_chunk(audio_chunk):
            nonlocal full_text
            
            if len(audio_chunk) < 0.5 * audio_capture.sample_rate:  # Less than 0.5s
                return
            
            # Transcribe chunk
            phrase_text = self.transcribe_audio(audio_chunk)
            
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
    
    def unload_model(self):
        """Unload model to free memory (optional cleanup)"""
        with self.model_lock:
            if self.whisper_model:
                self.logger.info("Unloading Whisper model to free memory")
                self.whisper_model = None
                self.model_loaded = False
    
    def get_model_info(self) -> dict:
        """Get information about the loaded model"""
        return {
            'model_name': self.model_name,
            'device': self.device,
            'compute_type': self.compute_type,
            'loaded': self.model_loaded,
            'load_time': getattr(self, 'load_start_time', None)
        }