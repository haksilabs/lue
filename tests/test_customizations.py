"""Regression checks for the additions in this fork. No network calls."""

import asyncio
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlparse

# Imports must not read or write the reader's real cache or word history.
_sandbox = tempfile.TemporaryDirectory(prefix="lue-tests-")
with patch.dict(os.environ, {
    "XDG_DATA_HOME": _sandbox.name,
    "XDG_CACHE_HOME": _sandbox.name,
}):
    from lue import audio, config, dictionary, word_history
    from lue.reader import Lue
    from lue.tts.elevenlabs_tts import ElevenlabsTTS


def tearDownModule():
    _sandbox.cleanup()


class DictionaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        for target, value in [
            ("lue.config.PROGRESS_FILE_DIR", self.directory.name),
            ("lue.dictionary.CACHE_FILE", str(Path(self.directory.name) / "cache.json")),
            ("lue.dictionary._CACHE", {}),
        ]:
            context = patch(target, value)
            context.start()
            self.addCleanup(context.stop)

    def test_book_punctuation_is_removed_without_losing_accents(self):
        self.assertEqual(dictionary.normalize_word(' “Hello!” '), "hello")
        self.assertEqual(dictionary.normalize_word('—“Über”—'), "über")
        self.assertEqual(dictionary.normalize_word("well-known"), "well-known")

    def test_turkish_translation_can_use_only_ascii_letters(self):
        with patch.object(dictionary, "_fetch_json", return_value={
            "responseStatus": 200,
            "responseData": {"translatedText": "kitap"},
        }):
            self.assertEqual(dictionary._fetch_translation("book", "tr"), "kitap")

    def test_provider_error_is_not_shown_as_a_translation(self):
        with patch.object(dictionary, "_fetch_json", return_value={
            "responseStatus": 429,
            "responseData": {"translatedText": "Daily limit exceeded"},
        }):
            self.assertIsNone(dictionary._fetch_translation("book", "tr"))

    def test_translation_request_uses_selected_language(self):
        with patch.object(dictionary, "_fetch_json", return_value={
            "responseStatus": 200, "responseData": {"translatedText": "Buch"},
        }) as fetch:
            self.assertEqual(dictionary._fetch_translation("book", "de"), "Buch")
        self.assertEqual(parse_qs(urlparse(fetch.call_args.args[0]).query)["langpair"], ["en|de"])

    def test_default_lookup_does_not_contact_translation_service(self):
        with patch.object(dictionary, "_fetch_dictionary", return_value={
            "ipa": "/bʊk/", "meanings": [dictionary.Meaning("noun", "A written work.")],
        }), patch.object(dictionary, "_fetch_translation") as translate:
            result = dictionary.lookup_word("book")
        translate.assert_not_called()
        self.assertIsNone(result.translation)
        self.assertIsNone(result.translation_language)
        self.assertEqual(result.meanings[0].definition, "A written work.")

    def test_each_translation_has_its_own_cache_entry(self):
        with patch.object(dictionary, "_fetch_dictionary", return_value={
            "meanings": [dictionary.Meaning("noun", "A written work.")],
        }) as definitions, patch.object(dictionary, "_fetch_translation", side_effect=["Buch", "kitap"]) as translate:
            german = dictionary.lookup_word("book", "DE")
            turkish = dictionary.lookup_word("book", "tr")
            english = dictionary.lookup_word("book")
            self.assertEqual(dictionary.lookup_word("book", "de"), german)
        definitions.assert_called_once()
        self.assertEqual(translate.call_count, 2)
        self.assertEqual(german.translation, "Buch")
        self.assertEqual(turkish.translation, "kitap")
        self.assertIsNone(english.translation)

    def test_old_turkish_cache_is_preserved_without_changing_default(self):
        Path(dictionary.CACHE_FILE).write_text(json.dumps({"book": {
            "word": "book", "ipa": "/bʊk/", "translation_tr": "kitap",
            "meanings": [{"part_of_speech": "noun", "definition": "A written work."}],
        }}))
        dictionary._load_disk_cache()
        with patch.object(dictionary, "_fetch_json", side_effect=AssertionError("Network called")):
            self.assertIsNone(dictionary.lookup_word("book").translation)
            self.assertEqual(dictionary.lookup_word("book", "tr").translation, "kitap")

    def test_old_translation_only_entry_is_not_an_english_definition(self):
        Path(dictionary.CACHE_FILE).write_text(json.dumps({"word": {
            "word": "word", "translation_tr": "kelime", "meanings": [],
        }}))
        dictionary._load_disk_cache()
        with patch.object(dictionary, "_fetch_dictionary", return_value=None):
            with self.assertRaises(LookupError):
                dictionary.lookup_word("word")
            self.assertEqual(dictionary.lookup_word("word", "tr").translation, "kelime")

    def test_translation_failure_keeps_definitions_and_retries_later(self):
        with patch.object(dictionary, "_fetch_dictionary", return_value={
            "meanings": [dictionary.Meaning("noun", "A written work.")],
        }), patch.object(dictionary, "_fetch_translation", side_effect=[None, "Buch"]):
            first = dictionary.lookup_word("book", "de")
            second = dictionary.lookup_word("book", "de")
        self.assertTrue(first.meanings)
        self.assertIsNone(first.translation)
        self.assertEqual(second.translation, "Buch")

    def test_language_code_validation(self):
        self.assertEqual(dictionary.normalize_translation_language(" PT-BR "), "pt-br")
        self.assertIsNone(dictionary.normalize_translation_language("none"))
        self.assertIsNone(dictionary.normalize_translation_language("en"))
        for value in ["", "German", "en|de", "../de"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                dictionary.normalize_translation_language(value)

    def test_disk_cache_survives_restart_and_works_offline(self):
        definition = {"ipa": "/bʊk/", "meanings": [dictionary.Meaning("noun", "A written work.")]}
        with patch.object(dictionary, "_fetch_dictionary", return_value=definition), \
             patch.object(dictionary, "_fetch_translation", return_value="kitap"):
            first = dictionary.lookup_word("Book", "tr")
        dictionary._CACHE.clear()
        dictionary._load_disk_cache()
        with patch.object(dictionary, "_fetch_json", side_effect=AssertionError("Network called")):
            self.assertEqual(dictionary.lookup_word("“BOOK”", "tr"), first)
            self.assertIsNone(dictionary.lookup_word("Book").translation)

    def test_missing_result_does_not_poison_cache(self):
        with patch.object(dictionary, "_fetch_dictionary", return_value=None), \
             patch.object(dictionary, "_fetch_translation", return_value=None):
            with self.assertRaises(LookupError):
                dictionary.lookup_word("missing")
        self.assertFalse(dictionary._CACHE)


class WordHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        context = patch.object(word_history, "HISTORY_FILE", str(Path(self.directory.name) / "history.json"))
        context.start()
        self.addCleanup(context.stop)

    def test_repeat_lookups_are_counted_per_book(self):
        word_history.record_word("book", "First book")
        word_history.record_word("book", "First book")
        word_history.record_word("book", "Second book")
        entries = word_history.load_entries()
        self.assertEqual(len(entries), 2)
        self.assertEqual({entry.book: entry.count for entry in entries}, {"First book": 2, "Second book": 1})
        self.assertEqual(len(word_history.get_today_words()), 2)

    def test_history_retains_most_recent_entries_at_capacity(self):
        with patch.object(word_history, "MAX_ENTRIES", 2):
            for word in ["one", "two", "three"]:
                word_history.record_word(word, "Sample")
        self.assertEqual([entry.word for entry in word_history.load_entries()], ["two", "three"])


class TimingTests(unittest.TestCase):
    def test_character_alignment_produces_complete_last_word(self):
        text = "Hi there!"
        result = ElevenlabsTTS._alignment_to_word_timings({
            "characters": list(text),
            "character_start_times_seconds": [i / 10 for i in range(len(text))],
            "character_end_times_seconds": [(i + 1) / 10 for i in range(len(text))],
        })
        self.assertEqual(result, [("Hi", 0.0, 0.2), ("there", 0.3, 0.9)])

    def test_incomplete_alignment_is_rejected(self):
        self.assertEqual(ElevenlabsTTS._alignment_to_word_timings({"characters": ["x"]}), [])

    def test_dialogue_forms_are_recognized(self):
        for sentence in ['“Hello.”', '— Hello.', '- Hello.', 'She said, "Hello."']:
            self.assertTrue(audio._is_dialogue_sentence(sentence))
        self.assertFalse(audio._is_dialogue_sentence("A regular sentence."))


class PronunciationTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_uses_selected_backend_and_resumes_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            async def generate(word, output_path):
                Path(output_path).write_bytes(b"test-audio")

            backend = SimpleNamespace(initialized=True, output_format="mp3", generate_audio=AsyncMock(side_effect=generate))
            manager = Mock()
            manager.create_model.return_value = backend
            reader = SimpleNamespace(
                _get_lookup_target_word=Mock(return_value="hello"), book_title="Sample",
                is_paused=False, tts_model=SimpleNamespace(name="kokoro"),
                tts_voice="test-voice", _pronounce_tts=None,
                _pronounce_tts_name=None, _pronounce_tts_voice=None,
                _tts_manager=manager, console=Mock(), running=True,
                _save_extended_progress=Mock(), _show_lookup_error=Mock(),
            )
            process = SimpleNamespace(wait=AsyncMock())
            with patch.object(config, "AUDIO_DATA_DIR", directory), \
                 patch.object(word_history, "record_word") as record, \
                 patch.object(audio, "stop_and_clear_audio", new_callable=AsyncMock) as stop, \
                 patch.object(audio, "play_from_current_position", new_callable=AsyncMock) as resume, \
                 patch.object(asyncio, "create_subprocess_exec", new_callable=AsyncMock, return_value=process):
                await Lue._pronounce_current_word(reader)
            manager.create_model.assert_called_once_with("kokoro", reader.console, voice="test-voice", lang=None)
            backend.generate_audio.assert_awaited_once()
            stop.assert_awaited_once_with(reader)
            resume.assert_awaited_once_with(reader)
            record.assert_called_once_with("hello", "Sample")
            reader._show_lookup_error.assert_not_called()
            self.assertFalse(reader.is_paused)
            self.assertFalse((Path(directory) / "word_preview.mp3").exists())


if __name__ == "__main__":
    unittest.main()
