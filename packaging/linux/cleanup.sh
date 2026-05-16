#!/usr/bin/env bash
# =============================================================================
#  Spendif.ai — total cleanup (Linux: Debian/Ubuntu, Fedora/RHEL)
#
#  Removes the installed package via the system package manager,
#  wipes user data, the Hugging Face model cache, and all logs.
#  After this script the next install behaves like a brand new install:
#  re-download model, full onboarding wizard, fresh DB.
#
#  USAGE:
#    bash packaging/linux/cleanup.sh                # interactive
#    sudo bash packaging/linux/cleanup.sh --yes     # no prompt
#    bash packaging/linux/cleanup.sh --keep-models  # preserve GGUF cache
#
#  REQUIREMENTS:
#    sudo privileges if the package was installed system-wide via apt/dnf.
#    User-level cleanup of ~/.spendifai works without sudo.
# =============================================================================
set -euo pipefail

YES=false
KEEP_MODELS=false
for arg in "$@"; do
  case "$arg" in
    -y|--yes)        YES=true ;;
    --keep-models)   KEEP_MODELS=true ;;
    -h|--help)       sed -n '2,18p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "Unknown arg: $arg" >&2; exit 1 ;;
  esac
done

# Detect package manager
PKG_MGR=""
PKG_INSTALLED=false
if command -v dpkg &>/dev/null && dpkg -l spendifai 2>/dev/null | grep -q "^ii"; then
  PKG_MGR="apt"
  PKG_INSTALLED=true
elif command -v rpm &>/dev/null && rpm -q spendifai &>/dev/null; then
  PKG_MGR="dnf"
  PKG_INSTALLED=true
fi

# ── What we are about to wipe ────────────────────────────────────────────────
TARGETS=()
$PKG_INSTALLED && TARGETS+=("system package spendifai (via $PKG_MGR)")
[[ -d "$HOME/.spendifai" ]] && TARGETS+=("$HOME/.spendifai")
if ! $KEEP_MODELS; then
  [[ -d "$HOME/.cache/huggingface" ]] && TARGETS+=("$HOME/.cache/huggingface")
fi
# /opt/spendifai is owned by the package — apt/dnf removes it. Only call it out
# explicitly if the package isn't tracked but the dir is still there (manual install).
if ! $PKG_INSTALLED && [[ -d /opt/spendifai ]]; then
  TARGETS+=("/opt/spendifai (untracked — manual install)")
fi

if [[ ${#TARGETS[@]} -eq 0 ]]; then
  echo "✔ Nothing to clean — Spendif.ai is not installed and has no user data."
  exit 0
fi

echo "Spendif.ai — total cleanup"
echo "About to remove:"
for t in "${TARGETS[@]}"; do echo "  - $t"; done

# ── Confirmation ────────────────────────────────────────────────────────────
if ! $YES; then
  printf "\nProceed? [y/N] "
  read -r reply
  case "$reply" in
    [yY]|[yY][eE][sS]) ;;
    *) echo "Aborted."; exit 1 ;;
  esac
fi

# ── 1. Kill running processes ────────────────────────────────────────────────
echo
echo "▸ Killing running SpendifAi / Streamlit processes..."
pgrep -f "spendifai|SpendifAi|desktop\.launcher" | xargs -r kill -9 2>/dev/null || true
sleep 1
echo "  ✔ done"

# ── 2. Uninstall via package manager ────────────────────────────────────────
if $PKG_INSTALLED; then
  echo "▸ Removing system package (sudo required)..."
  case "$PKG_MGR" in
    apt)
      sudo apt-get remove --purge -y spendifai
      ;;
    dnf)
      sudo dnf remove -y spendifai
      ;;
  esac
fi

# ── 3. Remove untracked /opt install if present ─────────────────────────────
if ! $PKG_INSTALLED && [[ -d /opt/spendifai ]]; then
  echo "▸ Removing untracked /opt/spendifai (sudo required)..."
  sudo rm -rf /opt/spendifai
fi

# ── 4. Remove user data ──────────────────────────────────────────────────────
if [[ -d "$HOME/.spendifai" ]]; then
  echo "▸ rm -rf $HOME/.spendifai"
  rm -rf "$HOME/.spendifai"
fi
if ! $KEEP_MODELS && [[ -d "$HOME/.cache/huggingface" ]]; then
  echo "▸ rm -rf $HOME/.cache/huggingface"
  rm -rf "$HOME/.cache/huggingface"
fi

# ── 5. Result ────────────────────────────────────────────────────────────────
echo
echo "✔ Spendif.ai cleanup complete."
if $KEEP_MODELS; then
  echo "  (Hugging Face model cache preserved — first launch will not re-download.)"
else
  echo "  Next install will perform a fresh model download (~3 GB)."
fi
