#!/usr/bin/env python3
"""Visual audio level indicator wrapper.

Uses a temp file for fast IPC with the GTK subprocess.
"""

import subprocess
import os
import tempfile


class AudioIndicator:
    """Wrapper that spawns the GTK indicator as a subprocess."""

    def __init__(self):
        self.process = None
        self.level_file = "/tmp/voice_indicator_level"
        self.last_write = 0
        self.write_interval = 0.05  # Write at most every 50ms

    def show(self):
        """Show the indicator (starts subprocess)."""
        if self.process is not None:
            return

        # Initialize level file
        try:
            with open(self.level_file, 'w') as f:
                f.write("0\n")
        except:
            pass

        script_dir = os.path.dirname(os.path.abspath(__file__))
        gtk_script = os.path.join(script_dir, 'visual_indicator_gtk.py')

        self.process = subprocess.Popen(
            ['/usr/bin/python3', gtk_script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    def update_level(self, volume: float):
        """Write volume level to shared file (rate-limited)."""
        if self.process and self.process.poll() is None:
            import time
            now = time.time()
            if now - self.last_write >= self.write_interval:
                self.last_write = now
                try:
                    # Atomic write: write to temp file then rename
                    tmp_file = self.level_file + ".tmp"
                    with open(tmp_file, 'w') as f:
                        f.write(f"{volume}\n")
                    os.replace(tmp_file, self.level_file)
                except:
                    pass

    def hide(self):
        """Hide and clean up the indicator."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=1)
            except:
                pass
            self.process = None

        # Clean up level files
        for f in [self.level_file, self.level_file + ".tmp"]:
            try:
                os.remove(f)
            except:
                pass


# Standalone test
if __name__ == '__main__':
    import time
    import math

    print("Testing visual indicator...")
    indicator = AudioIndicator()
    indicator.show()

    start = time.time()
    while time.time() - start < 5:
        t = time.time() - start
        level = 100 + 150 * abs(math.sin(t * 3)) + 50 * math.sin(t * 7)
        indicator.update_level(level)
        time.sleep(0.05)

    indicator.hide()
    time.sleep(0.2)
    print("Test complete.")
