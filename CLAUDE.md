# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

monkeyplug is a CLI tool that censors profanity in audio files. It uses speech recognition to detect profanity timestamps, then either mutes, beeps, or replaces those sections with instrumental audio using FFmpeg. This is a fork of [mmguero/monkeyplug](https://github.com/mmguero/monkeyplug) with Groq API integration and AI-powered instrumental separation added.

## Development Commands

### Install for development
```bash
pip install -e .
```
This handles stale package cleanup and editable install. Must be run after any structural changes (new files, moved modules).

### Reinstall after code changes (usually not needed with editable mode)
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

| File | Purpose |
|------|---------|
| `monkeyplug.py` | All classes, CLI argument parsing (`RunMonkeyPlug`), FFmpeg filter building |
| `groq_config.py` | API key loading (priority: param > env var > `~/.groq/config.json` > `./.groq_key`) |
| `separation.py` | `SourceSeparator` class wrapping sherpa-onnx Spleeter 2-stems model |
| `data/profanity_list.json` | Built-in English profanity list, loaded via `importlib.resources` |

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

## Key External Dependencies

- **mmguero** (2.0.3): Utility library for process execution, JSON parsing, string helpers
- **tqdm** (>=4.65.0): Progress bar display
- **sherpa-onnx**: AI source separation (Spleeter int8 model, CPU-only, 4 threads)
- **soundfile + numpy**: Audio I/O for sherpa-onnx integration
- **mutagen**: Audio metadata read/write (used to tag processed files)
- All FFmpeg operations use `mmguero.run_process()` for subprocess execution

## Feature Branches

- **`feature/crossfade`** — Experimental crossfade support (WIP, not merged). Uses FFmpeg `afade`/`acrossfade` filters for smooth instrumental transitions. Includes `--clean-cache` flag and config path move to `~/.cache/monkeyplug/`.

## Version Bumping

Always bump the **patch** version (e.g. 2.2.2 → 2.2.3) unless the user explicitly requests a minor or major bump.
