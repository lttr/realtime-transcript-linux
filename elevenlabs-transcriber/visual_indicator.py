#!/usr/bin/python3
"""
Visual audio level indicator - Python/GTK3 + gtk-layer-shell subprocess.
Reads volume levels from a temp file and displays them in a floating Wayland overlay.
Uses CSS-styled widgets (no cairo) for Cosmic DE compatibility.
"""

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, GLib, GtkLayerShell
import time

LEVEL_FILE = "/tmp/voice_indicator_level"
NUM_BARS = 4
WIDTH = 64
HEIGHT = 32
SILENCE_THRESHOLD = 0.12
BAR_MAX_HEIGHT = 22

CSS = b"""
window { background-color: rgba(30,30,30,0.9); border-radius: 6px; padding: 6px 8px; }
window.hidden { background-color: transparent; }
.bar { background-color: rgba(255,255,255,0.6); border-radius: 1px; min-width: 4px; transition: all 100ms ease; }
.bar.hidden { background-color: transparent; min-height: 0; }
.stop-line { background-color: rgba(255,255,255,0.5); min-height: 2px; }
"""


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

        css = Gtk.CssProvider()
        css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gtk.Window().get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def run(self):
        self.win = Gtk.Window()
        GtkLayerShell.init_for_window(self.win)
        GtkLayerShell.set_layer(self.win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self.win, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self.win, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.BOTTOM, 20)
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.RIGHT, 20)
        GtkLayerShell.set_keyboard_mode(self.win, GtkLayerShell.KeyboardMode.NONE)
        self.win.set_decorated(False)
        self.win.set_accept_focus(False)
        self.win.set_default_size(WIDTH, HEIGHT)

        # Bar container centered in window
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.box.set_valign(Gtk.Align.END)
        self.box.set_halign(Gtk.Align.CENTER)
        self.box.set_margin_bottom(4)

        self.bar_widgets = []
        for _ in range(NUM_BARS):
            # Each bar in its own fixed-height cell, aligned to bottom
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            cell.set_size_request(4, BAR_MAX_HEIGHT)
            spacer = Gtk.Box()
            spacer.set_vexpand(True)
            bar = Gtk.Box()
            bar.get_style_context().add_class("bar")
            bar.set_size_request(4, 2)
            cell.pack_start(spacer, True, True, 0)
            cell.pack_end(bar, False, False, 0)
            self.box.pack_start(cell, False, False, 0)
            self.bar_widgets.append(bar)

        # Stop line (hidden by default)
        self.stop_line = Gtk.Box()
        self.stop_line.get_style_context().add_class("stop-line")
        self.stop_line.set_no_show_all(True)
        self.stop_line.set_margin_start(10)
        self.stop_line.set_margin_end(10)
        self.stop_line.set_valign(Gtk.Align.END)
        self.stop_line.set_margin_bottom(6)

        overlay = Gtk.Overlay()
        overlay.add(self.box)
        overlay.add_overlay(self.stop_line)
        self.win.add(overlay)
        self.win.show_all()

        GLib.timeout_add(50, self.poll)
        self.win.connect("destroy", Gtk.main_quit)
        Gtk.main()

    def poll(self):
        now = time.monotonic()

        if self.stop_mode:
            if now - self.stop_time > 0.3:
                Gtk.main_quit()
                return False
            return True

        new_level = None
        try:
            with open(LEVEL_FILE, "r") as f:
                text = f.read().strip()
            if text == "stop":
                self.stop_mode = True
                self.stop_time = now
                for b in self.bar_widgets:
                    b.hide()
                self.stop_line.show()
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

        self.hide_background = (
            self.all_bars_hidden_time is not None
            and now - self.all_bars_hidden_time >= 1.0
        )

        # Update window background
        ctx = self.win.get_style_context()
        if self.hide_background:
            ctx.add_class("hidden")
        else:
            ctx.remove_class("hidden")

        # Update bar heights and visibility
        for i, bar in enumerate(self.bar_widgets):
            if i < self.bars_to_hide:
                bar.set_size_request(4, 0)
                bar.hide()
            else:
                level = self.levels[i]
                h = max(2, int(level * BAR_MAX_HEIGHT))
                bar.set_size_request(4, h)
                bar.show()

        return True


if __name__ == "__main__":
    Indicator().run()
