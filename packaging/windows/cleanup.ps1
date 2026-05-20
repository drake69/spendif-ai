<#
.SYNOPSIS
    Spendif.ai — total cleanup on Windows.

.DESCRIPTION
    Uninstalls the MSIX package via Remove-AppxPackage, wipes user
    data, the Hugging Face model cache, and all logs. After running
    this script the next install behaves like a brand new install:
    re-download model, full onboarding wizard, fresh DB.

    The optional dev-install self-signed cert is preserved by default
    (re-using it on the next install avoids re-prompting the trust UI).
    Pass `-RemoveDevCert` to wipe that too.

.PARAMETER Yes
    Skip the confirmation prompt.

.PARAMETER KeepModels
    Preserve `$HOME\.cache\huggingface` (the Hugging Face model cache
    where the GGUF lives during download). The next install will not
    re-download if a model is already present.

.PARAMETER RemoveDevCert
    Also remove the self-signed `CN=SpendifAi Dev` certificate created
    by dev-install.ps1, from CurrentUser\My and LocalMachine\{TrustedPeople,Root}.

.EXAMPLE
    .\packaging\windows\cleanup.ps1
    .\packaging\windows\cleanup.ps1 -Yes -KeepModels
    .\packaging\windows\cleanup.ps1 -Yes -RemoveDevCert

.NOTES
    Auto-elevates if needed for cert store operations or AppX removal
    in restricted contexts.
#>
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$KeepModels,
    [switch]$RemoveDevCert
)

$ErrorActionPreference = "Stop"

# ── Auto-elevate when manipulating LocalMachine cert stores ────────────────
if ($RemoveDevCert) {
    $identity = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "▸ Relaunching as Administrator (required for -RemoveDevCert)..."
        $argv = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
        if ($Yes)           { $argv += "-Yes" }
        if ($KeepModels)    { $argv += "-KeepModels" }
        if ($RemoveDevCert) { $argv += "-RemoveDevCert" }
        Start-Process powershell -Verb RunAs -ArgumentList $argv -Wait
        exit 0
    }
}

# ── What we are about to wipe ───────────────────────────────────────────────
$Targets = @()
$pkg = Get-AppxPackage -Name SpendifAi -ErrorAction SilentlyContinue
if ($pkg) { $Targets += "AppX package: $($pkg.Name) $($pkg.Version)" }
$paths = @(
    "$HOME\.spendifai",
    "$HOME\AppData\Roaming\Spendif.ai",
    "$HOME\AppData\Local\Spendif.ai"
)
foreach ($p in $paths) {
    if (Test-Path $p) { $Targets += $p }
}
if (-not $KeepModels) {
    $hfCache = "$HOME\.cache\huggingface"
    if (Test-Path $hfCache) { $Targets += $hfCache }
}
if ($RemoveDevCert) {
    $Targets += "self-signed cert: CN=SpendifAi Dev"
}

if ($Targets.Count -eq 0) {
    Write-Host "✔ Nothing to clean — Spendif.ai is not installed and has no user data."
    exit 0
}

Write-Host "Spendif.ai — total cleanup"
Write-Host "About to remove:"
foreach ($t in $Targets) { Write-Host "  - $t" }

# ── Confirmation ───────────────────────────────────────────────────────────
if (-not $Yes) {
    Write-Host ""
    $reply = Read-Host "Proceed? [y/N]"
    if ($reply -notmatch '^[yY]') {
        Write-Host "Aborted."
        exit 1
    }
}

# ── 1. Kill running processes ───────────────────────────────────────────────
Write-Host ""
Write-Host "▸ Killing running SpendifAi / Streamlit processes..."
Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -match 'SpendifAi|streamlit|pythonw?' -and $_.Path -match 'SpendifAi' } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500
Write-Host "  ✔ done"

# ── 2. Uninstall AppX ──────────────────────────────────────────────────────
if ($pkg) {
    Write-Host "▸ Removing AppX package $($pkg.Name) $($pkg.Version)..."
    Remove-AppxPackage -Package $pkg.PackageFullName
}

# ── 3. Remove user data dirs ───────────────────────────────────────────────
foreach ($p in $paths) {
    if (Test-Path $p) {
        Write-Host "▸ Remove $p"
        Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue
    }
}
if (-not $KeepModels) {
    $hfCache = "$HOME\.cache\huggingface"
    if (Test-Path $hfCache) {
        Write-Host "▸ Remove $hfCache"
        Remove-Item -Recurse -Force $hfCache -ErrorAction SilentlyContinue
    }
}

# ── 4. Remove dev cert (optional) ──────────────────────────────────────────
if ($RemoveDevCert) {
    $subject = "CN=SpendifAi Dev, O=Spendif.ai, C=IT"
    foreach ($store in @("Cert:\CurrentUser\My",
                         "Cert:\LocalMachine\TrustedPeople",
                         "Cert:\LocalMachine\Root")) {
        Get-ChildItem $store -ErrorAction SilentlyContinue |
            Where-Object Subject -eq $subject |
            ForEach-Object {
                Write-Host "▸ Remove cert from $store (thumbprint $($_.Thumbprint))"
                Remove-Item $_.PSPath -ErrorAction SilentlyContinue
            }
    }
}

# ── 5. Result ──────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "✔ Spendif.ai cleanup complete."
if ($KeepModels) {
    Write-Host "  (Hugging Face model cache preserved — first launch will not re-download.)"
} else {
    Write-Host "  Next install will perform a fresh model download (~3 GB)."
}
