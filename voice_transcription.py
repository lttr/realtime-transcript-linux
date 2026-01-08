#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import sys
import os
import logging
import time
from audio_utils import AudioCapture, NotificationHelper, TextInjector
from elevenlabs_transcriber import ElevenLabsTranscriber
from assemblyai_transcriber import AssemblyAITranscriber
from visual_indicator import AudioIndicator


class VoiceTranscriber:
    """Voice transcription system with AssemblyAI and ElevenLabs engines"""

    def __init__(self, engine='assemblyai', use_xdotool=False):
        self.assemblyai = AssemblyAITranscriber(skip_availability_check=True)
        self.elevenlabs = ElevenLabsTranscriber(skip_availability_check=True)
        self.text_injector = TextInjector(use_xdotool=use_xdotool)
        self.notification = NotificationHelper()

        # AudioCapture only needed for ElevenLabs, but we initialize it lazily
        self.audio_capture = None

        # Visual indicator for audio levels
        self.indicator = AudioIndicator()

        # Default engine configuration
        self.engine = engine.lower()
        if self.engine not in ['assemblyai', 'elevenlabs']:
            self.engine = 'assemblyai'
        
        # Transcription state
        self.stop_flag = {'stop': False}
        self.stop_file = "/tmp/voice_transcription_stop.flag"
        self.lock_file = "/tmp/voice_transcription.pid"
        
        # Setup logging first
        logging.basicConfig(
            level=logging.DEBUG if os.getenv('DEBUG') else logging.INFO,
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
        """Check if selected transcription API is available"""
        if self.engine == 'assemblyai':
            if not self.assemblyai.api_key:
                self.logger.error("❌ AssemblyAI API key not configured")
                return False

            if not self.assemblyai.is_available():
                self.logger.error("❌ AssemblyAI API not available")
                return False
        else:  # elevenlabs
            if not self.elevenlabs.api_key:
                self.logger.error("❌ ElevenLabs API key not configured")
                return False

            if not self.elevenlabs.is_available():
                self.logger.error("❌ ElevenLabs API not available")
                return False

        return True
    
    def _handle_transcription_result(self, phrase_text, full_text):
        """Handle partial transcription results with progressive injection"""

        # The transcriber now sends only NEW text in phrase_text
        if phrase_text.strip():
            self.logger.info(f"Injecting phrase: '{phrase_text}'")
            print(f"Phrase: '{phrase_text}'")

            # Inject the new text
            injection_start = time.time()
            if self.text_injector.inject_text(phrase_text + " "):
                injection_time = time.time() - injection_start
                self.logger.info(f"Text successfully injected ({injection_time*1000:.0f}ms total)")
                print(f"✓ Injected: '{phrase_text}'")
            else:
                injection_time = time.time() - injection_start
                self.logger.error(f"Text injection failed ({injection_time*1000:.0f}ms total)")
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
                # Only remove if we own the lock (our PID matches)
                with open(self.lock_file, 'r') as f:
                    lock_pid = int(f.read().strip())
                if lock_pid == os.getpid():
                    os.remove(self.lock_file)
        except FileNotFoundError:
            pass  # Already removed (e.g., by stop command)
        except Exception as e:
            self.logger.debug(f"Lock release: {e}")
    
    def transcribe(self):
        """Main transcription method using selected API"""

        # Acquire instance lock first
        if not self._acquire_lock():
            return False

        try:
            engine_name = self.engine.upper()
            print(f"Starting voice transcription with {engine_name}...")

            # Check API availability
            if not self._check_api_availability():
                self.notification.show_notification(
                    f"❌ {engine_name} API not available",
                    urgency="critical"
                )
                return False

            # Show initial notification
            self.notification.show_notification(f"🎤 Recording with {engine_name}", urgency="normal")

            # Reset stop flag and remove any existing stop file
            self.stop_flag['stop'] = False
            if os.path.exists(self.stop_file):
                os.remove(self.stop_file)

            # Show visual indicator
            self.indicator.show()

            # Start transcription with selected engine
            start_time = time.time()

            # Get language code
            language_code = self.supported_languages[self.current_language]['code']

            # Choose transcriber based on engine
            if self.engine == 'assemblyai':
                # AssemblyAI doesn't use AudioCapture - it has its own MicrophoneStream
                final_text = self.assemblyai.transcribe_streaming(
                    None,  # audio_capture not used
                    text_callback=self._handle_transcription_result,
                    stop_flag=self.stop_flag,
                    language=language_code,
                    volume_callback=self.indicator.update_level
                )
            else:  # elevenlabs
                # Initialize AudioCapture for ElevenLabs if not already done
                if self.audio_capture is None:
                    self.audio_capture = AudioCapture()

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
            # Hide visual indicator
            self.indicator.hide()
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

            # Remove lock file immediately so a new session can start
            # The old session will finish cleanup in background
            if os.path.exists(self.lock_file):
                try:
                    os.remove(self.lock_file)
                    self.logger.info("Lock released for immediate restart")
                except:
                    pass

            self.notification.show_notification("🛑 Recording stopped", urgency="normal")
        except Exception as e:
            print(f"Error creating stop file: {e}")
            self.stop_flag['stop'] = True
    
    def get_engine_status(self):
        """Get status of both transcription engines"""
        status = {
            'assemblyai': {
                'available': self.assemblyai.is_available(),
                'api_key_configured': bool(self.assemblyai.api_key),
                'default': self.engine == 'assemblyai'
            },
            'elevenlabs': {
                'available': self.elevenlabs.is_available(),
                'api_key_configured': bool(self.elevenlabs.api_key),
                'default': self.engine == 'elevenlabs'
            }
        }
        return status
    
    def print_status(self):
        """Print current system status"""
        print("Engine Status:")
        status = self.get_engine_status()

        for engine, info in status.items():
            default_marker = " (DEFAULT)" if info['default'] else ""
            available_marker = "✅" if info['available'] else "❌"
            print(f"  {engine}{default_marker}: {available_marker} (API key: {info['api_key_configured']})")

        # Check if default engine is ready
        default_engine = self.engine
        if status[default_engine]['available']:
            print(f"\nStatus: Ready (using {default_engine})")
        else:
            print(f"\nStatus: Not ready - check {default_engine} API configuration")
    
    def ping_test(self):
        """Test connectivity to both transcription services"""
        print("Testing API connectivity...\n")

        assemblyai_ok = False
        elevenlabs_ok = False

        print("AssemblyAI:")
        if self.assemblyai.is_available():
            print("  ✅ Connected")
            assemblyai_ok = True
        else:
            print("  ❌ Connection failed")

        print("\nElevenLabs:")
        if self.elevenlabs.is_available():
            print("  ✅ Connected")
            elevenlabs_ok = True
        else:
            print("  ❌ Connection failed")

        print(f"\nDefault engine: {self.engine}")

        return assemblyai_ok or elevenlabs_ok


def main():
    # Parse command line flags
    engine = 'assemblyai'  # Default engine
    use_xdotool = False    # Default: clipboard injection
    args = sys.argv[1:]

    # Check for --engine flag
    if '--engine' in args:
        engine_idx = args.index('--engine')
        if engine_idx + 1 < len(args):
            engine = args[engine_idx + 1]
            # Remove engine args from the list
            args = args[:engine_idx] + args[engine_idx + 2:]

    # Check for --xdotool flag
    if '--xdotool' in args:
        use_xdotool = True
        args.remove('--xdotool')

    if len(args) < 1:
        # Default: start transcription
        transcriber = VoiceTranscriber(engine=engine, use_xdotool=use_xdotool)
        transcriber.transcribe()
        return

    command = args[0].lower()
    transcriber = VoiceTranscriber(engine=engine, use_xdotool=use_xdotool)
    
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
        print("  ./voice_transcription.py                      # Start transcription (clipboard mode)")
        print("  ./voice_transcription.py --xdotool            # Use xdotool type instead of clipboard")
        print("  ./voice_transcription.py --engine assemblyai  # Use AssemblyAI (default)")
        print("  ./voice_transcription.py --engine elevenlabs  # Use ElevenLabs")
        print("  ./voice_transcription.py status               # Show system status")
        print("  ./voice_transcription.py ping                 # Test API connectivity")
        print("  ./voice_transcription.py stop                 # Stop active recording")
        print("  ./voice_transcription.py lang                 # Show current language")
        print("  ./voice_transcription.py lang <code>          # Set language (auto/en/cs)")


if __name__ == "__main__":
    main()
