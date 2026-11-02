"""Kernel-level virtual keyboard via /dev/uinput (stdlib only).

Used on Wayland to send the paste shortcut instead of wtype. wtype goes
through the zwp_virtual_keyboard protocol and uploads its own keymap on every
run; on Cosmic that intermittently drops the Ctrl/Shift state (the window gets
a bare 'v') and leaks wtype's US keymap into the session (a Czech layout
flips to US). A uinput device looks like a physical keyboard to the
compositor: it uses the seat's own keymap and normal modifier tracking, so
neither problem can occur.

Needs write access to /dev/uinput (systemd-logind grants the active seat user
an ACL on most desktops; otherwise add a udev rule or the 'input' group).
"""

import fcntl
import os
import struct
import time

EV_SYN, EV_KEY = 0x00, 0x01
SYN_REPORT = 0

# linux/uinput.h ioctls (x86_64/aarch64 encoding)
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

# linux/input-event-codes.h - physical key positions, layout-independent for
# these keys on both us and cz(qwerty)
KEY_ENTER = 28
KEY_LEFTCTRL = 29
KEY_LEFTSHIFT = 42
KEY_V = 47

_KEYS = (KEY_ENTER, KEY_LEFTCTRL, KEY_LEFTSHIFT, KEY_V)

# Time for libinput/the compositor to pick up a freshly created device.
# Measured: 0.1s already delivers correctly on Cosmic; keep headroom.
_SETTLE_S = 0.3
# Gap between events so clients see distinct modifier/key frames
_KEY_GAP_S = 0.01


class UInputKeyboard:
    def __init__(self):
        self._fd = os.open('/dev/uinput', os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(self._fd, UI_SET_EVBIT, EV_KEY)
            for key in _KEYS:
                fcntl.ioctl(self._fd, UI_SET_KEYBIT, key)
            # legacy struct uinput_user_dev: name[80], input_id (bustype=BUS_VIRTUAL,
            # vendor, product, version), ff_effects_max, absmax/min/fuzz/flat[64]
            os.write(self._fd, struct.pack('80sHHHHi' + 'i' * 256,
                                           b'voice-transcription-kbd', 0x06, 1, 1, 1, 0,
                                           *([0] * 256)))
            fcntl.ioctl(self._fd, UI_DEV_CREATE)
        except Exception:
            os.close(self._fd)
            raise
        self._ready_at = time.monotonic() + _SETTLE_S

    def _emit(self, code, value):
        os.write(self._fd, struct.pack('llHHi', 0, 0, EV_KEY, code, value))
        os.write(self._fd, struct.pack('llHHi', 0, 0, EV_SYN, SYN_REPORT, 0))
        time.sleep(_KEY_GAP_S)

    def _wait_ready(self):
        remaining = self._ready_at - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    def press_combo(self, *keys):
        """Press keys in order, release in reverse (e.g. ctrl, shift, v)."""
        self._wait_ready()
        for key in keys:
            self._emit(key, 1)
        for key in reversed(keys):
            self._emit(key, 0)

    def paste(self):
        self.press_combo(KEY_LEFTCTRL, KEY_LEFTSHIFT, KEY_V)

    def enter(self):
        self.press_combo(KEY_ENTER)

    def close(self):
        if self._fd is not None:
            try:
                fcntl.ioctl(self._fd, UI_DEV_DESTROY)
            finally:
                os.close(self._fd)
                self._fd = None
