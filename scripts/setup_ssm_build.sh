#!/usr/bin/env bash
# setup_ssm_build.sh — opt-in: compila llama-cpp-python da source per supportare
# architetture nuove (Qwen 3.5 hybrid SSM, eventuali Mamba/RWKV, Gemma 4 dove la
# wheel PyPI corrente non basta).
#
# Quando serve:
#   - hai bisogno di Qwen 3.5 9B (categorizer leader nel benchmark)
#   - vedi l'errore: "missing tensor 'blk.X.ssm_conv1d.weight'" caricando un modello
#   - vedi l'errore: "unknown model architecture: 'qwen3'"
#
# Effetto: ricompila llama-cpp-python da source con i CMAKE_ARGS adatti al backend
# GPU rilevato e aggiunge `llama_cpp_python` a `benchmark/.custom_packages` (così
# `scripts/safe_sync.sh` e `start.sh` non lo sovrascrivono — vedi AI-142).
#
# Quando NON serve: macchina che usa solo modelli supportati dalla wheel PyPI
# standard (Llama 3.x, Qwen 2.5, Gemma 3, Phi-3...). In quel caso non lanciarlo,
# `start.sh` farà il normale `uv sync` con la wheel binaria pre-compilata.

[ -z "${BASH_VERSION:-}" ] && exec bash "$0" "$@"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
info()  { echo -e "${GREEN}[setup_ssm]${NC} $*"; }
warn()  { echo -e "${YELLOW}[setup_ssm]${NC} $*"; }
error() { echo -e "${RED}[setup_ssm]${NC} $*"; exit 1; }

# ── Flags ────────────────────────────────────────────────────────────────────
YES=false
NO_CUSTOM_LIST=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)           YES=true;            shift ;;
    --no-custom-list)   NO_CUSTOM_LIST=true; shift ;;
    *) error "Unknown argument: $1" ;;
  esac
done

PYTHON="${PYTHON:-.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="python3"
CUSTOM_LIST="benchmark/.custom_packages"

