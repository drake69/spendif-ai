#!/usr/bin/env bash
# safe_sync.sh — canonical replacement for `uv sync` that protects custom-compiled packages.
#
# Use this instead of bare `uv sync` whenever you have manually compiled packages
# (e.g. llama-cpp-python built from source for SSM / Vulkan / ROCm support) that
# `uv sync` would otherwise silently overwrite with the standard PyPI wheel.
#
# Packages to protect are listed in `benchmark/.custom_packages` (one per line).
#
# Behaviour: if uv sync would modify a custom-compiled package, prompts for confirmation;
# on confirm, runs the sync and restores any downgraded package from backup.

[ -z "${BASH_VERSION:-}" ] && exec bash "$0" "$@"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

PYTHON="${PYTHON:-.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="python3"
SAFE_SYNC_MODE="interactive"

# shellcheck source=scripts/_lib/protect_custom.sh
source "$SCRIPT_DIR/scripts/_lib/protect_custom.sh"

safe_sync_run
