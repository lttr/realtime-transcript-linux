#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import os
import subprocess
import numpy as np
import logging
import time
import shutil

class AudioCapture:
    """Shared audio capture utilities using parecord (PulseAudio) - no PyAudio dependency"""

    def __init__(self, sample_rate=16000, chunk_size=1024, channels=1):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.channels = channels
        self.bytes_per_sample = 2  # 16-bit audio
        self.chunk_bytes = chunk_size * self.bytes_per_sample

        # VAD settings
        self.silence_threshold = 50
        self.short_pause_frames = int(sample_rate / chunk_size * 1.5)  # 1.5s phrase boundary
        self.long_pause_frames = int(sample_rate / chunk_size * 4.0)   # 4s end recording
        self.min_phrase_frames = int(sample_rate / chunk_size * 2.0)   # Min 2s for phrase

        self.logger = logging.getLogger(__name__)

        # Check for parecord availability
        self._recorder_cmd = self._find_recorder()

    def _find_recorder(self):
        """Find available audio recorder command (parecord or arecord)"""
        # Prefer parecord (PulseAudio/PipeWire) - works on modern GNOME
        if shutil.which('parecord'):
            return ['parecord', '--raw', '--rate', str(self.sample_rate),
                    '--channels', str(self.channels), '--format=s16le']
        # Fallback to arecord (ALSA)
        if shutil.which('arecord'):
            return ['arecord', '-q', '-f', 'S16_LE', '-r', str(self.sample_rate),
                    '-c', str(self.channels), '-t', 'raw']
        raise RuntimeError("No audio recorder found. Install pulseaudio-utils or alsa-utils.")

    def capture_streaming_audio(self, max_duration=45, callback=None, stop_flag=None):
        """
        Capture audio with streaming processing on natural speech pauses

        Args:
            max_duration: Maximum recording duration in seconds
            callback: Function called with audio chunks when phrase detected
            stop_flag: Shared flag to stop recording externally

        Returns:
            List of all audio frames captured
        """
        process = None
        all_frames = []

        try:
            process = subprocess.Popen(
                self._recorder_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )

            self.logger.info("🎤 Recording with natural pause detection...")

            phrase_frames = []
            silence_frames = 0
            recording_started = False
            max_frames = int(self.sample_rate / self.chunk_size * max_duration)

            for frame_count in range(max_frames):
                # Check external stop flag (in-process)
                if stop_flag and stop_flag.get('stop', False):
                    self.logger.info("Recording stopped by external signal")
                    if phrase_frames and recording_started and callback:
                        self.logger.info("Processing remaining audio from external stop")
                        audio_chunk = self._frames_to_numpy(phrase_frames)
                        callback(audio_chunk)
                        phrase_frames = []
                    break

                # Check external stop file (inter-process)
                if os.path.exists("/tmp/voice_transcription_stop.flag"):
                    self.logger.info("Recording stopped by external command")
                    if phrase_frames and recording_started and callback:
                        self.logger.info("Processing remaining audio from external stop")
                        audio_chunk = self._frames_to_numpy(phrase_frames)
                        callback(audio_chunk)
                        phrase_frames = []
                    break

                # Read chunk from subprocess stdout
                data = process.stdout.read(self.chunk_bytes)
                if not data or len(data) < self.chunk_bytes:
                    self.logger.warning("Audio stream ended unexpectedly")
                    break

                all_frames.append(data)
                phrase_frames.append(data)

                # Voice activity detection
                volume = self._calculate_volume(data)

                if volume > self.silence_threshold:
                    if not recording_started:
                        self.logger.info(f"Speech detected (volume: {volume:.1f})")
                    recording_started = True
                    silence_frames = 0
                elif recording_started:
                    silence_frames += 1

                    # Short pause = phrase boundary
                    if (silence_frames == self.short_pause_frames and
                        len(phrase_frames) >= self.min_phrase_frames):

                        phrase_duration = len(phrase_frames) / (self.sample_rate / self.chunk_size)
                        self.logger.info(f"Phrase boundary detected - sending {phrase_duration:.1f}s audio to transcriber")

                        try:
                            NotificationHelper.show_notification(
                                "🔄 Processing speech...",
                                urgency="low",
                                expire_time="1000"
                            )
                        except:
                            pass

                        if callback:
                            audio_chunk = self._frames_to_numpy(phrase_frames)
                            callback(audio_chunk)

                        phrase_frames = []

                    # Long pause = end recording
                    elif silence_frames > self.long_pause_frames:
                        self.logger.info("✅ Recording complete - long pause detected")
                        break

        except Exception as e:
            self.logger.error(f"Audio capture error: {e}")
            return []

        finally:
            if process:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()

        # Process any remaining phrase
        if phrase_frames and recording_started:
            final_min_frames = int(self.sample_rate / self.chunk_size * 1.0)
            if len(phrase_frames) >= final_min_frames and callback:
                phrase_duration = len(phrase_frames) / (self.sample_rate / self.chunk_size)
                self.logger.info(f"Final phrase detected - sending {phrase_duration:.1f}s audio to transcriber")
                audio_chunk = self._frames_to_numpy(phrase_frames)
                callback(audio_chunk)
            elif phrase_frames:
                phrase_duration = len(phrase_frames) / (self.sample_rate / self.chunk_size)
                self.logger.info(f"Final phrase too short ({phrase_duration:.1f}s < 1.0s) - skipping")

        return all_frames
    
    def capture_complete_audio(self, max_duration=20):
        """
        Capture complete audio session (for single-shot transcription)
        
        Returns:
            numpy array of audio data or None if failed
        """
        frames = []
        
        def collect_frames(audio_chunk):
            # Convert back to frames for collection
            audio_int16 = (audio_chunk * 32768.0).astype(np.int16)
            frames.extend(audio_int16.tobytes(order='C'))
        
        all_frames = self.capture_streaming_audio(
            max_duration=max_duration,
            callback=collect_frames
        )
        
        if not all_frames:
            return None
        
        return self._frames_to_numpy(all_frames)
    
    def _calculate_volume(self, audio_data):
        """Calculate RMS volume from audio data"""
        try:
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            if len(audio_array) > 0:
                rms_squared = np.mean(audio_array.astype(np.float64)**2)
                return np.sqrt(max(0, rms_squared))
            return 0
        except Exception:
            return 0
    
    def _frames_to_numpy(self, frames):
        """Convert audio frames to numpy array suitable for transcription"""
        try:
            if isinstance(frames, list):
                audio_data = b''.join(frames)
            else:
                audio_data = frames
            
            audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            return audio_np
        except Exception as e:
            self.logger.error(f"Frame conversion error: {e}")
            return np.array([], dtype=np.float32)
    
    def frames_to_wav_bytes(self, frames):
        """Convert frames to WAV format bytes for API submission"""
        import io
        import wave
        
        try:
            if isinstance(frames, list):
                audio_data = b''.join(frames)
            else:
                # Assume numpy array
                audio_data = (frames * 32768.0).astype(np.int16).tobytes()
            
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(audio_data)
            
            wav_buffer.seek(0)
            return wav_buffer.getvalue()
            
        except Exception as e:
            self.logger.error(f"WAV conversion error: {e}")
            return None


