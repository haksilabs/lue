"""Free dictionary lookup helpers for Lue."""

from __future__ import annotations

from dataclasses import dataclass, asdict, replace
import json
import os
import re
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
    translation: str | None
    origin: str | None
    meanings: list[Meaning]
    translation_language: str | None = None
    source_label: str = "dictionaryapi.dev"


def normalize_translation_language(value: str | None) -> str | None:
    if value is None:
        return None
    language = value.strip().lower()
    if language in {"none", "en"}:
        return None
    if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", language):
        raise ValueError("Use a language code such as de, es or tr, or 'none'.")
    return language


def _cache_key(word: str, language: str | None) -> str:
    return f"en|{language or ''}|{word}"


def _remember(result: WordLookupResult) -> None:
    _CACHE[_cache_key(result.word, result.translation_language)] = result
    while len(_CACHE) > MAX_CACHE_ENTRIES:
        del _CACHE[next(iter(_CACHE))]


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
    for entry in raw.values():
        if not isinstance(entry, dict) or not isinstance(entry.get("word"), str):
            continue
        try:
            meanings = [Meaning(**m) for m in entry.get("meanings", [])]
            result = WordLookupResult(
                word=entry["word"],
                ipa=entry.get("ipa"),
                translation=None,
                origin=entry.get("origin"),
                meanings=meanings,
            )
            if "translation_tr" in entry:
                # Keep old Turkish results without showing them in English-only mode.
                if meanings or result.ipa or result.origin:
                    _remember(result)
                if entry.get("translation_tr"):
                    _remember(replace(result, translation=entry["translation_tr"],
                                      translation_language="tr", source_label="dictionaryapi.dev + MyMemory"))
            else:
                language = normalize_translation_language(entry.get("translation_language"))
                _remember(replace(result, translation=entry.get("translation") if language else None,
                                  translation_language=language,
                                  source_label=entry.get("source_label", "dictionaryapi.dev")))
        except (TypeError, KeyError, ValueError):
            continue


def _save_disk_cache() -> None:
    try:
        os.makedirs(config.PROGRESS_FILE_DIR, exist_ok=True)
        serializable = {key: asdict(result) for key, result in _CACHE.copy().items()}
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


_load_disk_cache()


def normalize_word(raw_word: str) -> str:
    return raw_word.strip().strip("\"'‘’“”«»`()[]{}<>,.:;!?/\\|*_+=~-–—").lower()


def lookup_word(raw_word: str, translation_language: str | None = None) -> WordLookupResult:
    word = normalize_word(raw_word)
    if not word:
        raise ValueError("Empty word")

    language = normalize_translation_language(translation_language)
    cached = _CACHE.get(_cache_key(word, language))
    if cached is not None:
        return cached

    base = _CACHE.get(_cache_key(word, None))
    if base is None:
        definition = _fetch_dictionary(word)
        if definition is not None:
            base = WordLookupResult(
                word=word, ipa=definition.get("ipa"), translation=None,
                origin=definition.get("origin"), meanings=definition.get("meanings", []),
            )
            _remember(base)

    if language is None:
        if base is None:
            raise LookupError(f"No English definition found for '{word}'.")
        _save_disk_cache()
        return base

    translation = _fetch_translation(word, language)
    if base is None and translation is None:
        raise LookupError(f"No lookup result for '{word}'.")

    result = replace(
        base or WordLookupResult(word, None, None, None, []),
        translation=translation, translation_language=language,
        source_label="dictionaryapi.dev + MyMemory" if translation else "dictionaryapi.dev",
    )
    # A temporary translation failure must not prevent the next lookup from retrying.
    if translation is not None:
        _remember(result)
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


def _fetch_translation(word: str, language: str) -> str | None:
    try:
        query = urlencode({"q": word, "langpair": f"en|{language}"})
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
