# Spendif.ai — Desktop build & test loop

> 🇮🇹 [Leggi in italiano](desktop_build_and_test.it.md)

This document is the **dev/test loop** for the native desktop bundle:
how to build a DMG locally, how to get a Windows MSIX from CI without
publishing a release, how to sign and install it on a clean Windows VM,
and where to look when something dies silently.

For the **public release** workflow (tagging, signing for distribution,
publishing on Homebrew / winget) see
[release_process.md](release_process.md) instead.

---

## 1. Local DMG build (macOS, Apple Silicon)

Used during the iterate-test-fix loop on the host machine.

```bash
cd sw_artifacts
bash packaging/macos/build-dmg.sh
```

Output: `build/SpendifAi-<VERSION>.dmg` (≈140 MB, ad-hoc signed by
PyInstaller).

To skip PyInstaller (much faster when only `packaging/macos/*` changed):

```bash
bash packaging/macos/build-dmg.sh --skip-pyinstaller
```

The script also leaves `dist/SpendifAi.app/` — the unpacked bundle you
can launch directly without going through the DMG:

```bash
open dist/SpendifAi.app
```

Cross-arch note: the resulting binary is `arm64` only. To produce an
`x86_64` build you must run PyInstaller on an Intel Mac (or under
Rosetta with an x86_64 venv). The `release.yml` CI job builds on
`macos-latest` which today is Apple Silicon — same constraint.

---

## 2. Windows MSIX from CI (no public release)

PyInstaller does not cross-compile to Windows, so MSIX must be built on
a Windows runner. The cheapest path is `workflow_dispatch` on the
existing `release.yml` workflow — produces all four installer artefacts
(DMG, MSIX, .deb, .rpm) and uploads them to the workflow run, **without**
creating a GitHub Release.

```bash
gh workflow run release.yml --ref <your-branch> -f version=0.1.0
```

Use a version that is valid for **every** target format:

| Format | Allowed |
|---|---|
| DMG / `.app` | anything (filename only) |
| MSIX | `X.Y.Z.W` — four numeric components, **no** dashes or letters |
| `.deb` | `X.Y.Z` recommended, dashes tolerated but discouraged |
| `.rpm` | `X.Y.Z` only, **no dashes** (`-` forbidden in `Version:`) |

→ Stick to plain `MAJOR.MINOR.PATCH` for `workflow_dispatch` runs
(`0.1.0`, `0.2.0-rc1` will break RPM and MSIX).

Once the run finishes (15–20 min):

```bash
# List runs to find the one you triggered
gh run list --workflow=release.yml --limit 5

# Download the MSIX (or any other artefact)
gh run download <RUN_ID> --name windows-msix --dir dist/

# Available artefact names per run:
#   windows-msix   →  SpendifAi-<ver>.msix
#   macos-dmg      →  SpendifAi-<ver>.dmg
#   deb-package    →  spendifai_<ver>_amd64.deb
#   rpm-package    →  spendifai-<ver>-1.x86_64.rpm  (currently failing — see §6)
```

---

## 3. Installing the MSIX on a Windows VM

The MSIX produced by CI is **unsigned**. Windows refuses to install
unsigned packages with `0x800B010A — TRUST_E_CHAIN_BUILD_INVALID`.

For development / testing on a VM, `packaging/windows/dev-install.ps1`
generates a self-signed certificate matching the manifest's Publisher
CN, imports it as trusted, signs the MSIX with SignTool, and installs.
It is idempotent — re-running after a new MSIX build just re-signs and
re-installs.

```powershell
# Copy dev-install.ps1 + SpendifAi-<ver>.msix to the VM in the same folder.
# Then in PowerShell (no admin needed — auto-elevates):
.\dev-install.ps1
```

What it does (each step is no-op if already satisfied):

1. Locates the MSIX (newest `SpendifAi-*.msix` in cwd or `-Msix` arg).
2. Auto-elevates if not running as Administrator.
3. Generates `CN=SpendifAi Dev, O=Spendif.ai, C=IT` cert in
   `Cert:\CurrentUser\My`. Reuses if already present and not expired.
4. Exports `spendifai-dev.pfx` and `.cer` to the Desktop.
5. Imports the cert into `Cert:\LocalMachine\TrustedPeople` and
   `Cert:\LocalMachine\Root` so SignTool-signed packages are trusted.
6. Locates `signtool.exe` from the Windows SDK install.
7. Signs the MSIX (SHA-256, RFC 3161 timestamp).
8. Uninstalls any previous `SpendifAi` AppX package.
9. `Add-AppxPackage` to install fresh.

Prerequisite — **Windows SDK** must be installed (provides
`signtool.exe`):

```powershell
winget install Microsoft.WindowsSDK.10.0.22621
```

If the script exits with `signtool.exe not found`, that is the fix.

For **production** distribution (real cert from Sectigo / DigiCert,
notarisation if applicable) use `packaging/windows/sign-local.ps1`
instead — same code path but with a real `.pfx`.

---

## 4. Logs and debug