# ── 1. Detect GPU backend ───────────────────────────────────────────────────
GPU_BACKEND="cpu"
GPU_LABEL="CPU-only"
CMAKE_ARGS_VAL=""
if [ "$(uname)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
    GPU_BACKEND="metal"
    GPU_LABEL="Apple Silicon (Metal)"
    CMAKE_ARGS_VAL="-DGGML_METAL=on"
elif command -v nvidia-smi &>/dev/null; then
    GPU_BACKEND="cuda"
    GPU_LABEL="NVIDIA (CUDA)"
    CMAKE_ARGS_VAL="-DGGML_CUDA=on"
elif command -v rocm-smi &>/dev/null && command -v rocminfo &>/dev/null && rocminfo 2>/dev/null | grep -q "gfx9"; then
    GPU_BACKEND="rocm"
    GPU_LABEL="AMD ROCm (CDNA gfx9xx)"
    CMAKE_ARGS_VAL="-DGGML_HIPBLAS=on"
elif command -v vulkaninfo &>/dev/null && vulkaninfo --summary 2>/dev/null | grep -qi "deviceName.*AMD\|deviceName.*Radeon"; then
    GPU_BACKEND="vulkan"
    GPU_LABEL="AMD Vulkan"
    CMAKE_ARGS_VAL="-DGGML_VULKAN=ON"
fi
info "GPU backend rilevato: $GPU_LABEL"

# ── 2. Verifica venv + uv ───────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    error "uv non trovato. Esegui prima ./start.sh (lo installa) oppure: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    error ".venv non trovato. Esegui prima ./start.sh per creare il venv."
fi

# ── 3. Stato corrente llama-cpp-python ──────────────────────────────────────
CURRENT_VER=""
if "$PYTHON" -c "import llama_cpp" 2>/dev/null; then
    CURRENT_VER=$("$PYTHON" -c "import llama_cpp; print(llama_cpp.__version__)" 2>/dev/null || echo "?")
    info "llama-cpp-python attualmente installato: $CURRENT_VER"
else
    warn "llama-cpp-python non installato — verrà compilato ex novo"
fi

# ── 4. Conferma ─────────────────────────────────────────────────────────────
# La source release su PyPI bundle un commit fisso di llama.cpp come sottomodulo —
# ricompilarla non aggiorna llama.cpp e quindi NON aggiunge il supporto SSM se
# il commit pinned è anteriore al merge SSM upstream. Per coprire SSM serve
# l'ultimo llama.cpp, raggiungibile installando llama-cpp-python da git HEAD
# (il submodule viene aggiornato a quello che main referenzia).
LLAMACPP_GIT_REF="${LLAMACPP_GIT_REF:-main}"
INSTALL_SPEC="llama-cpp-python @ git+https://github.com/abetlen/llama-cpp-python.git@${LLAMACPP_GIT_REF}"

echo ""
echo "Sto per compilare llama-cpp-python da git HEAD con i seguenti parametri:"
echo "  Backend     : $GPU_BACKEND"
echo "  CMAKE_ARGS  : $CMAKE_ARGS_VAL"
echo "  Git ref     : $LLAMACPP_GIT_REF (override via env LLAMACPP_GIT_REF=<tag|sha>)"
echo "  Comando     : CMAKE_ARGS=\"$CMAKE_ARGS_VAL\" uv pip install --upgrade --force-reinstall --no-cache-dir \"$INSTALL_SPEC\""
echo ""
echo "Tempo stimato: ~3-5 min su Apple Silicon, ~5-10 min su CUDA, ~10+ min su ROCm/Vulkan."
echo "Note: git HEAD può essere instabile. Se rompe, riprova con LLAMACPP_GIT_REF=<tag-noto>."
echo ""
if ! $YES; then
  read -r -p "Procedo? [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || { info "Annullato — nessuna modifica."; exit 0; }
fi

# ── 5. Build ────────────────────────────────────────────────────────────────
info "Avvio compilazione…"
if CMAKE_ARGS="$CMAKE_ARGS_VAL" uv pip install --upgrade --force-reinstall --no-cache-dir "$INSTALL_SPEC"; then
    NEW_VER=$("$PYTHON" -c "import llama_cpp; print(llama_cpp.__version__)" 2>/dev/null || echo "?")
    info "Build completata — llama-cpp-python $NEW_VER (git ref: $LLAMACPP_GIT_REF)"
else
    error "Compilazione fallita. Verifica: header GPU installati (xcode-select --install su Mac, CUDA toolkit su Linux); accesso a github.com; eventualmente prova un tag specifico con LLAMACPP_GIT_REF."
fi

# ── 6. Verifica import + log capabilities ───────────────────────────────────
info "Verifica import e capabilities…"
"$PYTHON" - <<'PY' || warn "Import o verifica falliti — la build potrebbe essere parziale"
import llama_cpp
print(f"  version : {llama_cpp.__version__}")
try:
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        llama_cpp.llama_print_system_info()
    info_str = buf.getvalue().strip()
    if info_str:
        print(f"  system  : {info_str[:200]}")
except Exception as e:
    print(f"  system info non disponibile: {e}")
PY

# ── 7. Garantisce .custom_packages contenga llama_cpp_python ────────────────
if $NO_CUSTOM_LIST; then
    info "Salto aggiornamento custom_packages (--no-custom-list)."
elif [ -f "$CUSTOM_LIST" ]; then
    if grep -qE '^[[:space:]]*llama_cpp_python[[:space:]]*$' "$CUSTOM_LIST"; then
        info "$CUSTOM_LIST già contiene llama_cpp_python"
    else
        echo "llama_cpp_python" >> "$CUSTOM_LIST"
        info "Aggiunto llama_cpp_python a $CUSTOM_LIST"
    fi
else
    warn "$CUSTOM_LIST non trovato — la protezione AI-142 non è installata. La build custom può essere sovrascritta da uv sync futuri."
fi

echo ""
info "Setup SSM completato."
info "D'ora in avanti usa 'bash scripts/safe_sync.sh' per aggiornare le dipendenze senza perdere questa build."
info "Quando la wheel PyPI di llama-cpp-python supporterà SSM nativamente, rimuovi 'llama_cpp_python' da $CUSTOM_LIST."
