#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Tests for graceful degradation of Shazam metadata tagging.

Metadata tagging is best-effort: a broken or unsupported shazamio install (e.g. on
Python 3.14, where shazamio-core 1.1.2 publishes no wheels) must not abort the run,
but it must not fail silently either.
"""

import sys
import types

import pytest

from monkeyplug.monkeyplug import Plugger


class MockPlugger:
    """Minimal mock Plugger for testing metadata handling without an audio file"""

    def __init__(self, disableMetadata=False, debug=False):
        self.disableMetadata = disableMetadata
        self.debug = debug
        self.inputFileSpec = "fake.mp3"
        self._metadataWarningShown = False

        self._metadata_warning = Plugger._metadata_warning.__get__(self)
        self._fetch_shazam_metadata = Plugger._fetch_shazam_metadata.__get__(self)


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
