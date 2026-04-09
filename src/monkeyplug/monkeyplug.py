#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import base64
import errno
import importlib
import importlib.metadata
import importlib.util
import json
import mmguero
import mutagen
import os
import pathlib
import glob
import requests
import shutil
import string
import sys
import threading
import time
import wave
from tqdm import tqdm

from urllib.parse import urlparse
from itertools import tee

###################################################################################################
CHANNELS_REPLACER = 'CHANNELS'
SAMPLE_RATE_REPLACER = 'SAMPLE'
BIT_RATE_REPLACER = 'BITRATE'
VORBIS_QSCALE_REPLACER = 'QSCALE'
AUDIO_DEFAULT_PARAMS_BY_FORMAT = {
    "flac": ["-c:a", "flac", "-ar", SAMPLE_RATE_REPLACER, "-ac", CHANNELS_REPLACER],
    "m4a": ["-c:a", "aac", "-b:a", BIT_RATE_REPLACER, "-ar", SAMPLE_RATE_REPLACER, "-ac", CHANNELS_REPLACER],
    "aac": ["-c:a", "aac", "-b:a", BIT_RATE_REPLACER, "-ar", SAMPLE_RATE_REPLACER, "-ac", CHANNELS_REPLACER],
    "mp3": ["-c:a", "libmp3lame", "-b:a", BIT_RATE_REPLACER, "-ar", SAMPLE_RATE_REPLACER, "-ac", CHANNELS_REPLACER],
    "ogg": [
        "-c:a",
        "libvorbis",
        "-qscale:a",
        VORBIS_QSCALE_REPLACER,
        "-ar",
        SAMPLE_RATE_REPLACER,
        "-ac",
        CHANNELS_REPLACER,
    ],
    "opus": ["-c:a", "libopus", "-b:a", BIT_RATE_REPLACER, "-ar", SAMPLE_RATE_REPLACER, "-ac", CHANNELS_REPLACER],
    "ac3": ["-c:a", "ac3", "-b:a", BIT_RATE_REPLACER, "-ar", SAMPLE_RATE_REPLACER, "-ac", CHANNELS_REPLACER],
    "wav": ["-c:a", "pcm_s16le", "-ar", SAMPLE_RATE_REPLACER, "-ac", CHANNELS_REPLACER],
}
AUDIO_CODEC_TO_FORMAT = {
    "aac": "m4a",
    "ac3": "ac3",
    "flac": "flac",
    "mp3": "mp3",
    "opus": "opus",
    "vorbis": "ogg",
    "pcm_s16le": "wav",
}

AUDIO_DEFAULT_FORMAT = "mp3"
AUDIO_DEFAULT_CHANNELS = 2
AUDIO_DEFAULT_SAMPLE_RATE = 48000
AUDIO_DEFAULT_BIT_RATE = "256K"
AUDIO_DEFAULT_VORBIS_QSCALE = 5
AUDIO_MATCH_FORMAT = "MATCH"
AUDIO_INTERMEDIATE_PARAMS = ["-c:a", "pcm_s16le", "-ac", "1", "-ar", "16000"]
AUDIO_DEFAULT_WAV_FRAMES_CHUNK = 8000
BEEP_HERTZ_DEFAULT = 1000
BEEP_MIX_NORMALIZE_DEFAULT = False
BEEP_AUDIO_WEIGHT_DEFAULT = 1
BEEP_SINE_WEIGHT_DEFAULT = 1
BEEP_DROPOUT_TRANSITION_DEFAULT = 0
SWEARS_FILENAME_DEFAULT = 'swears.txt'
MUTAGEN_METADATA_TAGS = ['encodedby', 'comment']
MUTAGEN_METADATA_TAG_VALUE = u'monkeyplug'
SPEECH_REC_MODE_VOSK = "vosk"
SPEECH_REC_MODE_WHISPER = "whisper"
SPEECH_REC_MODE_GROQ = "groq"
DEFAULT_SPEECH_REC_MODE = os.getenv("MONKEYPLUG_MODE", SPEECH_REC_MODE_GROQ)
DEFAULT_VOSK_MODEL_DIR = os.getenv(
    "VOSK_MODEL_DIR", os.path.join(os.path.join(os.path.join(os.path.expanduser("~"), '.cache'), 'vosk'))
)
DEFAULT_WHISPER_MODEL_DIR = os.getenv(
    "WHISPER_MODEL_DIR", os.path.join(os.path.join(os.path.join(os.path.expanduser("~"), '.cache'), 'whisper'))
)
DEFAULT_WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL_NAME", "small.en")
DEFAULT_TORCH_THREADS = 0

AI_DETECT_PROMPT_DEFAULT = (
    "You are a profanity detection assistant for audio content. "
    "Given a numbered transcript with timestamps, identify all words that are profane, vulgar, or offensive. "
    "Return each word's index number, the word itself, and its timestamps. "
    "Consider context — some words are profane in one context but not another."
)

AI_DETECT_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string", "description": "Brief explanation of detection decisions"},
        "profane_words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "Word index in transcript"},
                    "word": {"type": "string"},
                    "start": {"type": "number"},
                    "end": {"type": "number"}
                },
                "required": ["index", "word", "start", "end"],
                "additionalProperties": False
            }
        }
    },
    "required": ["reasoning", "profane_words"],
    "additionalProperties": False
}

UNIFY_ALBUM_PROMPT_DEFAULT = (
    "You are a music metadata expert. Given a list of songs with their filenames, "
    "titles, and current album names, determine the correct unified album name and "
    "assign track numbers to each song. Consider the existing album name guesses and "
    "song titles to infer the real album. Return track numbers in the order the songs "
    "should appear on the album."
)

UNIFY_ALBUM_RENAME_PROMPT_DEFAULT = (
    "You are a music file naming expert. Suggest clean, consistent filenames for each track. "
    "Use format: 'XX - Song Name' where XX is the track number with leading zero if needed. "
    "Keep only essential information, remove extra words like 'feat', 'explicit', etc. "
    "Return the suggested filename WITHOUT the file extension."
)

UNIFY_ALBUM_SCHEMA = {
    "type": "object",
    "properties": {
        "unified_album": {"type": "string", "description": "The unified album name"},
        "tracks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "track_number": {"type": "integer"},
                    "album_name": {"type": "string"},
                    "suggested_name": {"type": "string", "description": "Suggested filename without extension"}
                },
                "required": ["filename", "track_number", "album_name", "suggested_name"],
                "additionalProperties": False
            }
        }
    },
    "required": ["unified_album", "tracks"],
    "additionalProperties": False
}

###################################################################################################
# Determine script_path and script_name in a way that works both as module and direct execution
try:
    # This works when running as a module
    script_name = 'monkeyplug.py'
    script_path = os.path.dirname(os.path.realpath(__file__))
except (NameError, TypeError):
    # Fallback for edge cases
    script_name = 'monkeyplug.py'
    script_path = os.path.dirname(os.path.realpath(sys.argv[0])) if sys.argv and sys.argv[0] else os.getcwd()


# thanks https://docs.python.org/3/library/itertools.html#recipes
def pairwise(iterable):
    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)


def scrubword(value):
    return str(value).lower().replace("’", "'").lower().strip(string.punctuation)


###################################################################################################
# download to file
def DownloadToFile(url, local_filename=None, chunk_bytes=4096, debug=False):
    tmpDownloadedFileSpec = local_filename if local_filename else os.path.basename(urlparse(url).path)
    r = requests.get(url, stream=True, allow_redirects=True)
    with open(tmpDownloadedFileSpec, "wb") as f:
        for chunk in r.iter_content(chunk_size=chunk_bytes):
            if chunk:
                f.write(chunk)
    fExists = os.path.isfile(tmpDownloadedFileSpec)
    fSize = os.path.getsize(tmpDownloadedFileSpec)
    if debug:
        mmguero.eprint(
            f"Download of {url} to {tmpDownloadedFileSpec} {'succeeded' if fExists else 'failed'} ({mmguero.size_human_format(fSize)})"
        )

    if fExists and (fSize > 0):
        return tmpDownloadedFileSpec
    else:
        if fExists:
            os.remove(tmpDownloadedFileSpec)
        return None


###################################################################################################
# Get tag from file to indicate monkeyplug has already been set
def GetMonkeyplugTagged(local_filename, debug=False):
    result = False
    if os.path.isfile(local_filename):
        mut = mutagen.File(local_filename, easy=True)
        if debug:
            mmguero.eprint(f'Tags of {local_filename}: {mut}')
        if hasattr(mut, 'get'):
            for tag in MUTAGEN_METADATA_TAGS:
                try:
                    if MUTAGEN_METADATA_TAG_VALUE in mmguero.get_iterable(mut.get(tag, default=())):
                        result = True
                        break
                except Exception as e:
                    if debug:
                        mmguero.eprint(e)
    return result


###################################################################################################
# Set tag to file to indicate monkeyplug has worked its magic
def SetMonkeyplugTag(local_filename, debug=False):
    result = False
    if os.path.isfile(local_filename):
        mut = mutagen.File(local_filename, easy=True)
        if debug:
            mmguero.eprint(f'Tags of {local_filename} before: {mut}')
        if hasattr(mut, '__setitem__'):
            for tag in MUTAGEN_METADATA_TAGS:
                try:
                    mut[tag] = MUTAGEN_METADATA_TAG_VALUE
                    result = True
                    break
                except Exception as e:
                    if debug:
                        mmguero.eprint(e)
            if result:
                try:
                    mut.save(local_filename)
                except Exception as e:
                    result = False
                    mmguero.eprint(e)
            if debug:
                mmguero.eprint(f'Tags of {local_filename} after: {mut}')

    return result


###################################################################################################
# Read metadata from audio files for album unification
def _read_metadata_from_files(file_paths, debug=False):
    """Read title and album metadata from audio files using mutagen.

    Args:
        file_paths: List of audio file paths
        debug: Enable debug output

    Returns:
        List of dicts with 'filename', 'title', 'album' keys
    """
    import mutagen
    metadata_list = []

    for filepath in file_paths:
        basename = os.path.basename(filepath)
        try:
            mut = mutagen.File(filepath, easy=True)
            if mut is None:
                if debug:
                    mmguero.eprint(f"Could not read metadata from {basename}")
                metadata_list.append({'filename': basename, 'title': '', 'album': ''})
                continue

            # Handle different tag formats (MP3 ID3, MP4, FLAC, etc.)
            title = ''
            album = ''

            # Try common tag keys
            for key in ['title', 'TIT2', '\xa9nam']:  # title, ID3v2.4, MP4
                if key in mut:
                    value = mut[key]
                    if isinstance(value, list):
                        title = str(value[0]) if value else ''
                    else:
                        title = str(value)
                    break

            for key in ['album', 'TALB', '\xa9alb']:  # album, ID3v2.4, MP4
                if key in mut:
                    value = mut[key]
                    if isinstance(value, list):
                        album = str(value[0]) if value else ''
                    else:
                        album = str(value)
                    break

            metadata_list.append({
                'filename': basename,
                'title': title,
                'album': album
            })

            if debug:
                mmguero.eprint(f"{basename}: title='{title}', album='{album}'")

        except Exception as e:
            if debug:
                mmguero.eprint(f"Error reading metadata from {basename}: {e}")
            metadata_list.append({'filename': basename, 'title': '', 'album': ''})

    return metadata_list


