"""System settings and model registry loader.

Loads tuning parameters from config/system_settings.yaml (repo defaults)
and merges with ~/.spendifai/system_settings.yaml (user overrides) if present.

Also loads the model registry from config/models_registry.yaml.

Usage:
    from config import system_settings, get_recommended_model
    threshold = system_settings["history"]["auto_threshold"]
    model = get_recommended_model(ram_gb=16)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from support.logging import setup_logging

logger = setup_logging()

_DEFAULTS_PATH = Path(__file__).parent / "system_settings.yaml"
_USER_OVERRIDE_PATH = Path(os.environ.get(
    "SPENDIFAI_SYSTEM_SETTINGS",
    Path.home() / ".spendifai" / "system_settings.yaml",
))


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (override wins)."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _load() -> dict[str, Any]:
    """Load system settings with optional user overrides."""
    # Load defaults
    with open(_DEFAULTS_PATH, encoding="utf-8") as f:
        settings = yaml.safe_load(f) or {}

    # Merge user overrides if present
    if _USER_OVERRIDE_PATH.exists():
        try:
            with open(_USER_OVERRIDE_PATH, encoding="utf-8") as f:
                overrides = yaml.safe_load(f) or {}
            settings = _deep_merge(settings, overrides)
            logger.info(f"system_settings: merged overrides from {_USER_OVERRIDE_PATH}")
        except Exception as exc:
            logger.warning(f"system_settings: failed to load {_USER_OVERRIDE_PATH}: {exc}")

    return settings


# Module-level singleton — loaded once at import time
system_settings: dict[str, Any] = _load()


# ── Model Registry ──────────────────────────────────────────────────────────

_REGISTRY_PATH = Path(__file__).parent / "models_registry.yaml"


@dataclass
class ModelInfo:
    """A single model entry from the registry."""
    id: str
    name: str
    params: str
    quant: str
    filename: str
    repo: str
    size_mb: int
    ram_min_gb: int
    tier: str
    languages: list[str]


def _load_registry() -> dict[str, Any]:
    """Load model registry YAML."""
    with open(_REGISTRY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_all_models() -> list[ModelInfo]:
    """Return all models from the registry."""
    reg = _load_registry()
    return [
        ModelInfo(**{k: v for k, v in m.items()})
        for m in reg.get("models", [])
    ]


def get_recommended_model(ram_gb: int) -> ModelInfo | None:
    """Pick the best model for the given RAM amount.

    Uses the ``default_tier_map`` in the registry: picks the entry
    whose RAM key is the largest that fits in ``ram_gb``.
    Returns None if no model fits.
    """
    chain = get_fallback_chain(ram_gb)
    return chain[0] if chain else None


def get_fallback_chain(ram_gb: int) -> list[ModelInfo]:
    """Return the recommended model PLUS smaller fallbacks, largest first.

    Use this when the caller wants to try the recommended model and
    automatically fall back to a smaller one if the download fails (e.g.
    the HuggingFace repo went private or returned 404). Returns an empty
    list if no model in the registry fits ``ram_gb``.
    """
    reg = _load_registry()
    tier_map = reg.get("default_tier_map", {})
    models_by_id = {m["id"]: m for m in reg.get("models", [])}

    # Tier thresholds ≤ ram_gb, largest first
    candidate_tiers = sorted(
        (int(k) for k in tier_map if int(k) <= ram_gb),
        reverse=True,
    )

    chain: list[ModelInfo] = []
    seen_ids: set[str] = set()
    for tier in candidate_tiers:
        model_id = tier_map[tier]
        if model_id in seen_ids:
            continue
        seen_ids.add(model_id)
        m = models_by_id.get(model_id)
        if m:
            chain.append(ModelInfo(**{k: v for k, v in m.items()}))
    return chain
