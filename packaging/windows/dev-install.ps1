<#
.SYNOPSIS
    Spendif.ai — one-shot dev install on Windows from an unsigned MSIX.

.DESCRIPTION
    Build artefacts shipped by the CI (`Build Windows MSIX` job) are
    deliberately unsigned — the hybrid signing model has the owner sign
    locally before publishing. Until that owner cert exists, testers
    (and the developer themselves) cannot install the MSIX because
    Windows rejects it with `0x800B010A` (cert chain invalid).

    This script does, idempotently:

    1. Generates a self-signed Code Signing certificate whose Subject CN
       matches the Publisher declared in our AppxManifest exactly. If
       the cert already exists in the current user store it is reused.
    2. Exports it to .pfx + .cer on the desktop.
    3. Imports the .cer into LocalMachine\TrustedPeople and ...\Root so
       Windows trusts MSIX packages signed with it. Requires admin —
       the script auto-elevates if not already.
    4. Locates SignTool.exe from the Windows SDK and signs the MSIX.
    5. Installs the MSIX via Add-AppxPackage (uninstall + reinstall
       if a previous version of SpendifAi is already installed).

    Re-running the script after a new MSIX build is safe: cert reuse,
    re-sign, re-install.

.PARAMETER Msix
    Path to the .msix file to install. Default: tries
    .\SpendifAi-*.msix in the current directory, picks the newest.

.PARAMETER Password
    Password used for the .pfx export. Defaults to "spendif-dev".
    Pick anything reasonable — it never leaves your machine.

.PARAMETER PublisherCN
    Subject CN of the self-signed cert. MUST match the manifest's
    Publisher attribute exactly. Default matches the value baked into
    `packaging/windows/AppxManifest.xml.in`: "CN=SpendifAi Dev, O=Spendif.ai, C=IT".

.PARAMETER NoInstall
    Skip the final `Add-AppxPackage`. Useful when you only want to
    sign the file (for example to test the signature on a different VM).

.EXAMPLE
    # Most common: drop the MSIX in the same folder and run.
    .\packaging\windows\dev-install.ps1

.EXAMPLE
    .\packaging\windows\dev-install.ps1 -Msix C:\Downloads\SpendifAi-0.1.0.msix

.NOTES
    Self-signed certs are for development / sideload only. For real
    distribution buy an OV ($200/yr) or EV ($400/yr) Code Signing cert
    and use packaging/windows/sign-local.ps1 instead.
#>
[CmdletBinding()]
param(
    [string]$Msix = "",
    [string]$Password = "spendif-dev",
    [string]$PublisherCN = "CN=SpendifAi Dev, O=Spendif.ai, C=IT",
    [switch]$NoInstall
)

$ErrorActionPreference = "Stop"

# ── 0. Locate MSIX ────────────────────────────────────────────────────────────
if (-not $Msix) {
    $candidate = Get-ChildItem -Path . -Filter "SpendifAi-*.msix" -ErrorAction SilentlyContinue |
                 Sort-Object LastWriteTime -Descending |
                 Select-Object -First 1
    if ($candidate) {
        $Msix = $candidate.FullName
    } else {
        throw "No SpendifAi-*.msix found in current directory. Pass -Msix <path>."
    }
}
if (-not (Test-Path $Msix)) {
    throw "MSIX not found: $Msix"
}
$Msix = (Get-Item $Msix).FullName
Write-Host "▸ MSIX: $Msix"

# ── 1. Self-elevate if not admin ──────────────────────────────────────────────
$identity = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "▸ Not running as Administrator — relaunching elevated..."
    $argv = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-Msix", "`"$Msix`"",
        "-Password", "`"$Password`"",
        "-PublisherCN", "`"$PublisherCN`""
    )
    if ($NoInstall) { $argv += "-NoInstall" }
    Start-Process powershell -Verb RunAs -ArgumentList $argv -Wait
    exit 0
}

# ── 2. Cert: reuse or generate ────────────────────────────────────────────────
$existing = Get-ChildItem Cert:\CurrentUser\My |
    Where-Object { $_.Subject -eq $PublisherCN -and $_.NotAfter -gt (Get-Date) }
