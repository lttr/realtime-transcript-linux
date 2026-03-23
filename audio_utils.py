#!/home/lukas/code/realtime-transcript-linux/venv/bin/python

import os
import logging
import time
import shutil


def is_wayland() -> bool:
    """Detect if running under a Wayland session."""
    return bool(os.environ.get('WAYLAND_DISPLAY') or
                os.environ.get('XDG_SESSION_TYPE') == 'wayland')


def find_recorder(sample_rate=16000, channels=1):
    """Find available audio recorder command. Priority: pw-record > parecord > arecord."""
    if shutil.which('pw-record'):
        return ['pw-record', '--raw', f'--format=s16', f'--rate={sample_rate}',
                f'--channels={channels}', '-']
    if shutil.which('parecord'):
        return ['parecord', '--raw', '--rate', str(sample_rate),
                '--channels', str(channels), '--format=s16le', '--latency-msec=50']
    if shutil.which('arecord'):
        return ['arecord', '-q', '-f', 'S16_LE', '-r', str(sample_rate),
                '-c', str(channels), '-t', 'raw']
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

            # Pick icon based on urgency for proper error/warning look
            icon_map = {
                "critical": "dialog-error",
                "normal": "audio-input-microphone",
                "low": "audio-input-microphone",
            }
            icon = icon_map.get(urgency, "audio-input-microphone")

            subprocess.run([
                'notify-send',
                '--app-name', 'Voice Transcription',
                '--icon', icon,
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

    def __init__(self, use_xdotool=False):
        self.logger = logging.getLogger(__name__)
        self.use_xdotool = use_xdotool  # False = clipboard (default), True = xdotool type
        self._wayland = is_wayland()

        # Verify required tools at startup
        if self._wayland:
            missing = []
            if not shutil.which('wl-copy'):
                missing.append('wl-copy (wl-clipboard)')
            if not shutil.which('wtype'):
                missing.append('wtype')
            if missing:
                self.logger.warning(f"Wayland tools missing: {', '.join(missing)}")
        else:
            missing = []
            if not shutil.which('xdotool'):
                missing.append('xdotool')
            if not shutil.which('xsel'):
                missing.append('xsel')
            if missing:
                self.logger.warning(f"X11 tools missing: {', '.join(missing)}")

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

    def _do_inject(self, text):
        """Perform the actual text injection using clipboard + paste"""
        import subprocess

        if self._wayland:
            # Wayland: wl-copy + wtype Ctrl+Shift+V
            proc = subprocess.Popen(['wl-copy'], stdin=subprocess.PIPE, text=True)
            proc.communicate(input=text)
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(proc.returncode, 'wl-copy')

            time.sleep(0.05)

            # Always Ctrl+Shift+V on Wayland (works in both terminals and apps)
            subprocess.run(['wtype', '-M', 'ctrl', '-M', 'shift', '-k', 'v',
                           '-m', 'shift', '-m', 'ctrl'], check=True)
        elif self.use_xdotool:
            # X11: Direct keystroke simulation
            subprocess.run(['xdotool', 'type', '--delay', '0', text], check=True)
        else:
            # X11: Clipboard-based injection via xsel + xdotool paste
            if not shutil.which('xsel'):
                self.logger.error("xsel not installed (required for clipboard mode)")
                raise subprocess.CalledProcessError(1, 'xsel')

            # Copy text to clipboard
            proc = subprocess.Popen(['xsel', '--clipboard', '--input'],
                                   stdin=subprocess.PIPE, text=True)
            proc.communicate(input=text)
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(proc.returncode, 'xsel')

            # Small delay to ensure clipboard is ready
            time.sleep(0.05)

            # Detect if active window is a terminal (needs Ctrl+Shift+V)
            paste_key = 'ctrl+v'
            try:
                window_id = subprocess.run(['xdotool', 'getactivewindow'],
                                          capture_output=True, text=True, check=True).stdout.strip()
                wm_class = subprocess.run(['xprop', '-id', window_id, 'WM_CLASS'],
                                         capture_output=True, text=True, check=True).stdout.lower()
                # Common terminal emulators
                terminals = ['gnome-terminal', 'kitty', 'alacritty', 'konsole', 'xterm',
                            'tilix', 'terminator', 'urxvt', 'st', 'foot', 'wezterm']
                if any(term in wm_class for term in terminals):
                    paste_key = 'ctrl+shift+v'
            except subprocess.CalledProcessError:
                pass  # Fall back to ctrl+v if detection fails

            # Paste using detected shortcut
            subprocess.run(['xdotool', 'key', paste_key], check=True)

    def inject_text(self, text):
        """Inject text into the currently active window"""
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

            if self._wayland:
                # Wayland tool check
                if not shutil.which('wl-copy') or not shutil.which('wtype'):
                    self.logger.error("wl-copy/wtype not installed (required for Wayland)")
                    return False
                if self.use_xdotool:
                    self.logger.warning("--xdotool not supported on Wayland, using clipboard")
                method = "wayland-clipboard"
            else:
                # X11 tool check
                if not shutil.which('xdotool'):
                    self.logger.error("xdotool not installed")
                    return False
                method = "xdotool" if self.use_xdotool else "clipboard"

            self.logger.info(f"Starting text injection ({method}): '{cleaned_text[:30]}{'...' if len(cleaned_text) > 30 else ''}'")

            # Small delay for focus stability
            time.sleep(0.1)

            # Check for "just enter" command
            just_enter_match = re.search(r'(.*)just\s+enter[.\s]*$', cleaned_text.strip(), re.IGNORECASE)
            if just_enter_match:
                preceding_text = just_enter_match.group(1).strip()
                text_to_inject = (preceding_text + " (enter)") if preceding_text else "(enter)"
                self._do_inject(text_to_inject)
                if self._wayland:
                    subprocess.run(['wtype', '-k', 'Return'], check=True)
                else:
                    subprocess.run(['xdotool', 'key', 'Return'], check=True)
            else:
                self._do_inject(cleaned_text)

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
