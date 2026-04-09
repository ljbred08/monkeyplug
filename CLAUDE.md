# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

monkeyplug is a CLI tool that censors profanity in audio files. It uses speech recognition to detect profanity timestamps, then either mutes, beeps, or replaces those sections with instrumental audio using FFmpeg. This is a fork of [mmguero/monkeyplug](https://github.com/mmguero/monkeyplug) with Groq API integration, AI-powered instrumental separation, and automatic ShazamIO metadata tagging added.

## Development Commands

### Install for development

```bash
pip install -e .
```

This handles stale package cleanup and editable install. Must be run after any structural changes (new files, moved modules).

### Reinstall after code changes ONLY IF USER SAYS CHANGES AREN'T SHOWING UP

```bash
pip install -e . --no-deps --force-reinstall
```

### Clear Python cache if stale imports

```bash
find . -type d -name __pycache__ -exec rm -rf {} +
```

### Verify installation

```bash
python -c "import monkeyplug; print(monkeyplug.__file__)"
# Should point to src/monkeyplug/__init__.py, NOT site-packages/monkeyplug
```

### Run tests

```bash
pytest tests/
pytest tests/test_swears_loading.py  # single test file
pytest tests/test_swears_loading.py::test_load_builtin_swears -v  # single test
```

### Run the tool

```bash
monkeyplug -i input.mp3 -o output_clean.mp3 -v
```

## Architecture

### Class Hierarchy

```
Plugger (base class)          - Core audio processing, FFmpeg integration
├── VoskPlugger(Plugger)      - Vosk speech recognition
├── WhisperPlugger(Plugger)   - OpenAI Whisper local model
└── GroqPlugger(Plugger)      - Groq Whisper API (default mode)
```

All classes live in `src/monkeyplug/monkeyplug.py`. The base `Plugger` class handles FFmpeg audio processing, profanity detection, and output encoding. Subclasses override `RecognizeSpeech()`.

### Key Data Flow

1. **Transcription**: Groq API (or Whisper/Vosk) produces `wordList` - a list of dicts with `word`, `start`, `end`, `conf`, `scrub` keys

2. **Profanity detection**: `naughtyWordList` = words where `scrub=True`, checked against `swearsMap` loaded from built-in JSON + optional custom file

3. **Segment creation**: Three modes determined by `CreateCleanMuteList()`:
   
   - **Mute/Beep**: `_create_mute_beep_list()` builds FFmpeg volume/filter chains
   
   - **Traditional instrumental**: User provides full instrumental file, `_build_instrumental_filters()` uses `asplit` to reference both streams
   
   - **Auto-separation**: `_create_combined_profanity_file()` extracts profanity segments with padding into one combined WAV, runs through sherpa-onnx `SourceSeparator`, then `_build_instrumental_filters()` splices the AI-generated instrumental back in

### Module Responsibilities

| File                       | Purpose                                                                             |
| -------------------------- | ----------------------------------------------------------------------------------- |
| `monkeyplug.py`            | All classes, CLI argument parsing (`RunMonkeyPlug`), FFmpeg filter building         |
| `groq_config.py`           | API key loading (priority: param > env var > `~/.groq/config.json` > `./.groq_key`) |
| `separation.py`            | `SourceSeparator` class wrapping sherpa-onnx Spleeter 2-stems model                 |
| `data/profanity_list.json` | Built-in English profanity list, loaded via `importlib.resources`                   |

### Auto-Separation Mode (AI Instrumental Generation)

When `--instrumental auto` or `--instrumental generate` is used:

1. Profanity segments are merged (gap < 100ms) into `instrumentalSegments` list of `(start, end)` tuples
2. Segments are extracted with configurable padding (`separationPadding`, default 1.0s) into one combined WAV
3. `segMapping` tracks timestamp translation: `(profanity_start, profanity_end, combined_start, combined_end, padded_start, padded_end)`
4. Combined file is separated by sherpa-onnx into vocals + instrumental
5. `_build_instrumental_filters()` uses `segMapping` to extract the correct instrumental portions and splice them in

### Config System

Search order (first found wins): `./.monkeyplug.json` (CWD) → `~/.cache/monkeyplug/config.json`. If neither exists, a default config is auto-created at the latter path. Config provides defaults for padding, beep, and display settings, overridable by CLI args. Clean all caches: `monkeyplug --clean-cache`.

### Show Words (-w / --show-words)

Controls profanity detection output in normal mode (non-verbose). Three modes:

- **`full`**: Print each detected word with timestamp (`"word" (M:SS.mmm - M:SS.mmm)`) + count
- **`clean`** (default): Print only the count (e.g., "3 words detected" or "No profanity detected")
- **`none`**: Silent — no profanity output at all

Default is settable via `show_words` key in config file. CLI `-w full|clean|none` overrides config default. Output goes to stderr via `mmguero.eprint()`. Called from `EncodeCleanAudio()` after `CreateCleanMuteList()` populates `naughtyWordList`.

### AI Detection (--detect)

Profanity detection method. Three modes:

- **`list`** (default): Static profanity list (current behavior)
- **`ai`**: Groq LLM with structured outputs replaces the list entirely. Context-aware detection.
- **`both`**: List + AI combined (OR logic — word flagged if either method catches it)

Requires Groq API key (same key as Groq STT mode). Works with all STT modes (Groq/Vosk/Whisper) as long as the key is available.

Config keys: `detect_mode` (default `"list"`), `ai_detect_model` (default `"openai/gpt-oss-20b"`), `ai_detect_prompt` (custom system prompt). Model must support Groq structured outputs with strict mode (`openai/gpt-oss-20b` or `openai/gpt-oss-120b`).

### ShazamIO Metadata Tagging (--disable-metadata)

Automatic song identification and metadata tagging via Shazam API. Enabled by default, disabled with `--disable-metadata` flag.

**What it does:**

1. **Recognition**: Uses ShazamIO to identify the song from the input audio
2. **Metadata fetch**: Retrieves title, artist, genre, and cover art URL
3. **Cover art download**: Downloads album artwork (400x400 JPEG)
4. **Embedding**: Writes ID3 tags to output file (MP3 only for cover art)

**Implementation:**

- `_fetch_shazam_metadata()`: Async function using `shazamio.Shazam.recognize()`
- `_embed_metadata()`: Uses `mutagen.mp3.MP3` with direct ID3 tag manipulation
- Cover art embedded as APIC frame (type=3, cover front)
- Text tags: TIT2 (title), TPE1 (artist), TCON (genre), TALB (album), TDRC (year)

**Key attributes:**

- `self.disableMetadata`: Flag to skip metadata fetch (from `--disable-metadata`)
- `self.shazamMetadata`: Dict containing fetched metadata
- Called in `Plugger.__init__()` after input file validation
- Embedded in `EncodeCleanAudio()` after FFmpeg encoding completes

**Format support:**

- MP3: Full support (text tags + cover art via APIC frames)
- Other formats: Text tags only via mutagen easy mode

**Error handling:**

- Graceful degradation if Shazam recognition fails (no error, just no metadata)
- Network timeouts handled (10 second timeout for cover art download)
- Debug mode (`-v`) shows recognition progress and errors

### Album Unification (--unify-album)

Unifies album metadata across all files in a folder using AI. Assigns track numbers and determines a consistent album name.

**Two modes:**

1. **Combined with processing**: Runs after normal audio processing completes
   
   ```bash
   monkeyplug -i "*.mp3" -o "*_clean.mp3" --unify-album
   ```

2. **Standalone**: Processes existing files without audio processing
   
   ```bash
   monkeyplug --unify-album -i /path/to/album
   # Uses current directory if -i not specified
   ```

**What it does:**

1. Reads metadata (filename, title, album) from all audio files
2. Sends to Groq AI (gpt-oss-120b) for analysis
3. Returns unified album name and track numbers
4. Applies changes to all files

**Implementation:**

- `_read_metadata_from_files()`: Uses mutagen to extract title/album from files
- `_unify_album_metadata()`: Groq API call with structured outputs
- `_apply_unified_metadata()`: Writes album + track to files via mutagen
- `_run_album_unification()`: Main orchestration function

**Config settings:**

- `unify_album_model`: AI model to use (default: "openai/gpt-oss-120b")
- `unify_album_prompt`: System prompt for the AI

**Requirements:**

- Groq API key (same as other AI features)
- Files must have existing metadata (title, album)

**Supported formats:**

- MP3: Full support (album + track number via ID3 tags)
- Other formats: Album only (via mutagen easy mode)

**Error handling:**

- Graceful degradation if files have no metadata
- Network timeouts handled with retry logic
- Debug mode (`-v`) shows API progress and responses

#### Spotify Integration (--use-spotify)

When used with `--unify-album`, fetches official cover art and track listings from Spotify for accurate results:

```bash
# Get official cover art and accurate track ordering
monkeyplug --unify-album --use-spotify

# With direct Spotify URL (skip search)
monkeyplug --unify-album --use-spotify "https://open.spotify.com/album/1kCHru7uhxBUdzkm4gzRQc"

# Combined with processing
monkeyplug -i "*.mp3" -o "*_clean.mp3" --unify-album --use-spotify

# Full workflow with renaming
monkeyplug -i "album/*.mp3" -o "album/*_clean.mp3" --unify-album --use-spotify --auto-rename
```

**How it works:**

1. AI determines unified album name from file metadata
2. **If Spotify URL provided**: Uses that URL directly
3. **If no URL provided (`--use-spotify` only)**: Searches Spotify for the album using DuckDuckGo
4. Gets official album info from Spotify:
   
   - Cover art URLs (prefers 640x640 or higher)
   
   - Official track listing
5. Second AI call matches local files to Spotify tracks for accurate ordering
6. Downloads and applies official cover art to all files
7. Applies unified album name and track numbers

**Benefits:**

- Consistent, high-quality cover art across all tracks
- Accurate track ordering based on official Spotify listing
- Two-pass AI approach ensures best results

**Implementation:**

- `_search_spotify_album()`: Uses DDGS to find Spotify album URL
- `_get_spotify_album_info()`: Uses spotify_scraper to fetch album data
- `_download_cover_art()`: Downloads image bytes from URL
- `_apply_cover_art_to_files()`: Embeds APIC tag (cover art) into MP3s

**Requirements:**

- `--unify-album` flag must be used
- Internet connection for Spotify access
- `ddgs` and `spotifyscraper` packages installed

**Error handling:**

- Spotify search fails: Continues with AI-only unification (logged)
- Spotify scraper fails: Continues with AI-only unification (logged)
- Cover art download fails: Skips cover art, still applies metadata (logged)

**Supported formats:**

- MP3: Full support (cover art via APIC tag)
- Other formats: Cover art not applied (metadata only)

### Progress Bar (tqdm)

In non-verbose mode (default), a tqdm progress bar shows overall progress. Steps displayed:

- **Transcribing** — Speech recognition (or loading transcript)
- **Extracting instrumental** — Only shown in auto-generation mode
- **Encoding** — FFmpeg processing

Uses timing data from `~/.cache/monkeyplug/timing_log.json` for smooth estimation. On first run, falls back to step-based bar. Progress updates happen inside `CreateCleanMuteList()` and `EncodeCleanAudio()`. Disabled entirely when `-v` flag is used.

### Timing Log

`~/.cache/monkeyplug/timing_log.json` stores running averages per operation (transcribe, extract, encode) for smooth progress bar estimation. Format: `{operation: {total_audio_seconds, total_wall_seconds, run_count}}`. Rate = wall/audio seconds. On first run (no log), falls back to step-based bar. Updated after each successful run. Cleaned by `--clean-cache`.

### FFmpeg Patterns

- **Traditional instrumental**: `[0:a]asplit=2[orig][inst]` then `atrim` from each stream + `concat`
- **Auto-separation**: `[0:a]` for original, `[1:a]` for combined instrumental, `atrim` + `concat`
- **Mute**: `afade` volume filters with `enable='between(t,start,end)'`, 5ms fade edges
- **Beep**: `volume=0` mute + `sine` generator + `amix`

### CLI Entry Point

`monkeyplug = "monkeyplug:RunMonkeyPlug"` in pyproject.toml. `RunMonkeyPlug()` handles all argument parsing and mode routing. Mode priority: `--mute` > `--beep` > `--instrumental`.

### Wildcard/Batch Mode

When input contains `*`, `expand_and_detect_vocals()` uses Groq API to detect which files have vocals, skipping instrumentals. Each vocal file is processed individually.

**Skip completed songs:** The `--skip-completed-songs` flag skips input files that already have a corresponding output file. For example, with `-i "*.mp3" -o "*_clean.mp3"`, if both `song.mp3` and `song_clean.mp3` exist, `song.mp3` will be skipped. Only applies when using wildcards.

## Key External Dependencies

- **mmguero** (2.0.3): Utility library for process execution, JSON parsing, string helpers
- **tqdm** (>=4.65.0): Progress bar display
- **sherpa-onnx**: AI source separation (Spleeter int8 model, CPU-only, 4 threads)
- **soundfile + numpy**: Audio I/O for sherpa-onnx integration
- **mutagen** (1.47.0): Audio metadata read/write (used to tag processed files with Shazam metadata)
- **shazamio** (>=0.8.0): Song recognition via Shazam API for automatic metadata tagging
- **aiohttp** (>=3.9.0): Async HTTP client for ShazamIO
- All FFmpeg operations use `mmguero.run_process()` for subprocess execution

## Feature Branches

- **`feature/crossfade`** — Experimental crossfade support (WIP, not merged). Uses FFmpeg `afade`/`acrossfade` filters for smooth instrumental transitions. Includes `--clean-cache` flag and config path move to `~/.cache/monkeyplug/`.

## Version Bumping

Always bump the **patch** version (e.g. 2.2.2 → 2.2.3) unless the user explicitly requests a minor or major bump.

# Docs

ALWAYS update relevant documentation files (README.md, CLAUDE.md, etc.) BEFORE committing.
