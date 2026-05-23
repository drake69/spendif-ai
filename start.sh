#!/usr/bin/env bash
# ──────────────────────────────────────────────
# Spendif.ai — Startup script (macOS / Linux)
# Conforme a SW_ENGINEERING_BLUEPRINT.md §16.
# ──────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── App paths (assoluti = chiave univoca per pgrep, §16.6.1) ───────────────
APP_PATH_UI="$SCRIPT_DIR/app.py"
APP_PATH_API="$SCRIPT_DIR/api/main.py"

UI_PORT_BASE=8501
UI_PORT_MAX=8510
API_PORT_BASE=8000
API_PORT_MAX=8010

# ── Multi-instance management (§16.6) ──────────────────────────────────────
kill_previous_instance() {
    local pattern="$1"
    local label="${2:-istanza}"
    local pids
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    [ -z "$pids" ] && return 0
    for pid in $pids; do
        if [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ]; then
            continue
        fi
        warn "Killing previous $label (PID $pid)..."
        kill -TERM "$pid" 2>/dev/null || true
        for _ in 1 2 3 4 5; do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.5
        done
        kill -KILL "$pid" 2>/dev/null || true
    done
    return 0
}

find_free_port() {
    local base="$1"
    local max="$2"
    local port
    for port in $(seq "$base" "$max"); do
        if ! lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
            echo "$port"
            return 0
        fi
    done
    return 1
}

# ── stop mode — bypass del pre-flight (§16.6.4) ────────────────────────────
if [ "${1:-}" = "stop" ]; then
    kill_previous_instance "$APP_PATH_UI"  "UI"
    kill_previous_instance "$APP_PATH_API" "API"
    info "Stopped (or nothing to stop)."
    exit 0
fi

# ── Pre-flight checks ──────────────────────────

# Python 3.13+ — cerca il più recente compatibile
PYTHON=""
for candidate in python3.14 python3.13 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 13 ]; then
            PYTHON="$candidate"
            PY_VER="$ver"
            break
        fi
    fi
done
if [ -z "$PYTHON" ]; then
    error "Python >= 3.13 non trovato. Installa Python >= 3.13."
fi
info "Python $PY_VER OK ($PYTHON)"

# uv
if ! command -v uv &>/dev/null; then
    warn "uv non trovato. Installazione in corso..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv &>/dev/null; then
        error "Installazione di uv fallita. Installa manualmente: https://docs.astral.sh/uv/"
    fi
fi
info "uv $(uv --version | head -1) OK"

# ── Setup ───────────────────────────────────────

# .env
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        info "File .env creato da .env.example"
    else
        warn "File .env.example non trovato — procedo senza .env"
    fi
fi

# Dipendenze (protegge build custom — vedi scripts/_lib/protect_custom.sh, §16.4.1)
info "Sincronizzazione dipendenze..."
SAFE_SYNC_MODE=non-interactive
# shellcheck source=scripts/_lib/protect_custom.sh
source "$SCRIPT_DIR/scripts/_lib/protect_custom.sh"
safe_sync_run

# Attivazione virtualenv
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    error "Virtualenv non trovato in $VENV_DIR. Esegui 'uv sync' manualmente."
fi
export PATH="$VENV_DIR/bin:$PATH"
export VIRTUAL_ENV="$VENV_DIR"
info "Virtualenv attivato ($VENV_DIR)"

# ── Avvio ───────────────────────────────────────

MODE="${1:-ui}"

case "$MODE" in
    ui)
        kill_previous_instance "$APP_PATH_UI" "UI"
        UI_PORT=$(find_free_port "$UI_PORT_BASE" "$UI_PORT_MAX") \
            || error "Nessuna porta libera in range $UI_PORT_BASE-$UI_PORT_MAX"
        [ "$UI_PORT" != "$UI_PORT_BASE" ] && warn "Porta $UI_PORT_BASE occupata (non nostra) — uso $UI_PORT"
        info "Avvio Streamlit UI su http://localhost:$UI_PORT"
        exec "$VENV_DIR/bin/streamlit" run "$APP_PATH_UI" --server.headless true --server.port "$UI_PORT"
        ;;
    api)
        kill_previous_instance "$APP_PATH_API" "API"
        API_PORT=$(find_free_port "$API_PORT_BASE" "$API_PORT_MAX") \
            || error "Nessuna porta libera in range $API_PORT_BASE-$API_PORT_MAX"
        [ "$API_PORT" != "$API_PORT_BASE" ] && warn "Porta $API_PORT_BASE occupata (non nostra) — uso $API_PORT"
        info "Avvio API server su http://localhost:$API_PORT"
        exec "$VENV_DIR/bin/uvicorn" api.main:app --host 0.0.0.0 --port "$API_PORT"
        ;;
    all)
        kill_previous_instance "$APP_PATH_UI"  "UI"
        kill_previous_instance "$APP_PATH_API" "API"
        UI_PORT=$(find_free_port "$UI_PORT_BASE" "$UI_PORT_MAX") \
            || error "Nessuna porta libera in range $UI_PORT_BASE-$UI_PORT_MAX"
        API_PORT=$(find_free_port "$API_PORT_BASE" "$API_PORT_MAX") \
            || error "Nessuna porta libera in range $API_PORT_BASE-$API_PORT_MAX"
        [ "$UI_PORT"  != "$UI_PORT_BASE"  ] && warn "Porta $UI_PORT_BASE occupata — uso $UI_PORT per UI"
        [ "$API_PORT" != "$API_PORT_BASE" ] && warn "Porta $API_PORT_BASE occupata — uso $API_PORT per API"
        info "Avvio UI + API..."
        "$VENV_DIR/bin/uvicorn" api.main:app --host 0.0.0.0 --port "$API_PORT" &
        API_PID=$!
        trap "kill $API_PID 2>/dev/null" EXIT
        info "API avviata (PID $API_PID) su http://localhost:$API_PORT"
        info "Avvio Streamlit UI su http://localhost:$UI_PORT"
        "$VENV_DIR/bin/streamlit" run "$APP_PATH_UI" --server.headless true --server.port "$UI_PORT"
        ;;
    *)
        echo "Uso: $0 [ui|api|all|stop]"
        echo "  ui    — Solo interfaccia Streamlit (default)"
        echo "  api   — Solo server API REST"
        echo "  all   — Entrambi"
        echo "  stop  — Termina istanze precedenti (UI + API) ed esce"
        exit 1
        ;;
esac
