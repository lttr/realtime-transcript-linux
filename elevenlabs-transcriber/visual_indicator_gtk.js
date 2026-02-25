#!/usr/bin/gjs
/**
 * Visual audio level indicator - GJS/GTK3 subprocess.
 * Reads volume levels from a temp file and displays them in a floating overlay.
 * Port of visual_indicator_gtk.py for zero-Python Deno setup.
 */

const { Gtk, Gdk, GLib } = imports.gi;

const LEVEL_FILE = "/tmp/voice_indicator_level";
const NUM_BARS = 4;
const WIDTH = 48;
const HEIGHT = 24;
const PI = 3.14159;

Gtk.init(null);

const win = new Gtk.Window({ type: Gtk.WindowType.POPUP });
win.set_decorated(false);
win.set_keep_above(true);
win.set_skip_taskbar_hint(true);
win.set_skip_pager_hint(true);
win.set_accept_focus(false);
win.set_default_size(WIDTH, HEIGHT);

// Enable transparency
const screen = win.get_screen();
const visual = screen.get_rgba_visual();
if (visual) win.set_visual(visual);
win.set_app_paintable(true);

// Position bottom-right
const display = Gdk.Display.get_default();
const monitor = display.get_primary_monitor();
const geometry = monitor.get_geometry();
win.move(
  geometry.x + geometry.width - WIDTH - 20,
  geometry.y + geometry.height - HEIGHT - 60,
);

// State
let levels = [0, 0, 0, 0];
let lastVolume = 0;
let silenceStart = null;
let barsToHide = 0;
let allBarsHiddenTime = null;
let hideBackground = false;
let stopMode = false;
let stopTime = null;
const SILENCE_THRESHOLD = 0.12;

// Drawing area
const drawingArea = new Gtk.DrawingArea();
drawingArea.connect("draw", (_widget, cr) => {
  if (hideBackground) return false;

  const w = _widget.get_allocated_width();
  const h = _widget.get_allocated_height();
  const radius = 4;

  // Stop mode - solid horizontal line at bottom
  if (stopMode) {
    cr.setSourceRGBA(0.12, 0.12, 0.12, 0.75);
    cr.arc(radius, radius, radius, PI, 1.5 * PI);
    cr.arc(w - radius, radius, radius, 1.5 * PI, 2 * PI);
    cr.arc(w - radius, h - radius, radius, 0, 0.5 * PI);
    cr.arc(radius, h - radius, radius, 0.5 * PI, PI);
    cr.closePath();
    cr.fill();
    cr.setSourceRGBA(1, 1, 1, 0.5);
    cr.rectangle(12, h - 6, w - 24, 2);
    cr.fill();
    return false;
  }

  // Dark background with rounded corners
  cr.setSourceRGBA(0.12, 0.12, 0.12, 0.75);
  cr.arc(radius, radius, radius, PI, 1.5 * PI);
  cr.arc(w - radius, radius, radius, 1.5 * PI, 2 * PI);
  cr.arc(w - radius, h - radius, radius, 0, 0.5 * PI);
  cr.arc(radius, h - radius, radius, 0.5 * PI, PI);
  cr.closePath();
  cr.fill();

  // Draw bars
  const barWidth = 3;
  const barGap = 3;
  const totalBarsWidth = NUM_BARS * barWidth + (NUM_BARS - 1) * barGap;
  const padding = (w - totalBarsWidth) / 2;
  const maxBarHeight = h - 8;

  for (let i = 0; i < NUM_BARS; i++) {
    if (i < barsToHide) continue;
    const x = padding + i * (barWidth + barGap);
    const level = levels[i];
    const barHeight = Math.max(2, level * maxBarHeight);
    const y = h - 4 - barHeight;
    const opacity = 0.4 + level * 0.5;
    cr.setSourceRGBA(1, 1, 1, opacity);
    cr.rectangle(x, y, barWidth, barHeight);
    cr.fill();
  }

  return false;
});
win.add(drawingArea);
win.show_all();

// Poll file every 50ms
GLib.timeout_add(GLib.PRIORITY_DEFAULT, 50, () => {
  const now = GLib.get_monotonic_time() / 1e6; // seconds

  // Handle stop animation
  if (stopMode) {
    if (now - stopTime > 0.3) {
      Gtk.main_quit();
      return GLib.SOURCE_REMOVE;
    }
    drawingArea.queue_draw();
    return GLib.SOURCE_CONTINUE;
  }

  let newLevel = null;
  try {
    if (GLib.file_test(LEVEL_FILE, GLib.FileTest.EXISTS)) {
      const [ok, contents] = GLib.file_get_contents(LEVEL_FILE);
      if (ok) {
        const text =
          contents instanceof Uint8Array
            ? new TextDecoder().decode(contents)
            : String(contents);
        const trimmed = text.trim();
        if (trimmed === "stop") {
          stopMode = true;
          stopTime = now;
          drawingArea.queue_draw();
          return GLib.SOURCE_CONTINUE;
        }
        const volume = parseFloat(trimmed);
        if (!isNaN(volume)) {
          newLevel = Math.min(1, Math.max(0, volume / 250));
        }
      }
    }
  } catch (_e) {
    /* ignore */
  }

  // Shift bars left
  for (let i = 0; i < NUM_BARS - 1; i++) {
    levels[i] = levels[i + 1];
  }

  if (newLevel !== null && Math.abs(newLevel - lastVolume) > 0.01) {
    levels[NUM_BARS - 1] = newLevel;
    lastVolume = newLevel;
  }

  // Track silence
  if (newLevel !== null && newLevel > SILENCE_THRESHOLD) {
    if (barsToHide < NUM_BARS) {
      silenceStart = null;
      barsToHide = 0;
      allBarsHiddenTime = null;
    }
  } else {
    if (silenceStart === null) silenceStart = now;
    const silenceSecs = now - silenceStart;
    barsToHide = Math.min(NUM_BARS, Math.floor(silenceSecs));

    if (barsToHide >= NUM_BARS && allBarsHiddenTime === null) {
      allBarsHiddenTime = now;
    }
  }

  hideBackground = false;
  if (allBarsHiddenTime !== null && now - allBarsHiddenTime >= 1.0) {
    hideBackground = true;
  }

  drawingArea.queue_draw();
  return GLib.SOURCE_CONTINUE;
});

win.connect("destroy", Gtk.main_quit);
Gtk.main();
