#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import socket
import json
import sys
import subprocess
import time
import os

class VoiceTranscriptionTrigger:
    def __init__(self, socket_path="/tmp/voice_transcriber.sock"):
        self.socket_path = socket_path
    
    def _connect_to_daemon(self):
        """Connect to the voice transcription daemon"""
        try:
            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(self.socket_path)
            return client_socket
        except (socket.error, FileNotFoundError) as e:
            print(f"Error: Cannot connect to voice daemon. Is it running?")
            print(f"Details: {e}")
            return None
    
    def _send_request(self, client_socket, command):
        """Send request to daemon and receive response"""
        try:
            request = {'command': command}
            client_socket.send(json.dumps(request).encode('utf-8'))
            
            response_data = client_socket.recv(4096).decode('utf-8')
            return json.loads(response_data)
        except Exception as e:
            print(f"Error communicating with daemon: {e}")
            return None
    
    def _inject_text(self, text):
        """Inject text into the currently active window using xdotool"""
        try:
            if not text.strip():
                print("No text to inject")
                return False
            
            # Check if xdotool is available
            result = subprocess.run(['which', 'xdotool'], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                print("Error: xdotool not installed. Install with: sudo apt install xdotool")
                return False
            
            # Small delay to ensure focus is stable
            time.sleep(0.1)
            
            # Type the text into the active window
            subprocess.run(['xdotool', 'type', '--delay', '0', text], check=True)
            
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"Error injecting text with xdotool: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error: {e}")
            return False
    
    def _show_notification(self, message, urgency="normal"):
        """Show desktop notification if notify-send is available"""
        try:
            subprocess.run([
                'notify-send', 
                '--urgency', urgency,
                '--expire-time', '2000',
                'Voice Transcription', 
                message
            ], check=False)  # Don't fail if notify-send is not available
        except:
            pass  # Silently ignore notification errors
    
    def _handle_streaming_responses(self, client_socket):
        """Handle streaming partial transcription responses and inject text progressively"""
        final_text = ""
        
        try:
            while True:
                # Receive response
                response_data = client_socket.recv(4096).decode('utf-8')
                if not response_data:
                    break
                    
                response = json.loads(response_data)
                status = response.get('status')
                
                if status == 'partial':
                    # Handle partial transcription
                    partial_text = response.get('text', '').strip()
                    if partial_text:
                        print(f"Partial: '{partial_text}'")
                        # Inject partial text immediately
                        if self._inject_text(partial_text + " "):
                            print(f"✓ Injected: '{partial_text}'")
                        else:
                            print(f"✗ Failed to inject: '{partial_text}'")
                
                elif status == 'completed':
                    # Handle final result
                    final_text = response.get('text', '').strip()
                    print(f"Recording completed")
                    break
                    
                elif status == 'error':
                    error_msg = response.get('message', 'Unknown error')
                    print(f"Streaming error: {error_msg}")
                    self._show_notification(f"Error: {error_msg}", "critical")
                    break
                    
                else:
                    print(f"Unknown response status: {status}")
                    break
                    
        except Exception as e:
            print(f"Error handling streaming responses: {e}")
            return ""
        
        return final_text
    
    def transcribe(self):
        """Trigger voice transcription"""
        print("Connecting to voice transcription daemon...")
        
        # Connect to daemon
        client_socket = self._connect_to_daemon()
        if not client_socket:
            self._show_notification("Cannot connect to voice daemon", "critical")
            return False
        
        try:
            # Send transcription request
            print("Requesting transcription...")
            self._show_notification("🎤 Recording... Multi-sentence mode active!", "normal")
            
            response = self._send_request(client_socket, 'transcribe')
            if not response:
                self._show_notification("Failed to communicate with daemon", "critical")
                return False
            
            # Handle recording acknowledgment
            if response.get('status') == 'recording':
                print("Recording started, speak now...")
                
                # Handle streaming responses
                final_text = self._handle_streaming_responses(client_socket)
                
                if final_text:
                    print(f"Final transcription: '{final_text}'")
                    return True
                else:
                    print("No speech detected")
                    self._show_notification("No speech detected", "low")
                    return False
            
            elif response.get('status') == 'error':
                error_msg = response.get('message', 'Unknown error')
                print(f"Transcription error: {error_msg}")
                self._show_notification(f"Error: {error_msg}", "critical")
                return False
            
            else:
                print(f"Unexpected response: {response}")
                self._show_notification("Unexpected response from daemon", "critical")
                return False
                
        except Exception as e:
            print(f"Error during transcription: {e}")
            self._show_notification("Transcription failed", "critical")
            return False
        
        finally:
            client_socket.close()
    
    def ping(self):
        """Check if daemon is running"""
        client_socket = self._connect_to_daemon()
        if not client_socket:
            return False
        
        try:
            response = self._send_request(client_socket, 'ping')
            return response and response.get('status') == 'alive'
        except:
            return False
        finally:
            client_socket.close()

def main():
    trigger = VoiceTranscriptionTrigger()
    
    # Check command line arguments
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == 'ping':
            if trigger.ping():
                print("Voice daemon is running")
                sys.exit(0)
            else:
                print("Voice daemon is not running")
                sys.exit(1)
        
        elif command == 'help':
            print("Voice Transcription Trigger")
            print("Usage:")
            print("  voice_trigger.py          - Start voice transcription")
            print("  voice_trigger.py ping     - Check if daemon is running")
            print("  voice_trigger.py help     - Show this help")
            sys.exit(0)
        
        else:
            print(f"Unknown command: {command}")
            print("Use 'voice_trigger.py help' for usage information")
            sys.exit(1)
    
    # Default action: transcribe
    success = trigger.transcribe()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()