if ($existing) {
    $cert = $existing | Select-Object -First 1
    Write-Host "▸ Reusing existing cert (thumbprint $($cert.Thumbprint), expires $($cert.NotAfter.ToString('yyyy-MM-dd')))"
} else {
    Write-Host "▸ Generating self-signed cert: $PublisherCN"
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $PublisherCN `
        -KeyUsage DigitalSignature `
        -FriendlyName "Spendif.ai Dev" `
        -CertStoreLocation Cert:\CurrentUser\My `
        -NotAfter (Get-Date).AddYears(3) `
        -TextExtension @(
            "2.5.29.37={text}1.3.6.1.5.5.7.3.3",  # EKU: Code Signing
            "2.5.29.19={text}"                       # BasicConstraints
        )
    Write-Host "  ✔ Generated (thumbprint $($cert.Thumbprint))"
}

# ── 3. Export cert files ──────────────────────────────────────────────────────
$desk = [Environment]::GetFolderPath('Desktop')
$pfxPath = Join-Path $desk "spendifai-dev.pfx"
$cerPath = Join-Path $desk "spendifai-dev.cer"
$pwdSec = ConvertTo-SecureString -String $Password -Force -AsPlainText

Write-Host "▸ Exporting cert → $pfxPath / $cerPath"
Export-PfxCertificate -Cert "Cert:\CurrentUser\My\$($cert.Thumbprint)" -FilePath $pfxPath -Password $pwdSec | Out-Null
Export-Certificate -Cert "Cert:\CurrentUser\My\$($cert.Thumbprint)" -FilePath $cerPath | Out-Null

# ── 4. Trust the cert ─────────────────────────────────────────────────────────
foreach ($store in @("Cert:\LocalMachine\TrustedPeople", "Cert:\LocalMachine\Root")) {
    $alreadyThere = Get-ChildItem $store -ErrorAction SilentlyContinue |
        Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
    if ($alreadyThere) {
        Write-Host "▸ Already trusted in $store"
    } else {
        Write-Host "▸ Importing cert into $store"
        Import-Certificate -FilePath $cerPath -CertStoreLocation $store | Out-Null
    }
}

# ── 5. Locate SignTool.exe ────────────────────────────────────────────────────
$signtool = $null
foreach ($base in @("${env:ProgramFiles(x86)}\Windows Kits\10\bin",
                    "${env:ProgramFiles}\Windows Kits\10\bin")) {
    if (-not (Test-Path $base)) { continue }
    $found = Get-ChildItem -Path $base -Recurse -Filter "signtool.exe" -ErrorAction SilentlyContinue |
             Where-Object { $_.FullName -match "\\x64\\" } |
             Sort-Object FullName -Descending |
             Select-Object -First 1
    if ($found) { $signtool = $found.FullName; break }
}
if (-not $signtool) {
    throw "signtool.exe not found. Install Windows SDK:`n  winget install Microsoft.WindowsSDK.10.0.22621"
}
Write-Host "▸ SignTool: $signtool"

# ── 6. Sign the MSIX ──────────────────────────────────────────────────────────
Write-Host "▸ Signing $Msix"
& $signtool sign `
    /fd SHA256 /a `
    /f $pfxPath /p $Password `
    /tr "http://timestamp.digicert.com" /td SHA256 `
    $Msix
if ($LASTEXITCODE -ne 0) { throw "SignTool failed (exit $LASTEXITCODE)" }

& $signtool verify /pa /v $Msix
if ($LASTEXITCODE -ne 0) { throw "Signature verification failed" }

# ── 7. Install ────────────────────────────────────────────────────────────────
if ($NoInstall) {
    Write-Host ""
    Write-Host "✔ MSIX signed: $Msix"
    Write-Host "  (skipping Add-AppxPackage because -NoInstall was passed)"
    exit 0
}

# Best-effort uninstall of any previous version so we re-install cleanly.
$existingPkg = Get-AppxPackage -Name SpendifAi -ErrorAction SilentlyContinue
if ($existingPkg) {
    Write-Host "▸ Removing existing SpendifAi $($existingPkg.Version)"
    Remove-AppxPackage -Package $existingPkg.PackageFullName
}

Write-Host "▸ Installing $Msix"
Add-AppxPackage -Path $Msix

$installed = Get-AppxPackage -Name SpendifAi -ErrorAction SilentlyContinue
if ($installed) {
    Write-Host ""
    Write-Host "✔ Installed: $($installed.Name) $($installed.Version)"
    Write-Host "  Launch from Start Menu → Spendif.ai"
} else {
    throw "Add-AppxPackage succeeded but the package is not listed. Check Event Viewer → Apps and Services Logs → Microsoft → Windows → AppxDeploymentServer."
}
