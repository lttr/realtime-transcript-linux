#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import sys
import os
import logging
import time
from audio_utils import AudioCapture, NotificationHelper, TextInjector
from elevenlabs_transcriber import ElevenLabsTranscriber


class VoiceTranscriber:
    """ElevenLabs voice transcription system with instance locking"""
    
    def __init__(self):
        self.audio_capture = AudioCapture()
        self.elevenlabs = ElevenLabsTranscriber(skip_availability_check=True)
        self.text_injector = TextInjector()
        self.notification = NotificationHelper()
        
        # Transcription state
        self.stop_flag = {'stop': False}
        self.stop_file = "/tmp/voice_transcription_stop.flag"
        self.lock_file = "/tmp/voice_transcription.pid"
        
        # Setup logging first
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('/tmp/voice_transcription.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Language configuration
        self.supported_languages = {
            'auto': {'name': 'Auto-detect', 'code': None},
            'en': {'name': 'English', 'code': 'en'},
            'cs': {'name': 'Czech', 'code': 'cs'}
        }
        self.current_language = self._detect_system_language()
    
    def _detect_system_language(self):
        """Detect system language preference, default to auto-detection for best mixed-language support"""
        try:
            import locale
            import os
            
            # Try environment variables first (more reliable)
            for env_var in ['LANG', 'LC_ALL', 'LC_MESSAGES']:
                lang_env = os.getenv(env_var)
                if lang_env:
                    lang_code = lang_env.split('_')[0].lower()
                    if lang_code in self.supported_languages and lang_code != 'auto':
                        self.logger.info(f"Detected system language: {self.supported_languages[lang_code]['name']}, but using auto-detection for mixed-language support")
                        return 'auto'  # Use auto-detection even if we detect a specific language
                    break
            
            # Fall back to locale if env vars don't work
            try:
                system_lang = locale.getlocale()[0]
                if system_lang:
                    lang_code = system_lang.split('_')[0].lower()
                    if lang_code in self.supported_languages and lang_code != 'auto':
                        self.logger.info(f"Detected system language: {self.supported_languages[lang_code]['name']}, but using auto-detection for mixed-language support")
                        return 'auto'  # Use auto-detection even if we detect a specific language
            except:
                pass
                
        except Exception as e:
            self.logger.debug(f"Could not detect system language: {e}")
        
        # Default to auto-detection for best bilingual experience
        self.logger.info("Using automatic language detection for optimal bilingual transcription")
        return 'auto'
    
    def set_language(self, lang_code: str):
        """Set transcription language"""
        if lang_code in self.supported_languages:
            self.current_language = lang_code
            self.logger.info(f"Language set to: {self.supported_languages[lang_code]['name']}")
            return True
        else:
            self.logger.error(f"Unsupported language: {lang_code}")
            return False
    
    def _check_api_availability(self):
        """Check if ElevenLabs API is available"""
        if not self.elevenlabs.api_key:
            self.logger.error("❌ ElevenLabs API key not configured")
            return False
        
        if not self.elevenlabs.is_available():
            self.logger.error("❌ ElevenLabs API not available")
            return False
        
        return True
    
    def _handle_transcription_result(self, phrase_text, full_text):
        """Handle partial transcription results with progressive injection"""
        
        if phrase_text.strip():
            self.logger.info(f"Transcribed phrase: '{phrase_text}'")
            print(f"Phrase: '{phrase_text}'")
            
            # Inject text immediately
            injection_start = time.time()
            if self.text_injector.inject_text(phrase_text + " "):
                injection_time = time.time() - injection_start
                self.logger.info(f"Phrase successfully injected ({injection_time*1000:.0f}ms total)")
                print(f"✓ Injected: '{phrase_text}'")
            else:
                injection_time = time.time() - injection_start
                self.logger.error(f"Phrase injection failed ({injection_time*1000:.0f}ms total)")
                print(f"✗ Failed to inject: '{phrase_text}'")
    
    def _acquire_lock(self):
        """Acquire instance lock to prevent multiple simultaneous recordings"""
        try:
            if os.path.exists(self.lock_file):
                # Check if existing PID is still running
                with open(self.lock_file, 'r') as f:
                    old_pid = int(f.read().strip())
                
                try:
                    # Check if process is still running
                    os.kill(old_pid, 0)
                    # Process exists - another instance is running
                    self.logger.info("🔒 Another transcription session is already active")
                    self.notification.show_notification(
                        "🔒 Voice transcription already in progress", 
                        urgency="normal"
                    )
                    return False
                except (OSError, ProcessLookupError):
                    # Process doesn't exist - stale lock file
                    self.logger.info("🧹 Removing stale lock file")
                    os.remove(self.lock_file)
            
            # Write current PID to lock file
            with open(self.lock_file, 'w') as f:
                f.write(str(os.getpid()))
            
            return True
            
        except Exception as e:
            self.logger.error(f"Lock acquisition error: {e}")
            return False
    
    def _release_lock(self):
        """Release instance lock"""
        try:
            if os.path.exists(self.lock_file):
                os.remove(self.lock_file)
        except Exception as e:
            self.logger.error(f"Lock release error: {e}")
    
    def transcribe(self):
        """Main transcription method using ElevenLabs API"""
        
        # Acquire instance lock first
        if not self._acquire_lock():
            return False
        
        try:
            print("Starting voice transcription...")
            
            # Check API availability
            if not self._check_api_availability():
                self.notification.show_notification(
                    "❌ ElevenLabs API not available", 
                    urgency="critical"
                )
                return False
            
            # Show initial notification
            self.notification.show_notification("🎤 Recording with ElevenLabs", urgency="normal")
            
            # Reset stop flag and remove any existing stop file
            self.stop_flag['stop'] = False
            if os.path.exists(self.stop_file):
                os.remove(self.stop_file)
            
            # Start transcription with ElevenLabs
            start_time = time.time()
            
            # Get language code
            language_code = self.supported_languages[self.current_language]['code']
            
            final_text = self.elevenlabs.transcribe_streaming(
                self.audio_capture,
                text_callback=self._handle_transcription_result,
                stop_flag=self.stop_flag,
                language=language_code
            )
            
            elapsed = time.time() - start_time
            
            # Handle final result
            if final_text.strip():
                self.logger.info(f"Complete transcription session finished ({elapsed:.1f}s): '{final_text}'")
                print(f"✅ Transcription complete ({elapsed:.1f}s): '{final_text}'")
                return True
            else:
                self.logger.info(f"Transcription session ended with no speech detected ({elapsed:.1f}s)")
                print("No speech detected")
                self.notification.show_notification("No speech detected", urgency="low")
                return False
        
        except KeyboardInterrupt:
            print("\n🛑 Transcription interrupted by user")
            self.stop_flag['stop'] = True
            return False
        
        except Exception as e:
            self.logger.error(f"Transcription error: {e}")
            self.notification.show_notification(
                "❌ Transcription failed", 
                urgency="critical"
            )
            return False
        
        finally:
            # Always release the lock
            self._release_lock()
    
    def stop_recording(self):
        """Stop active recording session"""
        print("Stopping recording...")
        # Create stop file for inter-process communication
        try:
            with open(self.stop_file, 'w') as f:
                f.write(str(time.time()))
            self.stop_flag['stop'] = True
            self.notification.show_notification("🛑 Recording stopped", urgency="normal")
        except Exception as e:
            print(f"Error creating stop file: {e}")
            self.stop_flag['stop'] = True
    
    def get_engine_status(self):
        """Get status of ElevenLabs transcription engine"""
        status = {
            'elevenlabs': {
                'available': self.elevenlabs.is_available(),
                'api_key_configured': bool(self.elevenlabs.api_key)
            }
        }
        return status
    
    def print_status(self):
        """Print current system status"""
        print("Engine Status:")
        status = self.get_engine_status()
        
        for engine, info in status.items():
            print(f"  {engine}: {info}")
        
        if status['elevenlabs']['available']:
            print("Status: Ready")
        else:
            print("Status: Not ready - check API configuration")
    
    def ping_test(self):
        """Test connectivity to transcription service"""
        print("Testing ElevenLabs API connectivity...")
        
        if self.elevenlabs.is_available():
            print("✅ ElevenLabs API: Connected")
            return True
        else:
            print("❌ ElevenLabs API: Connection failed")
            return False


def main():
    if len(sys.argv) < 2:
        # Default: start transcription
        transcriber = VoiceTranscriber()
        transcriber.transcribe()
        return
    
    command = sys.argv[1].lower()
    transcriber = VoiceTranscriber()
    
    if command == "status":
        transcriber.print_status()
    elif command == "ping":
        transcriber.ping_test()
    elif command == "stop":
        transcriber.stop_recording()
    elif command == "lang":
        if len(sys.argv) > 2:
            lang = sys.argv[2].lower()
            if transcriber.set_language(lang):
                print(f"Language set to: {transcriber.supported_languages[lang]['name']}")
            else:
                print(f"Unsupported language: {lang}")
                print(f"Supported: {', '.join(transcriber.supported_languages.keys())}")
        else:
            current = transcriber.current_language
            print(f"Current language: {transcriber.supported_languages[current]['name']} ({current})")
            print("Available languages:")
            for code, info in transcriber.supported_languages.items():
                print(f"  {code}: {info['name']}")
    else:
        print("Usage:")
        print("  ./voice_transcription.py         # Start transcription")
        print("  ./voice_transcription.py status  # Show system status")
        print("  ./voice_transcription.py ping    # Test API connectivity")
        print("  ./voice_transcription.py stop    # Stop active recording")
        print("  ./voice_transcription.py lang    # Show current language")
        print("  ./voice_transcription.py lang <code>  # Set language (auto/en/cs)")


if __name__ == "__main__":
    main()
