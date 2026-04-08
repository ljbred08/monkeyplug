# monkeyplug-enhanced

[![Latest Version](https://img.shields.io/pypi/v/monkeyplug-enhanced)](https://pypi.python.org/pypi/monkeyplug-enhanced/)

**monkeyplug-enhanced** is an enhanced fork of [mmguero/monkeyplug](https://github.com/mmguero/monkeyplug) (available on PyPI as `monkeyplug`). It censors profanity in audio files using speech recognition, detecting profanity timestamps and either muting, beeping, or splicing in instrumental audio using FFmpeg.

The CLI command is still `monkeyplug` — only the package name changed to avoid conflicting with the original.

### Enhancements over the original

- **Groq API** integration (fast, default mode)
- **AI instrumental generation** via sherpa-onnx source separation
- **AI profanity detection** via Groq LLM with structured outputs
- **Wildcard/batch processing** with automatic vocal detection
- **Progress bar** for non-verbose mode
- **Transcript save/reuse** for faster reprocessing
- **Config file** support with sensible defaults
- **Automatic metadata tagging** via ShazamIO (title, artist, genre, cover art)

## How It Works

1. Speech recognition produces word-level timestamps (using Groq, Whisper, or Vosk)
2. Each word is checked against a built-in profanity list (or your custom list)
3. FFmpeg creates a cleaned audio file by either muting, beeping, or replacing profanity sections with instrumental audio
4. Optionally, transcripts can be saved and reused to skip transcription on future runs

If provided a video file, monkeyplug processes the audio stream and remultiplexes it with the original video stream.

## Installation

```bash
pip install monkeyplug-enhanced
```

Or install from GitHub:

```bash
pip install 'git+https://github.com/ljbred08/monkeyplug'
```

### Prerequisites

- **FFmpeg** — install via your OS package manager or from [ffmpeg.org](https://www.ffmpeg.org/download.html)
- **Python 3.10+**
- **Groq API key** (for default mode) — see [Groq API Setup](#groq-api-setup)
- Optional: [Whisper](https://github.com/openai/whisper) or [Vosk](https://github.com/alphacep/vosk-api) for offline recognition

## Groq API Setup

The default mode uses Groq's fast Whisper API. Configure your API key using one of these methods (in order of priority):

**Command-line parameter:**
```bash
monkeyplug -i input.mp3 -o output.mp3 --groq-api-key gsk_...
```

**Environment variable:**
```bash
export GROQ_API_KEY=gsk_...
```

**Config file** (`~/.groq/config.json`):
```json
{"api_key": "gsk_..."}
```

**Project-local file** (add `.groq_key` to `.gitignore`):
```bash
echo 'gsk_...' > .groq_key
```

## Quick Start

```bash
# Basic usage — mutes profanity using Groq API and built-in word list
# Shows progress bar automatically in non-verbose mode
monkeyplug -i song.mp3 -o song_clean.mp3

# Verbose output to see what's happening
monkeyplug -i song.mp3 -o song_clean.mp3 -v

# Use local Whisper instead of Groq
monkeyplug -i song.mp3 -o song_clean.mp3 -m whisper
```

## Censorship Modes

Three modes are available. Priority order: `--mute` > `--beep` > `--instrumental`.

### Mute

Silences profanity sections with short fade transitions.

```bash
monkeyplug -i song.mp3 -o song_clean.mp3 --mute
```

### Beep

Replaces profanity with a beep tone.

```bash
# Basic beep
monkeyplug -i song.mp3 -o song_clean.mp3 -b

# Customize beep frequency and mix
monkeyplug -i song.mp3 -o song_clean.mp3 -b -z 1000 --beep-mix-normalize
```

### Instrumental

Replaces profanity sections with instrumental audio for a professional-sounding clean edit. Supports several sub-modes:

#### Provide an instrumental file directly

```bash
monkeyplug -i explicit.mp3 -o clean.mp3 --instrumental instrumental.mp3
```

#### Auto mode (default)

Searches for an instrumental file using fuzzy matching. If not found, falls back to AI generation.

```bash
# Default behavior — searches for matching instrumental, generates if not found
monkeyplug -i song.mp3 -o song_clean.mp3 --instrumental auto

# This is also the default when no --instrumental flag is given
monkeyplug -i song.mp3 -o song_clean.mp3
```

AUTO fuzzy matching searches the same directory for audio files with similar names (30% similarity threshold). Examples:
- `1-satisfied.mp3` → finds `satisfied-inst.mp3`
- `MySong_v2.mp3` → finds `MySong_instrumental.mp3`

#### Prefix search

Searches for instrumental files using a specific prefix/suffix pattern:

```bash
# Searches for: song_inst.mp3, song-inst.mp3, inst_song.mp3, etc.
monkeyplug -i song.mp3 -o song_clean.mp3 --instrumental prefix --instrumental-prefix inst
```

#### AI Generation (force)

Uses sherpa-onnx to AI-generate instrumental sections for profanity segments. Skips all instrumental file searching.

```bash
monkeyplug -i song.mp3 -o song_clean.mp3 --instrumental generate
```

The AI separation process:
1. Extracts profanity segments from the original audio
2. Concatenates them with configurable padding (default: 1.0s)
3. Separates vocals from instrumental using a Spleeter model
4. Splices the AI-generated instrumental back into the original

Separation models are cached at `~/.cache/monkeyplug/separation_models/` (downloaded on first use).

## Wildcard / Batch Mode

Process multiple files at once using `*` wildcards:

```bash
# Process all MP3s in current directory
monkeyplug -i "*.mp3" -o "*_clean.mp3" --instrumental generate

# With verbose output
monkeyplug -i "*.mp3" -o "*_clean.mp3 -v
```

### Vocal detection

In wildcard mode, monkeyplug automatically detects which files have vocals by transcribing a 10-second sample from the middle of each file. Instrumental files (no speech detected) are skipped.

With `--instrumental generate`, vocal detection is **skipped by default** (all files are processed) since you're generating instrumentals anyway. Use `--filter-instrumentals` to re-enable it:

```bash
# Process all files (default — no vocal detection)
monkeyplug -i "*.mp3" -o "*_clean.mp3" --instrumental generate

# Skip files detected as instrumentals
monkeyplug -i "*.mp3" -o "*_clean.mp3" --instrumental generate --filter-instrumentals
```

Files matching the output pattern are automatically skipped (already processed).

## Transcript Workflow

Save and reuse transcripts to avoid redundant API calls (up to 22x faster on repeat runs):

```bash
# Generate and save transcript alongside output
monkeyplug -i song.mp3 -o song_clean.mp3 --save-transcript
# Creates: song_clean.mp3 + song_clean_transcript.json

# Second run: automatically finds and reuses the transcript
monkeyplug -i song.mp3 -o song_clean.mp3 --save-transcript

# Force new transcription (ignore existing transcript)
monkeyplug -i song.mp3 -o song_clean.mp3 --save-transcript --force-retranscribe

# Manually specify a transcript to load
monkeyplug -i song.mp3 -o song_clean_strict.mp3 --input-transcript song_clean_transcript.json -w strict_swears.txt
```

## Custom Profanity Lists

```bash
# Use a custom text file (one word per line, or word|replacement)
monkeyplug -i podcast.mp3 -o podcast_clean.mp3 --swears custom_swears.txt

# Use a custom JSON file (array of strings)
monkeyplug -i podcast.mp3 -o podcast_clean.mp3 --swears custom_swears.json

# Custom words are merged with the built-in profanity list
```

## Automatic Metadata Tagging

monkeyplug automatically fetches song metadata from Shazam and embeds it into the output file:

- **Title, Artist, Genre** - Text tags embedded in the audio file
- **Cover Art** - Album artwork downloaded and embedded (MP3 only)

```bash
# Metadata is enabled by default
monkeyplug -i song.mp3 -o song_clean.mp3

# Disable metadata fetching
monkeyplug -i song.mp3 -o song_clean.mp3 --disable-metadata
```

**What happens:**
1. The input file is analyzed by Shazam to identify the song
2. Metadata (title, artist, genre, cover art URL) is retrieved
3. Cover art is downloaded and embedded as ID3/APIC frames
4. Text tags are added to the output file

**Notes:**
- Requires internet connection for Shazam recognition
- Cover art embedding is supported for MP3 files
- If recognition fails, the file is still processed (no error)
- Metadata can be viewed in any music player or with `ffprobe`

## Show Profanity Output

Control what's printed about detected profanity in normal (non-verbose) mode:

```bash
# Show count only (default)
monkeyplug -i song.mp3 -o song_clean.mp3 -w clean

# Show full list with timestamps
monkeyplug -i song.mp3 -o song_clean.mp3 -w full

# Silent mode (no profanity output)
monkeyplug -i song.mp3 -o song_clean.mp3 -w none
```

## AI Profanity Detection

Use Groq's LLM for context-aware profanity detection instead of (or in addition to) the static word list:

```bash
# AI-only detection (replaces static list)
monkeyplug -i song.mp3 -o song_clean.mp3 --detect ai

# Both list + AI (word flagged if either catches it)
monkeyplug -i song.mp3 -o song_clean.mp3 --detect both

# Default: static list only
monkeyplug -i song.mp3 -o song_clean.mp3 --detect list
```

Requires a Groq API key (same setup as Groq STT mode). Works with all speech recognition modes (Groq, Whisper, Vosk).

Configurable via `~/.cache/monkeyplug/config.json`:
```json
{
  "detect_mode": "list",
  "ai_detect_model": "openai/gpt-oss-20b",
  "ai_detect_prompt": "You are a profanity detection assistant..."
}
```

## Config File

monkeyplug looks for a JSON config file in this order (first found wins):

1. `./.monkeyplug.json` (current directory — project-specific)
2. `~/.cache/monkeyplug/config.json` (user-specific)

If neither exists, a default config is auto-created at `~/.cache/monkeyplug/config.json`:

```json
{
  "pad_milliseconds": 10,
  "pad_milliseconds_pre": 10,
  "pad_milliseconds_post": 10,
  "separation_padding": 1.0,
  "beep_hertz": 1000,
  "show_words": "clean",
  "detect_mode": "list",
  "ai_detect_model": "openai/gpt-oss-20b",
  "ai_detect_prompt": "You are a profanity detection assistant..."
}
```

Config values provide defaults that can be overridden by CLI arguments.

Clean all caches (models, config) with:

```bash
monkeyplug --clean-cache
```

## Padding Control

Add padding around profanity for smoother transitions:

```bash
# Equal padding on both sides
monkeyplug -i song.mp3 -o clean.mp3 --pad-milliseconds 100

# Different pre and post padding
monkeyplug -i song.mp3 -o clean.mp3 --pad-milliseconds-pre 50 --pad-milliseconds-post 100
```

## Full Usage Reference

```
usage: monkeyplug <arguments>

Core Options:
  -i, --input <string>              Input file, URL, or wildcard pattern
  -o, --output <string>             Output file or pattern
  -v [concise|full], --verbose      Verbose output
  -m [groq|whisper|vosk], --mode    Speech recognition engine (default: groq)

Censorship Modes:
  --mute                            Mute profanity (disables instrumental mode)
  -b, --beep                        Beep instead of silence
  --instrumental <mode|file>        Instrumental mode: auto, generate, prefix, or file path
  --instrumental-prefix <string>    Prefix to search for instrumental file (default: AUTO)
  --instrumental-auto-candidates <int>  Top candidates for AUTO matching (default: 5)

Profanity:
  --swears <file>                   Custom profanity list (text or JSON)
  --detect <list|ai|both>           Profanity detection method (default: list)
  -w, --show-words <clean|full|none>  Show detected profanity (default: clean)
  --pad-milliseconds <int>          Padding around profanity (default: 10)
  --pad-milliseconds-pre <int>      Padding before profanity (default: 10)
  --pad-milliseconds-post <int>     Padding after profanity (default: 10)

Beep Options:
  -z, --beep-hertz <int>            Beep frequency in Hz (default: 1000)
  --beep-mix-normalize              Normalize audio/beep mix
  --beep-audio-weight <int>         Non-beeped audio weight (default: 1)
  --beep-sine-weight <int>          Beep weight (default: 1)
  --beep-dropout-transition <int>   Dropout transition for beep (default: 0)

Transcript:
  --save-transcript                 Save transcript JSON alongside output
  --input-transcript <file>         Load existing transcript JSON
  --output-json <file>              Save transcript to specific file
  --force-retranscribe              Force new transcription

AI Separation:
  --separation-padding <seconds>    Context padding for AI generation (default: 1.0)
  --filter-instrumentals            Filter out instrumental files in wildcard mode with generate

Audio Output:
  -f, --format <string>             Output format (default: inferred from extension or "MATCH")
  -c, --channels <int>              Output channels (default: 2)
  -s, --sample-rate <int>           Output sample rate (default: 48000)
  -r, --bitrate <string>            Output bitrate (default: 256K)
  -a, --audio-params <string>       FFmpeg audio parameters
  -q, --vorbis-qscale <int>         qscale for libvorbis (default: 5)

Other:
  --force                           Process file even if already tagged
  --disable-metadata                Disable automatic metadata fetching via ShazamIO
  --clean-cache                     Delete all cached data (models, config) and exit

Groq Options:
  --groq-api-key <string>           Groq API key
  --groq-model <string>             Groq Whisper model (default: whisper-large-v3)

Whisper Options:
  --whisper-model-dir <string>      Model directory (default: ~/.cache/whisper)
  --whisper-model-name <string>     Model name (default: small.en)
  --torch-threads <int>             CPU inference threads (default: 0)

VOSK Options:
  --vosk-model-dir <string>         Model directory (default: ~/.cache/vosk)
  --vosk-read-frames-chunk <int>    WAV frame chunk (default: 8000)
```

## Contributing

Pull requests welcome!

## Authors

- **Seth Grover** - Initial work - [mmguero](https://github.com/mmguero)
- **Lincoln Brown** - Enhanced fork (Groq API, AI generation, batch mode) - [ljbred08](https://github.com/ljbred08)

## License

BSD 3-Clause License — see the [LICENSE](LICENSE) file for details.
