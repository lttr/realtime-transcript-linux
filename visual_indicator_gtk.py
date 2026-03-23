#!/usr/bin/python3
"""Visual audio level indicator GTK subprocess.

Reads volume levels from a temp file and displays them in a floating overlay.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
import os
from collections import deque


LEVEL_FILE = "/tmp/voice_indicator_level"


class AudioIndicatorWindow(Gtk.Window):
    """Floating GTK overlay showing real-time audio levels."""

    def __init__(self, num_bars: int = 4, width: int = 48, height: int = 24):
        super().__init__(type=Gtk.WindowType.POPUP)

        self.num_bars = num_bars
        self.width = width
        self.height = height
        self.levels = [0.0] * num_bars
        self.last_volume = 0.0
        self.decay_rate = 0.92  # Slower fade out
        self.silence_start = None  # Track when silence began
        self.silence_threshold = 0.12  # Below this = silence (normalized)
        self.bars_to_hide = 0
        self.all_bars_hidden_time = None  # When all bars disappeared
        self.stop_mode = False  # Stop signal received
        self.stop_time = None  # When stop was triggered

        # Window properties
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_default_size(width, height)

        # Enable transparency
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        # Position bottom-right
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor()
        geometry = monitor.get_geometry()
        x = geometry.x + geometry.width - width - 20
        y = geometry.y + geometry.height - height - 60
        self.move(x, y)

        # Drawing area
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.connect('draw', self._on_draw)
        self.add(self.drawing_area)

        self.show_all()

        # Poll file and refresh display every 50ms (~20Hz)
        GLib.timeout_add(50, self._poll_and_refresh)

    def _poll_and_refresh(self):
        """Read level from file and refresh display with decay effect."""
        import time

        # Handle stop mode animation
        if self.stop_mode:
            if time.time() - self.stop_time > 0.3:
                Gtk.main_quit()
                return False
            self.drawing_area.queue_draw()
            return True

        new_level = None
        try:
            if os.path.exists(LEVEL_FILE):
                with open(LEVEL_FILE, 'r') as f:
                    content = f.read().strip()
                    if content == "stop":
                        self.stop_mode = True
                        self.stop_time = time.time()
                        self.drawing_area.queue_draw()
                        return True
                    volume = float(content)
                    new_level = min(1.0, max(0.0, volume / 250.0))
        except:
            pass

        # Shift bars left and add new level (or decay last bar)
        for i in range(self.num_bars - 1):
            self.levels[i] = self.levels[i + 1]

        if new_level is not None and abs(new_level - self.last_volume) > 0.01:
            # New audio level - use it
            self.levels[-1] = new_level
            self.last_volume = new_level

        # Track silence duration
        if new_level is not None and new_level > self.silence_threshold:
            # Sound detected - only reset if we haven't fully counted down
            if self.bars_to_hide < self.num_bars:
                self.silence_start = None
                self.bars_to_hide = 0
                self.all_bars_hidden_time = None
        else:
            # Silence - start or continue tracking
            if self.silence_start is None:
                self.silence_start = time.time()
            # Calculate how many bars to hide based on silence duration
            silence_seconds = time.time() - self.silence_start
            self.bars_to_hide = min(self.num_bars, int(silence_seconds))

            # Track when all bars became hidden
            if self.bars_to_hide >= self.num_bars and self.all_bars_hidden_time is None:
                self.all_bars_hidden_time = time.time()

        # Should we hide background too?
        self.hide_background = False
        if self.all_bars_hidden_time is not None:
            if time.time() - self.all_bars_hidden_time >= 1.0:
                self.hide_background = True

        self.drawing_area.queue_draw()
        return True  # Continue polling

    def _on_draw(self, widget, cr):
        """Draw the audio level bars."""
        # Hide everything if background should be hidden
        if getattr(self, 'hide_background', False):
            return False

        width = widget.get_allocated_width()
        height = widget.get_allocated_height()

        # Stop mode - solid horizontal line at bottom
        if self.stop_mode:
            # Dark background
            cr.set_source_rgba(0.12, 0.12, 0.12, 0.75)
            radius = 4
            cr.arc(radius, radius, radius, 3.14159, 1.5 * 3.14159)
            cr.arc(width - radius, radius, radius, 1.5 * 3.14159, 2 * 3.14159)
            cr.arc(width - radius, height - radius, radius, 0, 0.5 * 3.14159)
            cr.arc(radius, height - radius, radius, 0.5 * 3.14159, 3.14159)
            cr.close_path()
            cr.fill()
            # Subtle white line at bottom
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.5)
            cr.rectangle(12, height - 6, width - 24, 2)
            cr.fill()
            return False

        # Dark background with rounded corners
        cr.set_source_rgba(0.12, 0.12, 0.12, 0.75)
        radius = 4
        cr.arc(radius, radius, radius, 3.14159, 1.5 * 3.14159)
        cr.arc(width - radius, radius, radius, 1.5 * 3.14159, 2 * 3.14159)
        cr.arc(width - radius, height - radius, radius, 0, 0.5 * 3.14159)
        cr.arc(radius, height - radius, radius, 0.5 * 3.14159, 3.14159)
        cr.close_path()
        cr.fill()

        # Draw bars - white only, thin
        bar_width = 3
        bar_gap = 3
        total_bars_width = self.num_bars * bar_width + (self.num_bars - 1) * bar_gap
        padding = (width - total_bars_width) / 2
        max_bar_height = height - 8

        # How many bars to hide from left (countdown during silence)
        bars_to_hide = getattr(self, 'bars_to_hide', 0)

        for i, level in enumerate(self.levels):
            # Skip bars hidden from the left during silence countdown
            if i < bars_to_hide:
                continue

            x = padding + i * (bar_width + bar_gap)
            bar_height = max(2, level * max_bar_height)
            y = height - 4 - bar_height

            # White with opacity based on level
            opacity = 0.4 + level * 0.5
            cr.set_source_rgba(1.0, 1.0, 1.0, opacity)

            # Draw bar
            cr.rectangle(x, y, bar_width, bar_height)
            cr.fill()

        return False


def main():
    """Run GTK main loop."""
    win = AudioIndicatorWindow()
    win.connect('destroy', Gtk.main_quit)
    Gtk.main()


if __name__ == '__main__':
    main()
