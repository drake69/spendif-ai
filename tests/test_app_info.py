"""Tests for services/app_info.py — build metadata exposed to the UI."""
from __future__ import annotations

import sys


def test_get_build_info_returns_string_tuple():
    from services.app_info import get_build_info

    version, build_time = get_build_info()
    assert isinstance(version, str)
    assert isinstance(build_time, str)
    assert version and build_time


def test_get_build_info_falls_back_to_dev(monkeypatch):
    # Force the optional core._build_info import to fail (source checkout, no
    # frozen build stamp) and assert the graceful ("dev", "dev") fallback.
    monkeypatch.setitem(sys.modules, "core._build_info", None)

    from services.app_info import get_build_info

    assert get_build_info() == ("dev", "dev")