class NotificationHelper:
    """Helper for desktop notifications"""
    
    @staticmethod
    def show_notification(message, urgency="normal", expire_time=None):
        """Show desktop notification if notify-send is available"""
        import subprocess
        
        try:
            if expire_time is None:
                expire_time = "800" if urgency == "low" else "1500"
            
            subprocess.run([
                'notify-send', 
                '--app-name', 'Voice Transcription',
                '--urgency', urgency,
                '--expire-time', str(expire_time),
                '--hint', 'int:transient:1',
                '--hint', 'string:desktop-entry:voice-transcription',
                'Voice Transcription', 
                message
            ], check=False)
        except Exception:
            pass  # Silently ignore notification errors


class TextInjector:
    """Helper for injecting text into active window"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Only very short filler words - conservative list
        self.filler_words = {'uh', 'um', 'er', 'ah', 'eh', 'uhm', 'hmm', 'hm', 'mm'}
    
    def _clean_filler_words(self, text):
        """Remove short filler words from text"""
        import re
        
        # Simple approach: remove filler words with word boundaries
        pattern = r'\b(' + '|'.join(re.escape(word) for word in self.filler_words) + r')\b'
        
        # Remove filler words (case insensitive)
        result = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Clean up extra spaces and punctuation issues
        result = re.sub(r'\s+', ' ', result)  # Multiple spaces to single space
        result = re.sub(r'\s*,\s*,\s*', ', ', result)  # Double commas
        result = re.sub(r'^[,\s]+', '', result)  # Leading comma/space
        result = re.sub(r'[,\s]+$', '', result)  # Trailing comma/space
        result = re.sub(r'\s+([,.!?;:])', r'\1', result)  # Remove space before punctuation
        
        return result.strip()
    
    def inject_text(self, text):
        """Inject text into the currently active window using xdotool"""
        import subprocess
        import re

        start_time = time.time()

        try:
            if not text.strip():
                return False

            # Preserve trailing space before cleaning
            has_trailing_space = text.endswith(' ')

            # Clean filler words from text
            cleaned_text = self._clean_filler_words(text)
            if not cleaned_text.strip():
                self.logger.debug(f"Text injection skipped - only filler words: '{text}'")
                return False

            # Restore trailing space if it was present
            if has_trailing_space and not cleaned_text.endswith(' '):
                cleaned_text += ' '

            self.logger.info(f"Starting text injection: '{cleaned_text[:30]}{'...' if len(cleaned_text) > 30 else ''}'")

            # Check if xdotool is available
            result = subprocess.run(['which', 'xdotool'],
                                  capture_output=True, text=True)
            if result.returncode != 0:
                self.logger.error("xdotool not installed")
                return False

            # Small delay for focus stability
            time.sleep(0.1)

            # Check for "just enter" command
            just_enter_match = re.search(r'(.*)just\s+enter[.\s]*$', cleaned_text.strip(), re.IGNORECASE)
            if just_enter_match:
                # Type preceding text and press Enter
                preceding_text = just_enter_match.group(1).strip()
                if preceding_text:
                    subprocess.run(['xdotool', 'type', '--delay', '0', preceding_text + " (enter)"], check=True)
                else:
                    subprocess.run(['xdotool', 'type', '--delay', '0', "(enter)"], check=True)
                subprocess.run(['xdotool', 'key', 'Return'], check=True)
            else:
                # Type the cleaned text normally
                subprocess.run(['xdotool', 'type', '--delay', '0', cleaned_text], check=True)
            
            elapsed = time.time() - start_time
            self.logger.info(f"Text injection completed ({elapsed*1000:.0f}ms): '{cleaned_text[:30]}{'...' if len(cleaned_text) > 30 else ''}'")
            return True
            
        except subprocess.CalledProcessError as e:
            elapsed = time.time() - start_time
            self.logger.error(f"Text injection failed ({elapsed*1000:.0f}ms): {e}")
            return False
        except Exception as e:
            elapsed = time.time() - start_time
            self.logger.error(f"Unexpected injection error ({elapsed*1000:.0f}ms): {e}")
            return False
