# monkeyplug

[![Latest Version](https://img.shields.io/pypi/v/monkeyplug)](https://pypi.python.org/pypi/monkeyplug/) [![VOSK Docker Images](https://github.com/mmguero/monkeyplug/workflows/monkeyplug-build-push-vosk-ghcr/badge.svg)](https://github.com/mmguero/monkeyplug/pkgs/container/monkeyplug) [![Whisper Docker Images](https://github.com/mmguero/monkeyplug/workflows/monkeyplug-build-push-whisper-ghcr/badge.svg)](https://github.com/mmguero/monkeyplug/pkgs/container/monkeyplug)

**monkeyplug** is a little script to censor profanity in audio files (intended for podcasts, but YMMV) in a few simple steps:

1. The user provides a local audio file (or a URL pointing to an audio file which is downloaded)
2. Either [Groq Whisper API](https://groq.com), [Whisper](https://openai.com/research/whisper) ([GitHub](https://github.com/openai/whisper)) or the [Vosk](https://alphacephei.com/vosk/)-[API](https://github.com/alphacep/vosk-api) is used to recognize speech in the audio file (or a pre-generated transcript can be loaded)
3. Each recognized word is checked against a built-in profanity list or a custom [list](./src/monkeyplug/swears.txt) of profanity or other words you'd like muted (supports text or [JSON format](./SWEARS_JSON_FORMAT.md))
4. [`ffmpeg`](https://www.ffmpeg.org/) is used to create a cleaned audio file, muting or "bleeping" the objectional words, or splicing in instrumental sections for a cleaner edit
5. Optionally, the transcript can be saved for reuse in future processing runs

You can then use your favorite media player to play the cleaned audio file.

If provided a video file for input, **monkeyplug** will attempt to process the audio stream from the file and remultiplex it, copying the original video stream.

**monkeyplug** is part of a family of projects with similar goals:

* 📼 [cleanvid](https://github.com/mmguero/cleanvid) for video files (using [SRT-formatted](https://en.wikipedia.org/wiki/SubRip#Format) subtitles)
* 🎤 [monkeyplug](https://github.com/mmguero/monkeyplug) for audio and video files (using [Groq API](https://groq.com), [Whisper](https://openai.com/research/whisper), or the [Vosk](https://alphacephei.com/vosk/)-[API](https://github.com/alphacep/vosk-api) for speech recognition)
* 📕 [montag](https://github.com/mmguero/montag) for ebooks

## Installation

Using `pip`, to install the latest [release from PyPI](https://pypi.org/project/monkeyplug/):

```
python3 -m pip install -U monkeyplug
```

Or to install directly from GitHub:


```
python3 -m pip install -U 'git+https://github.com/mmguero/monkeyplug'
```

## Prerequisites

[monkeyplug](./src/monkeyplug/monkeyplug.py) requires:

* [FFmpeg](https://www.ffmpeg.org)
* Python 3
    - [mutagen](https://github.com/quodlibet/mutagen)
    - [groq](https://console.groq.com/) (for Groq API mode - default)
    - Optional speech recognition libraries:
        + [Whisper](https://github.com/openai/whisper)
        + [vosk-api](https://github.com/alphacep/vosk-api) with a VOSK [compatible model](https://alphacephei.com/vosk/models)

To install FFmpeg, use your operating system's package manager or install binaries from [ffmpeg.org](https://www.ffmpeg.org/download.html). The Python dependencies will be installed automatically if you are using `pip` to install monkeyplug, except for [`vosk`](https://pypi.org/project/vosk/) or [`openai-whisper`](https://pypi.org/project/openai-whisper/); as monkeyplug can work with multiple speech recognition engines, there is not a hard installation requirement for any specific one until runtime.

### Groq API Setup

The default mode uses Groq's fast Whisper API. To get started:

1. Sign up at [console.groq.com](https://console.groq.com)
2. Generate an API key from the API Keys section
3. Configure your API key using one of these methods (in order of priority):

   **Method 1: Environment variable (recommended for production)**
   ```bash
   export GROQ_API_KEY=gsk_...
   monkeyplug -i input.mp3 -o output.mp3
   ```

   **Method 2: Command-line parameter**
   ```bash
   monkeyplug -i input.mp3 -o output.mp3 --groq-api-key gsk_...
   ```

   **Method 3: Config file**
   ```bash
   mkdir -p ~/.groq
   echo '{"api_key": "gsk_..."}' > ~/.groq/config.json
   ```

   **Method 4: Project-local file**
   ```bash
   echo 'gsk_...' > .groq_key
   # Add .groq_key to .gitignore to keep it private
   ```

## usage

```
usage: monkeyplug <arguments>

options:
  -h, --help            show this help message and exit
  -v [true|false], --verbose [true|false]
                        Verbose/debug output
  -m <string>, --mode <string>
                        Speech recognition engine (groq|whisper|vosk) (default: groq)
  -i <string>, --input <string>
                        Input file (or URL)
  -o <string>, --output <string>
                        Output file
  -w <profanity file>, --swears <profanity file>
                        text or JSON file containing profanity (default: built-in list)
  --output-json <string>
                        Output file to store transcript JSON
  --input-transcript <string>
                        Load existing transcript JSON instead of performing speech recognition
  --save-transcript     Automatically save transcript JSON alongside output audio file
  --force-retranscribe  Force new transcription even if transcript file exists (overrides automatic reuse)
  --instrumental <string>
                        Instrumental version of the audio file for splicing profanity sections
  --instrumental-prefix <string>
                        Prefix/suffix to search for instrumental file, or 'AUTO' for fuzzy matching (e.g., 'instrumental' finds 'song_instrumental.mp3')
  -a <str>, --audio-params <str>
                        Audio parameters for ffmpeg (default depends on output audio codec)
  -c <int>, --channels <int>
                        Audio output channels (default: 2)
  -s <int>, --sample-rate <int>
                        Audio output sample rate (default: 48000)
  -r <str>, --bitrate <str>
                        Audio output bitrate (default: 256K)
  -q <int>, --vorbis-qscale <int>
                        qscale for libvorbis output (default: 5)
  -f <string>, --format <string>
                        Output file format (default: inferred from extension of --output, or "MATCH")
  --pad-milliseconds <int>
                        Milliseconds to pad on either side of muted segments (default: 0)
  --pad-milliseconds-pre <int>
                        Milliseconds to pad before muted segments (default: 0)
  --pad-milliseconds-post <int>
                        Milliseconds to pad after muted segments (default: 0)
  -b [true|false], --beep [true|false]
                        Beep instead of silence
  -z <int>, --beep-hertz <int>
                        Beep frequency hertz (default: 1000)
  --beep-mix-normalize [true|false]
                        Normalize mix of audio and beeps (default: False)
  --beep-audio-weight <int>
                        Mix weight for non-beeped audio (default: 1)
  --beep-sine-weight <int>
                        Mix weight for beep (default: 1)
  --beep-dropout-transition <int>
                        Dropout transition for beep (default: 0)
  --force [true|false]  Process file despite existence of embedded tag

Groq Options:
  --groq-api-key <string>
                        Groq API key (default: GROQ_API_KEY env var, ~/.groq/config.json, or ./.groq_key)
  --groq-model <string>
                        Groq Whisper model (default: whisper-large-v3)

VOSK Options:
  --vosk-model-dir <string>
                        VOSK model directory (default: ~/.cache/vosk)
  --vosk-read-frames-chunk <int>
                        WAV frame chunk (default: 8000)

Whisper Options:
  --whisper-model-dir <string>
                        Whisper model directory (~/.cache/whisper)
  --whisper-model-name <string>
                        Whisper model name (base.en)
  --torch-threads <int>
                        Number of threads used by torch for CPU inference (0)

```

### Docker

Alternately, a [Dockerfile](./docker/Dockerfile) is provided to allow you to run monkeyplug in Docker. You can pull one of the following images:

* [VOSK](https://alphacephei.com/vosk/models)
    - oci.guero.org/monkeyplug:vosk-small
    - oci.guero.org/monkeyplug:vosk-large
* [Whisper](https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages)
    - oci.guero.org/monkeyplug:whisper-tiny.en
    - oci.guero.org/monkeyplug:whisper-tiny
    - oci.guero.org/monkeyplug:whisper-base.en
    - oci.guero.org/monkeyplug:whisper-base
    - oci.guero.org/monkeyplug:whisper-small.en
    - oci.guero.org/monkeyplug:whisper-small
    - oci.guero.org/monkeyplug:whisper-medium.en
    - oci.guero.org/monkeyplug:whisper-medium
    - oci.guero.org/monkeyplug:whisper-large-v1
    - oci.guero.org/monkeyplug:whisper-large-v2
    - oci.guero.org/monkeyplug:whisper-large-v3
    - oci.guero.org/monkeyplug:whisper-large

then run [`monkeyplug-docker.sh`](./docker/monkeyplug-docker.sh) inside the directory where your audio files are located.

## Transcript Workflow

**monkeyplug** supports saving and reusing transcripts to improve workflow efficiency:

### Save Transcript for Later Reuse

```bash
# Generate transcript once and save it
monkeyplug -i input.mp3 -o output.mp3 --save-transcript

# This creates output.mp3 and output_transcript.json
```

### Automatic Transcript Reuse

```bash
# Second run: Automatically detects and reuses transcript (22x faster!)
monkeyplug -i input.mp3 -o output.mp3 --save-transcript
# Finds output_transcript.json and reuses it automatically

# Force new transcription when needed
monkeyplug -i input.mp3 -o output.mp3 --save-transcript --force-retranscribe
```

### Manual Transcript Loading

```bash
# Explicitly specify transcript to load
monkeyplug -i input.mp3 -o output_strict.mp3 --input-transcript output_transcript.json -w strict_swears.txt
```

## Usage Examples

### Basic Usage with Built-in Profanity List

```bash
# Uses built-in profanity list and Groq API (default)
monkeyplug -i song.mp3 -o song_clean.mp3
```

### Instrumental Mode - Professional Clean Edit

```bash
# Create radio edit by splicing instrumental sections
# This produces a clean version that maintains the music flow
monkeyplug -i explicit_song.mp3 \
           -o clean_song.mp3 \
           --instrumental instrumental_song.mp3 \
           --save-transcript

# The output will have profanity sections replaced with the instrumental
# Multiple consecutive profanities within 100ms are merged into one splice
```

### Instrumental Mode - Auto-Search with Prefix

```bash
# Automatically find instrumental file by prefix/suffix
# Searches for patterns like:
#   - song_instrumental.mp3
#   - song-instrumental.mp3
#   - instrumental_song.mp3
#   - instrumental-song.mp3
monkeyplug -i song.mp3 -o song_clean.mp3 --instrumental-prefix instrumental

# With your file naming convention:
# If you have: "MyTrack.mp3" and "MyTrack_instrumental.mp3"
monkeyplug -i MyTrack.mp3 -o MyTrack_clean.mp3 --instrumental-prefix instrumental

# Or if you have: "MyTrack.mp3" and "inst_MyTrack.mp3"
monkeyplug -i MyTrack.mp3 -o MyTrack_clean.mp3 --instrumental-prefix inst
```

### Instrumental Mode - AUTO Fuzzy Matching

```bash
# AUTO mode - automatically finds the best matching instrumental file
# Uses fuzzy string matching to find similar filenames in the same directory
# Great when you have inconsistent naming conventions

# Example: Given "1-satisfied.mp3", it will find "satisfied-inst.mp3"
monkeyplug -i 1-satisfied.mp3 -o 1-satisfied_clean.mp3 --instrumental-prefix AUTO

# More examples:
# Input: "MySong_v2.mp3" → Auto-finds: "MySong_instrumental.mp3"
# Input: "Track_Final.mp3" → Auto-finds: "Track_Inst.mp3"
# Input: "song.mp3" → Auto-finds: "song instrumental.wav"

# AUTO mode searches the same directory and finds the closest match by name similarity
# Requires at least 30% similarity to avoid false matches
# Use -v to see similarity scores for all candidates
monkeyplug -i song.mp3 -o song_clean.mp3 --instrumental-prefix AUTO -v
```

### Custom Profanity Lists

```bash
# Use custom text file (pipe-delimited: word|replacement)
monkeyplug -i podcast.mp3 -o podcast_clean.mp3 -w custom_swears.txt

# Use custom JSON file
monkeyplug -i podcast.mp3 -o podcast_clean.mp3 -w custom_swears.json

# Combine built-in list with custom additions
# Custom words are merged with built-in profanity list
monkeyplug -i podcast.mp3 -o podcast_clean.mp3 -w additional_words.json
```

### Speech Recognition Mode Selection

```bash
# Use Groq API (default, fastest)
monkeyplug -i audio.mp3 -o clean.mp3

# Use local Whisper model
monkeyplug -i audio.mp3 -o clean.mp3 -m whisper

# Use Vosk API
monkeyplug -i audio.mp3 -o clean.mp3 -m vosk
```

### Padding and Timing Control

```bash
# Add padding around profanity for smoother transitions
monkeyplug -i song.mp3 -o clean.mp3 --pad-milliseconds 100

# Different pre and post padding
monkeyplug -i song.mp3 -o clean.mp3 --pad-milliseconds-pre 50 --pad-milliseconds-post 100
```

### Beep Mode

```bash
# Use beep instead of silence
monkeyplug -i audio.mp3 -o clean.mp3 -b

# Customize beep frequency and mix
monkeyplug -i audio.mp3 -o clean.mp3 -b -z 1000 --beep-mix-normalize
```

## Contributing

If you'd like to help improve monkeyplug, pull requests will be welcomed!

## Authors

* **Seth Grover** - *Initial work* - [mmguero](https://github.com/mmguero)

## License

This project is licensed under the BSD 3-Clause License - see the [LICENSE](LICENSE) file for details.
