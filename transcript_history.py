"""Durable transcript history: one JSONL line per dictation session.

Lives outside /tmp so it survives reboots (the log in /tmp does not).
Stdlib only. A write failure is logged and swallowed: losing a history line
must never break a dictation session.
"""

import json
import logging
import os
from datetime import datetime

HISTORY_FILE = os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
    "voice-transcription",
    "history.jsonl",
)

logger = logging.getLogger(__name__)


def append_session(started_at, duration_s, engine, language_mode, phrases, outcome):
    """Append one session record.

    phrases: list of {"text": str, "injected": bool}, in dictation order.
    outcome: "completed" | "interrupted" | "error".
    """
    if not phrases:
        return
    record = {
        "ts": datetime.fromtimestamp(started_at).astimezone().isoformat(timespec="seconds"),
        "duration_s": round(duration_s, 1),
        "engine": engine,
        "language_mode": language_mode,
        "outcome": outcome,
        "text": " ".join(p["text"] for p in phrases),
        "phrases": phrases,
    }
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.error(f"Could not write transcript history: {e}")


def read_sessions(limit=None):
    """Return session records, oldest first (the last `limit` if given)."""
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []
    if limit:
        lines = lines[-limit:]
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # tolerate a torn final line
    return records
