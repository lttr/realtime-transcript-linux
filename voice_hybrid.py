#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import sys
import os
import logging
import time
from audio_utils import AudioCapture, NotificationHelper, TextInjector
from elevenlabs_transcriber import ElevenLabsTranscriber
from whisper_fallback import WhisperFallback


class HybridVoiceTranscriber:
    """Hybrid voice transcription system with ElevenLabs primary and Whisper fallback"""
    
    def __init__(self):
        self.audio_capture = AudioCapture()
        # Use optimistic mode - skip availability check, just try API directly
        self.elevenlabs = ElevenLabsTranscriber(skip_availability_check=True)
        self.whisper = WhisperFallback()
        self.text_injector = TextInjector()
        self.notification = NotificationHelper()
        
        # Transcription state
        self.stop_flag = {'stop': False}
        self.current_engine = None
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('/tmp/voice_hybrid.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def _select_transcription_engine(self):
        """Smart engine selection: Try ElevenLabs first, fallback on failure"""
        
        # Always try ElevenLabs first if API key is configured
        if self.elevenlabs.api_key:
            self.logger.info("🌐 Attempting ElevenLabs API transcription")
            self.current_engine = "elevenlabs"
            return self.elevenlabs
        
        # No API key - use Whisper directly
        if self.whisper.is_available():
            self.logger.info("🔄 No API key configured, using Whisper")
            self.notification.show_notification(
                "🔄 Using local processing (no API key)", 
                urgency="normal", 
                expire_time="2000"
            )
            self.current_engine = "whisper"
            return self.whisper
        
        # No engines available
        self.logger.error("❌ No transcription engines available")
        self.current_engine = None
        return None
    
    def _handle_transcription_result(self, phrase_text, full_text):
        """Handle partial transcription results with progressive injection"""
        
        if phrase_text.strip():
            print(f"Phrase: '{phrase_text}'")
            
            # Inject text immediately
            if self.text_injector.inject_text(phrase_text + " "):
                print(f"✓ Injected: '{phrase_text}'")
            else:
                print(f"✗ Failed to inject: '{phrase_text}'")
    
    def transcribe(self):
        """Main transcription method with smart engine selection"""
        
        print("Starting hybrid voice transcription...")
        
        # Select best available engine
        engine = self._select_transcription_engine()
        if not engine:
            self.notification.show_notification(
                "❌ No transcription engines available", 
                urgency="critical"
            )
            return False
        
        # Show initial notification
        if self.current_engine == "elevenlabs":
            self.notification.show_notification("🎤 Recording with ElevenLabs", urgency="normal")
        else:
            # For Whisper, show loading notification if model needs to load
            if not self.whisper.model_loaded:
                self.notification.show_notification(
                    "⏳ Loading local model (first time)", 
                    urgency="normal", 
                    expire_time="8000"
                )
        
        try:
            # Reset stop flag
            self.stop_flag['stop'] = False
            
            # Start transcription with selected engine
            start_time = time.time()
            
            final_text = engine.transcribe_streaming(
                self.audio_capture,
                text_callback=self._handle_transcription_result,
                stop_flag=self.stop_flag
            )
            
            elapsed = time.time() - start_time
            
            # Handle final result
            if final_text.strip():
                print(f"✅ Transcription complete ({elapsed:.1f}s): '{final_text}'")
                print(f"Engine used: {self.current_engine}")
                return True
            else:
                print("No speech detected")
                self.notification.show_notification("No speech detected", urgency="low")
                return False
        
        except KeyboardInterrupt:
            print("\n🛑 Transcription interrupted by user")
            self.stop_flag['stop'] = True
            return False
        
        except Exception as e:
            self.logger.error(f"Transcription error: {e}")
            
            # Try fallback if primary engine failed
            if self.current_engine == "elevenlabs" and self.whisper.is_available():
                self.logger.info("🔄 Trying Whisper fallback after ElevenLabs error")
                self.notification.show_notification(
                    "🔄 API failed, trying local processing", 
                    urgency="normal"
                )
                
                try:
                    self.current_engine = "whisper"
                    self.stop_flag['stop'] = False  # Reset for retry
                    
                    final_text = self.whisper.transcribe_streaming(
                        self.audio_capture,
                        text_callback=self._handle_transcription_result,
                        stop_flag=self.stop_flag
                    )
                    
                    if final_text.strip():
                        print(f"✅ Fallback transcription successful: '{final_text}'")
                        return True
                    
                except Exception as fallback_error:
                    self.logger.error(f"Fallback transcription also failed: {fallback_error}")
            
            # All engines failed
            self.notification.show_notification(
                "❌ Transcription failed", 
                urgency="critical"
            )
            return False
    
    def stop_recording(self):
        """Stop active recording session"""
        print("Stopping recording...")
        self.stop_flag['stop'] = True
        self.notification.show_notification("🛑 Recording stopped", urgency="normal")
    
    def get_engine_status(self):
        """Get status of available transcription engines"""
        status = {
            'elevenlabs': {
                'available': self.elevenlabs.is_available(),
                'api_key_configured': bool(self.elevenlabs.api_key)
            },
            'whisper': {
                'available': self.whisper.is_available(),
                'model_loaded': self.whisper.model_loaded
            }
        }
        
        return status
    
    def ping(self):
        """Health check for the transcription system"""
        status = self.get_engine_status()
        
        if status['elevenlabs']['available'] or status['whisper']['available']:
            print("✅ Hybrid transcription system is ready")
            print(f"ElevenLabs: {'✅' if status['elevenlabs']['available'] else '❌'}")
            print(f"Whisper: {'✅' if status['whisper']['available'] else '❌'}")
            return True
        else:
            print("❌ No transcription engines available")
            return False


def main():
    transcriber = HybridVoiceTranscriber()
    
    # Handle command line arguments
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == 'ping':
            success = transcriber.ping()
            sys.exit(0 if success else 1)
        
        elif command == 'stop':
            transcriber.stop_recording()
            sys.exit(0)
        
        elif command == 'status':
            status = transcriber.get_engine_status()
            print("Engine Status:")
            for engine, info in status.items():
                print(f"  {engine}: {info}")
            sys.exit(0)
        
        elif command == 'help':
            print("Hybrid Voice Transcription System")
            print("Primary: ElevenLabs API | Fallback: Local Whisper")
            print()
            print("Usage:")
            print("  voice_hybrid.py          - Start transcription")
            print("  voice_hybrid.py ping     - Check system status") 
            print("  voice_hybrid.py stop     - Stop active recording")
            print("  voice_hybrid.py status   - Show engine availability")
            print("  voice_hybrid.py help     - Show this help")
            print()
            print("Environment:")
            print("  ELEVENLABS_API_KEY - Required for ElevenLabs API")
            sys.exit(0)
        
        else:
            print(f"Unknown command: {command}")
            print("Use 'voice_hybrid.py help' for usage information")
            sys.exit(1)
    
    # Default action: transcribe
    try:
        success = transcriber.transcribe()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
        sys.exit(130)  # Standard exit code for Ctrl+C


if __name__ == "__main__":
    main()