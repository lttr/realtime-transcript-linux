"""Shared audio level scaling for the transcribers and the visual indicators.

Deliberately dependency-free (stdlib only): the transcribers import it under the
project venv, while the GTK indicator subprocesses import it under system
python3. Keeping the constants here is what makes the documented agreement
between "session silence" and "overlay fade-out" true by construction instead of
by two hand-matched magic numbers.

Levels are int16 RMS. Measured on this setup (pw-record, 16kHz mono):
silent room 16-40 (stray keyboard/mouse transients up to ~270), conversational
speech ~1000-4000, emphatic ~6000-14000.

Note the two floors are separate concerns and must NOT be collapsed into one:

  SILENCE_RMS (30)        - is anyone talking at all? Drives the overlay fade and
                            the transcriber's silence timeout. Sits just above the
                            room noise floor.
  DISPLAY_FLOOR_RMS (300) - what counts as the bottom of the bar display. Much
                            higher, because mapping the bars all the way down to
                            30 would squeeze all real speech into the top third of
                            the range and leave the bars visibly flat.

The previous linear `volume / 250` mapping conflated them and saturated at 1.0 on
every chunk of real speech, which is why the bars froze at full height.
"""

import math

# Above this RMS the mic counts as active: the overlay fade resets and the
# transcriber's silence timeout restarts. Just above the measured room floor.
SILENCE_RMS = 30.0

# Bottom of the bar display: at or below this the bars sit at minimum height.
DISPLAY_FLOOR_RMS = 300.0

# RMS that fills the bars completely. Above this the display just clips.
LOUD_RMS = 12000.0

_CEILING_DB = 20.0 * math.log10(LOUD_RMS / DISPLAY_FLOOR_RMS)


def rms_to_level(volume: float) -> float:
    """Map an int16 RMS volume to a 0.0-1.0 bar level.

    Logarithmic (dB above DISPLAY_FLOOR_RMS) rather than linear, so that normal
    speech uses the whole range instead of pinning at the top: loudness is
    perceived logarithmically and speech RMS spans more than an order of
    magnitude.
    """
    if volume <= DISPLAY_FLOOR_RMS:
        return 0.0
    db = 20.0 * math.log10(volume / DISPLAY_FLOOR_RMS)
    return min(1.0, db / _CEILING_DB)


def is_active(volume: float) -> bool:
    """True when the mic is picking up speech rather than room noise.

    Intentionally independent of rms_to_level(): a quiet utterance can be real
    speech (resetting the fade and the silence timeout) while still drawing as a
    near-zero bar.
    """
    return volume > SILENCE_RMS
