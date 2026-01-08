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
        new_level = None
        try:
            if os.path.exists(LEVEL_FILE):
                with open(LEVEL_FILE, 'r') as f:
                    volume = float(f.read().strip())
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
        else:
            # No new input - decay the last bar slowly
            self.levels[-1] = self.levels[-1] * self.decay_rate

        self.drawing_area.queue_draw()
        return True  # Continue polling

    def _on_draw(self, widget, cr):
        """Draw the audio level bars."""
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()

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

        for i, level in enumerate(self.levels):
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
