import asyncio
import base64
import json
import logging
import os
from urllib import error, request

from rich.console import Console

from .base import TTSBase
from .. import config


class ElevenlabsTTS(TTSBase):
    """TTS implementation for ElevenLabs cloud API."""

    API_BASE = "https://api.elevenlabs.io/v1"
    OUTPUT_FORMAT = "mp3_44100_128"
    MODEL_ID = "eleven_multilingual_v2"

    @property
    def name(self) -> str:
        return "elevenlabs"

    @property
    def output_format(self) -> str:
        return "mp3"

    def __init__(self, console: Console, voice: str = None, lang: str = None):
        super().__init__(console, voice, lang)
        self.api_key = None
        if self.voice is None:
            self.voice = config.TTS_VOICES.get(self.name)

    async def initialize(self) -> bool:
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        if self.api_key:
            self.api_key = self.api_key.strip()

        if not self.api_key:
            self.console.print("[bold red]Error: ELEVENLABS_API_KEY is not set.[/bold red]")
            self.console.print("[yellow]Set it first: export ELEVENLABS_API_KEY=...[/yellow]")
            logging.error("ELEVENLABS_API_KEY is missing for ElevenLabs TTS.")
            return False

        if not self.voice:
            self.console.print("[bold red]Error: ElevenLabs voice ID is not configured.[/bold red]")
            logging.error("ElevenLabs voice is not configured.")
            return False

        self.initialized = True
        self.console.print("[green]ElevenLabs TTS model is available.[/green]")
        return True

    def _call_with_timestamps(self, text: str) -> dict:
        payload = json.dumps(
            {
                "text": text,
                "model_id": self.MODEL_ID,
                "output_format": self.OUTPUT_FORMAT,
            }
        ).encode("utf-8")

        req = request.Request(
            f"{self.API_BASE}/text-to-speech/{self.voice}/with-timestamps",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "xi-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ElevenLabs API error ({exc.code}): {body[:250]}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"ElevenLabs network error: {exc.reason}") from exc

    @staticmethod
    def _alignment_to_word_timings(alignment: dict) -> list[tuple[str, float, float]]:
        chars = alignment.get("characters") or []
        starts = alignment.get("character_start_times_seconds") or []
        ends = alignment.get("character_end_times_seconds") or []

        if (
            not isinstance(chars, list)
            or not isinstance(starts, list)
            or not isinstance(ends, list)
            or len(chars) != len(starts)
            or len(chars) != len(ends)
        ):
            return []

        word_timings: list[tuple[str, float, float]] = []
        current_chars: list[str] = []
        start_time = None
        end_time = None

        def flush():
            nonlocal current_chars, start_time, end_time
            if not current_chars:
                return
            word = "".join(current_chars).strip(" \t\n\r.,:;!?\"'`()[]{}<>-–—")
            if word and start_time is not None and end_time is not None and end_time >= start_time:
                word_timings.append((word, start_time, end_time))
            current_chars = []
            start_time = None
            end_time = None

        for ch, s, e in zip(chars, starts, ends):
            if str(ch).isspace():
                flush()
                continue
            current_chars.append(str(ch))
            if start_time is None:
                start_time = float(s) if s is not None else None
            if e is not None:
                end_time = float(e)
        flush()
        return word_timings

    async def get_raw_timing_data(self, text: str, output_path: str):
        if not self.initialized:
            raise RuntimeError("ElevenLabs TTS has not been initialized.")

        def _blocking():
            data = self._call_with_timestamps(text)
            audio_b64 = data.get("audio_base64")
            if not audio_b64:
                raise RuntimeError("ElevenLabs response did not include audio data.")

            with open(output_path, "wb") as f:
                f.write(base64.b64decode(audio_b64))

            alignment = data.get("normalized_alignment") or data.get("alignment") or {}
            return self._alignment_to_word_timings(alignment)

        return await asyncio.to_thread(_blocking)

    async def generate_audio_with_timing(self, text: str, output_path: str):
        raw_timings = await self.get_raw_timing_data(text, output_path)

        try:
            from .. import audio
        except ImportError:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            import audio
        duration = await audio.get_audio_duration(output_path)

        try:
            from ..timing_calculator import process_tts_timing_data
        except ImportError:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            import timing_calculator
            process_tts_timing_data = timing_calculator.process_tts_timing_data
        return process_tts_timing_data(text, raw_timings, duration)

    async def generate_audio(self, text: str, output_path: str):
        if not self.initialized:
            raise RuntimeError("ElevenLabs TTS has not been initialized.")
        await self.get_raw_timing_data(text, output_path)