###################################################################################################
# Unify album metadata using Groq AI
def _unify_album_metadata(file_paths, groq_api_key, model, prompt, rename_prompt=None, spotify_tracks=None, debug=False):
    """Use Groq AI to unify album metadata and assign track numbers.

    Args:
        file_paths: List of audio file paths
        groq_api_key: Groq API key for authentication
        model: AI model name (e.g., "openai/gpt-oss-120b")
        prompt: System prompt for the AI
        rename_prompt: Optional prompt for renaming (if provided, adds suggested_name to response)
        spotify_tracks: Optional list of track names from Spotify for accurate ordering
        debug: Enable debug output

    Returns:
        Dict with 'unified_album' (str) and 'tracks' (list of dicts with
        'filename', 'track_number', 'album_name', optionally 'suggested_name')

    Raises:
        ValueError: If API key is missing
        Exception: If API call fails
    """
    import requests
    import time

    if not groq_api_key:
        raise ValueError("Groq API key required for album unification")

    # Read metadata from all files
    if debug:
        mmguero.eprint("Reading metadata from files...")
    metadata_list = _read_metadata_from_files(file_paths, debug=debug)

    # Build input for AI
    input_text = json.dumps(metadata_list, indent=2, ensure_ascii=False)

    # Build system prompt (add rename and Spotify instructions if needed)
    system_prompt = prompt
    if rename_prompt:
        system_prompt = f"{prompt}\n\n{rename_prompt}"
    if spotify_tracks:
        # Add Spotify track listing to guide accurate ordering
        tracks_json = json.dumps(spotify_tracks, ensure_ascii=False)
        system_prompt = f"{system_prompt}\n\nOfficial track listing from Spotify: {tracks_json}"
        if debug:
            mmguero.eprint(f"Provided {len(spotify_tracks)} Spotify tracks for accurate ordering")

    # API call with retry logic
    max_retries = 3
    retry_delay = 1

    for attempt in range(max_retries):
        try:
            if debug:
                mmguero.eprint(f"Calling Groq API (attempt {attempt + 1}/{max_retries})...")

            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": input_text},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "album_unification",
                            "strict": True,
                            "schema": UNIFY_ALBUM_SCHEMA,
                        }
                    }
                },
                timeout=120,
            )

            # Handle rate limiting
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    if debug:
                        mmguero.eprint(f"Rate limited, retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                raise Exception("Album unification rate limit exceeded")

            if response.status_code == 401:
                raise Exception("Invalid Groq API key for album unification")

            response.raise_for_status()

            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            parsed = json.loads(content)

            if debug:
                mmguero.eprint(f"AI unification response: {content}")

            return parsed

        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                if debug:
                    mmguero.eprint(f"Request timed out, retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                raise Exception("Album unification request timed out")

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                if debug:
                    mmguero.eprint(f"Request failed: {e}, retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                raise Exception(f"Album unification request failed: {e}")

    raise Exception("Album unification failed after maximum retries")


###################################################################################################
# Apply unified metadata to audio files
def _apply_unified_metadata(file_paths, unified_result, debug=False):
    """Apply unified album name and track numbers to audio files.

    Args:
        file_paths: List of audio file paths (order must match input)
        unified_result: Dict from _unify_album_metadata with 'unified_album' and 'tracks'
        debug: Enable debug output

    Returns:
        int: Number of files successfully updated
    """
    import mutagen

    # Build lookup by filename (only need track numbers, use unified_album for all)
    track_info = {}
    for track in unified_result.get('tracks', []):
        track_info[track['filename']] = track['track_number']

    unified_album = unified_result.get('unified_album', '')
    success_count = 0

    for filepath in file_paths:
        basename = os.path.basename(filepath)
        if basename not in track_info:
            if debug:
                mmguero.eprint(f"Warning: No track info for {basename}")
            continue

        track_number = track_info[basename]

        try:
            ext = os.path.splitext(filepath)[1].lower()

            if ext == '.mp3':
                # MP3 with ID3 tags
                from mutagen.mp3 import MP3
                from mutagen.id3 import ID3, TALB, TRCK

                audio = MP3(filepath)
                if audio.tags is None:
                    audio.tags = ID3()

                # Update or add album tag (always use unified_album)
                audio.tags.delall('TALB')
                audio.tags.add(TALB(encoding=3, text=unified_album))

                # Update or add track number tag
                audio.tags.delall('TRCK')
                audio.tags.add(TRCK(encoding=3, text=str(track_number)))

                audio.save(v2_version=3)
                success_count += 1

                if debug:
                    mmguero.eprint(f"Updated {basename}: album='{unified_album}', track={track_number}")

            else:
                # Other formats using easy mode
                mut = mutagen.File(filepath, easy=True)
                if mut is not None:
                    if 'album' in mut:
                        mut['album'] = unified_album
                    if 'tracknumber' in mut:
                        mut['tracknumber'] = str(track_number)

                    mut.save()
                    success_count += 1

                    if debug:
                        mmguero.eprint(f"Updated {basename}: album='{unified_album}', track={track_number}")

        except Exception as e:
            mmguero.eprint(f"Failed to update {basename}: {e}")

    return success_count


###################################################################################################
# Apply smart renaming to audio files
def _apply_renames(file_paths, unified_result, rename_prompt, debug=False):
    """Rename files based on AI-suggested names.

    Args:
        file_paths: List of audio file paths
        unified_result: Dict with 'tracks' containing 'filename' and 'suggested_name'
        rename_prompt: The rename prompt that was used (None if renaming not requested)
        debug: Enable debug output

    Returns:
        int: Number of files successfully renamed
    """
    import shutil

    # Only rename if the flag was actually passed
    if rename_prompt is None:
        if debug:
            mmguero.eprint("Rename not requested (--auto-rename not passed), skipping rename")
        return 0

    # Build lookup by filename
    rename_map = {}
    for track in unified_result.get('tracks', []):
        suggested = track.get('suggested_name', '').strip()
        if suggested:  # Only add if not empty
            rename_map[track['filename']] = suggested

    if not rename_map:
        if debug:
            mmguero.eprint("No suggested names provided by AI, skipping rename")
        return 0

    success_count = 0

    for filepath in file_paths:
        basename = os.path.basename(filepath)
        if basename not in rename_map:
            continue

        suggested_name = rename_map[basename]

        # Get directory and extension
        dirname = os.path.dirname(filepath)
        ext = os.path.splitext(filepath)[1]

        # Build new filename
        new_name = f"{suggested_name}{ext}"
        new_path = os.path.join(dirname, new_name)

        # Skip if same name
        if new_path == filepath:
            if debug:
                mmguero.eprint(f"Skipping rename (same name): {basename}")
            continue

        # Check if target already exists
        if os.path.exists(new_path):
            mmguero.eprint(f"Cannot rename {basename} to {new_name}: target already exists")
            continue

        try:
            shutil.move(filepath, new_path)
            success_count += 1
            if debug:
                mmguero.eprint(f"Renamed: {basename} → {new_name}")
        except Exception as e:
            mmguero.eprint(f"Failed to rename {basename}: {e}")

    return success_count


###################################################################################################
# Spotify integration for album art and track listings
def _search_spotify_album(album_name, debug=False):
    """Search for Spotify album URL using DuckDuckGo.

    Args:
        album_name: The album name to search for
        debug: Enable debug output

    Returns:
        str: Spotify album URL or None if not found
    """
    try:
        from ddgs import DDGS
    except ImportError:
        if debug:
            mmguero.eprint("duckduckgo-search not installed, skipping Spotify search")
        return None

    query = f"site:spotify.com {album_name} album"

    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=1)
            for result in results:
                url = result.get('href', '')
                if url and 'spotify.com/albu' in url:
                    if debug:
                        mmguero.eprint(f"Found Spotify album: {url}")
                    return url
    except Exception as e:
        if debug:
            mmguero.eprint(f"Spotify search failed: {e}")

    return None


def _get_spotify_album_info(spotify_url, debug=False):
    """Get album info from Spotify including cover art and track listing.

    Args:
        spotify_url: Spotify album URL
        debug: Enable debug output

    Returns:
        dict: {'images': [urls], 'tracks': [track names]} or None if failed
    """
    try:
        from spotify_scraper import SpotifyClient
    except ImportError:
        if debug:
            mmguero.eprint("spotify-scraper not installed, skipping Spotify info")
        return None

    try:
        client = SpotifyClient()
        album = client.get_album_info(spotify_url)

        # Extract cover art URLs (prefer 640x640)
        images = []
        for img in album.get('images', []):
            if img.get('width', 0) >= 640:
                images.append(img['url'])

        # Fallback to any image
        if not images and album.get('images'):
            images.append(album['images'][0]['url'])

        # Extract track names
        tracks = []
        for track in album.get('tracks', []):
            track_name = track.get('name', '')
            if track_name:
                tracks.append(track_name)

        if debug:
            mmguero.eprint(f"Spotify album: {album.get('name', 'Unknown')}")
            mmguero.eprint(f"  Found {len(tracks)} tracks, {len(images)} cover art images")

        return {'images': images, 'tracks': tracks}

    except Exception as e:
        if debug:
            mmguero.eprint(f"Failed to get Spotify album info: {e}")
        return None


def _download_cover_art(image_url, debug=False):
    """Download cover art image from URL.

    Args:
        image_url: URL of the cover art image
        debug: Enable debug output

    Returns:
        bytes: Image data or None if failed
    """
    try:
        response = requests.get(image_url, timeout=10)
        if response.status_code == 200:
            if debug:
                mmguero.eprint(f"Downloaded cover art: {len(response.content)} bytes")
            return response.content
        else:
            if debug:
                mmguero.eprint(f"Failed to download cover art: HTTP {response.status_code}")
    except Exception as e:
        if debug:
            mmguero.eprint(f"Failed to download cover art: {e}")

    return None


def _apply_cover_art_to_files(file_paths, image_data, debug=False):
    """Apply cover art to all audio files.

    Args:
        file_paths: List of audio file paths
        image_data: Image bytes to embed as cover art
        debug: Enable debug output

    Returns:
        int: Number of files successfully updated
    """
    import mutagen

    success_count = 0

    for filepath in file_paths:
        try:
            ext = os.path.splitext(filepath)[1].lower()

            if ext == '.mp3':
                # MP3 with ID3 tags
                from mutagen.mp3 import MP3
                from mutagen.id3 import ID3, APIC

                audio = MP3(filepath)
                if audio.tags is None:
                    audio.tags = ID3()

                # Remove existing cover art
                audio.tags.delall('APIC')

                # Add new cover art
                audio.tags.add(APIC(
                    encoding=3,
                    mime='image/jpeg',
                    type=3,  # 3 = cover front
                    desc='Cover',
                    data=image_data
                ))

                audio.save(v2_version=3)
                success_count += 1

                if debug:
                    mmguero.eprint(f"Applied cover art: {os.path.basename(filepath)}")

        except Exception as e:
            mmguero.eprint(f"Failed to apply cover art to {os.path.basename(filepath)}: {e}")

    return success_count


###################################################################################################
# Run album unification process
def _run_album_unification(input_path, output_path, config, rename_prompt=None, use_spotify=None, debug=False):
    """Run the album unification process on a folder of files.

    Args:
        input_path: Input file or pattern (for wildcard mode)
        output_path: Output file or pattern (for wildcard mode)
        config: Config dict containing unify_album_model and unify_album_prompt
        rename_prompt: Optional prompt for smart renaming (None = no renaming)
        use_spotify: Spotify URL if provided, True to search for album, None/False to disable
        debug: Enable debug output

    Returns:
        str: Status message
    """
    # Load Groq API key
    try:
        from monkeyplug.groq_config import load_groq_api_key
    except ImportError:
        from .groq_config import load_groq_api_key

    groq_api_key = load_groq_api_key(None, debug=debug)
    if not groq_api_key:
        raise ValueError(
            "Groq API key required for album unification. "
            "Provide via --groq-api-key, GROQ_API_KEY env var, ~/.groq/config.json, or ./.groq_key"
        )

    model = config.get("unify_album_model", "openai/gpt-oss-120b")
    prompt = config.get("unify_album_prompt", UNIFY_ALBUM_PROMPT_DEFAULT)

    # Determine files to process
    audio_extensions = ['.mp3', '.mp4', '.m4a', '.wav', '.flac', '.ogg', '.aac', '.wma']

    # Check if input is a directory or wildcard pattern
    if os.path.isdir(input_path):
        # Standalone mode with directory
        mmguero.eprint(f"Scanning directory: {input_path}")
        file_paths = []
        for ext in audio_extensions:
            pattern = os.path.join(input_path, f'*{ext}')
            file_paths.extend(glob.glob(pattern))

        # Also check subdirectories one level deep
        for item in os.listdir(input_path):
            item_path = os.path.join(input_path, item)
            if os.path.isdir(item_path):
                for ext in audio_extensions:
                    pattern = os.path.join(item_path, f'*{ext}')
                    file_paths.extend(glob.glob(pattern))

    elif '*' in input_path or '*' in output_path:
        # Wildcard mode - expand and get matched files
        # In combined mode (processing files), only unify the output files, not the originals
        if '*' in output_path and output_path:
            file_paths = glob.glob(output_path)
        else:
            file_paths = glob.glob(input_path)
    else:
        # Single file mode - get all audio files in same directory
        dirname = os.path.dirname(input_path) or '.'
        file_paths = []
        for ext in audio_extensions:
            pattern = os.path.join(dirname, f'*{ext}')
            file_paths.extend(glob.glob(pattern))

    if not file_paths:
        return "No audio files found for album unification"

    file_paths = sorted(file_paths)
    mmguero.eprint(f"Found {len(file_paths)} audio files for album unification")

    # Call AI to unify album metadata (first pass - gets unified album name)
    unified_result = _unify_album_metadata(
        file_paths, groq_api_key, model, prompt, rename_prompt=rename_prompt, debug=debug
    )

    unified_album = unified_result.get('unified_album', '')
    spotify_info = None  # Will hold Spotify data if fetched

    # If Spotify integration requested, look up official album info
    if use_spotify and unified_album:
        mmguero.eprint("\nSearching Spotify for album info...")

        # Determine Spotify URL (provided directly or search for it)
        if isinstance(use_spotify, str) and use_spotify.startswith('https://'):
            # User provided direct Spotify URL
            spotify_url = use_spotify
            if debug:
                mmguero.eprint(f"Using provided Spotify URL: {spotify_url}")
        else:
            # Search for Spotify album URL
            spotify_url = _search_spotify_album(unified_album, debug=debug)

        if spotify_url:
            # Get Spotify album info (cover art + track listing)
            spotify_info = _get_spotify_album_info(spotify_url, debug=debug)

        if spotify_info:
            mmguero.eprint(f"Found Spotify album with {len(spotify_info.get('tracks', []))} tracks")

            # Second AI pass with Spotify track listing for accurate ordering
            mmguero.eprint("Refining track order with Spotify data...")
            unified_result = _unify_album_metadata(
                file_paths, groq_api_key, model, prompt,
                rename_prompt=rename_prompt,
                spotify_tracks=spotify_info.get('tracks', []),
                debug=debug
            )
        else:
            mmguero.eprint("Could not fetch Spotify info, using AI results only")

    # Display results
    unified_album = unified_result.get('unified_album', '')
    mmguero.eprint(f"\nUnified Album: {unified_album}")
    mmguero.eprint("Track Order:")
    for track in unified_result.get('tracks', []):
        line = f"  {track['track_number']}: {track['filename']}"
        suggested = track.get('suggested_name', '').strip()
        if suggested:
            line += f" → {suggested}"
        mmguero.eprint(line)

    # Apply metadata changes
    success_count = _apply_unified_metadata(file_paths, unified_result, debug=debug)

    # Apply Spotify cover art if available
    cover_art_count = 0
    if use_spotify and spotify_info and spotify_info.get('images'):
        # Download first available cover art (prefer highest resolution)
        for image_url in spotify_info['images'][:1]:
            image_data = _download_cover_art(image_url, debug=debug)
            if image_data:
                cover_art_count = _apply_cover_art_to_files(file_paths, image_data, debug=debug)
                break

    # Apply renames if requested
    rename_count = _apply_renames(file_paths, unified_result, rename_prompt, debug=debug)

    # Build result message
    result = f"Album unification complete: {success_count}/{len(file_paths)} files updated"
    if cover_art_count > 0:
        result += f", {cover_art_count} files updated with cover art"
    if rename_prompt:
        result += f", {rename_count} files renamed"

    return result



###################################################################################################
# get stream codecs from an input filename
# e.g. result: {'video': {'h264'}, 'audio': {'eac3'}, 'subtitle': {'subrip'}}
def GetCodecs(local_filename, debug=False):
    result = {}
    if os.path.isfile(local_filename):
        ffprobeCmd = [
            'ffprobe',
            '-v',
            'quiet',
            '-print_format',
            'json',
            '-show_format',
            '-show_streams',
            local_filename,
        ]
        ffprobeResult, ffprobeOutput = mmguero.run_process(ffprobeCmd, stdout=True, stderr=False, debug=debug)
        if ffprobeResult == 0:
            ffprobeOutput = mmguero.load_str_if_json(' '.join(ffprobeOutput))
            if 'streams' in ffprobeOutput:
                for stream in ffprobeOutput['streams']:
                    if 'codec_name' in stream and 'codec_type' in stream:
                        cType = stream['codec_type'].lower()
                        cValue = stream['codec_name'].lower()
                        if cType in result:
                            result[cType].add(cValue)
                        else:
                            result[cType] = set([cValue])
            result['format'] = mmguero.deep_get(ffprobeOutput, ['format', 'format_name'])
            if isinstance(result['format'], str):
                result['format'] = result['format'].split(',')
        else:
            mmguero.eprint(' '.join(mmguero.flatten(ffprobeCmd)))
            mmguero.eprint(ffprobeResult)
            mmguero.eprint(ffprobeOutput)
            raise ValueError(f"Could not analyze {local_filename}")

    return result


###################################################################################################
class _SmoothProgressTicker:
    """Background thread that smoothly advances a tqdm bar based on elapsed time.

    Used when historical timing data allows estimating step durations.
    The bar advances linearly within each step's estimated range, clamped
    so it never overshoots. When the step completes, stop() snaps to actual.
    """

    def __init__(self, bar):
        self._bar = bar
        self._cumulative = 0.0  # Position where current step begins
        self._step_estimate = 0.0  # Estimated seconds for current step
        self._step_start = 0.0  # time.time() when step started
        self._stop_event = threading.Event()
        self._thread = None

    def start(self, cumulative, step_estimated_seconds):
        """Begin ticking for a new step."""
        self.stop()  # Stop any previous tick
        self._cumulative = cumulative
        self._step_estimate = step_estimated_seconds
        self._step_start = time.time()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._tick, daemon=True)
        self._thread.start()

    def _tick(self):
        while not self._stop_event.is_set():
            try:
                elapsed = time.time() - self._step_start
                position = self._cumulative + min(elapsed, self._step_estimate)
                # Never exceed the bar's total
                if self._bar.total is not None:
                    position = min(position, self._bar.total)
                self._bar.n = position
                self._bar.refresh()
            except (TypeError, ValueError, AttributeError):
                break  # Bar was closed externally
            self._stop_event.wait(0.25)

    def stop(self):
        """Stop the ticker and return actual elapsed seconds for this step."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        if self._step_start > 0:
            return time.time() - self._step_start
        return 0.0

    def adjust_total(self, delta):
        """Adjust the bar's total by delta (e.g., remove an unused step estimate)."""
        if self._bar.total is not None:
            self._bar.total = max(self._bar.total + delta, self._bar.n)


#################################################################################
class Plugger(object):
    debug = False
    inputFileSpec = ""
    inputCodecs = {}
    inputFileParts = None
    outputFileSpec = ""
    outputAudioFileFormat = ""
    outputVideoFileFormat = ""
    outputJson = ""
    tmpDownloadedFileSpec = ""
    swearsFileSpec = ""
    swearsMap = {}
    wordList = []
    naughtyWordList = []
    # for beep and mute
    muteTimeList = []
    # for beep only
    sineTimeList = []
    beepDelayList = []
    padSecPre = 0.0
    padSecPost = 0.0
    beep = False
    beepHertz = BEEP_HERTZ_DEFAULT
    beepMixNormalize = BEEP_MIX_NORMALIZE_DEFAULT
    beepAudioWeight = BEEP_AUDIO_WEIGHT_DEFAULT
    beepSineWeight = BEEP_SINE_WEIGHT_DEFAULT
    beepDropTransition = BEEP_DROPOUT_TRANSITION_DEFAULT
    forceDespiteTag = False
    aParams = None
    tags = None
    # for instrumental splicing
    instrumentalFileSpec = ""
    instrumentalMode = False
    instrumentalSegments = []  # List of (start, end) tuples for profanity sections

    ######## init #################################################################
    def __init__(
        self,
        iFileSpec,
        oFileSpec,
        oAudioFileFormat,
        iSwearsFileSpec,
        outputJson,
        inputTranscript=None,
        saveTranscript=False,
        forceRetranscribe=False,
        aParams=None,
        aChannels=AUDIO_DEFAULT_CHANNELS,
        aSampleRate=AUDIO_DEFAULT_SAMPLE_RATE,
        aBitRate=AUDIO_DEFAULT_BIT_RATE,
        aVorbisQscale=AUDIO_DEFAULT_VORBIS_QSCALE,
        padMsecPre=0,
        padMsecPost=0,
        beep=False,
        beepHertz=BEEP_HERTZ_DEFAULT,
        beepMixNormalize=BEEP_MIX_NORMALIZE_DEFAULT,
        beepAudioWeight=BEEP_AUDIO_WEIGHT_DEFAULT,
        beepSineWeight=BEEP_SINE_WEIGHT_DEFAULT,
        beepDropTransition=BEEP_DROPOUT_TRANSITION_DEFAULT,
        force=False,
        dbug=False,
        instrumentalFileSpec=None,
        showWords="clean",
        detectMode="list",
        groqApiKey=None,
        aiDetectModel="openai/gpt-oss-20b",
        aiDetectPrompt=AI_DETECT_PROMPT_DEFAULT,
        disableMetadata=False,
    ):
        self.debug = dbug
        self.outputJson = outputJson
        self.inputTranscript = inputTranscript
        self.saveTranscript = saveTranscript
        self.forceDespiteTag = force
        self.beep = beep
        self.beepHertz = beepHertz
        self.beepMixNormalize = beepMixNormalize
        self.beepAudioWeight = beepAudioWeight
        self.beepSineWeight = beepSineWeight
        self.beepDropTransition = beepDropTransition
        self.padSecPre = padMsecPre / 1000.0
        self.padSecPost = padMsecPost / 1000.0
        self.showWords = showWords
        self.detectMode = detectMode
        self.groqApiKey = groqApiKey
        self.aiDetectModel = aiDetectModel
        self.aiDetectPrompt = aiDetectPrompt
        self.disableMetadata = disableMetadata
        self.shazamMetadata = {}

        # determine input file name, or download and save file
        if (iFileSpec is not None) and os.path.isfile(iFileSpec):
            self.inputFileSpec = iFileSpec
        elif iFileSpec.lower().startswith("http"):
            self.tmpDownloadedFileSpec = DownloadToFile(iFileSpec)
            if (self.tmpDownloadedFileSpec is not None) and os.path.isfile(self.tmpDownloadedFileSpec):
                self.inputFileSpec = self.tmpDownloadedFileSpec
            else:
                raise IOError(errno.ENOENT, os.strerror(errno.ENOENT), iFileSpec)
        else:
            raise IOError(errno.ENOENT, os.strerror(errno.ENOENT), iFileSpec)

        # input file should exist locally by now
        if os.path.isfile(self.inputFileSpec):
            self.inputFileParts = os.path.splitext(self.inputFileSpec)
            self.inputCodecs = GetCodecs(self.inputFileSpec)
            inputFormat = next(
                iter([x for x in self.inputCodecs.get('format', None) if x in AUDIO_DEFAULT_PARAMS_BY_FORMAT]), None
            )
        else:
            raise IOError(errno.ENOENT, os.strerror(errno.ENOENT), self.inputFileSpec)

        # determine output file name (either specified or based on input filename)
        self.outputFileSpec = oFileSpec if oFileSpec else self.inputFileParts[0] + "_clean"
        if self.outputFileSpec:
            outParts = os.path.splitext(self.outputFileSpec)
            if (
                ((not oAudioFileFormat) or (str(oAudioFileFormat).upper() == AUDIO_MATCH_FORMAT))
                and oFileSpec
                and (len(outParts) > 1)
                and outParts[1]
            ):
                oAudioFileFormat = outParts[1]

        if str(oAudioFileFormat).upper() == AUDIO_MATCH_FORMAT:
            # output format not specified, base on input filename matching extension (or codec)
            if self.inputFileParts[1] in AUDIO_DEFAULT_PARAMS_BY_FORMAT:
                self.outputFileSpec = self.outputFileSpec + self.inputFileParts[1]
            elif str(inputFormat).lower() in AUDIO_DEFAULT_PARAMS_BY_FORMAT:
                self.outputFileSpec = self.outputFileSpec + '.' + inputFormat.lower()
            else:
                for codec in mmguero.get_iterable(self.inputCodecs.get('audio', [])):
                    if codec.lower() in AUDIO_CODEC_TO_FORMAT:
                        self.outputFileSpec = self.outputFileSpec + '.' + AUDIO_CODEC_TO_FORMAT[codec.lower()]
                        break

        elif oAudioFileFormat:
            # output filename not specified, base on input filename with specified format
            newSuffix = '.' + oAudioFileFormat.lower().lstrip('.')
            self.outputFileSpec = mmguero.remove_suffix(self.outputFileSpec, newSuffix) + newSuffix

        else:
            # can't determine what output file audio format should be
            raise ValueError("Output file audio format unspecified")

        # determine output file extension if it's not already obvious
        outParts = os.path.splitext(self.outputFileSpec)
        self.outputAudioFileFormat = outParts[1].lower().lstrip('.')

        if (not self.outputAudioFileFormat) or (
            (not aParams) and (self.outputAudioFileFormat not in AUDIO_DEFAULT_PARAMS_BY_FORMAT)
        ):
            raise ValueError("Output file audio format unspecified or unsupported")
        elif not aParams:
            # we're using ffmpeg encoding params based on output file format
            self.aParams = AUDIO_DEFAULT_PARAMS_BY_FORMAT[self.outputAudioFileFormat]
        else:
            # they specified custom ffmpeg encoding params
            self.aParams = aParams
            if self.aParams.startswith("base64:"):
                self.aParams = base64.b64decode(self.aParams[7:]).decode("utf-8")
            self.aParams = self.aParams.split(' ')
        self.aParams = [
            {
                CHANNELS_REPLACER: str(aChannels),
                SAMPLE_RATE_REPLACER: str(aSampleRate),
                BIT_RATE_REPLACER: str(aBitRate),
                VORBIS_QSCALE_REPLACER: str(aVorbisQscale),
            }.get(aParam, aParam)
            for aParam in self.aParams
        ]

        # if we're actually just replacing the audio stream(s) inside a video file, the actual output file is still a video file
        self.outputVideoFileFormat = (
            self.inputFileParts[1]
            if (
                (len(mmguero.get_iterable(self.inputCodecs.get('video', []))) > 0)
                and (str(oAudioFileFormat).upper() == AUDIO_MATCH_FORMAT)
            )
            else ''
        )
        if self.outputVideoFileFormat:
            self.outputFileSpec = outParts[0] + self.outputVideoFileFormat

        # create output directory if it doesn't exist
        self._ensure_directory_exists(self.outputFileSpec, "output directory")

        # if output file already exists, remove as we'll be overwriting it anyway
        if os.path.isfile(self.outputFileSpec):
            if self.debug:
                mmguero.eprint(f'Removing existing destination file {self.outputFileSpec}')
            os.remove(self.outputFileSpec)

        # If save-transcript is enabled and no explicit JSON output path, auto-generate one
        if self.saveTranscript and not self.outputJson:
            outputBaseName = os.path.splitext(self.outputFileSpec)[0]
            self.outputJson = outputBaseName + '_transcript.json'
            if self.debug:
                mmguero.eprint(f'Auto-generated transcript output: {self.outputJson}')
        
        # Auto-detect existing transcript for reuse (unless force flag set or explicit input provided)
        if self.saveTranscript and not self.inputTranscript and self.outputJson and not forceRetranscribe:
            if os.path.exists(self.outputJson):
                self.inputTranscript = self.outputJson
                if self.debug:
                    mmguero.eprint(f'Found existing transcript, reusing: {self.inputTranscript}')
        
        # If JSON output is specified, ensure its directory exists too
        if self.outputJson:
            self._ensure_directory_exists(self.outputJson, "JSON output directory")

        # load the swears file (not actually mapping right now, but who knows, speech synthesis maybe someday?)
        self.swearsFileSpec = iSwearsFileSpec if (iSwearsFileSpec is not None) and os.path.isfile(iSwearsFileSpec) else None

        self._load_swears_file()

        # validate instrumental file if provided
        if instrumentalFileSpec:
            if not os.path.isfile(instrumentalFileSpec):
                raise IOError(errno.ENOENT, os.strerror(errno.ENOENT), instrumentalFileSpec)

            # Check duration of instrumental vs original
            # Need to get duration directly from ffprobe since GetCodecs doesn't extract it
            instrumentalDuration = self._get_file_duration(instrumentalFileSpec)
            originalDuration = self._get_file_duration(self.inputFileSpec)

            if instrumentalDuration > 0 and originalDuration > 0:
                if instrumentalDuration < originalDuration:
                    raise ValueError(
                        f"Instrumental file duration ({instrumentalDuration}s) is shorter than "
                        f"original file duration ({originalDuration}s)"
                    )
            elif self.debug:
                mmguero.eprint('Warning: Could not verify file durations')

            self.instrumentalFileSpec = instrumentalFileSpec
            self.instrumentalMode = True
        else:
            self.instrumentalMode = False

        if self.debug:
            mmguero.eprint(f'Input: {self.inputFileSpec}')
            mmguero.eprint(f'Input codec: {self.inputCodecs}')
            mmguero.eprint(f'Output: {self.outputFileSpec}')
            mmguero.eprint(f'Output audio format: {self.outputAudioFileFormat}')
            mmguero.eprint(f'Encode parameters: {self.aParams}')
            mmguero.eprint(f'Profanity file: {self.swearsFileSpec if self.swearsFileSpec else "built-in"}')
            mmguero.eprint(f'Intermediate downloaded file: {self.tmpDownloadedFileSpec}')
            if self.outputJson:
                mmguero.eprint(f'Transcript output: {self.outputJson}')
            if self.inputTranscript:
                mmguero.eprint(f'Input transcript: {self.inputTranscript}')
            mmguero.eprint(f'Beep instead of mute: {self.beep}')
            if self.beep:
                mmguero.eprint(f'Beep hertz: {self.beepHertz}')
                mmguero.eprint(f'Beep mix normalization: {self.beepMixNormalize}')
                mmguero.eprint(f'Beep audio weight: {self.beepAudioWeight}')
                mmguero.eprint(f'Beep sine weight: {self.beepSineWeight}')
                mmguero.eprint(f'Beep dropout transition: {self.beepDropTransition}')
            mmguero.eprint(f'Force despite tags: {self.forceDespiteTag}')
            mmguero.eprint(f'Instrumental mode: {self.instrumentalMode}')
            if self.instrumentalMode:
                mmguero.eprint(f'Instrumental file: {self.instrumentalFileSpec}')

        # Fetch metadata from Shazam if enabled
        self.shazamMetadata = self._fetch_shazam_metadata()
        if self.shazamMetadata and self.debug:
            mmguero.eprint(f'Shazam metadata found:')
            mmguero.eprint(f'  Title: {self.shazamMetadata.get("title")}')
            mmguero.eprint(f'  Artist: {self.shazamMetadata.get("artist")}')
            mmguero.eprint(f'  Album: {self.shazamMetadata.get("album")}')
            mmguero.eprint(f'  Year: {self.shazamMetadata.get("year")}')
            mmguero.eprint(f'  Genre: {self.shazamMetadata.get("genre")}')
            mmguero.eprint(f'  Cover art: {self.shazamMetadata.get("cover_art_url")}')

    ######## del ##################################################################
    def __del__(self):
        # if we downloaded the input file, remove it as well
        if os.path.isfile(self.tmpDownloadedFileSpec):
            os.remove(self.tmpDownloadedFileSpec)

        # Clean up temporary separation files
        if hasattr(self, 'separationCacheDir') and self.separationCacheDir:
            import shutil
            try:
                if os.path.exists(self.separationCacheDir):
                    shutil.rmtree(self.separationCacheDir)
                    if self.debug:
                        mmguero.eprint(f'Cleaned up separation cache: {self.separationCacheDir}')
            except Exception as e:
                if self.debug:
                    mmguero.eprint(f'Warning: Failed to cleanup separation cache: {e}')

    ######## _ensure_directory_exists #############################################
    def _ensure_directory_exists(self, filepath, description="directory"):
        """Ensure the directory for a file path exists, creating it if necessary"""
        directory = os.path.dirname(filepath)
        if directory and not os.path.exists(directory):
            if self.debug:
                mmguero.eprint(f'Creating {description}: {directory}')
            os.makedirs(directory, exist_ok=True)
        return directory

    ######## _get_file_duration ###################################################
    def _get_file_duration(self, filepath):
        """Get the duration of an audio/video file using ffprobe"""
        try:
            ffprobeCmd = [
                'ffprobe',
                '-v',
                'quiet',
                '-print_format',
                'json',
                '-show_entries',
                'format=duration',
                filepath,
            ]
            ffprobeResult, ffprobeOutput = mmguero.run_process(ffprobeCmd, stdout=True, stderr=False, debug=False)
            if ffprobeResult == 0:
                ffprobeData = mmguero.load_str_if_json(' '.join(ffprobeOutput))
                duration_str = mmguero.deep_get(ffprobeData, ['format', 'duration'], '0')
                return float(duration_str)
            else:
                return 0.0
        except Exception as e:
            if self.debug:
                mmguero.eprint(f'Error getting duration for {filepath}: {e}')
            return 0.0

    ######## LoadTranscriptFromFile ##############################################
    def LoadTranscriptFromFile(self):
        """Load pre-generated transcript from JSON file"""
        if not self.inputTranscript:
            return False
        
        if not os.path.isfile(self.inputTranscript):
            raise IOError(errno.ENOENT, os.strerror(errno.ENOENT), self.inputTranscript)
        
        if self.debug:
            mmguero.eprint(f'Loading transcript from: {self.inputTranscript}')
        
        with open(self.inputTranscript, 'r') as f:
            self.wordList = json.load(f)
        
        # Recalculate scrub flags with current swears list
        for word in self.wordList:
            word['scrub'] = scrubword(word.get('word', '')) in self.swearsMap
        
        if self.debug:
            mmguero.eprint(f'Loaded {len(self.wordList)} words from transcript')
            scrubbed_count = sum(1 for w in self.wordList if w.get('scrub', False))
            mmguero.eprint(f'Words to censor with current swear list: {scrubbed_count}')
        
        return True
      
    ######## _load_swears_file ####################################################
    def _load_swears_file(self):
        """Load swears from built-in list first, then from custom text or JSON file if provided"""
        # Load built-in profanity list first
        self._load_builtin_swears()

        # Load custom swears file if provided
        if self.swearsFileSpec:
            # Try to detect and parse JSON first
            is_json = False
            if self.swearsFileSpec.lower().endswith('.json'):
                is_json = True
            else:
                # Try to parse as JSON even without .json extension
                try:
                    with open(self.swearsFileSpec, 'r') as f:
                        content = f.read()
                        json.loads(content)
                        is_json = True
                except (json.JSONDecodeError, ValueError):
                    pass

            if is_json:
                self._load_swears_from_json()
            else:
                self._load_swears_from_text()

            if self.debug:
                mmguero.eprint(f'Loaded {len(self.swearsMap)} profanity entries (built-in + custom from {self.swearsFileSpec})')
        else:
            if self.debug:
                mmguero.eprint(f'Loaded {len(self.swearsMap)} profanity entries from built-in list')

    def _load_builtin_swears(self):
        """Load built-in profanity list from package data"""
        data = None
        error_msgs = []

        # Method 1: Try importlib.resources.files (Python 3.9+)
        try:
            import importlib.resources as resources
            with resources.files('monkeyplug.data').joinpath('profanity_list.json').open('r') as f:
                data = json.load(f)
            if self.debug:
                mmguero.eprint('Loaded profanity list using importlib.resources.files')
        except Exception as e:
            error_msgs.append(f"importlib.resources.files failed: {e}")

        # Method 2: Fallback for older Python versions using pkg_resources
        if data is None:
            try:
                import pkg_resources
                resource_package = 'monkeyplug'
                resource_path = '/'.join(('data', 'profanity_list.json'))
                data = json.loads(pkg_resources.resource_string(resource_package, resource_path).decode('UTF-8'))
                if self.debug:
                    mmguero.eprint('Loaded profanity list using pkg_resources')
            except Exception as e:
                error_msgs.append(f"pkg_resources failed: {e}")

        # Method 3: Last resort - try to find the file relative to this module
        if data is None:
            try:
                module_dir = os.path.dirname(os.path.abspath(__file__))
                data_file = os.path.join(module_dir, 'data', 'profanity_list.json')
                if os.path.exists(data_file):
                    with open(data_file, 'r') as f:
                        data = json.load(f)
                    if self.debug:
                        mmguero.eprint(f'Loaded profanity list from file path: {data_file}')
                else:
                    error_msgs.append(f"File not found at {data_file}")
            except Exception as e:
                error_msgs.append(f"File path fallback failed: {e}")

        # If all methods failed, warn but continue (custom swears file might be provided)
        if data is None:
            if self.debug:
                mmguero.eprint('Could not load built-in profanity list:')
                for msg in error_msgs:
                    mmguero.eprint(f'  {msg}')
            return

        if isinstance(data, list):
            for item in data:
                if isinstance(item, str) and item.strip():
                    self.swearsMap[scrubword(item)] = "*****"
        elif self.debug:
            mmguero.eprint('Built-in profanity list has unexpected format')

    def _load_swears_from_json(self):
        """Load swears from JSON format - simple array of strings

        Format: ["word1", "word2", "word3", ...]
        Example: https://github.com/zautumnz/profane-words/blob/master/words.json
        """
        with open(self.swearsFileSpec, 'r') as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError(f"JSON swears file must contain an array of strings, got {type(data).__name__}")

        for item in data:
            if isinstance(item, str) and item.strip():
                self.swearsMap[scrubword(item)] = "*****"

    def _load_swears_from_text(self):
        """Load swears from pipe-delimited text format (legacy)"""
        lines = []
        with open(self.swearsFileSpec) as f:
            lines = [line.rstrip("\n") for line in f]
        for line in lines:
            lineMap = line.split("|")
            self.swearsMap[scrubword(lineMap[0])] = lineMap[1] if len(lineMap) > 1 else "*****"

    ######## CreateCleanMuteList #################################################
    def CreateCleanMuteList(self):
        smooth = hasattr(self, '_smooth_ticker') and self._smooth_ticker is not None
        cumulative = getattr(self, '_smooth_cumulative', 0.0)
        will_transcribe = getattr(self, '_will_transcribe', False)

        # Start ticker for transcribe step (if applicable)
        if smooth and will_transcribe:
            est = getattr(self, '_smooth_transcribe_est', 0)
            if hasattr(self, '_progress') and self._progress:
                self._progress.set_description("Transcribing")
            self._smooth_ticker.start(cumulative, est)

        transcribe_start = time.time() if will_transcribe else 0
        if not self.LoadTranscriptFromFile():
            self.RecognizeSpeech()

        if will_transcribe:
            actual_transcribe = time.time() - transcribe_start
            if smooth:
                self._smooth_ticker.stop()
                cumulative += actual_transcribe
                self._smooth_cumulative = cumulative
            if hasattr(self, '_step_timings') and self._step_timings is not None:
                self._step_timings['transcribe'] = (actual_transcribe, getattr(self, '_timing_file_duration', 0))

        self.naughtyWordList = [word for word in self.wordList if word["scrub"] is True]

        # AI-based profanity detection (replaces or supplements list)
        if self.detectMode in ("ai", "both"):
            if self.detectMode == "ai":
                # Reset list-based scrub flags — AI decides everything
                for word in self.wordList:
                    word["scrub"] = False
            self._ai_detect_profanity()
            # Rebuild naughtyWordList with AI results
            self.naughtyWordList = [word for word in self.wordList if word["scrub"] is True]

        # Handle auto-generation mode
        if hasattr(self, 'autoGenerateMode') and self.autoGenerateMode and len(self.naughtyWordList) > 0:
            # Create merged profanity segments
            self._create_instrumental_splice_list()

            # Extract, separate, and get instrumental file
            if self.instrumentalSegments:
                try:
                    # Update progress bar for extraction step
                    if hasattr(self, '_progress') and self._progress and not self.debug:
                        if smooth:
                            extract_est = getattr(self, '_smooth_extract_est', 0)
                            self._progress.set_description("Extracting instrumental")
                            self._smooth_ticker.start(cumulative, extract_est)
                        else:
                            self._progress.update(1)
                            self._progress.total = 3
                            self._progress.set_description("Extracting instrumental")

                    extract_start = time.time()
                    self.instrumentalFileSpec = self._create_combined_profanity_file()

                    actual_extract = time.time() - extract_start
                    if smooth:
                        self._smooth_ticker.stop()
                        cumulative += actual_extract
                        self._smooth_cumulative = cumulative
                    if hasattr(self, '_step_timings') and self._step_timings is not None:
                        self._step_timings['extract'] = (actual_extract, getattr(self, '_timing_file_duration', 0))

                    # Update progress after extraction completes (step-based mode)
                    if not smooth and hasattr(self, '_progress') and self._progress and not self.debug:
                        self._progress.update(1)

                    if self.instrumentalFileSpec:
                        self.instrumentalMode = True
                        self._build_instrumental_filters()
                        return []  # Return empty list for muteTimeList
                except Exception as e:
                    # Fallback to mute if generation fails
                    if smooth:
                        self._smooth_ticker.stop()
                    if self.debug:
                        mmguero.eprint(f"Generation failed: {e}, falling back to mute mode")
                    self.instrumentalMode = False
                    return self._create_mute_beep_list()
            else:
                # No instrumental segments — remove extract estimate from smooth bar
                if smooth and hasattr(self, '_progress') and self._progress:
                    extract_est = getattr(self, '_smooth_extract_est', 0)
                    self._smooth_ticker.adjust_total(-extract_est)
                return []

        else:
            # No profanity found in auto mode — remove extract estimate if applicable
            if smooth and hasattr(self, 'autoGenerateMode') and self.autoGenerateMode:
                extract_est = getattr(self, '_smooth_extract_est', 0)
                if extract_est > 0 and hasattr(self, '_progress') and self._progress:
                    self._smooth_ticker.adjust_total(-extract_est)

        # Handle traditional instrumental file mode or mute/beep mode
        if self.instrumentalMode:
            return self._create_instrumental_splice_list()
        else:
            return self._create_mute_beep_list()

    def _create_instrumental_splice_list(self):
        """Create list of profanity segments for instrumental splicing"""
        if len(self.naughtyWordList) == 0:
            self.instrumentalSegments = []
            return []

        # Sort by start time
        sorted_naughty = sorted(self.naughtyWordList, key=lambda x: x['start'])

        # Merge consecutive profanity segments (gap < 100ms)
        merged_segments = []
        if sorted_naughty:
            current_start = max(0, sorted_naughty[0]['start'] - self.padSecPre)
            current_end = sorted_naughty[0]['end'] + self.padSecPost

            for word in sorted_naughty[1:]:
                word_start = max(0, word['start'] - self.padSecPre)
                word_end = word['end'] + self.padSecPost

                # If gap between segments is less than 100ms, merge them
                if word_start - current_end < 0.1:
                    current_end = max(current_end, word_end)
                else:
                    merged_segments.append((current_start, current_end))
                    current_start = word_start
                    current_end = word_end

            # Add the last segment
            merged_segments.append((current_start, current_end))

        self.instrumentalSegments = merged_segments

        if self.debug:
            mmguero.eprint(f'Instrumental segments: {self.instrumentalSegments}')

        # Return empty list for muteTimeList (not used in instrumental mode)
        return []

    def _create_mute_beep_list(self):
        """Create traditional mute or beep filter list"""
        if len(self.naughtyWordList) > 0:
            # append a dummy word at the very end so that pairwise can peek then ignore it
            self.naughtyWordList.extend(
                [
                    {
                        "conf": 1,
                        "end": self.naughtyWordList[-1]["end"] + 2.0,
                        "start": self.naughtyWordList[-1]["end"] + 1.0,
                        "word": "mothaflippin",
                        "scrub": True,
                    }
                ]
            )
        if self.debug:
            mmguero.eprint(self.naughtyWordList)

        self.muteTimeList = []
        self.sineTimeList = []
        self.beepDelayList = []
        for word, wordPeek in pairwise(self.naughtyWordList):
            wordStart = format(word["start"] - self.padSecPre, ".3f")
            wordEnd = format(word["end"] + self.padSecPost, ".3f")
            wordDuration = format(float(wordEnd) - float(wordStart), ".3f")
            wordPeekStart = format(wordPeek["start"] - self.padSecPre, ".3f")
            if self.beep:
                self.muteTimeList.append(f"volume=enable='between(t,{wordStart},{wordEnd})':volume=0")
                self.sineTimeList.append(f"sine=f={self.beepHertz}:duration={wordDuration}")
                self.beepDelayList.append(
                    f"atrim=0:{wordDuration},adelay={'|'.join([str(int(float(wordStart) * 1000))] * 2)}"
                )
            else:
                self.muteTimeList.append(
                    "afade=enable='between(t," + wordStart + "," + wordEnd + ")':t=out:st=" + wordStart + ":d=5ms"
                )
                self.muteTimeList.append(
                    "afade=enable='between(t," + wordEnd + "," + wordPeekStart + ")':t=in:st=" + wordEnd + ":d=5ms"
                )

        if self.debug:
            mmguero.eprint(self.muteTimeList)
            if self.beep:
                mmguero.eprint(self.sineTimeList)
                mmguero.eprint(self.beepDelayList)

        return self.muteTimeList

    def _fmt_time(self, seconds):
        """Format seconds as M:SS.mmm"""
        mins = int(seconds) // 60
        secs = seconds - mins * 60
        return f"{mins}:{secs:06.3f}"

    def _print_words_summary(self):
        """Print profanity detection summary based on showWords mode."""
        if self.showWords == "none":
            return

        if not self.naughtyWordList:
            mmguero.eprint("No profanity detected")
            return

        count = len(self.naughtyWordList)
        if self.showWords == "clean":
            word = "word" if count == 1 else "words"
            mmguero.eprint(f"{count} {word} detected")
        elif self.showWords == "full":
            mmguero.eprint("Profanity detected:")
            for w in self.naughtyWordList:
                start = w.get('start', 0)
                end = w.get('end', 0)
                mmguero.eprint(f'  - "{w["word"]}" ({self._fmt_time(start)} - {self._fmt_time(end)})')
            word = "word" if count == 1 else "words"
            mmguero.eprint(f"{count} {word} detected")

    def _fetch_shazam_metadata(self):
        """Fetch song metadata from ShazamIO.

        Returns dict with keys: title, artist, genre, cover_art_url, album, year
        Returns empty dict if recognition fails or metadata disabled.
        """
        if self.disableMetadata:
            return {}

        import asyncio
        from shazamio import Shazam

        async def recognize():
            try:
                shazam = Shazam()
                result = await shazam.recognize(self.inputFileSpec)
                track = result.get('track', {})

                if self.debug:
                    mmguero.eprint(f"Full Shazam track response: {track}")

                # Extract album from sections metadata (recommended by ShazamIO maintainer)
                # Look for section where type == "SONG" and metadata item with title == "Album"
                album = ''
                for section in track.get('sections', []):
                    if section.get('type') == 'SONG':
                        for item in section.get('metadata', []):
                            if item.get('title') == 'Album':
                                album = item.get('text', '')
                                break
                        if album:
                            break

                # Extract year from sections metadata
                year = ''
                for section in track.get('sections', []):
                    if section.get('type') == 'SONG':
                        for item in section.get('metadata', []):
                            if item.get('title') == 'Released':
                                # Extract year from release date (e.g., "2015-09-25")
                                import re
                                date_text = item.get('text', '')
                                date_match = re.search(r'\d{4}', date_text)
                                if date_match:
                                    year = date_match.group()
                                    break
                        if year:
                            break

                metadata = {
                    'title': track.get('title', ''),
                    'artist': track.get('subtitle', ''),
                    'genre': track.get('genres', {}).get('primary', ''),
                    'album': album,
                    'year': year,
                    'cover_art_url': track.get('images', {}).get('coverart', ''),
                }

                return metadata
            except Exception as e:
                if self.debug:
                    mmguero.eprint(f"ShazamIO recognition failed: {e}")
                return {}

        try:
            return asyncio.run(recognize())
        except Exception as e:
            if self.debug:
                mmguero.eprint(f"ShazamIO async error: {e}")
            return {}

    def _embed_metadata(self, output_file):
        """Embed Shazam metadata into output file using mutagen."""
        if not self.shazamMetadata:
            return

        try:
            # Track file size before
            size_before = os.path.getsize(output_file)
            if self.debug:
                mmguero.eprint(f"Metadata embed: File size before: {size_before} bytes")

            # Detect file type and use appropriate mutagen API
            # Detect file type and use appropriate mutagen API
            ext = os.path.splitext(output_file)[1].lower()

            if ext == '.mp3':
                # MP3 files - use ID3 directly (not easy mode) for cover art support
                from mutagen.mp3 import MP3
                from mutagen.id3 import ID3, TIT2, TPE1, TCON, TALB, TDRC, APIC

                audio = MP3(output_file)

                # Clear existing tags and start fresh
                audio.tags = ID3()

                # Add text tags
                if self.shazamMetadata.get('title'):
                    audio.tags.add(TIT2(encoding=3, text=self.shazamMetadata['title']))
                if self.shazamMetadata.get('artist'):
                    audio.tags.add(TPE1(encoding=3, text=self.shazamMetadata['artist']))
                if self.shazamMetadata.get('genre'):
                    audio.tags.add(TCON(encoding=3, text=self.shazamMetadata['genre']))
                if self.shazamMetadata.get('album'):
                    audio.tags.add(TALB(encoding=3, text=self.shazamMetadata['album']))
                if self.shazamMetadata.get('year'):
                    audio.tags.add(TDRC(encoding=3, text=str(self.shazamMetadata['year'])))

                # Add cover art
                if self.shazamMetadata.get('cover_art_url'):
                    try:
                        import requests
                        if self.debug:
                            mmguero.eprint(f"Fetching cover art from: {self.shazamMetadata['cover_art_url']}")
                        response = requests.get(self.shazamMetadata['cover_art_url'], timeout=10)
                        if response.status_code == 200:
                            # Add new cover art
                            audio.tags.add(APIC(
                                encoding=3,
                                mime='image/jpeg',
                                type=3,  # 3 = cover front
                                desc='Cover',
                                data=response.content
                            ))
                            if self.debug:
                                mmguero.eprint(f"Embedded cover art ({len(response.content)} bytes)")
                        else:
                            if self.debug:
                                mmguero.eprint(f"Failed to fetch cover art: HTTP {response.status_code}")
                    except Exception as e:
                        if self.debug:
                            mmguero.eprint(f"Failed to embed cover art: {e}")

                audio.save(v2_version=3)  # ID3v2.3 for better compatibility
                if self.debug:
                    # Verify it was actually saved
                    try:
                        from mutagen.mp3 import MP3
                        check = MP3(output_file)
                        apic_found = False
                        if check.tags:
                            for tag in check.tags.values():
                                if hasattr(tag, 'FrameID') and tag.FrameID == 'APIC':
                                    apic_found = True
                                    mmguero.eprint(f"✓ Cover art verified in output file ({len(tag.data)} bytes)")
                                    break
                        if not apic_found:
                            mmguero.eprint(f"✗ Cover art NOT found in output file after save!")
                            mmguero.eprint(f"  Tags in file: {list(check.tags.keys()) if check.tags else 'None'}")
                    except Exception as verify_error:
                        mmguero.eprint(f"Verification error: {verify_error}")

                # Track file size after
                size_after = os.path.getsize(output_file)
                if self.debug:
                    mmguero.eprint(f"Metadata embed: File size after: {size_after} bytes (delta: {size_after - size_before})")
            else:
                # For other formats, use easy mode (no cover art support for now)
                mut = mutagen.File(output_file, easy=True)
                if mut is None or not hasattr(mut, '__setitem__'):
                    if self.debug:
                        mmguero.eprint(f"Cannot embed metadata in {output_file}")
                    return

                # Embed standard tags
                if self.shazamMetadata.get('title'):
                    mut['title'] = self.shazamMetadata['title']
                if self.shazamMetadata.get('artist'):
                    mut['artist'] = self.shazamMetadata['artist']
                if self.shazamMetadata.get('genre'):
                    mut['genre'] = self.shazamMetadata['genre']
                if self.shazamMetadata.get('album'):
                    mut['album'] = self.shazamMetadata['album']
                if self.shazamMetadata.get('year'):
                    mut['date'] = self.shazamMetadata['year']

                mut.save(output_file)

            if self.verbose_level:
                mmguero.eprint(f"Embedded metadata: {self.shazamMetadata.get('title')} - {self.shazamMetadata.get('artist')}")
                if self.shazamMetadata.get('cover_art_url'):
                    mmguero.eprint(f"Cover art: {self.shazamMetadata.get('cover_art_url')}")

        except Exception as e:
            if self.debug:
                mmguero.eprint(f"Failed to embed metadata: {e}")
            import traceback
            if self.debug:
                mmguero.eprint(traceback.format_exc())

    def _ai_detect_profanity(self):
        """Use Groq chat API with structured outputs to detect profanity."""
        import time as _time

        if not self.groqApiKey:
            raise ValueError("Groq API key required for AI detection")
        if not self.wordList:
            return

        # Build numbered transcript text
        transcript_lines = []
        for i, w in enumerate(self.wordList):
            transcript_lines.append(
                f"[{i}] ({w.get('start', 0):.2f}-{w.get('end', 0):.2f}) {w.get('word', '')}"
            )
        transcript_text = "\n".join(transcript_lines)

        # Get model and prompt (set from config via constructor)
        model = self.aiDetectModel
        prompt = self.aiDetectPrompt

        # API call with retry logic
        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.groqApiKey}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": transcript_text},
                        ],
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": "profanity_detection",
                                "strict": True,
                                "schema": AI_DETECT_SCHEMA,
                            }
                        }
                    },
                    timeout=120,
                )

                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        if self.debug:
                            mmguero.eprint(f"AI detection rate limited, retrying in {retry_delay}s...")
                        _time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    raise Exception("AI detection rate limit exceeded")

                if response.status_code == 401:
                    raise Exception("Invalid Groq API key for AI detection")

                response.raise_for_status()

                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                parsed = json.loads(content)

                profane_words = parsed.get("profane_words", [])
                for item in profane_words:
                    idx = item.get("index", -1)
                    if 0 <= idx < len(self.wordList):
                        self.wordList[idx]["scrub"] = True

                if self.debug:
                    mmguero.eprint(f"AI detection raw response: {content}")
                    reasoning = parsed.get("reasoning", "")
                    if reasoning:
                        mmguero.eprint(f"AI reasoning: {reasoning}")
                    mmguero.eprint(f"AI detection found {len(profane_words)} profane words")
                    for item in profane_words:
                        idx = item.get("index", -1)
                        word = item.get("word", "?")
                        mmguero.eprint(f"  [{idx}] \"{word}\" ({item.get('start', 0):.2f}-{item.get('end', 0):.2f})")

                return

            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    if self.debug:
                        mmguero.eprint(f"AI detection timed out, retrying ({attempt + 1}/{max_retries})...")
                    _time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise Exception("AI detection request timed out")

            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    if self.debug:
                        mmguero.eprint(f"AI detection request failed: {e}, retrying ({attempt + 1}/{max_retries})...")
                    _time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise Exception(f"AI detection failed after {max_retries} retries: {e}")

    def _build_instrumental_filters(self):
        """Build FFmpeg filter complex for instrumental splicing

        Supports both:
        - Traditional instrumental file (instrumentalFileSpec provided by user)
        - Auto-generated combined file (autoGenerateMode with segMapping)
        """
        if not self.instrumentalSegments:
            return []

        duration = self._get_file_duration(self.inputFileSpec)
        filter_parts = []
        seg_index = 0
        last_end = 0.0

        if hasattr(self, 'autoGenerateMode') and self.autoGenerateMode and hasattr(self, 'segMapping') and self.segMapping:
            # AUTO-SEPARATION MODE: Use segMapping to translate timestamps
            for idx, (orig_start, orig_end) in enumerate(self.instrumentalSegments):
                # Get the mapping for this segment
                if idx < len(self.segMapping):
                    profanity_start, profanity_end, combined_start, combined_end, padded_start, padded_end = self.segMapping[idx]
                else:
                    # Fallback: shouldn't happen
                    if orig_start > last_end:
                        filter_parts.append(f"[0:a]atrim={last_end:.2f}:{orig_start:.2f},asetpts=PTS-STARTPTS[seg{seg_index}]")
                        seg_index += 1
                    filter_parts.append(f"[0:a]atrim={orig_start:.2f}:{orig_end:.2f},volume=0[seg{seg_index}]")
                    seg_index += 1
                    last_end = orig_end
                    continue

                # Original audio before profanity
                if orig_start > last_end:
                    filter_parts.append(f"[0:a]atrim={last_end:.2f}:{orig_start:.2f},asetpts=PTS-STARTPTS[seg{seg_index}]")
                    seg_index += 1

                # Extract the profanity portion from the combined instrumental file
                # Calculate the position in the combined file where profanity starts
                # combined_start = where this padded segment is in combined file
                # (profanity_start - padded_start) = offset of profanity within the padded segment
                position_in_combined = combined_start + (profanity_start - padded_start)
                profanity_duration = profanity_end - profanity_start

                filter_parts.append(
                    f"[1:a]atrim={position_in_combined:.2f}:{position_in_combined + profanity_duration:.2f},asetpts=PTS-STARTPTS[seg{seg_index}]"
                )
                seg_index += 1

                last_end = orig_end

            # Final original audio segment
            if last_end < duration:
                filter_parts.append(f"[0:a]atrim={last_end:.2f},asetpts=PTS-STARTPTS[seg{seg_index}]")
                seg_index += 1

            # Concatenate all segments
            concat_input = ''.join([f'[seg{i}]' for i in range(seg_index)])
            filter_parts.append(f"{concat_input}concat=n={seg_index}:v=0:a=1[outa]")

        else:
            # TRADITIONAL MODE: Use provided instrumental file
            # Original logic works fine here
            filter_parts.append("[0:a]asplit=2[orig][inst]")

            seg_index = 0
            last_end = 0.0

            for start, end in self.instrumentalSegments:
                # Add original audio segment before profanity
                if start > last_end:
                    filter_parts.append(
                        f"[orig]atrim={last_end:.2f}:{start:.2f},asetpts=PTS-STARTPTS[seg{seg_index}]"
                    )
                    seg_index += 1

                # Add instrumental audio segment for profanity
                filter_parts.append(
                    f"[inst]atrim={start:.2f}:{end:.2f},asetpts=PTS-STARTPTS[seg{seg_index}]"
                )
                seg_index += 1

                last_end = end

            # Add final original audio segment after last profanity
            filter_parts.append(
                f"[orig]atrim={last_end:.2f},asetpts=PTS-STARTPTS[seg{seg_index}]"
            )
            seg_index += 1

            # Concatenate all segments
            concat_input = ''.join([f'[seg{i}]' for i in range(seg_index)])
            filter_parts.append(
                f"{concat_input}concat=n={seg_index}:v=0:a=1[outa]"
            )

        filter_complex = ';'.join(filter_parts)

        if self.debug:
            if hasattr(self, 'verbose_level') and self.verbose_level == "full":
                mmguero.eprint(f'Filter complex: {filter_complex}')
            else:
                # Concise mode: just show segment count
                mode = "auto-separation" if (hasattr(self, 'autoGenerateMode') and self.autoGenerateMode) else "traditional"
                mmguero.eprint(f'Building FFmpeg filter with {len(self.instrumentalSegments)} instrumental segment(s) ({mode} mode)')

        return ['-filter_complex', filter_complex, '-map', '[outa]']

    ######## EncodeCleanAudio ####################################################
    def EncodeCleanAudio(self):
        if (self.forceDespiteTag is True) or (GetMonkeyplugTagged(self.inputFileSpec, debug=self.debug) is False):
            # Initialize progress (only when not in debug mode)
            progress = None
            smooth_ticker = None
            step_timings = None
            timing_log = None
            file_duration = 0.0

            if not self.debug:
                # Load timing log and file duration for progress estimation
                timing_log = load_timing_log()
                file_duration = self._get_file_duration(self.inputFileSpec)
                step_timings = {}

                # Determine which steps will run
                will_transcribe = not self.inputTranscript
                will_extract = hasattr(self, 'autoGenerateMode') and self.autoGenerateMode
                # encode always runs

                # Check if we have estimates for all needed steps
                est_transcribe = estimate_step_duration(timing_log, 'transcribe', file_duration) if will_transcribe else None
                est_extract = estimate_step_duration(timing_log, 'extract', file_duration) if will_extract else None
                est_encode = estimate_step_duration(timing_log, 'encode', file_duration)

                can_smooth = (
                    file_duration > 0
                    and est_encode is not None
                    and (not will_transcribe or est_transcribe is not None)
                    and (not will_extract or est_extract is not None)
                )

                if can_smooth:
                    # Smooth mode: single bar with total in seconds
                    est_transcribe_val = est_transcribe or 0
                    est_extract_val = est_extract or 0
                    total_est = est_transcribe_val + est_extract_val + est_encode

                    initial_desc = "Transcribing" if will_transcribe else "Processing"
                    progress = tqdm(
                        total=total_est,
                        desc=initial_desc,
                        unit="s",
                        disable=False,
                        bar_format='{l_bar}{bar}| {n:.0f}/{total:.0f}s [{elapsed}<{remaining}]',
                    )

                    smooth_ticker = _SmoothProgressTicker(progress)
                    # Ticker will be started inside CreateCleanMuteList for each step

                    # Pass context to CreateCleanMuteList
                    self._smooth_ticker = smooth_ticker
                    self._smooth_cumulative = 0.0
                    self._smooth_transcribe_est = est_transcribe_val
                    self._smooth_extract_est = est_extract_val
                    self._step_timings = {}
                    self._timing_log = timing_log
                    self._timing_file_duration = file_duration
                    self._will_transcribe = will_transcribe
                else:
                    # Fallback: step-based bar (existing behavior)
                    initial_desc = "Transcribing" if not self.inputTranscript else "Processing"
                    progress = tqdm(
                        total=1,
                        desc=initial_desc,
                        unit="step",
                        disable=False,
                        bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]',
                    )

                # Always pass timing context (even in step-based mode, for data collection)
                self._step_timings = step_timings
                self._timing_file_duration = file_duration
                self._will_transcribe = not self.inputTranscript

            # Store progress reference for use in CreateCleanMuteList
            self._progress = progress

            self.CreateCleanMuteList()

            # Update progress after CreateCleanMuteList (step-based mode only)
            if progress and not smooth_ticker:
                did_extraction = (
                    hasattr(self, 'autoGenerateMode') and
                    self.autoGenerateMode and
                    hasattr(self, 'segMapping') and
                    self.segMapping
                )

                if not self.inputTranscript and not did_extraction:
                    progress.update(1)
                    progress.total = 2
                    progress.set_description("Encoding")
                elif not self.inputTranscript and did_extraction:
                    progress.set_description("Encoding")
                elif self.inputTranscript and did_extraction:
                    progress.total = 2
                    progress.set_description("Encoding")
                else:
                    progress.total = 1
                    progress.set_description("Encoding")

            # Get cumulative position after CreateCleanMuteList (smooth mode)
            cumulative = getattr(self, '_smooth_cumulative', 0.0) if smooth_ticker else 0

            # Handle instrumental mode differently
            if self.instrumentalMode:
                # Use instrumental splicing
                audioArgs = self._build_instrumental_filters()
            else:
                # Traditional mute or beep
                if len(self.muteTimeList) > 0:
                    if self.beep:
                        muteTimeListStr = ','.join(self.muteTimeList)
                        sineTimeListStr = ';'.join([f'{val}[beep{i+1}]' for i, val in enumerate(self.sineTimeList)])
                        beepDelayList = ';'.join(
                            [f'[beep{i+1}]{val}[beep{i+1}_delayed]' for i, val in enumerate(self.beepDelayList)]
                        )
                        beepMixList = ''.join([f'[beep{i+1}_delayed]' for i in range(len(self.beepDelayList))])
                        filterStr = f"[0:a]{muteTimeListStr}[mute];{sineTimeListStr};{beepDelayList};[mute]{beepMixList}amix=inputs={len(self.beepDelayList)+1}:normalize={str(self.beepMixNormalize).lower()}:dropout_transition={self.beepDropTransition}:weights={self.beepAudioWeight} {' '.join([str(self.beepSineWeight)] * len(self.beepDelayList))}"
                        audioArgs = ['-filter_complex', filterStr]
                    else:
                        audioArgs = ['-af', ",".join(self.muteTimeList)]
                else:
                    audioArgs = []

            if self.outputVideoFileFormat:
                # replace existing audio stream in video file with -copy
                ffmpegCmd = [
                    'ffmpeg',
                    '-nostdin',
                    '-hide_banner',
                    '-nostats',
                    '-loglevel',
                    'error',
                    '-y',
                    '-i',
                    self.inputFileSpec,
                ]

                # Add instrumental file input if in instrumental mode
                if self.instrumentalMode:
                    ffmpegCmd.extend(['-i', self.instrumentalFileSpec])

                ffmpegCmd.extend([
                    '-c:v',
                    'copy',
                    '-sn',
                    '-dn',
                ])
                ffmpegCmd.extend(audioArgs)
                ffmpegCmd.extend(self.aParams)
                ffmpegCmd.append(self.outputFileSpec)

            else:
                ffmpegCmd = [
                    'ffmpeg',
                    '-nostdin',
                    '-hide_banner',
                    '-nostats',
                    '-loglevel',
                    'error',
                    '-y',
                    '-i',
                    self.inputFileSpec,
                ]

                # Add instrumental file input if in instrumental mode
                if self.instrumentalMode:
                    ffmpegCmd.extend(['-i', self.instrumentalFileSpec])

                ffmpegCmd.extend(['-vn', '-sn', '-dn'])
                ffmpegCmd.extend(audioArgs)
                ffmpegCmd.extend(self.aParams)
                ffmpegCmd.append(self.outputFileSpec)

            # Start encode step with timing
            if progress and smooth_ticker:
                est_encode = estimate_step_duration(timing_log, 'encode', file_duration) or 0
                progress.set_description("Encoding")
                smooth_ticker.start(cumulative, est_encode)
            elif progress:
                progress.set_description("Encoding")
            encode_start = time.time()

            ffmpegResult, ffmpegOutput = mmguero.run_process(ffmpegCmd, stdout=True, stderr=True, debug=self.debug)
            if (ffmpegResult != 0) or (not os.path.isfile(self.outputFileSpec)):
                mmguero.eprint(' '.join(mmguero.flatten(ffmpegCmd)))
                mmguero.eprint(ffmpegResult)
                mmguero.eprint(ffmpegOutput)
                raise ValueError(f"Could not process {self.inputFileSpec}")

            # Record encode timing and finalize
            actual_encode = time.time() - encode_start
            if smooth_ticker:
                smooth_ticker.stop()
            if step_timings is not None:
                step_timings['encode'] = (actual_encode, file_duration)

            # Embed Shazam metadata if available
            self._embed_metadata(self.outputFileSpec)

            SetMonkeyplugTag(self.outputFileSpec, debug=self.debug)

            # Complete progress and save timing data
            if progress:
                if smooth_ticker:
                    # Snap bar to total
                    progress.n = progress.total
                    progress.refresh()
                else:
                    progress.update(1)
                progress.close()

            # Update timing log with actual measurements (only on success)
            if timing_log is not None and file_duration > 0:
                for op, (wall_secs, audio_secs) in step_timings.items():
                    update_timing_measurement(timing_log, op, wall_secs, audio_secs)
                save_timing_log(timing_log)

        else:
            shutil.copyfile(self.inputFileSpec, self.outputFileSpec)
            if progress:
                progress.close()

        # Clean up progress references
        if hasattr(self, '_progress'):
            delattr(self, '_progress')
        for attr in ('_smooth_ticker', '_smooth_cumulative', '_smooth_extract_est',
                      '_smooth_transcribe_est', '_will_transcribe',
                      '_step_timings', '_timing_log', '_timing_file_duration'):
            if hasattr(self, attr):
                delattr(self, attr)

        # Print profanity detection summary (after progress bar is closed)
        self._print_words_summary()

        return self.outputFileSpec


