#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Spendif.ai — Avvio in MODALITÀ SVILUPPATORE (AI-193)
#
# Lancia l'app con SPENDIFAI_DEV_MODE già impostata, così in sidebar compare
# la voce "🔬 Debugger" (pagina di trace pipeline, nessuna scrittura su DB).
#
# Uso:   ./run_debug.sh
# Stop:  Ctrl-C
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
APP="$SCRIPT_DIR/app.py"
PORT="${SPENDIFAI_DEBUG_PORT:-8599}"

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "[ERROR] venv non trovato in $VENV_DIR — esegui prima 'uv sync'." >&2
    exit 1
fi

# La variabile che sblocca la pagina dev — già impostata qui.
export SPENDIFAI_DEV_MODE=1

echo "[INFO] Modalità sviluppatore attiva (SPENDIFAI_DEV_MODE=1)"
echo "[INFO] Apri:  http://localhost:${PORT}  →  sidebar  →  🔬 Debugger"

# Invochiamo streamlit come modulo via il python del venv: i wrapper in
# .venv/bin/ (streamlit, uvicorn) hanno shebang assoluti che si rompono se la
# cartella del progetto viene rinominata (es. Spendify → Spendif-ai).
exec "$VENV_DIR/bin/python" -m streamlit run "$APP" \
    --server.port "$PORT" \
    --server.headless false \
    --browser.gatherUsageStats false
