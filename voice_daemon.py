#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import socket
import os
import sys
import threading
import time
import logging
from pathlib import Path
import signal
import json


try:
    from faster_whisper import WhisperModel
    import pyaudio
    import numpy as np
    import io
    import wave
except ImportError as e:
    print(f"Error: Required packages not installed. Run: pip install faster-whisper pyaudio numpy")
    print(f"Missing: {e}")
    sys.exit(1)

class VoiceTranscriptionDaemon:
    def __init__(self, socket_path="/tmp/voice_transcriber.sock"):
        self.socket_path = socket_path
        self.server_socket = None
        self.whisper_model = None  # Preloaded Whisper model
        self.running = False
        self.stop_recording = False  # Flag to stop recording early
        self.recording_socket = None  # Socket for active recording session
        
        # Audio capture settings
        self.sample_rate = 16000
        self.chunk_size = 1024
        self.audio_format = pyaudio.paInt16
        self.channels = 1
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('/tmp/voice_daemon.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        self.logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.shutdown()
    
    def _init_whisper_model(self):
        """Preload the Whisper model for fast transcription"""
        try:
            self.logger.info("Loading Whisper model (this may take a few seconds)...")
            
            # Load faster-whisper model with CPU optimization
            self.whisper_model = WhisperModel(
                "tiny.en",           # Fastest, most reliable English model
                device="cpu",        # CPU usage
                compute_type="float32", # Higher precision for better accuracy (was int8)
                download_root=None   # Use default cache location
            )
            
            self.logger.info("Whisper model loaded successfully - ready for transcription!")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to load Whisper model: {e}")
            return False
    
    def _setup_socket(self):
        """Setup Unix domain socket for IPC"""
        try:
            # Remove existing socket file
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
            
            self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.server_socket.bind(self.socket_path)
            self.server_socket.listen(5)
            
            # Make socket accessible
            os.chmod(self.socket_path, 0o666)
            
            self.logger.info(f"Socket listening on {self.socket_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to setup socket: {e}")
            return False
    
    def _handle_client(self, client_socket):
        """Handle incoming transcription request"""
        try:
            # Receive request
            request_data = client_socket.recv(1024).decode('utf-8')
            if not request_data:
                return
            
            request = json.loads(request_data)
            command = request.get('command')
            
            if command == 'transcribe':
                self.logger.info("Starting streaming transcription...")
                
                # Store the recording socket
                self.recording_socket = client_socket
                
                # Send acknowledgment
                response = {'status': 'recording', 'message': 'Recording started'}
                client_socket.send(json.dumps(response).encode('utf-8'))
                
                # Start streaming transcription with progressive results
                self._transcribe_speech_streaming(client_socket)
                
                # Clear recording socket when done
                self.recording_socket = None
            
            elif command == 'stop':
                if self.recording_socket:
                    self.logger.info("Stop recording command received")
                    self.stop_recording = True
                    response = {'status': 'stopped', 'message': 'Recording stopped'}
                    client_socket.send(json.dumps(response).encode('utf-8'))
                else:
                    response = {'status': 'not_recording', 'message': 'No active recording session'}
                    client_socket.send(json.dumps(response).encode('utf-8'))
            
            elif command == 'ping':
                response = {'status': 'alive', 'message': 'Daemon is running'}
                client_socket.send(json.dumps(response).encode('utf-8'))
            
            else:
                response = {'status': 'error', 'message': f'Unknown command: {command}'}
                client_socket.send(json.dumps(response).encode('utf-8'))
                
        except Exception as e:
            self.logger.error(f"Error handling client: {e}")
            try:
                response = {'status': 'error', 'message': str(e)}
                client_socket.send(json.dumps(response).encode('utf-8'))
            except:
                pass
        finally:
            client_socket.close()
    

    def _capture_audio_with_vad(self, max_duration=20):
        """Capture audio from microphone with simple voice activity detection"""
        audio = None
        stream = None
        try:
            # Initialize PyAudio
            audio = pyaudio.PyAudio()
            
            # Use OS default microphone
            self.logger.info("Using OS default microphone")
            
            # Open microphone stream with default device
            stream = audio.open(
                format=self.audio_format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size
            )
            
            self.logger.info("🎤 Recording... speak now!")
            
            frames = []
            silence_threshold = 50  # Lowered for better detection
            silence_frames = 0
            max_silence_frames = int(self.sample_rate / self.chunk_size * 2.5)  # 2.5 seconds of silence for better responsiveness
            recording_started = False
            max_frames = int(self.sample_rate / self.chunk_size * max_duration)
            
            for frame_count in range(max_frames):
                data = stream.read(self.chunk_size)
                frames.append(data)
                
                # Simple voice activity detection
                audio_data = np.frombuffer(data, dtype=np.int16)
                if len(audio_data) > 0:
                    # Calculate RMS volume safely
                    rms_squared = np.mean(audio_data.astype(np.float64)**2)
                    volume = np.sqrt(max(0, rms_squared))  # Ensure non-negative
                else:
                    volume = 0
                
                # Show recording progress every second
                if frame_count % int(self.sample_rate / self.chunk_size) == 0:
                    elapsed_seconds = frame_count // int(self.sample_rate / self.chunk_size)
                    if recording_started:
                        self.logger.info(f"🎤 Recording... {elapsed_seconds}s (silence: {silence_frames}/{max_silence_frames})")
                    elif elapsed_seconds > 0:
                        self.logger.info(f"⏰ Waiting for speech... {elapsed_seconds}s")
                
                if volume > silence_threshold:
                    if not recording_started:
                        self.logger.info(f"🎙️ Speech started! Volume: {volume:.1f}")
                    recording_started = True
                    silence_frames = 0
                elif recording_started:
                    silence_frames += 1
                    if silence_frames > max_silence_frames:
                        elapsed_total = frame_count / (self.sample_rate / self.chunk_size)
                        self.logger.info(f"✅ Recording complete after {elapsed_total:.1f}s")
                        break
            
        except Exception as e:
            self.logger.error(f"Audio capture error: {e}")
            return None
        
        finally:
            # Always clean up audio resources
            try:
                if stream:
                    stream.stop_stream()
                    stream.close()
                if audio:
                    audio.terminate()
            except:
                pass
        
        if not frames:
            self.logger.warning("No audio frames captured")
            return None
        
        # Convert to audio data
        audio_data = b''.join(frames)
        
        # Convert to numpy array for faster-whisper
        audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        
        self.logger.info(f"Captured {len(audio_np)/self.sample_rate:.1f} seconds of audio")
        return audio_np
    
    def _transcribe_speech_streaming(self, client_socket):
        """Perform streaming speech transcription with progressive results"""
        try:
            if not self.whisper_model:
                response = {'status': 'error', 'text': '', 'message': 'Whisper model not loaded'}
                client_socket.send(json.dumps(response).encode('utf-8'))
                return
            
            # Capture audio with streaming processing
            final_text = self._capture_and_transcribe_streaming(client_socket)
            
            # Send final result
            response = {
                'status': 'completed',
                'text': final_text,
                'message': 'Transcription completed'
            }
            client_socket.send(json.dumps(response).encode('utf-8'))
            
            self.logger.info(f"Final transcription: '{final_text}'")
            
        except Exception as e:
            self.logger.error(f"Streaming transcription error: {e}")
            response = {'status': 'error', 'text': '', 'message': str(e)}
            client_socket.send(json.dumps(response).encode('utf-8'))
    
    def _capture_and_transcribe_streaming(self, client_socket, max_duration=45):
        """Capture audio and transcribe on natural speech pauses for progressive results"""
        audio = None
        stream = None
        full_text = ""
        self.stop_recording = False
        
        try:
            # Initialize PyAudio
            audio = pyaudio.PyAudio()
            
            # Use OS default microphone
            self.logger.info("Using OS default microphone for streaming")
            
            # Open microphone stream
            stream = audio.open(
                format=self.audio_format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size
            )
            
            self.logger.info("🎤 Natural pause recording... speak now!")
            
            frames = []
            phrase_frames = []  # Accumulate frames for current phrase
            silence_threshold = 50
            silence_frames = 0
            
            # Dual pause detection - more relaxed for natural speech
            short_pause_frames = int(self.sample_rate / self.chunk_size * 1.5)  # 1.5s = phrase boundary
            long_pause_frames = int(self.sample_rate / self.chunk_size * 4.0)   # 4s = end recording
            
            recording_started = False
            max_frames = int(self.sample_rate / self.chunk_size * max_duration)
            min_phrase_frames = int(self.sample_rate / self.chunk_size * 2.0)  # Min 2s for phrase
            
            for frame_count in range(max_frames):
                # Check for manual stop signal
                if self.stop_recording:
                    self.logger.info("🛑 Recording stopped by user command")
                    break
                
                data = stream.read(self.chunk_size)
                frames.append(data)
                phrase_frames.append(data)
                
                # Voice activity detection
                audio_data = np.frombuffer(data, dtype=np.int16)
                if len(audio_data) > 0:
                    rms_squared = np.mean(audio_data.astype(np.float64)**2)
                    volume = np.sqrt(max(0, rms_squared))
                else:
                    volume = 0
                
                if volume > silence_threshold:
                    if not recording_started:
                        self.logger.info(f"🎙️ Speech started!")
                    recording_started = True
                    silence_frames = 0
                elif recording_started:
                    silence_frames += 1
                    
                    # Short pause = end of phrase, transcribe and continue
                    if silence_frames == short_pause_frames and len(phrase_frames) >= min_phrase_frames:
                        # Check if recording was stopped during silence
                        if self.stop_recording:
                            self.logger.info("🛑 Recording stopped during phrase processing")
                            break
                            
                        phrase_text = self._transcribe_audio_chunk(phrase_frames)
                        if phrase_text.strip():
                            full_text += phrase_text + " "
                            # Send partial result
                            response = {
                                'status': 'partial',
                                'text': phrase_text.strip(),
                                'full_text': full_text.strip(),
                                'message': 'Natural phrase completed'
                            }
                            client_socket.send(json.dumps(response).encode('utf-8'))
                            self.logger.info(f"Phrase: '{phrase_text.strip()}'")
                        
                        # Reset for next phrase
                        phrase_frames = []
                    
                    # Long pause = end recording
                    elif silence_frames > long_pause_frames:
                        self.logger.info(f"✅ Recording complete after long pause")
                        break
        
        except Exception as e:
            self.logger.error(f"Streaming audio capture error: {e}")
            return ""
        
        finally:
            if stream:
                stream.stop_stream()
                stream.close()
            if audio:
                audio.terminate()
        
        # Process any remaining phrase audio only if recording wasn't manually stopped
        if phrase_frames and recording_started and len(phrase_frames) >= min_phrase_frames and not self.stop_recording:
            remaining_text = self._transcribe_audio_chunk(phrase_frames)
            if remaining_text.strip():
                full_text += remaining_text + " "
                # Send final partial result
                response = {
                    'status': 'partial',
                    'text': remaining_text.strip(),
                    'full_text': full_text.strip(),
                    'message': 'Final phrase completed'
                }
                client_socket.send(json.dumps(response).encode('utf-8'))
                self.logger.info(f"Final phrase: '{remaining_text.strip()}'")
        
        # Reset stop flag to prevent interference with next recording
        self.stop_recording = False
        
        return full_text.strip()
    
    def _transcribe_audio_chunk(self, frames):
        """Transcribe a chunk of audio frames"""
        try:
            if not frames:
                return ""
            
            # Convert frames to audio data
            audio_data = b''.join(frames)
            audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            
            if len(audio_np) < self.sample_rate * 0.5:  # Less than 0.5 seconds
                return ""
            
            self.logger.info(f"Transcribing {len(audio_np)/self.sample_rate:.1f}s audio chunk")
            
            # Transcribe chunk with anti-repetition parameters
            segments, info = self.whisper_model.transcribe(
                audio_np,
                language="en",
                beam_size=1,        # Reduced beam size to prevent repetition loops
                temperature=0.3,    # Add randomness to break repetition patterns
                condition_on_previous_text=False  # Disable to prevent repetition loops
            )
            
            text = " ".join([segment.text for segment in segments]).strip()
            self.logger.info(f"Transcription result: '{text[:50]}{'...' if len(text) > 50 else ''}'")
            return text
            
        except Exception as e:
            self.logger.error(f"Chunk transcription error: {e}")
            return ""
    
    def _transcribe_speech(self):
        """Perform speech transcription using preloaded model"""
        try:
            if not self.whisper_model:
                return "Error: Whisper model not loaded"
            
            # Capture audio from microphone (brief access)
            audio_data = self._capture_audio_with_vad()
            
            if audio_data is None or len(audio_data) < self.sample_rate * 0.5:  # Less than 0.5 seconds
                self.logger.info("No sufficient audio captured")
                return ""
            
            # Transcribe using preloaded model
            self.logger.info("Transcribing audio with preloaded model...")
            segments, info = self.whisper_model.transcribe(
                audio_data,
                language="en",
                beam_size=5,        # Maximum search breadth
                best_of=5,          # Try 5 attempts for best result
                temperature=0.0,    # Deterministic output
                condition_on_previous_text=False,  # Disable to prevent repetition loops
                initial_prompt="High quality transcription with proper punctuation and grammar."
            )
            
            # Combine all segments into one text
            text = " ".join([segment.text for segment in segments]).strip()
            
            self.logger.info(f"Transcription result: '{text}'")
            return text
            
        except Exception as e:
            self.logger.error(f"Transcription error: {e}")
            return f"Error: {str(e)}"
    
    def start(self):
        """Start the daemon"""
        self.logger.info("Starting Voice Transcription Daemon...")
        
        # Load Whisper model (one-time startup cost)
        if not self._init_whisper_model():
            self.logger.error("Failed to load Whisper model, exiting")
            return False
        
        # Setup socket
        if not self._setup_socket():
            self.logger.error("Failed to setup socket, exiting")
            return False
        
        self.running = True
        self.logger.info("Daemon started successfully, waiting for requests...")
        
        try:
            while self.running:
                try:
                    client_socket, address = self.server_socket.accept()
                    self.logger.info("Client connected")
                    
                    # Handle client in separate thread for responsiveness
                    client_thread = threading.Thread(
                        target=self._handle_client, 
                        args=(client_socket,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                except socket.error as e:
                    if self.running:
                        self.logger.error(f"Socket error: {e}")
                    break
                    
        except KeyboardInterrupt:
            self.logger.info("Received keyboard interrupt")
        
        self.shutdown()
        return True
    
    def shutdown(self):
        """Shutdown the daemon gracefully"""
        if not self.running:
            return
            
        self.logger.info("Shutting down daemon...")
        self.running = False
        
        if self.server_socket:
            self.server_socket.close()
        
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        
        # No persistent recorder to clean up anymore
        
        self.logger.info("Daemon shutdown complete")

def main():
    daemon = VoiceTranscriptionDaemon()
    try:
        daemon.start()
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()