#################################################################################


#################################################################################
class VoskPlugger(Plugger):
    tmpWavFileSpec = ""
    modelPath = ""
    wavReadFramesChunk = AUDIO_DEFAULT_WAV_FRAMES_CHUNK
    vosk = None

    def __init__(
        self,
        iFileSpec,
        oFileSpec,
        oAudioFileFormat,
        iSwearsFileSpec,
        mDir,
        outputJson,
        inputTranscript=None,
        saveTranscript=False,
        forceRetranscribe=False,
        aParams=None,
        aChannels=AUDIO_DEFAULT_CHANNELS,
        aSampleRate=AUDIO_DEFAULT_SAMPLE_RATE,
        aBitRate=AUDIO_DEFAULT_BIT_RATE,
        aVorbisQscale=AUDIO_DEFAULT_VORBIS_QSCALE,
        wChunk=AUDIO_DEFAULT_WAV_FRAMES_CHUNK,
        padMsecPre=0,
        padMsecPost=0,
        beep=False,
        beepHertz=BEEP_HERTZ_DEFAULT,
        beepMixNormalize=BEEP_MIX_NORMALIZE_DEFAULT,
        beepAudioWeight=BEEP_AUDIO_WEIGHT_DEFAULT,
        beepSineWeight=BEEP_SINE_WEIGHT_DEFAULT,
        beepDropTransition=BEEP_DROPOUT_TRANSITION_DEFAULT,
        force=False,
        dbug=False,
        showWords="clean",
        detectMode="list",
        groqApiKey=None,
        aiDetectModel="openai/gpt-oss-20b",
        aiDetectPrompt=AI_DETECT_PROMPT_DEFAULT,
        disableMetadata=False,
    ):
        self.wavReadFramesChunk = wChunk
        self.modelPath = None
        self.vosk = None

        # Only load model if we're actually going to transcribe
        if not inputTranscript:
            # make sure the VOSK model path exists
            if (mDir is not None) and os.path.isdir(mDir):
                self.modelPath = mDir
            else:
                raise IOError(
                    errno.ENOENT,
                    os.strerror(errno.ENOENT) + " (see https://alphacephei.com/vosk/models)",
                    mDir,
                )

            self.vosk = mmguero.dynamic_import("vosk", "vosk", debug=dbug)
            if not self.vosk:
                raise Exception("Unable to initialize VOSK API")
            if not dbug:
                self.vosk.SetLogLevel(-1)

        super().__init__(
            iFileSpec=iFileSpec,
            oFileSpec=oFileSpec,
            oAudioFileFormat=oAudioFileFormat,
            iSwearsFileSpec=iSwearsFileSpec,
            outputJson=outputJson,
            inputTranscript=inputTranscript,
            saveTranscript=saveTranscript,
            forceRetranscribe=forceRetranscribe,
            aParams=aParams,
            aChannels=aChannels,
            aSampleRate=aSampleRate,
            aBitRate=aBitRate,
            aVorbisQscale=aVorbisQscale,
            padMsecPre=padMsecPre,
            padMsecPost=padMsecPost,
            beep=beep,
            beepHertz=beepHertz,
            beepMixNormalize=beepMixNormalize,
            beepAudioWeight=beepAudioWeight,
            beepSineWeight=beepSineWeight,
            beepDropTransition=beepDropTransition,
            force=force,
            dbug=dbug,
            showWords=showWords,
            detectMode=detectMode,
            groqApiKey=groqApiKey,
            aiDetectModel=aiDetectModel,
            aiDetectPrompt=aiDetectPrompt,
            disableMetadata=disableMetadata,
        )

        self.tmpWavFileSpec = self.inputFileParts[0] + ".wav"

        if self.debug:
            if inputTranscript:
                mmguero.eprint(f'Using input transcript (skipping speech recognition)')
            else:
                mmguero.eprint(f'Model directory: {self.modelPath}')
                mmguero.eprint(f'Intermediate audio file: {self.tmpWavFileSpec}')
                mmguero.eprint(f'Read frames: {self.wavReadFramesChunk}')

    def __del__(self):
        super().__del__()
        # clean up intermediate WAV file used for speech recognition
        if os.path.isfile(self.tmpWavFileSpec):
            os.remove(self.tmpWavFileSpec)

    def CreateIntermediateWAV(self):
        ffmpegCmd = [
            'ffmpeg',
            '-nostdin',
            '-hide_banner',
            '-nostats',
            '-loglevel',
            'error',
            '-y',
            '-i',
            self.inputFileSpec,
            '-vn',
            '-sn',
            '-dn',
            AUDIO_INTERMEDIATE_PARAMS,
            self.tmpWavFileSpec,
        ]
        ffmpegResult, ffmpegOutput = mmguero.run_process(ffmpegCmd, stdout=True, stderr=True, debug=self.debug)
        if (ffmpegResult != 0) or (not os.path.isfile(self.tmpWavFileSpec)):
            mmguero.eprint(' '.join(mmguero.flatten(ffmpegCmd)))
            mmguero.eprint(ffmpegResult)
            mmguero.eprint(ffmpegOutput)
            raise ValueError(
                f"Could not convert {self.inputFileSpec} to {self.tmpWavFileSpec} (16 kHz, mono, s16 PCM WAV)"
            )

        return self.inputFileSpec

    def RecognizeSpeech(self):
        self.CreateIntermediateWAV()
        self.wordList.clear()
        with wave.open(self.tmpWavFileSpec, "rb") as wf:
            if (
                (wf.getnchannels() != 1)
                or (wf.getframerate() != 16000)
                or (wf.getsampwidth() != 2)
                or (wf.getcomptype() != "NONE")
            ):
                raise Exception(f"Audio file ({self.tmpWavFileSpec}) must be 16 kHz, mono, s16 PCM WAV")

            rec = self.vosk.KaldiRecognizer(self.vosk.Model(self.modelPath), wf.getframerate())
            rec.SetWords(True)
            while True:
                data = wf.readframes(self.wavReadFramesChunk)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    res = json.loads(rec.Result())
                    if "result" in res:
                        self.wordList.extend(
                            [
                                dict(r, **{'scrub': scrubword(mmguero.deep_get(r, ["word"])) in self.swearsMap})
                                for r in res["result"]
                            ]
                        )
            res = json.loads(rec.FinalResult())
            if "result" in res:
                self.wordList.extend(
                    [
                        dict(r, **{'scrub': scrubword(mmguero.deep_get(r, ["word"])) in self.swearsMap})
                        for r in res["result"]
                    ]
                )

            if self.debug:
                if hasattr(self, 'verbose_level') and self.verbose_level == "full":
                    mmguero.eprint(json.dumps(self.wordList))
                else:
                    # Concise mode: just show summary
                    profanity_count = sum(1 for word in self.wordList if word.get('scrub', False))
                    mmguero.eprint(f'Transcribed {len(self.wordList)} words, {profanity_count} profanity instances detected')

            if self.outputJson:
                with open(self.outputJson, "w") as f:
                    f.write(json.dumps(self.wordList))

        return self.wordList


