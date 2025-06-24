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
                "tiny.en",           # Fastest English model
                device="cpu",        # CPU usage
                compute_type="int8", # Optimized for CPU
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
                self.logger.info("Starting transcription...")
                
                # Send acknowledgment
                response = {'status': 'recording', 'message': 'Recording started'}
                client_socket.send(json.dumps(response).encode('utf-8'))
                
                # Start recording and transcription
                transcribed_text = self._transcribe_speech()
                
                # Send result
                response = {
                    'status': 'completed',
                    'text': transcribed_text,
                    'message': 'Transcription completed'
                }
                client_socket.send(json.dumps(response).encode('utf-8'))
                
                self.logger.info(f"Transcription completed: '{transcribed_text}'")
            
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
    

    def _capture_audio_with_vad(self, max_duration=10):
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
            max_silence_frames = int(self.sample_rate / self.chunk_size * 1.5)  # 1.5 seconds of silence
            recording_started = False
            max_frames = int(self.sample_rate / self.chunk_size * max_duration)
            
            for _ in range(max_frames):
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
                
                # Log volume for debugging
                if _ % 16 == 0:  # Log every 16th frame to avoid spam
                    self.logger.info(f"Audio volume: {volume:.1f} (threshold: {silence_threshold})")
                
                if volume > silence_threshold:
                    recording_started = True
                    silence_frames = 0
                    self.logger.info(f"Speech detected! Volume: {volume:.1f}")
                elif recording_started:
                    silence_frames += 1
                    if silence_frames > max_silence_frames:
                        self.logger.info("Silence detected, stopping recording")
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
                beam_size=1,  # Faster transcription
                best_of=1     # Single pass for speed
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