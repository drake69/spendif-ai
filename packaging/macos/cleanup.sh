#!/usr/bin/env bash
# =============================================================================
#  Spendif.ai — total cleanup (macOS)
#
#  Wipes every trace of Spendif.ai from the system: running processes,
#  user data, the Hugging Face model cache, all logs, and the installed
#  .app bundle. After this script the next install behaves like a brand
#  new installation: model re-download, full onboarding wizard, fresh DB.
#
#  USAGE:
#    bash packaging/macos/cleanup.sh                 # interactive: asks before wiping
#    bash packaging/macos/cleanup.sh --yes           # no prompt, just do it
#    bash packaging/macos/cleanup.sh --keep-models   # keep the GGUF models cache
#
#  SAFETY:
#    Never touches anything outside ~/.spendifai, ~/.cache/huggingface,
#    ~/Library/Logs/spendifai-*, and the SpendifAi.app bundles.
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

# ── What we are about to wipe ────────────────────────────────────────────────
TARGETS=()
[[ -d "$HOME/.spendifai" ]] && TARGETS+=("$HOME/.spendifai")
if ! $KEEP_MODELS; then
  [[ -d "$HOME/.cache/huggingface" ]] && TARGETS+=("$HOME/.cache/huggingface")
fi
[[ -f "$HOME/Library/Logs/spendifai-launcher.log" ]] && TARGETS+=("$HOME/Library/Logs/spendifai-launcher.log")
[[ -d "/Applications/SpendifAi.app" ]] && TARGETS+=("/Applications/SpendifAi.app")
[[ -d "$HOME/Applications/Spendif.ai" ]] && TARGETS+=("$HOME/Applications/Spendif.ai")

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
echo "▸ Killing running SpendifAi processes..."
ps aux | awk '/SpendifAi/ && !/grep|Google Drive|crashpad|cleanup\.sh/ {print $2}' | \
  xargs -I{} kill -9 {} 2>/dev/null || true
sleep 1
echo "  ✔ done"

# ── 2. Remove paths ──────────────────────────────────────────────────────────
for t in "${TARGETS[@]}"; do
  echo "▸ rm -rf $t"
  rm -rf "$t" 2>/dev/null || {
    echo "  ⚠ rm failed (try sudo): $t"
  }
done

# ── 3. Result ────────────────────────────────────────────────────────────────
echo
if [[ -d "$HOME/.spendifai" || -d "/Applications/SpendifAi.app" ]]; then
  echo "⚠ Some paths could not be removed. Try: sudo bash $0 --yes"
  exit 2
fi
echo "✔ Spendif.ai cleanup complete."
if $KEEP_MODELS; then
  echo "  (Hugging Face model cache preserved — first launch will not re-download.)"
else
  echo "  Next install will perform a fresh model download (~3 GB)."
fi
