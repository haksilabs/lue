"""Free dictionary lookup helpers for Lue."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import os
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from . import config

USER_AGENT = "Lue Dictionary/0.1"
_TIMEOUT = 10
_CACHE: dict[str, "WordLookupResult"] = {}

CACHE_FILE = os.path.join(config.PROGRESS_FILE_DIR, "dictionary_cache.json")
MAX_CACHE_ENTRIES = 2000


@dataclass
class Meaning:
    part_of_speech: str
    definition: str
    example: str | None = None


@dataclass
class WordLookupResult:
    word: str
    ipa: str | None
    translation_tr: str | None
    origin: str | None
    meanings: list[Meaning]
    source_label: str = "dictionaryapi.dev + MyMemory"


def _load_disk_cache() -> None:
    """Load previously looked-up words from disk so repeat lookups are instant."""
    if not os.path.exists(CACHE_FILE):
        return
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(raw, dict):
        return
    for word, entry in raw.items():
        try:
            meanings = [Meaning(**m) for m in entry.get("meanings", [])]
            _CACHE[word] = WordLookupResult(
                word=entry["word"],
                ipa=entry.get("ipa"),
                translation_tr=entry.get("translation_tr"),
                origin=entry.get("origin"),
                meanings=meanings,
                source_label=entry.get("source_label", "dictionaryapi.dev + MyMemory"),
            )
        except (TypeError, KeyError):
            continue


def _save_disk_cache() -> None:
    try:
        os.makedirs(config.PROGRESS_FILE_DIR, exist_ok=True)
        serializable = {
            word: {
                "word": result.word,
                "ipa": result.ipa,
                "translation_tr": result.translation_tr,
                "origin": result.origin,
                "meanings": [asdict(m) for m in result.meanings],
                "source_label": result.source_label,
            }
            for word, result in _CACHE.items()
        }
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


_load_disk_cache()


def normalize_word(raw_word: str) -> str:
    return raw_word.strip().strip("\"'‘’“”«»`()[]{}<>,.:;!?/\\|*_+=~-–—").lower()


def lookup_word(raw_word: str) -> WordLookupResult:
    word = normalize_word(raw_word)
    if not word:
        raise ValueError("Empty word")

    cached = _CACHE.get(word)
    if cached is not None:
        return cached

    translation = _fetch_tr_translation(word)
    dictionary = _fetch_dictionary(word)

    if dictionary is None and translation is None:
        raise LookupError(f"No lookup result for '{word}'")

    result = WordLookupResult(
        word=word,
        ipa=dictionary.get("ipa") if dictionary else None,
        translation_tr=translation,
        origin=dictionary.get("origin") if dictionary else None,
        meanings=dictionary.get("meanings", []) if dictionary else [],
    )
    _CACHE[word] = result
    if len(_CACHE) > MAX_CACHE_ENTRIES:
        oldest_key = next(iter(_CACHE))
        del _CACHE[oldest_key]
    _save_disk_cache()
    return result


def _fetch_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_dictionary(word: str) -> dict[str, Any] | None:
    try:
        payload = _fetch_json(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(word)}"
        )
    except Exception:
        return None

    if not isinstance(payload, list) or not payload:
        return None

    entry = payload[0]
    ipa = entry.get("phonetic")
    if not ipa:
        for phonetic in entry.get("phonetics", []):
            text = phonetic.get("text")
            if text:
                ipa = text
                break

    meanings: list[Meaning] = []
    for meaning in entry.get("meanings", [])[:4]:
        part_of_speech = meaning.get("partOfSpeech", "")
        for definition in meaning.get("definitions", [])[:2]:
            meanings.append(
                Meaning(
                    part_of_speech=part_of_speech,
                    definition=definition.get("definition", ""),
                    example=definition.get("example"),
                )
            )

    return {
        "ipa": ipa,
        "origin": entry.get("origin"),
        "meanings": meanings,
    }


def _fetch_tr_translation(word: str) -> str | None:
    try:
        query = urlencode({"q": word, "langpair": "en|tr"})
        payload = _fetch_json(f"https://api.mymemory.translated.net/get?{query}")
    except Exception:
        return None

    if not isinstance(payload, dict) or str(payload.get("responseStatus", 200)) != "200":
        return None

    translated = (
        payload.get("responseData", {}).get("translatedText", "").strip()
        if isinstance(payload, dict)
        else ""
    )
    if not translated:
        return None
    if normalize_word(translated) == normalize_word(word):
        return None
    return translated