#################################################################################


#################################################################################
class WhisperPlugger(Plugger):
    debug = False
    model = None
    torch = None
    whisper = None
    transcript = None

    def __init__(
        self,
        iFileSpec,
        oFileSpec,
        oAudioFileFormat,
        iSwearsFileSpec,
        mDir,
        mName,
        torchThreads,
        outputJson,
        inputTranscript=None,
        saveTranscript=False,
        forceRetranscribe=False,
        aParams=None,
        aChannels=AUDIO_DEFAULT_CHANNELS,
        aSampleRate=AUDIO_DEFAULT_SAMPLE_RATE,
        aBitRate=AUDIO_DEFAULT_BIT_RATE,
        aVorbisQscale=AUDIO_DEFAULT_VORBIS_QSCALE,
        padMsecPre=0,
        padMsecPost=0,
        beep=False,
        beepHertz=BEEP_HERTZ_DEFAULT,
        beepMixNormalize=BEEP_MIX_NORMALIZE_DEFAULT,
        beepAudioWeight=BEEP_AUDIO_WEIGHT_DEFAULT,
        beepSineWeight=BEEP_SINE_WEIGHT_DEFAULT,
        beepDropTransition=BEEP_DROPOUT_TRANSITION_DEFAULT,
        force=False,
        dbug=False,
        showWords="clean",
        detectMode="list",
        groqApiKey=None,
        aiDetectModel="openai/gpt-oss-20b",
        aiDetectPrompt=AI_DETECT_PROMPT_DEFAULT,
        disableMetadata=False,
    ):
        self.whisper = None
        self.model = None
        self.torch = None

        # Only load model if we're actually going to transcribe (no input transcript provided)
        if not inputTranscript:
            if torchThreads > 0:
                self.torch = mmguero.dynamic_import("torch", "torch", debug=dbug)
                if self.torch:
                    self.torch.set_num_threads(torchThreads)

            self.whisper = mmguero.dynamic_import("whisper", "openai-whisper", debug=dbug)
            if not self.whisper:
                raise Exception("Unable to initialize Whisper API")

            self.model = self.whisper.load_model(mName, download_root=mDir)
            if not self.model:
                raise Exception(f"Unable to load Whisper model {mName} in {mDir}")

        super().__init__(
            iFileSpec=iFileSpec,
            oFileSpec=oFileSpec,
            oAudioFileFormat=oAudioFileFormat,
            iSwearsFileSpec=iSwearsFileSpec,
            outputJson=outputJson,
            inputTranscript=inputTranscript,
            saveTranscript=saveTranscript,
            forceRetranscribe=forceRetranscribe,
            aParams=aParams,
            aChannels=aChannels,
            aSampleRate=aSampleRate,
            aBitRate=aBitRate,
            aVorbisQscale=aVorbisQscale,
            padMsecPre=padMsecPre,
            padMsecPost=padMsecPost,
            beep=beep,
            beepHertz=beepHertz,
            beepMixNormalize=beepMixNormalize,
            beepAudioWeight=beepAudioWeight,
            beepSineWeight=beepSineWeight,
            beepDropTransition=beepDropTransition,
            force=force,
            dbug=dbug,
            showWords=showWords,
            detectMode=detectMode,
            groqApiKey=groqApiKey,
            aiDetectModel=aiDetectModel,
            aiDetectPrompt=aiDetectPrompt,
            disableMetadata=disableMetadata,
        )

        if self.debug:
            if inputTranscript:
                mmguero.eprint(f'Using input transcript (skipping speech recognition)')
            else:
                mmguero.eprint(f'Model directory: {mDir}')
                mmguero.eprint(f'Model name: {mName}')

    def __del__(self):
        super().__del__()

    def RecognizeSpeech(self):
        self.wordList.clear()

        self.transcript = self.model.transcribe(word_timestamps=True, audio=self.inputFileSpec)
        if self.transcript and ('segments' in self.transcript):
            for segment in self.transcript['segments']:
                if 'words' in segment:
                    for word in segment['words']:
                        word['word'] = word['word'].strip()
                        word['scrub'] = scrubword(word['word']) in self.swearsMap
                        self.wordList.append(word)

        if self.debug:
            if hasattr(self, 'verbose_level') and self.verbose_level == "full":
                mmguero.eprint(json.dumps(self.wordList))
            else:
                # Concise mode: just show summary
                profanity_count = sum(1 for word in self.wordList if word.get('scrub', False))
                mmguero.eprint(f'Transcribed {len(self.wordList)} words, {profanity_count} profanity instances detected')

        if self.outputJson:
            with open(self.outputJson, "w") as f:
                f.write(json.dumps(self.wordList))

        return self.wordList


