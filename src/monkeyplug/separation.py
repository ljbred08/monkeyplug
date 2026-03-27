#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Source separation module for monkeyplug.

This module provides AI-based source separation using sherpa-onnx
to automatically generate instrumental audio from profanity segments.
"""

import os
import tarfile
import urllib.request
import tempfile
import urllib.error


class SourceSeparator:
    """Handles AI-based source separation using sherpa-onnx"""

    SEPARATION_MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/source-separation-models/sherpa-onnx-spleeter-2stems-int8.tar.bz2"
    MODEL_DIR = os.path.join(os.path.expanduser("~"), ".cache", "monkeyplug", "separation_models")
    MODEL_SUBDIR = os.path.join(MODEL_DIR, "sherpa-onnx-spleeter-2stems-int8")
    VOCALS_MODEL = os.path.join(MODEL_SUBDIR, "vocals.int8.onnx")
    ACCOMPANIMENT_MODEL = os.path.join(MODEL_SUBDIR, "accompaniment.int8.onnx")

    def __init__(self, debug=False):
        self.debug = debug
        self._ensure_model_exists()
        self._initialize_engine()

    def _ensure_model_exists(self):
        """Download and extract model if not present"""
        if os.path.exists(self.VOCALS_MODEL) and os.path.exists(self.ACCOMPANIMENT_MODEL):
            if self.debug:
                print(f"Model files found in {self.MODEL_DIR}")
            return

        if self.debug:
            print(f"Downloading source separation model...")

        os.makedirs(self.MODEL_DIR, exist_ok=True)
        archive_path = os.path.join(tempfile.gettempdir(), "spleeter_model.tar.bz2")

        try:
            # Download with progress indication
            def report_progress(block_num, block_size, total_size):
                if self.debug and total_size > 0:
                    percent = int(block_num * block_size * 100 / total_size)
                    # Build progress bar string separately to avoid f-string format issues
                    filled = '=' * (percent // 5)
                    empty = ' ' * (20 - percent // 5)
                    bar = f"[{filled}{empty}]"
                    print(f"\rDownload progress: {min(percent, 100)}% {bar}", end='', flush=True)

            urllib.request.urlretrieve(self.SEPARATION_MODEL_URL, archive_path, reporthook=report_progress)

            # Print newline after download completes
            if self.debug:
                print()  # New line after progress bar

            # Extract archive
            if self.debug:
                print(f"Extracting model to {self.MODEL_DIR}...")

            with tarfile.open(archive_path, "r:bz2") as tar:
                tar.extractall(self.MODEL_DIR)

            # Clean up archive
            os.remove(archive_path)

            if self.debug:
                print(f"Model ready: {self.MODEL_DIR}")

        except (urllib.error.URLError, tarfile.TarError, OSError) as e:
            if os.path.exists(archive_path):
                os.remove(archive_path)
            raise IOError(f"Failed to download/extract separation model: {e}")

    def _initialize_engine(self):
        """Initialize sherpa-onnx OfflineSourceSeparation"""
        try:
            import sherpa_onnx
        except ImportError:
            raise ImportError(
                "sherpa-onnx is not installed. Please install it with: pip install sherpa-onnx"
            )

        config = sherpa_onnx.OfflineSourceSeparationConfig(
            model=sherpa_onnx.OfflineSourceSeparationModelConfig(
                spleeter=sherpa_onnx.OfflineSourceSeparationSpleeterModelConfig(
                    vocals=self.VOCALS_MODEL,
                    accompaniment=self.ACCOMPANIMENT_MODEL,
                ),
                num_threads=4,
                provider="cpu",
            )
        )
        self.engine = sherpa_onnx.OfflineSourceSeparation(config)

        if self.debug:
            print("Sherpa-ONNX engine initialized")

    def separate_audio_file(self, input_file, output_dir):
        """
        Separate an audio file into vocals and instrumental

        Args:
            input_file: Path to input audio (WAV format)
            output_dir: Directory for output files

        Returns:
            tuple: (instrumental_path, vocals_path)
        """
        try:
            import soundfile as sf
            import numpy as np
        except ImportError:
            raise ImportError(
                "soundfile and numpy are required. Please install them with: pip install soundfile numpy"
            )

        if self.debug:
            print(f"Separating audio file: {input_file}")

        # Load audio
        samples, sample_rate = sf.read(input_file, dtype="float32", always_2d=True)
        samples = np.ascontiguousarray(np.transpose(samples))

        # Process through sherpa-onnx
        output = self.engine.process(sample_rate=sample_rate, samples=samples)

        # Save outputs
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        instrumental_path = os.path.join(output_dir, f"{base_name}_instrumental.wav")
        vocals_path = os.path.join(output_dir, f"{base_name}_vocals.wav")

        # Output stems: stem 0 is vocals, stem 1 is accompaniment (instrumental)
        sf.write(instrumental_path, np.transpose(output.stems[1].data), output.sample_rate)
        sf.write(vocals_path, np.transpose(output.stems[0].data), output.sample_rate)

        if self.debug:
            print(f"Separation complete:")
            print(f"  Instrumental: {instrumental_path}")
            print(f"  Vocals: {vocals_path}")

        return instrumental_path, vocals_path
