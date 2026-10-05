"""Local word lookup history for Lue (no external services)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
import json
import os

from . import config

HISTORY_FILE = os.path.join(config.PROGRESS_FILE_DIR, "word_history.json")
MAX_ENTRIES = 500


@dataclass
class WordEntry:
    word: str
    book: str
    first_seen: str
    last_seen: str
    count: int

    @property
    def first_seen_date(self) -> str:
        return self.first_seen[:10]

    @property
    def last_seen_date(self) -> str:
        return self.last_seen[:10]


def _load_raw() -> list[dict]:
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_raw(entries: list[dict]) -> None:
    try:
        os.makedirs(config.PROGRESS_FILE_DIR, exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def record_word(word: str, book_title: str) -> None:
    """Record that a word was looked up, aggregating same-day repeats."""
    if not word:
        return

    now = datetime.now().isoformat(timespec="seconds")
    today = date.today().isoformat()
    entries = _load_raw()

    for entry in entries:
        if (
            entry.get("word") == word
            and entry.get("book") == book_title
            and entry.get("first_seen", "")[:10] == today
        ):
            entry["last_seen"] = now
            entry["count"] = entry.get("count", 1) + 1
            _save_raw(entries)
            return

    entries.append(
        {
            "word": word,
            "book": book_title,
            "first_seen": now,
            "last_seen": now,
            "count": 1,
        }
    )

    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]

    _save_raw(entries)


def load_entries() -> list[WordEntry]:
    return [WordEntry(**entry) for entry in _load_raw()]


def get_today_words() -> list[WordEntry]:
    today = date.today().isoformat()
    todays = [e for e in load_entries() if e.first_seen_date == today]
    todays.sort(key=lambda e: e.last_seen, reverse=True)
    return todays


def get_recent_words(limit: int = 15) -> list[WordEntry]:
    entries = load_entries()
    entries.sort(key=lambda e: e.last_seen, reverse=True)
    return entries[:limit]