#################################################################################
class GroqPlugger(Plugger):
    GROQ_API_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
    debug = False
    api_key = None
    groq_model = "whisper-large-v3"
    transcript = None
    VOCAL_DETECTION_SAMPLE_DURATION = 10  # Seconds to sample for vocal detection
    # Filler words that indicate silence (including common hallucinations)
    VOCAL_DETECTION_FILLER_WORDS = {
        'thank', 'thanks', 'please', 'you', 'hey', 'yeah', 'oh', 'wow',
        '¶', '¶¶',  # Common hallucinations/artifacts
        '',  # Empty strings
    }  # Filler words that indicate silence

    def __init__(
        self,
        iFileSpec,
        oFileSpec,
        oAudioFileFormat,
        iSwearsFileSpec,
        groq_api_key,
        groq_model,
        outputJson,
        inputTranscript=None,
        saveTranscript=False,
        forceRetranscribe=False,
        aParams=None,
        aChannels=AUDIO_DEFAULT_CHANNELS,
        aSampleRate=AUDIO_DEFAULT_SAMPLE_RATE,
        aBitRate=AUDIO_DEFAULT_BIT_RATE,
        aVorbisQscale=AUDIO_DEFAULT_VORBIS_QSCALE,
        padMsecPre=0,
        padMsecPost=0,
        beep=False,
        beepHertz=BEEP_HERTZ_DEFAULT,
        beepMixNormalize=BEEP_MIX_NORMALIZE_DEFAULT,
        beepAudioWeight=BEEP_AUDIO_WEIGHT_DEFAULT,
        beepSineWeight=BEEP_SINE_WEIGHT_DEFAULT,
        beepDropTransition=BEEP_DROPOUT_TRANSITION_DEFAULT,
        force=False,
        dbug=False,
        instrumentalFileSpec=None,
        verbose_level="",
        auto_generate=False,
        separation_padding=1.0,
        showWords="clean",
        detectMode="list",
        groqApiKey=None,
        aiDetectModel="openai/gpt-oss-20b",
        aiDetectPrompt=AI_DETECT_PROMPT_DEFAULT,
        disableMetadata=False,
    ):
        # Import groq_config - handle both relative and absolute imports
        try:
            from .groq_config import load_groq_api_key
        except ImportError:
            from monkeyplug.groq_config import load_groq_api_key

        self.api_key = load_groq_api_key(groq_api_key, debug=dbug)
        if not self.api_key:
            raise ValueError(
                "Groq API key not found. Please provide it via --groq-api-key parameter, "
                "GROQ_API_KEY environment variable, ~/.groq/config.json file, or ./.groq_key file"
            )

        self.groq_model = groq_model
        self.debug = dbug
        self.verbose_level = verbose_level

        super().__init__(
            iFileSpec=iFileSpec,
            oFileSpec=oFileSpec,
            oAudioFileFormat=oAudioFileFormat,
            iSwearsFileSpec=iSwearsFileSpec,
            outputJson=outputJson,
            inputTranscript=inputTranscript,
            saveTranscript=saveTranscript,
            forceRetranscribe=forceRetranscribe,
            aParams=aParams,
            aChannels=aChannels,
            aSampleRate=aSampleRate,
            aBitRate=aBitRate,
            aVorbisQscale=aVorbisQscale,
            padMsecPre=padMsecPre,
            padMsecPost=padMsecPost,
            beep=beep,
            beepHertz=beepHertz,
            beepMixNormalize=beepMixNormalize,
            beepAudioWeight=beepAudioWeight,
            beepSineWeight=beepSineWeight,
            beepDropTransition=beepDropTransition,
            force=force,
            dbug=dbug,
            instrumentalFileSpec=instrumentalFileSpec,
            showWords=showWords,
            detectMode=detectMode,
            groqApiKey=groqApiKey,
            aiDetectModel=aiDetectModel,
            aiDetectPrompt=aiDetectPrompt,
            disableMetadata=disableMetadata,
        )

        # Initialize auto-separation mode
        self.autoGenerateMode = auto_generate
        self.separationPadding = separation_padding
        self.separationCacheDir = None
        self.segMapping = []  # Timestamp mapping for combined file
        self.separator = None

        if self.autoGenerateMode:
            try:
                from .separation import SourceSeparator
            except ImportError:
                from monkeyplug.separation import SourceSeparator

            import tempfile
            self.separator = SourceSeparator(debug=self.debug)
            self.separationCacheDir = tempfile.mkdtemp(prefix="monkeyplug_separation_")
            if self.debug:
                mmguero.eprint(f'Auto-separation mode enabled (padding: {self.separationPadding}s)')
                mmguero.eprint(f'Cache directory: {self.separationCacheDir}')

        if self.debug:
            if inputTranscript:
                mmguero.eprint('Using input transcript (skipping speech recognition)')
            else:
                mmguero.eprint(f'Using Groq API with model: {self.groq_model}')

    def RecognizeSpeech(self):
        import requests
        import time

        self.wordList.clear()

        # Prepare the API request
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

        data = {
            "model": self.groq_model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word"
        }

        # Implement retry logic for rate limiting
        max_retries = 3
        retry_delay = 1  # Initial delay in seconds

        for attempt in range(max_retries):
            file_handle = None
            try:
                # Prepare the file and data - open fresh for each attempt
                filename = os.path.basename(self.inputFileSpec)
                file_handle = open(self.inputFileSpec, 'rb')
                files = {
                    "file": (filename, file_handle, "audio/mpeg")
                }

                if self.debug:
                    mmguero.eprint(f"Sending request to Groq API (attempt {attempt + 1}/{max_retries})...")

                response = requests.post(
                    self.GROQ_API_ENDPOINT,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=120  # 2 minute timeout
                )

                # Handle rate limiting (HTTP 429)
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        if self.debug:
                            mmguero.eprint(f"Rate limit hit, retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    else:
                        raise Exception("Rate limit exceeded. Please try again later.")

                # Handle authentication errors (HTTP 401)
                if response.status_code == 401:
                    raise Exception(
                        "Invalid Groq API key. Please check your API key configuration."
                    )

                # Raise for other HTTP errors
                response.raise_for_status()

                # Parse the response
                self.transcript = response.json()

                if self.transcript and 'words' in self.transcript:
                    for word in self.transcript['words']:
                        word['word'] = word['word'].strip()
                        word['scrub'] = scrubword(word['word']) in self.swearsMap
                        self.wordList.append(word)

                if self.debug:
                    if hasattr(self, 'verbose_level') and self.verbose_level == "full":
                        mmguero.eprint(json.dumps(self.wordList))
                    else:
                        # Concise mode: just show summary
                        profanity_count = sum(1 for word in self.wordList if word.get('scrub', False))
                        mmguero.eprint(f'Transcribed {len(self.wordList)} words, {profanity_count} profanity instances detected')

                if self.outputJson:
                    with open(self.outputJson, "w") as f:
                        f.write(json.dumps(self.wordList))

                return self.wordList

            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    if self.debug:
                        mmguero.eprint(f"Request timed out, retrying (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise Exception("Request timed out. Please check your internet connection and try again.")

            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    if self.debug:
                        mmguero.eprint(f"Request failed: {e}, retrying (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise Exception(f"Failed to connect to Groq API: {e}")

            finally:
                # Make sure the file is closed after each attempt
                if file_handle is not None:
                    file_handle.close()

        raise Exception("Failed to complete speech recognition after maximum retries")

    def DetectVocals(self, filepath):
        """Detect if file has vocals by transcribing a short sample from the middle.

        Args:
            filepath: Path to audio file to check

        Returns:
            bool: True if vocals detected, False if instrumental (no speech)
        """
        import requests
        import tempfile

        # Get file duration
        duration = self._get_file_duration(filepath)
        if duration < self.VOCAL_DETECTION_SAMPLE_DURATION:
            # Short files, assume vocal (too short to be instrumental)
            return True

        # Calculate middle position for sample
        start_time = (duration - self.VOCAL_DETECTION_SAMPLE_DURATION) / 2

        # Create temporary file for sample
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # Extract sample from middle using ffmpeg
            ffmpegCmd = [
                'ffmpeg', '-nostdin', '-hide_banner', '-nostats', '-loglevel', 'error',
                '-i', filepath,
                '-ss', str(start_time),
                '-t', str(self.VOCAL_DETECTION_SAMPLE_DURATION),
                '-acodec', 'libmp3lame', '-b:a', '128K',
                '-y', tmp_path
            ]

            result, _ = mmguero.run_process(ffmpegCmd, stdout=False, stderr=False, debug=False)

            if result != 0:
                # On error, assume vocal
                if self.debug:
                    mmguero.eprint(f'Warning: Failed to extract sample from {os.path.basename(filepath)}, assuming vocals')
                return True

            # Transcribe sample with Groq API
            file_handle = None
            try:
                file_handle = open(tmp_path, 'rb')
                files = {"file": (os.path.basename(filepath), file_handle, "audio/mpeg")}
                data = {
                    "model": self.groq_model,
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "word"
                }

                headers = {"Authorization": f"Bearer {self.api_key}"}
                response = requests.post(
                    self.GROQ_API_ENDPOINT,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=30
                )

                if response.status_code == 200:
                    result = response.json()
                    # Check if any words were detected
                    words = result.get('words', [])

                    if len(words) == 0:
                        # No words detected = instrumental
                        if self.debug:
                            mmguero.eprint(f'Vocal detection: 0 words detected → instrumental')
                        return False

                    # Get all detected words for debugging
                    # Clean words: lowercase, strip punctuation and special characters
                    def clean_word(w):
                        # Remove common punctuation and special Unicode characters
                        cleaned = w.lower().strip('.,!?;:"\'()[]{}©®™¶§†‡•—–')
                        return cleaned

                    detected_words = {clean_word(word['word']) for word in words}
                    all_words_text = ', '.join([word['word'] for word in words])

                    # Check for "thank you" pattern - if only filler words detected, it's silence/instrumental
                    # If ALL detected words are filler words, treat as instrumental
                    if detected_words.issubset(self.VOCAL_DETECTION_FILLER_WORDS):
                        if self.debug:
                            mmguero.eprint(f'Vocal detection: Only filler words detected ({all_words_text}) → instrumental (silence)')
                        return False

                    # Real lyrics detected = vocal track
                    if self.debug:
                        mmguero.eprint(f'Vocal detection: {len(words)} words detected → vocals')
                        mmguero.eprint(f'  Words: {all_words_text}')

                    return True

                # On error, assume vocal
                if self.debug:
                    mmguero.eprint(f'Warning: API error during vocal detection, assuming vocals')
                return True

            finally:
                if file_handle:
                    file_handle.close()

        except Exception as e:
            # On any error, assume vocal
            if self.debug:
                mmguero.eprint(f'Warning: Exception during vocal detection: {e}, assuming vocals')
            return True

        finally:
            # Clean up temporary file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _extract_combined_segments(self, output_file):
        """
        Extract all profanity segments with padding and concatenate into one file
        Uses FFmpeg filter_complex to concatenate segments
        Tracks mapping between original timestamps and combined file timestamps

        Returns:
            float: Total duration of combined file, or 0 if failed
        """
        if not self.instrumentalSegments:
            return 0.0

        duration = self._get_file_duration(self.inputFileSpec)

        # Build filter to extract and concatenate all profanity segments
        filter_parts = []
        seg_index = 0
        combined_time = 0.0  # Track current position in combined file

        for start, end in self.instrumentalSegments:
            # Add padding
            padded_start = max(0, start - self.separationPadding)
            padded_end = min(duration, end + self.separationPadding)
            segment_duration = padded_end - padded_start

            # Extract this segment
            filter_parts.append(
                f"[0:a]atrim={padded_start:.2f}:{padded_end:.2f},asetpts=PTS-STARTPTS[seg{seg_index}]"
            )

            # Track mapping: where this original segment appears in combined file
            # Format: (original profanity start, original profanity end,
            #          combined file start, combined file end,
            #          padded segment start, padded segment end)
            padded_start = max(0, start - self.separationPadding)
            padded_end = min(duration, end + self.separationPadding)
            self.segMapping.append((
                start,  # Original profanity start
                end,    # Original profanity end
                combined_time,  # Start position in combined file
                combined_time + segment_duration,  # End position in combined file
                padded_start,  # Padded segment start (for offset calculation)
                padded_end,    # Padded segment end (for offset calculation)
            ))

            combined_time += segment_duration
            seg_index += 1

        # Concatenate all segments
        concat_input = ''.join([f'[seg{i}]' for i in range(seg_index)])
        filter_parts.append(f"{concat_input}concat=n={seg_index}:v=0:a=1[outa]")

        filter_complex = ';'.join(filter_parts)

        # Run ffmpeg to extract and concatenate
        ffmpegCmd = [
            'ffmpeg', '-nostdin', '-hide_banner', '-nostats', '-loglevel', 'error',
            '-y',
            '-i', self.inputFileSpec,
            '-filter_complex', filter_complex,
            '-map', '[outa]',
            '-acodec', 'pcm_s16le',  # WAV for sherpa-onnx
            '-ar', '44100',
            '-ac', '2',
            output_file
        ]

        result, _ = mmguero.run_process(ffmpegCmd, stdout=False, stderr=False, debug=self.debug)

        if result != 0:
            raise IOError("Failed to extract combined profanity segments")

        # Return duration of combined file
        return self._get_file_duration(output_file)

    def _create_combined_profanity_file(self):
        """
        Extract all profanity segments (with padding) into a single continuous file
        and separate it into instrumental

        Also creates timestamp mapping: where each original segment appears in the combined file

        Returns:
            str: Path to the combined instrumental file
        """
        if not self.instrumentalSegments:
            return None

        # Step 1: Extract all profanity segments (with padding) into one file
        # Also track the mapping between original timestamps and combined file timestamps
        combined_file = os.path.join(self.separationCacheDir, "combined_profanity.wav")
        self.segMapping = []  # Reset mapping

        segment_duration = self._extract_combined_segments(combined_file)

        if not segment_duration:
            return None

        if self.debug:
            mmguero.eprint(f'Extracted {len(self.instrumentalSegments)} profanity segment(s) into combined file ({segment_duration:.2f}s)')

        # Step 2: Separate the combined file
        instrumental_path, vocals_path = self.separator.separate_audio_file(
            combined_file,
            self.separationCacheDir
        )

        return instrumental_path


#################################################################################


###################################################################################################
# Wildcard and batch processing helpers
def apply_output_pattern(input_file, output_pattern):
    """Generate output filename from pattern.

    Args:
        input_file: Path to input file
        output_pattern: Output pattern (e.g., '*_clean.mp3')

    Returns:
        str: Generated output filepath
    """
    input_dir = os.path.dirname(input_file)
    input_basename = os.path.basename(input_file)
    input_name, input_ext = os.path.splitext(input_basename)

    # Replace * with input name
    output_name = output_pattern.replace('*', input_name)

    # Add extension if not present in pattern
    if not os.path.splitext(output_name)[1]:
        output_name += input_ext

    if input_dir:
        return os.path.join(input_dir, output_name)
    return output_name


def expand_and_detect_vocals(input_pattern, output_pattern, args, skip_detection=False):
    """Expand wildcards and detect which files have vocals.

    Args:
        input_pattern: Input file pattern (e.g., '*.mp3')
        output_pattern: Output file pattern (e.g., '*_clean.mp3')
        args: Parsed command-line arguments
        skip_detection: If True, assume all files have vocals (used with --instrumental generate)

    Returns:
        tuple: (vocal_files, instrumental_files, output_files)
    """
    import glob
    import re

    # Expand input wildcard
    input_files = glob.glob(input_pattern)

    if not input_files:
        raise IOError(f"No files found matching pattern: {input_pattern}")

    # If only one file and no wildcard, return it directly
    if len(input_files) == 1 and '*' not in input_pattern:
        output_file = apply_output_pattern(input_files[0], output_pattern)
        return [input_files[0]], [], [output_file]

    # Filter out files that match the output pattern (already processed)
    # Convert output pattern to regex for matching
    def pattern_to_regex(pattern):
        """Convert wildcard pattern to regex for matching"""
        # Escape special regex characters except *
        regex = re.escape(pattern)
        # Replace escaped * with .* (match anything)
        regex = regex.replace(r'\*', '.*')
        # Add anchors to match entire filename
        return f'^{regex}$'

    output_regex = pattern_to_regex(output_pattern)
    filtered_files = []
    skipped_output_files = []
    skipped_completed_files = []

    for filepath in input_files:
        basename = os.path.basename(filepath)
        # Check if file matches output pattern
        if re.match(output_regex, basename, re.IGNORECASE):
            skipped_output_files.append(filepath)
            if args.debug:
                mmguero.eprint(f'Skipping output file: {basename} (matches output pattern)')
        else:
            # Check if --skip-completed-songs is enabled and output file exists
            if args.skipCompletedSongs:
                expected_output = apply_output_pattern(filepath, output_pattern)
                if os.path.isfile(expected_output):
                    skipped_completed_files.append(filepath)
                    if args.debug:
                        mmguero.eprint(f'Skipping completed file: {basename} (output exists: {os.path.basename(expected_output)})')
                    continue
            filtered_files.append(filepath)

    input_files = filtered_files

    if not input_files:
        mmguero.eprint('No files to process after filtering out already-processed output files.')
        return [], [], []

    if args.debug:
        msg = f'Expanded wildcard to {len(input_files)} file(s)'
        if skipped_output_files:
            msg += f' (skipped {len(skipped_output_files)} output files)'
        if skipped_completed_files:
            msg += f' (skipped {len(skipped_completed_files)} completed files)'
        mmguero.eprint(msg)

    if skip_detection:
        if args.debug:
            mmguero.eprint('Skipping vocal detection (generate mode — assuming all files have vocals)')
        output_files = [apply_output_pattern(f, output_pattern) for f in input_files]
        return input_files, [], output_files

    # Create a GroqPlugger instance just for detection
    # We need to use dummy values for most parameters since we're only detecting vocals
    try:
        from .groq_config import load_groq_api_key
    except ImportError:
        from monkeyplug.groq_config import load_groq_api_key

    api_key = load_groq_api_key(args.groqApiKey, debug=args.debug)
    if not api_key:
        raise ValueError("Groq API key required for wildcard vocal detection")

    # Create minimal GroqPlugger for detection
    detector = GroqPlugger(
        iFileSpec=input_files[0],  # Dummy, will be overridden
        oFileSpec="dummy.mp3",
        oAudioFileFormat="MATCH",
        iSwearsFileSpec=args.swears,
        groq_api_key=api_key,
        groq_model=args.groqModel,
        outputJson=None,
        dbug=args.debug,
        verbose_level=args.verbose_level if hasattr(args, 'verbose_level') else "",
    )

    vocal_files = []
    instrumental_files = []
    output_files = []

    # Detect vocals in each file
    for filepath in input_files:
        basename = os.path.basename(filepath)

        if args.debug:
            mmguero.eprint(f'Detecting vocals in: {basename}')

        has_vocals = detector.DetectVocals(filepath)

        if has_vocals:
            output_file = apply_output_pattern(filepath, output_pattern)
            vocal_files.append(filepath)
            output_files.append(output_file)
            if args.debug:
                mmguero.eprint(f'  ✓ Vocals detected → will process')
        else:
            instrumental_files.append(filepath)
            if args.debug:
                mmguero.eprint(f'  ✗ No vocals → skipping (likely instrumental)')

    if args.debug:
        msg = f'\nVocal detection complete: {len(vocal_files)} vocal, {len(instrumental_files)} instrumental'
        if skipped_output_files:
            msg += f', {len(skipped_output_files)} already processed'
        if skipped_completed_files:
            msg += f', {len(skipped_completed_files)} skipped (output exists)'
        mmguero.eprint(msg)

    return vocal_files, instrumental_files, output_files


###################################################################################################
# Config file loading
MONKEYPLUG_CACHE_DIR = os.path.join(os.path.expanduser('~'), '.cache', 'monkeyplug')
MONKEYPLUG_CONFIG_PATH = os.path.join(MONKEYPLUG_CACHE_DIR, 'config.json')
MONKEYPLUG_TIMING_LOG_PATH = os.path.join(MONKEYPLUG_CACHE_DIR, 'timing_log.json')

DEFAULT_CONFIG = {
    "pad_milliseconds": 10,
    "pad_milliseconds_pre": 10,
    "pad_milliseconds_post": 10,
    "separation_padding": 1.0,
    "beep_hertz": BEEP_HERTZ_DEFAULT,
    "show_words": "clean",
    "detect_mode": "list",
    "ai_detect_model": "openai/gpt-oss-20b",
    "ai_detect_prompt": AI_DETECT_PROMPT_DEFAULT,
    "unify_album_model": "openai/gpt-oss-120b",
    "unify_album_prompt": UNIFY_ALBUM_PROMPT_DEFAULT,
}


def load_config_settings(debug=False):
    """
    Load settings from JSON config file.

    Config file search order (first found wins):
    1. ./.monkeyplug.json (current directory, project-specific)
    2. ~/.cache/monkeyplug/config.json (user-specific, alongside models)

    If no config exists anywhere, a default one is created at
    ~/.cache/monkeyplug/config.json so the user can find and edit it.

    Returns:
        dict: Config settings (empty dict if no config found)
    """
    config_paths = [
        os.path.join(os.getcwd(), '.monkeyplug.json'),
        MONKEYPLUG_CONFIG_PATH,
    ]

    for config_path in config_paths:
        if os.path.isfile(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)

                if debug:
                    mmguero.eprint(f"Loaded config from: {config_path}")

                return config
            except (json.JSONDecodeError, IOError) as e:
                if debug:
                    mmguero.eprint(f"Warning: Failed to load config from {config_path}: {e}")
                continue

    # No config found anywhere — create a default one so the user can edit it
    try:
        os.makedirs(MONKEYPLUG_CACHE_DIR, exist_ok=True)
        with open(MONKEYPLUG_CONFIG_PATH, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
            f.write('\n')
        if debug:
            mmguero.eprint(f"Created default config at: {MONKEYPLUG_CONFIG_PATH}")
    except (IOError, OSError) as e:
        if debug:
            mmguero.eprint(f"Warning: Could not create default config: {e}")

    return dict(DEFAULT_CONFIG)


###################################################################################################
# Timing log for progress estimation
def load_timing_log():
    """Load historical timing data for progress bar estimation.

    Returns:
        dict: Timing log with per-operation running averages, or {} if unavailable.
    """
    if not os.path.isfile(MONKEYPLUG_TIMING_LOG_PATH):
        return {}
    try:
        with open(MONKEYPLUG_TIMING_LOG_PATH, 'r') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, IOError, ValueError):
        pass
    return {}


def save_timing_log(timing_log):
    """Save timing log atomically to disk."""
    try:
        os.makedirs(os.path.dirname(MONKEYPLUG_TIMING_LOG_PATH), exist_ok=True)
        tmp_path = MONKEYPLUG_TIMING_LOG_PATH + '.tmp'
        with open(tmp_path, 'w') as f:
            json.dump(timing_log, f, indent=2)
            f.write('\n')
        os.replace(tmp_path, MONKEYPLUG_TIMING_LOG_PATH)
    except (IOError, OSError):
        pass  # Best-effort


def estimate_step_duration(timing_log, operation, audio_seconds):
    """Estimate wall-clock seconds for an operation based on historical data.

    Returns:
        float or None: Estimated seconds, or None if no data available.
    """
    entry = timing_log.get(operation)
    if not entry or entry.get('run_count', 0) == 0:
        return None
    total_audio = entry.get('total_audio_seconds', 0)
    if total_audio <= 0:
        return None
    rate = entry['total_wall_seconds'] / total_audio
    return rate * audio_seconds


def update_timing_measurement(timing_log, operation, wall_seconds, audio_seconds):
    """Add a new timing measurement to the running averages."""
    if operation not in timing_log:
        timing_log[operation] = {
            'total_audio_seconds': 0.0,
            'total_wall_seconds': 0.0,
            'run_count': 0,
        }
    entry = timing_log[operation]
    entry['total_audio_seconds'] += audio_seconds
    entry['total_wall_seconds'] += wall_seconds
    entry['run_count'] += 1


###################################################################################################
# RunMonkeyPlug
def RunMonkeyPlug():

    package_name = __package__ or "monkeyplug"
    try:
        metadata = importlib.metadata.metadata(package_name)
        version = metadata.get("Version", "unknown")
    except importlib.metadata.PackageNotFoundError:
        version = "source"

    # Load config file for default values (can be overridden by CLI args)
    config = load_config_settings(debug=False)

    parser = argparse.ArgumentParser(
        description=f"{package_name} (v{version})",
        add_help=True,
        usage=f"{package_name} <arguments>",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        type=str,
        nargs="?",
        const="concise",
        default="",
        metavar="[concise|full]",
        help="Verbose output level: -v for concise, -v full for detailed debug output",
    )
    parser.add_argument(
        "-m",
        "--mode",
        dest="speechRecMode",
        metavar="<string>",
        type=str,
        default=DEFAULT_SPEECH_REC_MODE,
        help=f"Speech recognition engine ({SPEECH_REC_MODE_GROQ}|{SPEECH_REC_MODE_WHISPER}|{SPEECH_REC_MODE_VOSK}) (default: {DEFAULT_SPEECH_REC_MODE})",
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input",
        type=str,
        default=None,
        required=False,
        metavar="<string>",
        help="Input file or folder (default: current directory for --unify-album standalone mode)",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        type=str,
        default=None,
        required=False,
        metavar="<string>",
        help="Output file",
    )
    parser.add_argument(
        "--skip-completed-songs",
        dest="skipCompletedSongs",
        action="store_true",
        help="Skip input files that already have a corresponding output file (wildcard mode only)",
    )
    parser.add_argument(
        "--output-json",
        dest="outputJson",
        type=str,
        default=None,
        required=False,
        metavar="<string>",
        help="Output file to store transcript JSON",
    )
    parser.add_argument(
        "-w",
        "--show-words",
        dest="showWords",
        type=str,
        choices=["full", "clean", "none"],
        default=config.get("show_words", "clean"),
        help="Show detected profanity: full (list with timestamps), clean (count only), none (default: clean)",
    )
    parser.add_argument(
        "--detect",
        dest="detectMode",
        type=str,
        choices=["list", "ai", "both"],
        default=config.get("detect_mode", "list"),
        help="Profanity detection method: list (static list), ai (Groq LLM), both (default: list)",
    )
    parser.add_argument(
        "--swears",
        help=f"text file containing profanity (default: \"{SWEARS_FILENAME_DEFAULT}\")",
        default=os.path.join(script_path, SWEARS_FILENAME_DEFAULT),
        metavar="<profanity file>",
    )
    parser.add_argument(
        "--input-transcript",
        dest="inputTranscript",
        type=str,
        default=None,
        required=False,
        metavar="<string>",
        help="Load existing transcript JSON instead of performing speech recognition",
    )
    parser.add_argument(
        "--save-transcript",
        dest="saveTranscript",
        action="store_true",
        default=False,
        help="Automatically save transcript JSON alongside output audio file",
    )
    parser.add_argument(
        "--force-retranscribe",
        dest="forceRetranscribe",
        action="store_true",
        default=False,
        help="Force new transcription even if transcript file exists (overrides automatic reuse)",
    )
    parser.add_argument(
        "--instrumental",
        dest="instrumentalFile",
        type=str,
        default=None,
        required=False,
        metavar="<mode|file>",
        help="Instrumental mode: 'auto' (default, try prefix search then generate), 'generate' (AI generation), 'prefix' (search with --instrumental-prefix), or file path",
    )
    parser.add_argument(
        "--instrumental-prefix",
        dest="instrumentalPrefix",
        type=str,
        default="AUTO",
        required=False,
        metavar="<string>",
        help="Prefix/suffix to search for instrumental file, or 'AUTO' for fuzzy matching (default)",
    )
    parser.add_argument(
        "--instrumental-auto-candidates",
        dest="instrumentalAutoCandidates",
        type=int,
        default=5,
        required=False,
        metavar="<int>",
        help="Number of top candidates to validate in AUTO mode (default: 5)",
    )
    parser.add_argument(
        "--separation-padding",
        dest="separationPadding",
        type=float,
        default=config.get("separation_padding", 1.0),
        metavar="<seconds>",
        help=f"Context padding for AI generation (default: {config.get('separation_padding', 1.0)} seconds)",
    )
    parser.add_argument(
        "--filter-instrumentals",
        dest="filterInstrumentals",
        action="store_true",
        default=False,
        help="In wildcard mode with --instrumental generate, filter out files detected as instrumentals (default: process all files)",
    )
    parser.add_argument(
        "--mute",
        dest="mute",
        action="store_true",
        default=False,
        help="Force mute mode (disable instrumental processing)",
    )
    parser.add_argument(
        "-a",
        "--audio-params",
        help="Audio parameters for ffmpeg (default depends on output audio codec)",
        dest="aParams",
        metavar="<str>",
        default=None,
    )
    parser.add_argument(
        "-c",
        "--channels",
        dest="aChannels",
        metavar="<int>",
        type=int,
        default=AUDIO_DEFAULT_CHANNELS,
        help=f"Audio output channels (default: {AUDIO_DEFAULT_CHANNELS})",
    )
    parser.add_argument(
        "-s",
        "--sample-rate",
        dest="aSampleRate",
        metavar="<int>",
        type=int,
        default=AUDIO_DEFAULT_SAMPLE_RATE,
        help=f"Audio output sample rate (default: {AUDIO_DEFAULT_SAMPLE_RATE})",
    )
    parser.add_argument(
        "-r",
        "--bitrate",
        dest="aBitRate",
        metavar="<str>",
        default=AUDIO_DEFAULT_BIT_RATE,
        help=f"Audio output bitrate (default: {AUDIO_DEFAULT_BIT_RATE})",
    )
    parser.add_argument(
        "-q",
        "--vorbis-qscale",
        dest="aVorbisQscale",
        metavar="<int>",
        type=int,
        default=AUDIO_DEFAULT_VORBIS_QSCALE,
        help=f"qscale for libvorbis output (default: {AUDIO_DEFAULT_VORBIS_QSCALE})",
    )
    parser.add_argument(
        "-f",
        "--format",
        dest="outputFormat",
        type=str,
        default=AUDIO_MATCH_FORMAT,
        required=False,
        metavar="<string>",
        help=f"Output file format (default: inferred from extension of --output, or \"{AUDIO_MATCH_FORMAT}\")",
    )
    parser.add_argument(
        "--pad-milliseconds",
        dest="padMsec",
        metavar="<int>",
        type=int,
        default=config.get("pad_milliseconds", 10),
        help=f"Milliseconds to pad on either side of muted segments (default: {config.get('pad_milliseconds', 10)})",
    )
    parser.add_argument(
        "--pad-milliseconds-pre",
        dest="padMsecPre",
        metavar="<int>",
        type=int,
        default=config.get("pad_milliseconds_pre", 10),
        help=f"Milliseconds to pad before muted segments (default: {config.get('pad_milliseconds_pre', 10)})",
    )
    parser.add_argument(
        "--pad-milliseconds-post",
        dest="padMsecPost",
        metavar="<int>",
        type=int,
        default=config.get("pad_milliseconds_post", 10),
        help=f"Milliseconds to pad after muted segments (default: {config.get('pad_milliseconds_post', 10)})",
    )
    parser.add_argument(
        "-b",
        "--beep",
        dest="beep",
        type=mmguero.str2bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help="Beep instead of silence",
    )
    parser.add_argument(
        "-z",
        "--beep-hertz",
        dest="beepHertz",
        metavar="<int>",
        type=int,
        default=config.get("beep_hertz", BEEP_HERTZ_DEFAULT),
        help=f"Beep frequency hertz (default: {config.get('beep_hertz', BEEP_HERTZ_DEFAULT)})",
    )
    parser.add_argument(
        "--beep-mix-normalize",
        dest="beepMixNormalize",
        type=mmguero.str2bool,
        nargs="?",
        const=True,
        default=BEEP_MIX_NORMALIZE_DEFAULT,
        metavar="true|false",
        help=f"Normalize mix of audio and beeps (default: {BEEP_MIX_NORMALIZE_DEFAULT})",
    )
    parser.add_argument(
        "--beep-audio-weight",
        dest="beepAudioWeight",
        metavar="<int>",
        type=int,
        default=BEEP_AUDIO_WEIGHT_DEFAULT,
        help=f"Mix weight for non-beeped audio (default: {BEEP_AUDIO_WEIGHT_DEFAULT})",
    )
    parser.add_argument(
        "--beep-sine-weight",
        dest="beepSineWeight",
        metavar="<int>",
        type=int,
        default=BEEP_SINE_WEIGHT_DEFAULT,
        help=f"Mix weight for beep (default: {BEEP_SINE_WEIGHT_DEFAULT})",
    )
    parser.add_argument(
        "--beep-dropout-transition",
        dest="beepDropTransition",
        metavar="<int>",
        type=int,
        default=BEEP_DROPOUT_TRANSITION_DEFAULT,
        help=f"Dropout transition for beep (default: {BEEP_DROPOUT_TRANSITION_DEFAULT})",
    )

    parser.add_argument(
        "--force",
        dest="forceDespiteTag",
        type=mmguero.str2bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help="Process file despite existence of embedded tag",
    )

    parser.add_argument(
        "--disable-metadata",
        dest="disableMetadata",
        action="store_true",
        default=False,
        help="Disable automatic metadata fetching via ShazamIO",
    )

    parser.add_argument(
        "--unify-album",
        dest="unifyAlbum",
        action="store_true",
        default=False,
        help="Unify album metadata across all files in the folder using AI",
    )

    # Custom action for --auto-rename to handle optional value
    class AutoRenameAction(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            if values is None:
                setattr(namespace, self.dest, UNIFY_ALBUM_RENAME_PROMPT_DEFAULT)
            else:
                setattr(namespace, self.dest, values)

    parser.add_argument(
        "--auto-rename",
        dest="autoRename",
        action=AutoRenameAction,
        nargs="?",
        const=None,  # Used when flag is present but no value
        default=None,
        metavar="<prompt>",
        help="Smart rename files using AI with --unify-album (optional: custom prompt for renaming)",
    )

    parser.add_argument(
        "--use-spotify",
        dest="useSpotify",
        nargs="?",
        const=True,  # Used when flag is present but no value
        default=None,
        metavar="<url>",
        help="Use Spotify to get official cover art and track listing with --unify-album (optional: direct Spotify URL)",
    )

    parser.add_argument(
        "--clean-cache",
        dest="cleanCache",
        action="store_true",
        default=False,
        help=f"Delete all cached data (models, config) at {MONKEYPLUG_CACHE_DIR} and exit",
    )

    parser.add_argument(
        "--clear-outputs",
        dest="clearOutputs",
        action="store_true",
        default=False,
        help="Delete all files matching the output glob pattern (-o) and exit",
    )

    voskArgGroup = parser.add_argument_group('VOSK Options')
    voskArgGroup.add_argument(
        "--vosk-model-dir",
        dest="voskModelDir",
        metavar="<string>",
        type=str,
        default=DEFAULT_VOSK_MODEL_DIR,
        help=f"VOSK model directory (default: {DEFAULT_VOSK_MODEL_DIR})",
    )
    voskArgGroup.add_argument(
        "--vosk-read-frames-chunk",
        dest="voskReadFramesChunk",
        metavar="<int>",
        type=int,
        default=os.getenv("VOSK_READ_FRAMES", AUDIO_DEFAULT_WAV_FRAMES_CHUNK),
        help=f"WAV frame chunk (default: {AUDIO_DEFAULT_WAV_FRAMES_CHUNK})",
    )

    whisperArgGroup = parser.add_argument_group('Whisper Options')
    whisperArgGroup.add_argument(
        "--whisper-model-dir",
        dest="whisperModelDir",
        metavar="<string>",
        type=str,
        default=DEFAULT_WHISPER_MODEL_DIR,
        help=f"Whisper model directory ({DEFAULT_WHISPER_MODEL_DIR})",
    )
    whisperArgGroup.add_argument(
        "--whisper-model-name",
        dest="whisperModelName",
        metavar="<string>",
        type=str,
        default=DEFAULT_WHISPER_MODEL_NAME,
        help=f"Whisper model name ({DEFAULT_WHISPER_MODEL_NAME})",
    )
    whisperArgGroup.add_argument(
        "--torch-threads",
        dest="torchThreads",
        metavar="<int>",
        type=int,
        default=DEFAULT_TORCH_THREADS,
        help=f"Number of threads used by torch for CPU inference ({DEFAULT_TORCH_THREADS})",
    )

    groqArgGroup = parser.add_argument_group('Groq Options')
    groqArgGroup.add_argument(
        "--groq-api-key",
        dest="groqApiKey",
        metavar="<string>",
        type=str,
        default=None,
        help="Groq API key (default: GROQ_API_KEY env var, ~/.groq/config.json, or ./.groq_key)",
    )
    groqArgGroup.add_argument(
        "--groq-model",
        dest="groqModel",
        metavar="<string>",
        type=str,
        default="whisper-large-v3",
        help="Groq Whisper model (default: whisper-large-v3)",
    )

    try:
        parser.error = parser.exit
        args = parser.parse_args()
    except SystemExit as se:
        mmguero.eprint(se)
        exit(2)

    # Handle --clean-cache early and exit
    if args.cleanCache:
        import shutil
        if os.path.isdir(MONKEYPLUG_CACHE_DIR):
            shutil.rmtree(MONKEYPLUG_CACHE_DIR)
            print(f"Deleted cache directory: {MONKEYPLUG_CACHE_DIR}")
        else:
            print(f"No cache directory found at: {MONKEYPLUG_CACHE_DIR}")
        return

    # Handle --clear-outputs early and exit
    if args.clearOutputs:
        import glob as glob_module
        if not args.output:
            mmguero.eprint("Error: --clear-outputs requires -o/--output with a glob pattern")
            mmguero.eprint("Example: monkeyplug --clear-outputs -o \"*_clean.mp3\"")
            sys.exit(1)
        # Expand the glob pattern
        matching_files = glob_module.glob(args.output, recursive=True)
        if not matching_files:
            print(f"No files found matching pattern: {args.output}")
            return
        # List files
        print(f"Found {len(matching_files)} file(s) matching pattern \"{args.output}\":")
        for f in sorted(matching_files):
            print(f"  {f}")
        # Prompt for confirmation
        response = input("\nDelete these files? [y/N]: ").strip().lower()
        if response in ('y', 'yes'):
            deleted = 0
            failed = 0
            for f in matching_files:
                try:
                    os.remove(f)
                    deleted += 1
                    print(f"Deleted: {f}")
                except OSError as e:
                    failed += 1
                    mmguero.eprint(f"Failed to delete {f}: {e}")
            print(f"\nDone: {deleted} deleted, {failed} failed")
        else:
            print("Cancelled - no files deleted")
        return

    # Set debug flag based on verbose level for backward compatibility
    if args.verbose == "full":
        args.debug = True
        args.verbose_level = "full"
    elif args.verbose == "concise":
        args.debug = True
        args.verbose_level = "concise"
    else:
        args.debug = False
        args.verbose_level = ""

    if args.debug:
        mmguero.eprint(os.path.join(script_path, script_name))
        mmguero.eprint(f"Arguments: {sys.argv[1:]}")
        if args.verbose_level == "full":
            mmguero.eprint(f"Arguments: {args}")
    else:
        sys.tracebacklimit = 0

    # Load Groq API key for AI detection (needed for all modes if --detect ai|both)
    if args.detectMode in ("ai", "both"):
        try:
            from monkeyplug.groq_config import load_groq_api_key
        except ImportError:
            from .groq_config import load_groq_api_key
        if not args.groqApiKey:
            args.groqApiKey = load_groq_api_key(None, debug=args.debug)
        if not args.groqApiKey:
            mmguero.eprint("Groq API key required for --detect ai or --detect both")
            mmguero.eprint("Provide via --groq-api-key, GROQ_API_KEY env var, ~/.groq/config.json, or ./.groq_key")
            sys.exit(1)
    elif args.speechRecMode == SPEECH_REC_MODE_GROQ and not args.groqApiKey:
        # Load key for Groq STT mode too (existing behavior)
        try:
            from monkeyplug.groq_config import load_groq_api_key
        except ImportError:
            from .groq_config import load_groq_api_key
        args.groqApiKey = load_groq_api_key(None, debug=args.debug)

    # Check if this is standalone --unify-album mode
    # Standalone: only --unify-album flag, no input/output specified for processing
    # Combined: --unify-album with input/output/wildcards for file processing
    standalone_unify = (
        args.unifyAlbum and
        not args.output and  # No explicit output means not processing files
        not (args.input and ('*' in args.input or os.path.isfile(args.input)))  # Not a file or wildcard pattern
    )

    if standalone_unify:
        # Standalone mode: only run album unification
        if not args.input:
            args.input = os.getcwd()
        args.output = None  # Not used in standalone mode

        try:
            result = _run_album_unification(
                args.input,
                args.output,
                config,
                rename_prompt=args.autoRename,
                use_spotify=args.useSpotify,
                debug=args.debug
            )
            print(result)
        except Exception as e:
            mmguero.eprint(f"Album unification failed: {e}")
            if args.debug:
                import traceback
                mmguero.eprint(traceback.format_exc())
        return

    # Require input for all other modes
    if not args.input:
        parser.error("-i/--input is required for this mode")

    # Set default output pattern if not specified: <input>_clean.<ext>
    if not args.output:
        input_base, input_ext = os.path.splitext(args.input)
        args.output = f"{input_base}_clean{input_ext}"

    # Check if wildcards are present in input or output
    has_wildcards = '*' in args.input or '*' in args.output

    # Process instrumental mode arguments
    auto_generate = False
    auto_mode_requested = False  # Track if --instrumental auto was used
    skip_detection = False  # Skip vocal detection in wildcard mode (--instrumental generate)

    # Mode priority: mute > beep > instrumental
    if args.mute:
        # Mute mode: disable all instrumental processing
        if args.debug:
            mmguero.eprint('Mute mode - disabling instrumental processing')
        args.instrumentalPrefix = None
        args.instrumentalFile = None
        auto_generate = False

    elif args.beep:
        # Beep mode: disable all instrumental processing (beep takes precedence)
        if args.debug:
            mmguero.eprint('Beep mode enabled - disabling instrumental mode')
        args.instrumentalPrefix = None
        args.instrumentalFile = None
        auto_generate = False

    # Process instrumental mode arguments
    # Default to auto mode if no instrumental flag provided or instrumentalPrefix is default "AUTO"
    elif args.instrumentalFile is None and (args.instrumentalPrefix is None or args.instrumentalPrefix == "AUTO"):
        # No --instrumental flag provided, default to auto mode
        auto_mode_requested = True
        args.instrumentalPrefix = "AUTO"
        if args.debug:
            mmguero.eprint('Default: Auto mode (try prefix search → if not found, generate)')

    elif args.instrumentalFile:
        # If --instrumental was provided with a value
        instrumental_mode = args.instrumentalFile.lower()

        if instrumental_mode == "auto":
            # Auto mode: try prefix search first, if not found, generate
            auto_mode_requested = True  # Track that auto mode was requested
            args.instrumentalFile = None  # Clear mode keyword so it's not treated as filename
            if not args.instrumentalPrefix:
                args.instrumentalPrefix = "AUTO"  # Set default for auto mode

            # The search will be done later; if not found, we'll set auto_generate
            if args.debug:
                mmguero.eprint('Auto mode: Will try prefix search first, then generate if needed')

        elif instrumental_mode == "generate":
            # Generate mode: force AI generation, skip instrumental file search
            auto_generate = True
            skip_detection = True
            args.instrumentalFile = None  # Clear mode keyword so it's not treated as filename
            args.instrumentalPrefix = None  # Skip instrumental file search entirely
            if args.debug:
                mmguero.eprint('Generate mode: Will use AI to generate instrumental')

        elif instrumental_mode == "prefix":
            # Prefix mode: search with --instrumental-prefix value
            args.instrumentalFile = None  # Clear mode keyword so it's not treated as filename
            if not args.instrumentalPrefix:
                args.instrumentalPrefix = "AUTO"  # Default to AUTO if not specified
            if args.debug:
                mmguero.eprint(f'Prefix mode: Searching for instrumental with prefix "{args.instrumentalPrefix}"')

        else:
            # Treat as filename - already set in args.instrumentalFile
            if args.debug:
                mmguero.eprint(f'Using specified instrumental file: {args.instrumentalFile}')

    # --filter-instrumentals overrides generate mode's skip_detection
    if args.filterInstrumentals:
        skip_detection = False

    if has_wildcards and args.speechRecMode == SPEECH_REC_MODE_GROQ:
        # Wildcard mode with vocal detection
        vocal_files, instrumental_files, output_files = expand_and_detect_vocals(
            args.input, args.output, args, skip_detection=skip_detection
        )

        if not vocal_files:
            mmguero.eprint('No vocal files found to process. All files appear to be instrumentals.')
            sys.exit(0)

        mmguero.eprint(f'\nProcessing {len(vocal_files)} file(s) with vocals...\n')

        # Process each vocal file
        for idx, (input_file, output_file) in enumerate(zip(vocal_files, output_files), 1):
            mmguero.eprint(f'\n[{idx}/{len(vocal_files)}] Processing: {os.path.basename(input_file)}')

            # Create a copy of args and modify input/output
            args_copy = argparse.Namespace(**vars(args))
            args_copy.input = input_file
            args_copy.output = output_file

            # Find instrumental file for this specific file if using AUTO/prefix mode
            if args_copy.instrumentalPrefix and not args_copy.instrumentalFile:
                import glob
                from difflib import SequenceMatcher

                input_dir = os.path.dirname(input_file)
                if not input_dir:
                    input_dir = '.'

                input_basename = os.path.basename(input_file)
                input_name, input_ext = os.path.splitext(input_basename)

                # AUTO mode - fuzzy matching
                if args_copy.instrumentalPrefix.upper() == 'AUTO':
                    if args_copy.debug:
                        mmguero.eprint(f'AUTO mode: Searching for instrumental file using fuzzy matching')

                    # Get all audio files in the directory
                    audio_extensions = ['.mp3', '.mp4', '.m4a', '.wav', '.flac', '.ogg', '.aac', '.wma']
                    all_files = []

                    for ext in audio_extensions:
                        all_files.extend(glob.glob(os.path.join(input_dir, f'*{ext}')))

                    # Filter out the input file itself and any files matching output pattern
                    def pattern_to_regex(pattern):
                        """Convert wildcard pattern to regex for matching"""
                        import re
                        regex = re.escape(pattern)
                        regex = regex.replace(r'\*', '.*')
                        return f'^{regex}$'

                    # If output file is specified, get its pattern to exclude matches
                    output_pattern_to_exclude = None
                    if output_file:
                        # For single file, check exact basename match
                        output_basename = os.path.basename(output_file)
                    else:
                        output_basename = None

                    other_files = []
                    for f in all_files:
                        basename = os.path.basename(f)
                        # Skip input file
                        if basename == input_basename:
                            continue
                        # Skip exact output file match if specified
                        if output_basename and basename == output_basename:
                            continue
                        other_files.append(f)

                    # Two-way fuzzy matching with validation
                    candidates_with_scores = []
                    for candidate in other_files:
                        candidate_basename = os.path.basename(candidate)
                        candidate_name, _ = os.path.splitext(candidate_basename)

                        ratio = SequenceMatcher(None, input_name.lower(), candidate_name.lower()).ratio()

                        if args_copy.debug:
                            mmguero.eprint(f'  {candidate_basename}: similarity={ratio:.3f}')

                        if ratio < 1.0:
                            candidates_with_scores.append((candidate, ratio))

                    candidates_with_scores.sort(key=lambda x: x[1], reverse=True)
                    top_candidates = candidates_with_scores[:args_copy.instrumentalAutoCandidates]

                    validated_candidates = []
                    for candidate, candidate_to_input_score in top_candidates:
                        candidate_basename = os.path.basename(candidate)
                        candidate_name, _ = os.path.splitext(candidate_basename)

                        best_other_score = 0.0
                        best_other_match = None

                        for other_file in all_files:
                            other_basename = os.path.basename(other_file)
                            if other_basename != input_basename and other_basename != candidate_basename:
                                other_name, _ = os.path.splitext(other_basename)
                                other_score = SequenceMatcher(None, candidate_name.lower(), other_name.lower()).ratio()

                                if other_score > best_other_score:
                                    best_other_score = other_score
                                    best_other_match = other_basename

                        if args_copy.debug:
                            mmguero.eprint(f'  Validating {candidate_basename}:')
                            mmguero.eprint(f'    to input: {candidate_to_input_score:.3f}')
                            mmguero.eprint(f'    to best other ({best_other_match}): {best_other_score:.3f}')

                        if candidate_to_input_score > best_other_score:
                            validated_candidates.append((candidate, candidate_to_input_score))
                            if args_copy.debug:
                                mmguero.eprint(f'    ✓ PASSED validation')
                        else:
                            if args_copy.debug:
                                mmguero.eprint(f'    ✗ FAILED validation')

                    if validated_candidates:
                        best_match, best_ratio = validated_candidates[0]
                        if best_ratio >= 0.3:
                            args_copy.instrumentalFile = best_match
                            if args_copy.debug:
                                mmguero.eprint(f'AUTO mode matched: {os.path.basename(best_match)} (similarity: {best_ratio:.3f})')
                        else:
                            # Auto mode: no valid match found, enable AI generation
                            if auto_mode_requested:
                                if args_copy.debug:
                                    mmguero.eprint(f'  Auto mode: No validated match above threshold, will use AI generation')
                            else:
                                mmguero.eprint(f'  No validated match above threshold, will use AI generation')
                    else:
                        # Auto mode: all candidates failed validation, enable AI generation
                        if auto_mode_requested:
                            if args_copy.debug:
                                mmguero.eprint(f'  Auto mode: All candidates failed validation, will use AI generation')
                        else:
                            mmguero.eprint(f'  All candidates failed validation, will use AI generation')

            # Process this file
            # Determine if AI generation should be used for this specific file
            file_auto_generate = auto_generate
            if auto_mode_requested and not args_copy.instrumentalFile:
                file_auto_generate = True

            plug = GroqPlugger(
                args_copy.input,
                args_copy.output,
                args_copy.outputFormat,
                args_copy.swears,
                args_copy.groqApiKey,
                args_copy.groqModel,
                args_copy.outputJson,
                inputTranscript=args_copy.inputTranscript,
                saveTranscript=args_copy.saveTranscript,
                forceRetranscribe=args_copy.forceRetranscribe,
                aParams=args_copy.aParams,
                aChannels=args_copy.aChannels,
                aSampleRate=args_copy.aSampleRate,
                aBitRate=args_copy.aBitRate,
                aVorbisQscale=args_copy.aVorbisQscale,
                padMsecPre=args_copy.padMsecPre if args_copy.padMsecPre > 0 else args_copy.padMsec,
                padMsecPost=args_copy.padMsecPost if args_copy.padMsecPost > 0 else args_copy.padMsec,
                beep=args_copy.beep,
                beepHertz=args_copy.beepHertz,
                beepMixNormalize=args_copy.beepMixNormalize,
                beepAudioWeight=args_copy.beepAudioWeight,
                beepSineWeight=args_copy.beepSineWeight,
                beepDropTransition=args_copy.beepDropTransition,
                force=args_copy.forceDespiteTag,
                dbug=args_copy.debug,
                instrumentalFileSpec=args_copy.instrumentalFile,
                verbose_level=args_copy.verbose_level if hasattr(args_copy, 'verbose_level') else "",
                auto_generate=file_auto_generate,
                separation_padding=args_copy.separationPadding,
                showWords=args_copy.showWords,
                detectMode=args_copy.detectMode,
                groqApiKey=args_copy.groqApiKey,
                aiDetectModel=config.get("ai_detect_model", "openai/gpt-oss-20b"),
                aiDetectPrompt=config.get("ai_detect_prompt", AI_DETECT_PROMPT_DEFAULT),
            )

            print(plug.EncodeCleanAudio())

        mmguero.eprint(f'\n✓ Completed processing {len(vocal_files)} file(s)')
        mmguero.eprint(f'Skipped {len(instrumental_files)} instrumental file(s)')

    if has_wildcards and args.speechRecMode == SPEECH_REC_MODE_GROQ:
        # Handle --unify-album flag (combined mode - runs after normal processing)
        if args.unifyAlbum:
            mmguero.eprint("\n" + "="*60)
            mmguero.eprint("Running Album Unification")
            mmguero.eprint("="*60)

            try:
                result = _run_album_unification(
                    args.input,
                    args.output,
                    config,
                    rename_prompt=args.autoRename,
                    use_spotify=args.useSpotify,
                    debug=args.debug
                )
                mmguero.eprint(result)
            except Exception as e:
                mmguero.eprint(f"Album unification failed: {e}")
                if args.debug:
                    import traceback
                    mmguero.eprint(traceback.format_exc())

        sys.exit(0)

    # Single file mode (no wildcards or not using Groq mode)
    # Find instrumental file if prefix is specified
    if args.instrumentalPrefix and not args.instrumentalFile:
        import glob
        from difflib import SequenceMatcher

        input_dir = os.path.dirname(args.input)
        if not input_dir:
            input_dir = '.'

        input_basename = os.path.basename(args.input)
        input_name, input_ext = os.path.splitext(input_basename)

        # AUTO mode - fuzzy matching
        if args.instrumentalPrefix.upper() == 'AUTO':
            if args.debug:
                mmguero.eprint(f'AUTO mode: Searching for instrumental file using fuzzy matching')

            # Get all audio files in the directory
            audio_extensions = ['.mp3', '.mp4', '.m4a', '.wav', '.flac', '.ogg', '.aac', '.wma']
            all_files = []

            for ext in audio_extensions:
                all_files.extend(glob.glob(os.path.join(input_dir, f'*{ext}')))

            # Filter out the input file itself and the output file
            output_basename = os.path.basename(args.output) if args.output else None
            other_files = []
            for f in all_files:
                basename = os.path.basename(f)
                # Skip input file
                if basename == input_basename:
                    continue
                # Skip exact output file match if specified
                if output_basename and basename == output_basename:
                    continue
                other_files.append(f)

            if not other_files:
                mmguero.eprint(f'Warning: AUTO mode found no other audio files in directory')
            else:
                # Two-way fuzzy matching with validation
                # Step 1: Find top N candidates by similarity to input
                candidates_with_scores = []
                for candidate in other_files:
                    candidate_basename = os.path.basename(candidate)
                    candidate_name, _ = os.path.splitext(candidate_basename)

                    # Calculate similarity ratio (0 to 1)
                    ratio = SequenceMatcher(None, input_name.lower(), candidate_name.lower()).ratio()

                    if args.debug:
                        mmguero.eprint(f'  {candidate_basename}: similarity={ratio:.3f}')

                    if ratio < 1.0:  # Don't match the exact same file
                        candidates_with_scores.append((candidate, ratio))

                # Sort by score descending, take top N
                candidates_with_scores.sort(key=lambda x: x[1], reverse=True)
                top_candidates = candidates_with_scores[:args.instrumentalAutoCandidates]

                if args.debug and top_candidates:
                    mmguero.eprint(f'Top {len(top_candidates)} candidates: {[os.path.basename(c[0]) for c in top_candidates]}')

                # Step 2: Validate each candidate with two-way check
                validated_candidates = []
                for candidate, candidate_to_input_score in top_candidates:
                    candidate_basename = os.path.basename(candidate)
                    candidate_name, _ = os.path.splitext(candidate_basename)

                    # Find candidate's best match among ALL files (except input and itself)
                    best_other_score = 0.0
                    best_other_match = None

                    for other_file in all_files:
                        other_basename = os.path.basename(other_file)
                        if other_basename != input_basename and other_basename != candidate_basename:
                            other_name, _ = os.path.splitext(other_basename)

                            # Calculate similarity between candidate and this other file
                            other_score = SequenceMatcher(None, candidate_name.lower(), other_name.lower()).ratio()

                            if other_score > best_other_score:
                                best_other_score = other_score
                                best_other_match = other_basename

                    # Validation: candidate must be more similar to input than to any other file
                    if args.debug:
                        mmguero.eprint(f'  Validating {candidate_basename}:')
                        mmguero.eprint(f'    to input: {candidate_to_input_score:.3f}')
                        mmguero.eprint(f'    to best other ({best_other_match}): {best_other_score:.3f}')

                    if candidate_to_input_score > best_other_score:
                        validated_candidates.append((candidate, candidate_to_input_score))
                        if args.debug:
                            mmguero.eprint(f'    ✓ PASSED validation')
                    else:
                        if args.debug:
                            mmguero.eprint(f'    ✗ FAILED validation (better match with {best_other_match})')

                # Step 3: Use best validated candidate
                if validated_candidates:
                    best_match, best_ratio = validated_candidates[0]  # Already sorted by score
                    if best_ratio >= 0.3:  # 30% similarity threshold
                        args.instrumentalFile = best_match
                        if args.debug:
                            mmguero.eprint(f'AUTO mode matched: {os.path.basename(best_match)} (similarity: {best_ratio:.3f})')
                    else:
                        # Auto mode: no valid match found, will use AI generation
                        if auto_mode_requested:
                            mmguero.eprint(f'Warning: AUTO mode found candidates but all below 30% threshold')
                            mmguero.eprint(f'Best validated match was {os.path.basename(best_match)} with similarity {best_ratio:.3f}')
                            mmguero.eprint(f'Auto mode: Will use AI to generate instrumental')
                        else:
                            mmguero.eprint(f'Warning: AUTO mode found candidates but all below 30% threshold')
                            mmguero.eprint(f'Best validated match was {os.path.basename(best_match)} with similarity {best_ratio:.3f}')
                            mmguero.eprint(f'No instrumental file found, will use AI generation')
                else:
                    # Auto mode: all candidates failed validation, will use AI generation
                    if auto_mode_requested:
                        mmguero.eprint(f'Warning: AUTO mode could not find a validated instrumental file')
                        mmguero.eprint(f'All top candidates failed two-way validation (likely belong to other songs)')
                        mmguero.eprint(f'Auto mode: Will use AI to generate instrumental')
                    else:
                        mmguero.eprint(f'Warning: AUTO mode could not find a validated instrumental file')
                        mmguero.eprint(f'All top candidates failed two-way validation (likely belong to other songs)')
                        mmguero.eprint(f'No instrumental file found, will use AI generation')
        else:
            # Pattern-based search with specified prefix
            # Common patterns to search for
            patterns = [
                f"{input_name}_{args.instrumentalPrefix}{input_ext}",  # song_instrumental.mp3
                f"{input_name}-{args.instrumentalPrefix}{input_ext}",  # song-instrumental.mp3
                f"{input_name}{args.instrumentalPrefix}{input_ext}",   # songinstrumental.mp3
                f"{args.instrumentalPrefix}_{input_name}{input_ext}",  # instrumental_song.mp3
                f"{args.instrumentalPrefix}-{input_name}{input_ext}",  # instrumental-song.mp3
            ]

            if args.debug:
                mmguero.eprint(f'Searching for instrumental file with prefix: {args.instrumentalPrefix}')
                mmguero.eprint(f'Patterns: {patterns}')

            found = False
            for pattern in patterns:
                search_path = os.path.join(input_dir, pattern)
                matches = glob.glob(search_path)
                if matches:
                    args.instrumentalFile = matches[0]
                    found = True
                    if args.debug:
                        mmguero.eprint(f'Found instrumental file: {args.instrumentalFile}')
                    break

            if not found:
                mmguero.eprint(f'Warning: Could not find instrumental file matching prefix "{args.instrumentalPrefix}"')
                mmguero.eprint(f'Searched for patterns: {patterns}')
                # If auto mode was requested, enable AI generation
                if auto_mode_requested:
                    auto_generate = True
                    mmguero.eprint(f'Auto mode: No instrumental found, will use AI to generate instrumental')
                else:
                    mmguero.eprint(f'Will use AI to generate instrumental instead')

    # Single file mode: check if we should enable auto_generate after search
    # If auto mode was requested and no file was found, enable generation
    if auto_mode_requested and not args.instrumentalFile and not auto_generate:
        auto_generate = True
        if args.debug:
            mmguero.eprint('Auto mode: No instrumental file found, enabling AI generation')

    if args.speechRecMode == SPEECH_REC_MODE_VOSK:
        pathlib.Path(args.voskModelDir).mkdir(parents=True, exist_ok=True)
        plug = VoskPlugger(
            args.input,
            args.output,
            args.outputFormat,
            args.swears,
            args.voskModelDir,
            args.outputJson,
            inputTranscript=args.inputTranscript,
            saveTranscript=args.saveTranscript,
            forceRetranscribe=args.forceRetranscribe,
            aParams=args.aParams,
            aChannels=args.aChannels,
            aSampleRate=args.aSampleRate,
            aBitRate=args.aBitRate,
            aVorbisQscale=args.aVorbisQscale,
            wChunk=args.voskReadFramesChunk,
            padMsecPre=args.padMsecPre if args.padMsecPre > 0 else args.padMsec,
            padMsecPost=args.padMsecPost if args.padMsecPost > 0 else args.padMsec,
            beep=args.beep,
            beepHertz=args.beepHertz,
            beepMixNormalize=args.beepMixNormalize,
            beepAudioWeight=args.beepAudioWeight,
            beepSineWeight=args.beepSineWeight,
            beepDropTransition=args.beepDropTransition,
            force=args.forceDespiteTag,
            dbug=args.debug,
            showWords=args.showWords,
            detectMode=args.detectMode,
            groqApiKey=args.groqApiKey,
            aiDetectModel=config.get("ai_detect_model", "openai/gpt-oss-20b"),
            aiDetectPrompt=config.get("ai_detect_prompt", AI_DETECT_PROMPT_DEFAULT),
            disableMetadata=args.disableMetadata,
        )

    elif args.speechRecMode == SPEECH_REC_MODE_WHISPER:
        pathlib.Path(args.whisperModelDir).mkdir(parents=True, exist_ok=True)
        plug = WhisperPlugger(
            args.input,
            args.output,
            args.outputFormat,
            args.swears,
            args.whisperModelDir,
            args.whisperModelName,
            args.torchThreads,
            args.outputJson,
            inputTranscript=args.inputTranscript,
            saveTranscript=args.saveTranscript,
            forceRetranscribe=args.forceRetranscribe,
            aParams=args.aParams,
            aChannels=args.aChannels,
            aSampleRate=args.aSampleRate,
            aBitRate=args.aBitRate,
            aVorbisQscale=args.aVorbisQscale,
            padMsecPre=args.padMsecPre if args.padMsecPre > 0 else args.padMsec,
            padMsecPost=args.padMsecPost if args.padMsecPost > 0 else args.padMsec,
            beep=args.beep,
            beepHertz=args.beepHertz,
            beepMixNormalize=args.beepMixNormalize,
            beepAudioWeight=args.beepAudioWeight,
            beepSineWeight=args.beepSineWeight,
            beepDropTransition=args.beepDropTransition,
            force=args.forceDespiteTag,
            dbug=args.debug,
            showWords=args.showWords,
            detectMode=args.detectMode,
            groqApiKey=args.groqApiKey,
            aiDetectModel=config.get("ai_detect_model", "openai/gpt-oss-20b"),
            aiDetectPrompt=config.get("ai_detect_prompt", AI_DETECT_PROMPT_DEFAULT),
            disableMetadata=args.disableMetadata,
        )

    elif args.speechRecMode == SPEECH_REC_MODE_GROQ:
        plug = GroqPlugger(
            args.input,
            args.output,
            args.outputFormat,
            args.swears,
            args.groqApiKey,
            args.groqModel,
            args.outputJson,
            inputTranscript=args.inputTranscript,
            saveTranscript=args.saveTranscript,
            forceRetranscribe=args.forceRetranscribe,
            aParams=args.aParams,
            aChannels=args.aChannels,
            aSampleRate=args.aSampleRate,
            aBitRate=args.aBitRate,
            aVorbisQscale=args.aVorbisQscale,
            padMsecPre=args.padMsecPre if args.padMsecPre > 0 else args.padMsec,
            padMsecPost=args.padMsecPost if args.padMsecPost > 0 else args.padMsec,
            beep=args.beep,
            beepHertz=args.beepHertz,
            beepMixNormalize=args.beepMixNormalize,
            beepAudioWeight=args.beepAudioWeight,
            beepSineWeight=args.beepSineWeight,
            beepDropTransition=args.beepDropTransition,
            force=args.forceDespiteTag,
            dbug=args.debug,
            instrumentalFileSpec=args.instrumentalFile,
            verbose_level=args.verbose_level if hasattr(args, 'verbose_level') else "",
            auto_generate=auto_generate,
            separation_padding=args.separationPadding,
            showWords=args.showWords,
            detectMode=args.detectMode,
            groqApiKey=args.groqApiKey,
            aiDetectModel=config.get("ai_detect_model", "openai/gpt-oss-20b"),
            aiDetectPrompt=config.get("ai_detect_prompt", AI_DETECT_PROMPT_DEFAULT),
            disableMetadata=args.disableMetadata,
        )
    else:
        raise ValueError(f"Unsupported speech recognition engine {args.speechRecMode}")

    print(plug.EncodeCleanAudio())

    # Handle --unify-album flag (combined mode - runs after normal processing)
    if args.unifyAlbum:
        mmguero.eprint("\n" + "="*60)
        mmguero.eprint("Running Album Unification")
        mmguero.eprint("="*60)

        try:
            result = _run_album_unification(
                args.input,
                args.output,
                config,
                rename_prompt=args.autoRename,
                use_spotify=args.useSpotify,
                debug=args.debug
            )
            mmguero.eprint(result)
        except Exception as e:
            mmguero.eprint(f"Album unification failed: {e}")
            if args.debug:
                import traceback
                mmguero.eprint(traceback.format_exc())

    sys.exit(0)


###################################################################################################
if __name__ == "__main__":
    RunMonkeyPlug()
