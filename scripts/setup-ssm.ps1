# setup-ssm.ps1 — Compile llama-cpp-python from git with GPU support (Windows)
#
# Equivalent of setup_ssm_build.sh for Windows. Required for Qwen 3.5 9B and
# other SSM-hybrid-architecture models that fail with the PyPI wheel.
#
# USAGE:
#   cd sw_artifacts
#   .\scripts\setup-ssm.ps1 [-Yes] [-NoCustomList] [-GitRef <ref>]
#
# PREREQUISITES:
#   uv installed (winget install astral-sh.uv)
#   Visual Studio Build Tools with C++ workload (for compiling llama-cpp)
#   CUDA Toolkit (optional, for NVIDIA GPU acceleration)

[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$NoCustomList,
    [string]$GitRef = "main"
)

$ErrorActionPreference = "Stop"

function info  { param($msg) Write-Host "[setup_ssm] $msg" -ForegroundColor Green }
function warn  { param($msg) Write-Host "[setup_ssm] $msg" -ForegroundColor Yellow }
function fatal { param($msg) Write-Host "[setup_ssm] $msg" -ForegroundColor Red; exit 1 }

$ScriptDir   = Split-Path -Parent $PSScriptRoot   # sw_artifacts root
$CustomList  = Join-Path $ScriptDir "benchmark\.custom_packages"
$PythonPath  = if ($env:PYTHON) { $env:PYTHON } else { Join-Path $ScriptDir ".venv\Scripts\python.exe" }

Push-Location $ScriptDir

# ── 1. Detect GPU backend ────────────────────────────────────────────────────
$CmakeArgs = ""
$GpuLabel  = "CPU-only"

if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $CmakeArgs = "-DGGML_CUDA=on"
    $GpuLabel  = "NVIDIA (CUDA)"
} else {
    warn "nvidia-smi not found — building CPU-only (no GPU acceleration)"
}
info "GPU backend: $GpuLabel"

# ── 2. Resolve Python ────────────────────────────────────────────────────────
if (-not (Test-Path $PythonPath)) {
    warn "Python not found at $PythonPath — falling back to system python"
    $PythonPath = (Get-Command python -ErrorAction SilentlyContinue)?.Source
    if (-not $PythonPath) { fatal "Python not found. Run .\start.bat first." }
}

# ── 3. Current version ───────────────────────────────────────────────────────
try {
    $CurrentVer = & $PythonPath -c "import llama_cpp; print(llama_cpp.__version__)" 2>$null
    info "Current llama-cpp-python: $CurrentVer"
} catch {
    warn "llama-cpp-python not yet installed"
    $CurrentVer = ""
}

# ── 4. Confirm ───────────────────────────────────────────────────────────────
$InstallSpec = "llama-cpp-python @ git+https://github.com/abetlen/llama-cpp-python.git@$GitRef"

Write-Host ""
Write-Host "About to compile llama-cpp-python from source:"
Write-Host "  GPU backend : $GpuLabel"
Write-Host "  CMAKE_ARGS  : $CmakeArgs"
Write-Host "  Git ref     : $GitRef"
Write-Host "  Spec        : $InstallSpec"
Write-Host ""
Write-Host "Estimated time: ~5-15 min (CUDA), ~3-8 min (CPU-only)"
Write-Host ""

if (-not $Yes) {
    $reply = Read-Host "Proceed? [y/N]"
    if ($reply -notmatch '^[Yy]$') { info "Cancelled — no changes made."; exit 0 }
}

# ── 5. Build ─────────────────────────────────────────────────────────────────
info "Starting compilation…"
$env:CMAKE_ARGS = $CmakeArgs
$env:FORCE_CMAKE = "1"

& uv pip install --upgrade --force-reinstall --no-cache-dir $InstallSpec
if ($LASTEXITCODE -ne 0) {
    fatal "Compilation failed. Check: VS Build Tools with C++ installed; CUDA Toolkit for GPU; github.com accessible."
}

$NewVer = & $PythonPath -c "import llama_cpp; print(llama_cpp.__version__)" 2>$null
info "Build complete — llama-cpp-python $NewVer"

# ── 6. Verify ────────────────────────────────────────────────────────────────
info "Verifying import…"
& $PythonPath -c "import llama_cpp; print('  version:', llama_cpp.__version__)"

# ── 7. Custom packages list ──────────────────────────────────────────────────
if (-not $NoCustomList) {
    if (Test-Path $CustomList) {
        $content = Get-Content $CustomList
        if ($content -notcontains "llama_cpp_python") {
            Add-Content $CustomList "llama_cpp_python"
            info "Added llama_cpp_python to $CustomList"
        } else {
            info "$CustomList already contains llama_cpp_python"
        }
    } else {
        warn "$CustomList not found — AI-142 protection not active. Custom build may be overwritten by future uv sync."
    }
}

Pop-Location
Write-Host ""
info "SSM setup complete."
info "Use .\scripts\safe-sync.ps1 to update dependencies without losing this build."