When something goes wrong the bundle is silent (`console=False` on
macOS bundles routes stdout/stderr to `/dev/null` by default — we
have flipped this to `console=True` for now, but the redirect into the
log files happens regardless).

| Path | Contents |
|---|---|
| `~/Library/Logs/spendifai-launcher.log` (macOS)<br>`~/.spendifai/spendifai-launcher.log` (Linux/Windows) | Bundle bootstrap: imports, splash path resolution, model download status, Streamlit start, cleanup. Truncated on every launch. |
| `~/.spendifai/logs/app_<ts>.log` | The Streamlit-side application log — `setup_logging()` in `support/logging.py`. One file per launch (timestamp in filename). |
| `~/.spendifai/model_download.status` | JSON with `pct`, `eta_remaining_s`, `done`, `error`. Updated continuously while the model is downloading. Read by the in-app banner via `st.fragment(run_every=2)`. |
| `~/.cache/huggingface/hub/` | HuggingFace's own download cache. The actual GGUF bytes live here while downloading; the file appears in `~/.spendifai/models/` only when the transfer finishes. |
| `~/Library/Logs/DiagnosticReports/SpendifAi-*.crash` (macOS) | Native crash reports if the binary dies before the log redirect catches it. |

Tail them all while testing a fresh launch:

```bash
( tail -f ~/Library/Logs/spendifai-launcher.log &
  tail -f ~/.spendifai/logs/app_*.log &
  while sleep 2; do
    cat ~/.spendifai/model_download.status 2>/dev/null | python3 -m json.tool
  done ) 2>/dev/null
```

---

## 5. Cleanup — start over

To simulate a fresh installation (most useful when testing the
onboarding wizard end-to-end):

```bash
# macOS / Linux
rm -rf ~/.spendifai/

# Windows (PowerShell)
Remove-Item -Recurse -Force $HOME\.spendifai
```

`~/.spendifai/` holds the DB (`ledger.db`), the downloaded model, the
download status file, the logs and the `.env`. Nuking it forces:

- First-launch immersive page (no sidebar)
- Model re-download from HuggingFace (≈3 GB, 5–15 min)
- Full 4-step onboarding wizard

Keep the existing model and only wipe DB + env:

```bash
rm -f ~/.spendifai/ledger.db ~/.spendifai/.env
```

To re-trigger only the onboarding wizard, delete the row in
`user_settings` with key `onboarding_done` (the DB stays intact):

```bash
sqlite3 ~/.spendifai/ledger.db "DELETE FROM user_settings WHERE key='onboarding_done';"
```

---

## 6. Known issues and workarounds

### RPM build fails in CI

`packaging/linux/build-rpm.sh` references `packaging/macos/spendifai_256.png`
in the `%files` section unconditionally. The file is generated by
`create_icon.py` only as part of the macOS `.icns` flow, so on the
Linux CI runner it is missing and the build aborts with `File not
found: ... spendifai.png`.

Workaround for now: skip RPM, distribute via `.deb` (which already
guards the icon copy correctly). Tracked as backlog item AI-56.

### MSIX "Unknown Publisher" warning

Even after `dev-install.ps1` imports the cert as trusted, the App
Installer UI may still show "Publisher: Unknown" briefly before
recognising the trust. Click `Install` anyway — installation succeeds.
The message disappears at the next reboot.

### App "reopens" during a long model download

Symptom: closing the pywebview window does not really kill the app;
double-clicking the icon a few minutes later finds the previous
instance still running. The current launcher kills the Streamlit
process tree via `os.killpg` on exit, so this should no longer happen
after the first install of this build. If you still see it, kill
manually:

```bash
ps aux | awk '/SpendifAi/ && !/grep/ {print $2}' | xargs kill -9
```

### Self-signed cert expires

The cert generated by `dev-install.ps1` expires after 3 years. When
that happens, regenerate by deleting it first:

```powershell
Get-ChildItem Cert:\CurrentUser\My |
    Where-Object Subject -eq "CN=SpendifAi Dev, O=Spendif.ai, C=IT" |
    Remove-Item
.\dev-install.ps1
```

---

## 7. Quick reference

```bash
# macOS — build + launch local
cd sw_artifacts
bash packaging/macos/build-dmg.sh                # ~5-10 min
open dist/SpendifAi.app                           # launch unpacked
# or
open build/SpendifAi-*.dmg                        # mount DMG → drag to /Applications

# CI artifacts — no public release
gh workflow run release.yml --ref $(git branch --show-current) -f version=0.1.0
# wait ~15 min, then
gh run download $(gh run list --workflow=release.yml --limit 1 --json databaseId -q '.[0].databaseId') --dir dist/

# Windows VM — install MSIX
# (in PowerShell, in the folder containing SpendifAi-*.msix and dev-install.ps1)
.\dev-install.ps1

# Logs
tail -f ~/Library/Logs/spendifai-launcher.log
tail -f ~/.spendifai/logs/app_*.log
cat ~/.spendifai/model_download.status | python3 -m json.tool

# Fresh-state simulation
rm -rf ~/.spendifai/
```
