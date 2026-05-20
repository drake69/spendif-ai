"""Unit tests for the small, pure helpers introduced by the desktop bundle PR.

These helpers were extracted from larger functions (or, in the case of
``_resolve_log_dir`` and ``_ai_model_still_downloading``, were always pure
file-IO probes) so the new desktop launch / first-run-download paths have
a deterministic test surface that does not need pywebview, Streamlit,
or a real HuggingFace download.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# ── support/logging._resolve_log_dir ────────────────────────────────────────

from support.logging import _resolve_log_dir


def test_resolve_log_dir_respects_env_override(tmp_path, monkeypatch):
    target = tmp_path / "custom-log-dir"
    monkeypatch.setenv("SPENDIFAI_LOG_DIR", str(target))
    assert _resolve_log_dir() == target


def test_resolve_log_dir_expanduser_on_override(monkeypatch):
    monkeypatch.setenv("SPENDIFAI_LOG_DIR", "~/some-log-dir")
    result = _resolve_log_dir()
    assert "~" not in str(result)
    assert str(result).endswith("some-log-dir")


def test_resolve_log_dir_frozen_uses_user_dotdir(monkeypatch):
    monkeypatch.delenv("SPENDIFAI_LOG_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    expected = Path.home() / ".spendifai" / "logs"
    assert _resolve_log_dir() == expected
    # Cleanup the frozen flag so it doesn't leak into other tests
    monkeypatch.delattr(sys, "frozen", raising=False)


def test_resolve_log_dir_source_mode_writable_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("SPENDIFAI_LOG_DIR", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False) if getattr(sys, "frozen", False) else None
    monkeypatch.chdir(tmp_path)
    result = _resolve_log_dir()
    assert result == Path("logs")
    assert (tmp_path / "logs").exists()


def test_resolve_log_dir_source_mode_readonly_cwd_falls_back(tmp_path, monkeypatch):
    monkeypatch.delenv("SPENDIFAI_LOG_DIR", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False) if getattr(sys, "frozen", False) else None
    monkeypatch.chdir(tmp_path)
    # Patch Path.mkdir to raise PermissionError so we exercise the fallback.
    with patch.object(Path, "mkdir", side_effect=PermissionError("read-only")):
        result = _resolve_log_dir()
    assert result == Path.home() / ".spendifai" / "logs"


# ── ui/upload_page._ai_model_still_downloading ──────────────────────────────

from ui.upload_page import _ai_model_still_downloading


def _write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_model_download_status_missing_file_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert _ai_model_still_downloading() is False


def test_model_download_status_done_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _write_status(tmp_path / ".spendifai" / "model_download.status", {"pct": 1.0, "done": True})
    assert _ai_model_still_downloading() is False


def test_model_download_status_error_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _write_status(tmp_path / ".spendifai" / "model_download.status",
                  {"pct": 0.3, "done": False, "error": "boom"})
    assert _ai_model_still_downloading() is False


def test_model_download_status_in_progress_returns_true(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _write_status(tmp_path / ".spendifai" / "model_download.status",
                  {"pct": 0.42, "done": False, "error": None})
    assert _ai_model_still_downloading() is True


def test_model_download_status_malformed_json_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    status_file = tmp_path / ".spendifai" / "model_download.status"
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text("not json {{{", encoding="utf-8")
    assert _ai_model_still_downloading() is False


# ── core/model_manager._make_callback_tqdm ──────────────────────────────────

from core.model_manager import _make_callback_tqdm


def test_make_callback_tqdm_returns_none_when_base_missing():
    """No tqdm installed → callback wrapping is impossible, return base (None)."""
    result = _make_callback_tqdm(None, lambda pct: None)
    assert result is None


def test_make_callback_tqdm_returns_base_when_callback_missing():
    """No callback provided → no point wrapping, return base unchanged."""
    sentinel = object()
    result = _make_callback_tqdm(sentinel, None)
    assert result is sentinel


def test_make_callback_tqdm_invokes_callback_on_update():
    """The wrapped subclass fires the callback with pct=n/total after every update."""
    progress: list[float] = []

    class FakeTqdmBase:
        def __init__(self, *_args, total=None, **_kwargs):
            self.total = total
            self.n = 0

        def update(self, n=1):
            self.n += n

    cls = _make_callback_tqdm(FakeTqdmBase, progress.append)
    bar = cls(total=10)
    bar.update(3)
    bar.update(2)
    bar.update(5)
    assert progress == [0.3, 0.5, 1.0]


def test_make_callback_tqdm_clamps_to_one():
    """An over-eager parent that reports n > total still emits pct ≤ 1.0."""
    progress: list[float] = []

    class FakeTqdmBase:
        def __init__(self, *_a, total=None, **_kw):
            self.total = total
            self.n = 0

        def update(self, n=1):
            self.n += n

    cls = _make_callback_tqdm(FakeTqdmBase, progress.append)
    bar = cls(total=10)
    bar.update(15)
    assert progress == [1.0]


def test_make_callback_tqdm_swallows_callback_exceptions():
    """A buggy UI callback must not abort the underlying download."""
    def boom(_pct):
        raise RuntimeError("UI is dead")

    class FakeTqdmBase:
        def __init__(self, *_a, total=None, **_kw):
            self.total = total
            self.n = 0

        def update(self, n=1):
            self.n += n
            return "underlying-return"

    cls = _make_callback_tqdm(FakeTqdmBase, boom)
    bar = cls(total=10)
    # Must not raise — callback errors are swallowed.
    assert bar.update(3) == "underlying-return"


def test_fallback_chain_includes_smaller_tiers_in_order():
    """The fallback chain is largest-tier-first; if a download fails we
    walk down to ever-smaller models instead of giving up (AI-59 root
    cause was: 16 GB tier pointed at a gated repo and the whole feature
    was disabled even though smaller working models exist)."""
    from config import get_fallback_chain
    chain = get_fallback_chain(64)
    ids = [m.id for m in chain]
    # On a 64 GB host every tier ≤ 64 must appear, ordered from largest.
    # The registry currently has 2/8/12/16 tiers, so chain length is 4.
    assert ids[0] == "gemma-3-12b"          # the recommended pick
    assert ids[-1] == "qwen2.5-1.5b"        # smallest fallback
    assert len(ids) >= 2                     # at least one fallback exists
    # Strictly decreasing model sizes
    sizes = [m.size_mb for m in chain]
    assert sizes == sorted(sizes, reverse=True)


def test_fallback_chain_empty_when_no_model_fits():
    from config import get_fallback_chain
    assert get_fallback_chain(1) == []      # below the lowest tier (2 GB)


def test_make_callback_tqdm_handles_zero_total():
    """When total is unknown (None) the callback is never fired — no ZeroDivisionError."""
    progress: list[float] = []

    class FakeTqdmBase:
        def __init__(self, *_a, total=None, **_kw):
            self.total = total
            self.n = 0

        def update(self, n=1):
            self.n += n

    cls = _make_callback_tqdm(FakeTqdmBase, progress.append)
    bar = cls(total=None)
    bar.update(5)
    assert progress == []
