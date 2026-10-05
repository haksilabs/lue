# Lue

A terminal ebook reader with text-to-speech. This is a personal fork of [paulilaaso/lue](https://github.com/paulilaaso/lue), with word lookup, pronunciation and a history of words looked up while reading.

## What changed

- **Word lookup (`d`):** English definitions, IPA and example sentences in a panel over the book. Results are cached on disk, so previously loaded words can be looked up offline.
- **Optional translation:** Add a translation with `--translate-to de`, `--translate-to es`, `--translate-to tr` or another language supported by MyMemory. Translations are off by default.
- **Pronunciation (`o`):** Listen to the selected word using the current TTS engine and voice. Reading pauses during pronunciation and resumes afterward.
- **Word history (`e`):** See today's words and recent lookups, with the book name and repeat counts.
- **Mouse selection:** Click a word to use it for lookup or pronunciation.
- **Speech pacing:** Short sentences use less audio overlap. Dialogue gets a short pause at the end, and rate-limit errors no longer trigger an immediate duplicate TTS request.
- **Optional ElevenLabs backend:** Available through `--tts elevenlabs`. Edge remains the default.

Lookups handle curly quotes around words. Translation results are cached separately for each language.

Lue's existing EPUB, PDF, TXT, DOCX, HTML, RTF and Markdown support, chapter navigation, reading progress, word highlighting, display modes and Kokoro backend come from the original project.

## Install

Requires Python 3.10 or newer and FFmpeg (`ffmpeg`, `ffplay` and `ffprobe`).

```bash
# Debian / Ubuntu
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

Clone this fork to get the additional features. The `lue-reader` package on PyPI is the upstream version.

```bash
git clone https://github.com/muhammetozkoc/lue.git
cd lue
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
lue examples/reading-sample.txt
```

On Windows, use WSL. For optional offline speech, install the Kokoro dependencies with `python -m pip install -e '.[kokoro]'` and install your system's `espeak` package.

## Read a book

```bash
lue path/to/book.epub
lue                         # reopen the last book
lue --guide                 # keyboard guide
lue --tts none book.epub     # read without continuous speech
lue --tts kokoro book.epub   # use Kokoro
lue --voice en-US-AriaNeural book.epub
lue --speed 1.5 book.epub
lue --keys vim book.epub
lue --translate-to de book.epub  # English definitions + German translation
lue --translate-to tr book.epub  # English definitions + Turkish translation
lue --filter book.pdf       # trim PDF headers and footers
lue --help
```

`o` can still pronounce a word when continuous speech is disabled with `--tts none`; in that case it uses the default TTS engine.

| Key | Action |
| --- | --- |
| `d` | Open or close word lookup |
| `o` | Pronounce the selected word |
| `e` | Open or close word history |
| `p` or Space | Pause or resume reading |
| `h` / `l` | Previous / next paragraph |
| `j` / `k` | Previous / next sentence |
| `z` / `x` | Previous / next chapter |
| `c` | Chapter index |
| `i` / `m` | Page up / down |
| `u` / `n` | Scroll up / down |
| `r` | Recent books |
| `,` / `.` | Decrease / increase playback speed |
| `a` | Toggle auto-scroll |
| `s` / `w` | Toggle sentence / word highlighting |
| `v` | Cycle display modes |
| `q` | Save progress and quit |

The lookup keys are also available in the Vim layout. Other bindings are listed in [keys_default.json](lue/keys_default.json) and [keys_vim.json](lue/keys_vim.json).

## Speech engines

Edge uses an online service through `edge-tts` and needs an internet connection. Kokoro runs locally after its models have been downloaded. See [VOICES.md](VOICES.md) for Edge and Kokoro voices.

ElevenLabs is optional and requires your own API key and a voice available to your account:

```bash
export ELEVENLABS_API_KEY='your-api-key'
export ELEVENLABS_VOICE_ID='your-voice-id'
lue --tts elevenlabs book.epub
```

You can also pass the voice ID with `--voice`. No account credentials are included in this repository. The ElevenLabs backend was recovered from the earlier local version; its timing conversion is tested locally, but it has not been retested against the live API during this recovery.

## Lookup and saved data

New lookups send the selected English word to [Free Dictionary API](https://dictionaryapi.dev/) for definitions, IPA and examples. [MyMemory](https://mymemory.translated.net/doc/spec.php) is contacted only when you enable translation with `--translate-to`. Language codes such as `de`, `es`, `tr` and `pt-br` are accepted; availability depends on the provider. `--translate-to none` disables translation.

Definitions currently cover English words, regardless of the translation language. Translations are word-level results and can choose the wrong meaning for the sentence. For example, `book` may be translated as a reservation rather than a printed book. If translation fails, the English definition remains available.

The dictionary cache stores up to 2,000 entries, including separate entries for each translation language. Existing Turkish cache entries are still available with `--translate-to tr`. Word history stores up to 500 records; repeat lookups of the same word in the same book on the same day share a record. The history panel shows today's words and the 15 most recent records. It does not yet offer search, flashcards or export.

On Linux, progress, dictionary cache and word history live in `~/.local/share/lue/`. Audio cache lives in `~/.cache/lue/`. Other platforms use the directories chosen by `platformdirs`. Personal reading data and generated audio are not part of the repository.

## Development

```bash
python -m unittest discover -s tests -v
python -m compileall -q lue
```

Tests cover English-only defaults, language selection, old cache migration, translation errors, offline cache reuse, word history, timing conversion and pronunciation pause/resume. They use temporary data directories and make no network requests.

See [DEVELOPER.md](DEVELOPER.md) for the TTS backend interface.

## License

GPL-3.0-or-later, as in the original project. See [LICENSE](LICENSE).
