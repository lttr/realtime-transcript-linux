#!/usr/bin/python3
"""
Visual audio level indicator - Python/GTK3 + gtk-layer-shell subprocess.
Reads volume levels from a temp file and displays them in a floating Wayland overlay.
"""

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GLib, GtkLayerShell
import math
import time

LEVEL_FILE = "/tmp/voice_indicator_level"
NUM_BARS = 4
WIDTH = 48
HEIGHT = 24
PI = math.pi
SILENCE_THRESHOLD = 0.12


class Indicator:
    def __init__(self):
        self.levels = [0.0] * NUM_BARS
        self.last_volume = 0.0
        self.silence_start = None
        self.bars_to_hide = 0
        self.all_bars_hidden_time = None
        self.hide_background = False
        self.stop_mode = False
        self.stop_time = None

    def run(self):
        win = Gtk.Window()

        # Layer shell setup for Wayland overlay
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(win, GtkLayerShell.Edge.BOTTOM, 60)
        GtkLayerShell.set_margin(win, GtkLayerShell.Edge.RIGHT, 20)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)

        win.set_decorated(False)
        win.set_accept_focus(False)
        win.set_default_size(WIDTH, HEIGHT)

        # Enable transparency
        screen = win.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            win.set_visual(visual)
        win.set_app_paintable(True)

        drawing_area = Gtk.DrawingArea()
        drawing_area.connect("draw", self.on_draw)
        win.add(drawing_area)
        win.show_all()

        GLib.timeout_add(50, self.poll, drawing_area)
        win.connect("destroy", Gtk.main_quit)
        Gtk.main()

    def on_draw(self, widget, cr):
        if self.hide_background:
            return False

        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        radius = 4

        # Stop mode - solid horizontal line at bottom
        if self.stop_mode:
            cr.set_source_rgba(0.12, 0.12, 0.12, 0.75)
            cr.arc(radius, radius, radius, PI, 1.5 * PI)
            cr.arc(w - radius, radius, radius, 1.5 * PI, 2 * PI)
            cr.arc(w - radius, h - radius, radius, 0, 0.5 * PI)
            cr.arc(radius, h - radius, radius, 0.5 * PI, PI)
            cr.close_path()
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 0.5)
            cr.rectangle(12, h - 6, w - 24, 2)
            cr.fill()
            return False

        # Dark background with rounded corners
        cr.set_source_rgba(0.12, 0.12, 0.12, 0.75)
        cr.arc(radius, radius, radius, PI, 1.5 * PI)
        cr.arc(w - radius, radius, radius, 1.5 * PI, 2 * PI)
        cr.arc(w - radius, h - radius, radius, 0, 0.5 * PI)
        cr.arc(radius, h - radius, radius, 0.5 * PI, PI)
        cr.close_path()
        cr.fill()

        # Draw bars
        bar_width = 3
        bar_gap = 3
        total_bars_width = NUM_BARS * bar_width + (NUM_BARS - 1) * bar_gap
        padding = (w - total_bars_width) / 2
        max_bar_height = h - 8

        for i in range(NUM_BARS):
            if i < self.bars_to_hide:
                continue
            x = padding + i * (bar_width + bar_gap)
            level = self.levels[i]
            bar_height = max(2, level * max_bar_height)
            y = h - 4 - bar_height
            opacity = 0.4 + level * 0.5
            cr.set_source_rgba(1, 1, 1, opacity)
            cr.rectangle(x, y, bar_width, bar_height)
            cr.fill()

        return False

    def poll(self, drawing_area):
        now = time.monotonic()

        # Handle stop animation
        if self.stop_mode:
            if now - self.stop_time > 0.3:
                Gtk.main_quit()
                return False
            drawing_area.queue_draw()
            return True

        new_level = None
        try:
            with open(LEVEL_FILE, "r") as f:
                text = f.read().strip()
            if text == "stop":
                self.stop_mode = True
                self.stop_time = now
                drawing_area.queue_draw()
                return True
            volume = float(text)
            new_level = min(1.0, max(0.0, volume / 250))
        except (FileNotFoundError, ValueError):
            pass

        # Shift bars left
        for i in range(NUM_BARS - 1):
            self.levels[i] = self.levels[i + 1]

        if new_level is not None and abs(new_level - self.last_volume) > 0.01:
            self.levels[NUM_BARS - 1] = new_level
            self.last_volume = new_level

        # Track silence
        if new_level is not None and new_level > SILENCE_THRESHOLD:
            if self.bars_to_hide < NUM_BARS:
                self.silence_start = None
                self.bars_to_hide = 0
                self.all_bars_hidden_time = None
        else:
            if self.silence_start is None:
                self.silence_start = now
            silence_secs = now - self.silence_start
            self.bars_to_hide = min(NUM_BARS, int(silence_secs))

            if self.bars_to_hide >= NUM_BARS and self.all_bars_hidden_time is None:
                self.all_bars_hidden_time = now

        self.hide_background = False
        if self.all_bars_hidden_time is not None and now - self.all_bars_hidden_time >= 1.0:
            self.hide_background = True

        drawing_area.queue_draw()
        return True


if __name__ == "__main__":
    Indicator().run()
