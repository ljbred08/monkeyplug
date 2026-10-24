#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Tests for graceful degradation of Shazam metadata tagging.

Metadata tagging is best-effort: a broken or unsupported shazamio install (e.g. on
Python 3.14, where shazamio-core 1.1.2 publishes no wheels) must not abort the run,
but it must not fail silently either.
"""

import pathlib
import sys
import types

import pytest

from monkeyplug.monkeyplug import Plugger
import monkeyplug.monkeyplug as monkeyplug


class MockPlugger:
    """Minimal mock Plugger for testing metadata handling without an audio file"""

    def __init__(self, disableMetadata=False, debug=False):
        self.disableMetadata = disableMetadata
        self.debug = debug
        self.inputFileSpec = "fake.mp3"

        self._metadata_warning = Plugger._metadata_warning.__get__(self)
        self._fetch_shazam_metadata = Plugger._fetch_shazam_metadata.__get__(self)


@pytest.fixture(autouse=True)
def reset_metadata_warning(monkeypatch):
    monkeypatch.setattr(Plugger, "_metadataWarningShown", False)


@pytest.fixture
def broken_shazamio(monkeypatch):
    """Simulate shazamio failing to import (no wheel for this Python version)"""
    monkeypatch.setitem(sys.modules, "shazamio", None)


@pytest.fixture
def failing_shazam(monkeypatch):
    """Simulate shazamio importing fine but recognition raising"""
    module = types.ModuleType("shazamio")

    class Shazam:
        async def recognize(self, path):
            raise RuntimeError("connection reset by peer")

    module.Shazam = Shazam
    monkeypatch.setitem(sys.modules, "shazamio", module)
    return module


class TestMetadataGracefulDegradation:
    @pytest.mark.parametrize("failure_fixture", ["broken_shazamio", "failing_shazam"])
    def test_wildcard_batch_warns_once_and_resets_for_next_run(
        self, failure_fixture, request, monkeypatch, tmp_path, capsys
    ):
        request.getfixturevalue(failure_fixture)
        inputs = [str(tmp_path / f"song_{index}.mp3") for index in range(3)]
        outputs = [str(tmp_path / f"song_{index}_clean.mp3") for index in range(3)]
        for input_file in inputs:
            pathlib.Path(input_file).touch()

        monkeypatch.setattr(monkeyplug, "load_config_settings", lambda **kwargs: {})
        monkeypatch.setattr(
            monkeyplug, "expand_and_detect_vocals",
            lambda *args, **kwargs: (inputs, [], outputs),
        )
        monkeypatch.setattr(
            monkeyplug, "GetCodecs", lambda path: {"format": ["mp3"], "audio": ["mp3"]}
        )
        processed = []

        def encode(plugger):
            assert plugger.shazamMetadata == {}
            processed.append(plugger.inputFileSpec)
            return plugger.outputFileSpec

        monkeypatch.setattr(monkeyplug.GroqPlugger, "EncodeCleanAudio", encode)
        monkeypatch.setattr(sys, "tracebacklimit", None, raising=False)
        monkeypatch.setattr(sys, "argv", [
            "monkeyplug", "-i", str(tmp_path / "song_*.mp3"),
            "-o", str(tmp_path / "song_*_clean.mp3"),
            "--mode", "groq", "--groq-api-key", "test-key", "--mute",
        ])

        for run in range(2):
            with pytest.raises(SystemExit) as exc:
                monkeyplug.RunMonkeyPlug()

            assert exc.value.code == 0
            assert processed == inputs * (run + 1)
            assert capsys.readouterr().err.count("Warning:") == 1

    def test_import_failure_returns_empty_and_warns(self, broken_shazamio, capsys):
        plugger = MockPlugger()

        assert plugger._fetch_shazam_metadata() == {}

        err = capsys.readouterr().err
        assert "Warning:" in err
        assert "shazamio" in err
        assert "could not be imported" in err
        assert "--disable-metadata" in err

    def test_import_failure_warns_only_once(self, broken_shazamio, capsys):
        plugger = MockPlugger()

        plugger._fetch_shazam_metadata()
        plugger._fetch_shazam_metadata()
        plugger._fetch_shazam_metadata()

        err = capsys.readouterr().err
        assert err.count("Warning:") == 1

    def test_disable_metadata_skips_import_and_stays_quiet(self, broken_shazamio, capsys):
        plugger = MockPlugger(disableMetadata=True)

        assert plugger._fetch_shazam_metadata() == {}
        assert capsys.readouterr().err == ""

    def test_recognition_failure_is_not_fatal(self, failing_shazam, capsys):
        plugger = MockPlugger()

        assert plugger._fetch_shazam_metadata() == {}

        err = capsys.readouterr().err
        assert "Warning:" in err
        assert "continuing without metadata" in err
        assert "--disable-metadata" in err
