#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Tests for the --reverse command line wiring.

Reverse mode only works with AI generation (it needs the separated vocal stem),
so the flag has to force generation instead of searching for an instrumental
file. These tests drive RunMonkeyPlug with a stubbed GroqPlugger, so no audio
is read and no API is called.
"""

import sys

import pytest

import monkeyplug.monkeyplug as mp


class FakeGroqPlugger:
    last_kwargs = None

    def __init__(self, *args, **kwargs):
        FakeGroqPlugger.last_kwargs = kwargs

    def EncodeCleanAudio(self):
        return "stub-output.mp3"


@pytest.fixture
def stub_plugger(monkeypatch):
    FakeGroqPlugger.last_kwargs = None
    monkeypatch.setattr(mp, "GroqPlugger", FakeGroqPlugger)
    return FakeGroqPlugger


def run_cli(monkeypatch, tmp_path, *extra):
    monkeypatch.setattr(sys, "argv", ["monkeyplug", "-i", str(tmp_path / "song.mp3")] + list(extra))
    # RunMonkeyPlug finishes a single-file run with sys.exit(0)
    with pytest.raises(SystemExit) as exit_info:
        mp.RunMonkeyPlug()
    assert exit_info.value.code in (0, None)


def test_reverse_flag_forces_ai_generation(stub_plugger, monkeypatch, tmp_path):
    run_cli(monkeypatch, tmp_path, "--reverse")

    kwargs = stub_plugger.last_kwargs
    assert kwargs["reverseMode"] is True
    assert kwargs["auto_generate"] is True
    # reverse mode cannot use a supplied instrumental file: it needs both stems
    assert kwargs["instrumentalFileSpec"] is None


def test_reverse_off_by_default(stub_plugger, monkeypatch, tmp_path):
    run_cli(monkeypatch, tmp_path, "--instrumental", "generate")

    kwargs = stub_plugger.last_kwargs
    assert kwargs["reverseMode"] is False
    assert kwargs["auto_generate"] is True


def test_mute_wins_over_reverse(stub_plugger, monkeypatch, tmp_path):
    run_cli(monkeypatch, tmp_path, "--reverse", "--mute")

    kwargs = stub_plugger.last_kwargs
    assert kwargs["auto_generate"] is False
