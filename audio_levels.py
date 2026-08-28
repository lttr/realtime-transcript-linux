"""Shared audio level scaling for the transcribers and the visual indicators.

Deliberately dependency-free (stdlib only): the transcribers import it under the
project venv, while the GTK indicator subprocesses import it under system
python3. Keeping the constants here is what makes the documented agreement
between "session silence" and "overlay fade-out" true by construction instead of
by two hand-matched magic numbers.

Levels are int16 RMS. Measured on this setup (pw-record, 16kHz mono): silent room
24-48 with keyboard/mouse transients to ~270; speech p50 413 soft-spoken and 2141
at normal volume, emphatic peaks 6000-14000. Note that speech level swings ~5x
with volume and distance while the noise floor stays put - so the display range
cannot be tuned from a single sample. See `SILENCE_RMS` and LOUD_RMS below.

Note the two floors are separate concerns and must NOT be collapsed into one:

  SILENCE_RMS (120)       - is anyone talking at all? Drives the overlay fade and
                            the transcriber's silence timeout. Must clear the room
                            noise floor INCLUDING keyboard transients: at 30 it sat
                            below this room's floor and the mic read as active 76%
                            of the time in silence, so the silence timeout never
                            fired.
  DISPLAY_FLOOR_RMS (300) - what counts as the bottom of the bar display. Higher
                            than the silence floor, because mapping the bars all
                            the way down to 120 would squeeze real speech into the
                            top of the range and leave the bars visibly flat.

The previous linear `volume / 250` mapping conflated them and saturated at 1.0 on
every chunk of real speech, which is why the bars froze at full height.
"""

import math

# Above this RMS the mic counts as active: the overlay fade resets and the
# transcriber's silence timeout restarts.
#
# 120 rather than the original 30: calibration measured this room's floor at
# median 34, p90 48, peaking at 106 on keyboard transients, so 30 sat BELOW the
# noise floor - the mic read as "active" 76% of the time even in silence, so the
# 5s silence timeout could never fire and sessions ran to the 300s cap. 120
# clears every measured silent sample while staying far below the quietest
# measured speech (median 413 in a soft-spoken run, 2141 in a normal one).
SILENCE_RMS = 120.0

# Bottom of the bar display: at or below this the bars sit at minimum height.
DISPLAY_FLOOR_RMS = 300.0

# RMS that fills the bars completely. Above this the display just clips.
#
# Speech level varies ~5x with how close and how loudly you speak (measured
# median 413 soft vs 2141 normal, against a near-constant noise floor), so these
# two cannot be tuned from a single sample without either flattening the bars on
# loud speech or clipping them on soft. They are set from normal dictation, which
# is what the overlay is actually watched during; run a real session and check
# the "session levels" line the transcriber logs before changing them.
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
