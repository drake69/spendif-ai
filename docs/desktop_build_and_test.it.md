# Spendif.ai — Loop di build e test desktop

> 🇬🇧 [Read in English](desktop_build_and_test.md)

Questo documento descrive il **dev/test loop** del bundle desktop nativo:
come buildare un DMG in locale, come ottenere un MSIX Windows dalla CI
senza pubblicare una release, come firmarlo e installarlo su una VM
Windows pulita, e dove guardare quando muore in silenzio.

Per il flusso di **release pubblica** (tag, firma per distribuzione,
pubblicazione su Homebrew / winget) vedi
[release_process.it.md](release_process.it.md).

---

## 1. Build DMG locale (macOS, Apple Silicon)

Usato durante il ciclo itera-testa-fixa sulla macchina host.

```bash
cd sw_artifacts
bash packaging/macos/build-dmg.sh
```

Output: `build/SpendifAi-<VERSION>.dmg` (≈140 MB, firmato ad-hoc da
PyInstaller).

Per saltare PyInstaller (molto più rapido se modifichi solo
`packaging/macos/*`):

```bash
bash packaging/macos/build-dmg.sh --skip-pyinstaller
```

Lo script lascia anche `dist/SpendifAi.app/` — il bundle non
impacchettato che puoi lanciare direttamente senza passare dal DMG:

```bash
open dist/SpendifAi.app
```

Nota cross-arch: il binario è `arm64` puro. Per produrre una build
`x86_64` devi girare PyInstaller su un Mac Intel (o sotto Rosetta con
un venv x86_64). Anche il job CI `release.yml` builda su
`macos-latest` che oggi è Apple Silicon — stesso vincolo.

---

## 2. MSIX Windows dalla CI (senza release pubblica)

PyInstaller non cross-compila per Windows, quindi l'MSIX va buildato
su un runner Windows. Il modo più economico è `workflow_dispatch`
sul workflow `release.yml` esistente — produce tutti e quattro gli
installer (DMG, MSIX, .deb, .rpm) come artifact della run, **senza**
creare una GitHub Release.

```bash
gh workflow run release.yml --ref <tuo-branch> -f version=0.1.0
```

Usa una versione valida per **tutti** i formati target:

| Formato | Ammesso |
|---|---|
| DMG / `.app` | qualsiasi cosa (solo filename) |
| MSIX | `X.Y.Z.W` — quattro componenti numerici, **niente** trattini o lettere |
| `.deb` | `X.Y.Z` consigliato, trattini tollerati ma sconsigliati |
| `.rpm` | solo `X.Y.Z`, **niente trattini** (`-` proibito in `Version:`) |

→ Per le run `workflow_dispatch` resta su `MAJOR.MINOR.PATCH` puro
(`0.1.0`, `0.2.0-rc1` rompe RPM e MSIX).

Quando la run finisce (15–20 min):

```bash
# Lista le run per trovare la tua
gh run list --workflow=release.yml --limit 5

# Scarica l'MSIX (o qualunque altro artifact)
gh run download <RUN_ID> --name windows-msix --dir dist/

# Artifact disponibili per ogni run:
#   windows-msix   →  SpendifAi-<ver>.msix
#   macos-dmg      →  SpendifAi-<ver>.dmg
#   deb-package    →  spendifai_<ver>_amd64.deb
#   rpm-package    →  spendifai-<ver>-1.x86_64.rpm  (attualmente fallisce — vedi §6)
```

---

## 3. Installazione dell'MSIX su una VM Windows

L'MSIX prodotto dalla CI è **non firmato**. Windows rifiuta i pacchetti
non firmati con `0x800B010A — TRUST_E_CHAIN_BUILD_INVALID`.

Per lo sviluppo / test su una VM, `packaging/windows/dev-install.ps1`
genera un certificato self-signed col CN che combacia col Publisher del
manifest, lo importa come trusted, firma l'MSIX con SignTool e installa.
È idempotente — rilanciandolo dopo una nuova build dell'MSIX rifà solo
firma + install.

```powershell
# Copia dev-install.ps1 + SpendifAi-<ver>.msix sulla VM nella stessa cartella.
# Poi in PowerShell (non serve admin — fa auto-elevate):
.\dev-install.ps1
```

Cosa fa (ogni passo è no-op se già soddisfatto):

1. Trova l'MSIX (il più recente `SpendifAi-*.msix` nella cwd, o passa `-Msix`).
2. Auto-elevazione se non è admin.
3. Genera cert `CN=SpendifAi Dev, O=Spendif.ai, C=IT` in
   `Cert:\CurrentUser\My`. Riusa se già presente e non scaduto.
4. Esporta `spendifai-dev.pfx` e `.cer` sul Desktop.
5. Importa il cert in `Cert:\LocalMachine\TrustedPeople` e
   `Cert:\LocalMachine\Root` così i pacchetti firmati col SignTool
   sono trusted.
6. Trova `signtool.exe` dall'installazione del Windows SDK.
7. Firma l'MSIX (SHA-256, timestamp RFC 3161).
8. Disinstalla qualunque versione precedente del pacchetto `SpendifAi`.
9. `Add-AppxPackage` per installare ex-novo.

Prerequisito — **Windows SDK** installato (fornisce `signtool.exe`):

```powershell
winget install Microsoft.WindowsSDK.10.0.22621
```

Se lo script muore con `signtool.exe not found`, questa è la fix.

Per la distribuzione **produzione** (cert vero da Sectigo / DigiCert,
notarizzazione se applicabile) usa `packaging/windows/sign-local.ps1`
— stesso codice ma con un `.pfx` reale.

---

## 4. Log e debug

Quando qualcosa va male il bundle è silenzioso (su macOS bundle
`console=False` redirige stdout/stderr a `/dev/null` per default — lo
abbiamo flippato a `console=True` per ora, ma la redirect verso i file
di log avviene comunque).

| Path | Contenuto |
|---|---|
| `~/Library/Logs/spendifai-launcher.log` (macOS)<br>`~/.spendifai/spendifai-launcher.log` (Linux/Windows) | Bootstrap del bundle: import, risoluzione path splash, status download modello, avvio Streamlit, cleanup. Truncato ad ogni launch. |
| `~/.spendifai/logs/app_<ts>.log` | Log lato Streamlit dell'app — `setup_logging()` in `support/logging.py`. Un file per launch (timestamp nel nome). |
| `~/.spendifai/model_download.status` | JSON con `pct`, `eta_remaining_s`, `done`, `error`. Aggiornato in continuo mentre il modello scarica. Letto dal banner in-app via `st.fragment(run_every=2)`. |
| `~/.cache/huggingface/hub/` | Cache di download interna di HuggingFace. I bytes del GGUF vivono qui durante il download; il file appare in `~/.spendifai/models/` solo a trasferimento completato. |
| `~/Library/Logs/DiagnosticReports/SpendifAi-*.crash` (macOS) | Crash report nativi se il binario muore prima che la redirect su log file scatti. |

Tail-li tutti durante un test di avvio fresh:

```bash
( tail -f ~/Library/Logs/spendifai-launcher.log &
  tail -f ~/.spendifai/logs/app_*.log &
  while sleep 2; do
    cat ~/.spendifai/model_download.status 2>/dev/null | python3 -m json.tool
  done ) 2>/dev/null
```

---

## 5. Cleanup — partire da zero

Per simulare un'installazione fresh (utile per testare il wizard
onboarding end-to-end):

```bash
# macOS / Linux
rm -rf ~/.spendifai/

# Windows (PowerShell)
Remove-Item -Recurse -Force $HOME\.spendifai
```

`~/.spendifai/` contiene il DB (`ledger.db`), il modello scaricato, il
file di stato del download, i log e il `.env`. Cancellarlo costringe:

- Pagina immersiva di primo avvio (no sidebar)
- Ri-download del modello da HuggingFace (≈3 GB, 5–15 min)
- Wizard onboarding completo a 4 step

Mantieni il modello esistente e ripulisci solo DB + env:

```bash
rm -f ~/.spendifai/ledger.db ~/.spendifai/.env
```

Per riattivare solo il wizard onboarding, elimina la riga in
`user_settings` con chiave `onboarding_done` (il DB resta intatto):

```bash
sqlite3 ~/.spendifai/ledger.db "DELETE FROM user_settings WHERE key='onboarding_done';"
```

---

## 6. Issue note e workaround

### La build RPM in CI fallisce

`packaging/linux/build-rpm.sh` riferisce `packaging/macos/spendifai_256.png`
nella sezione `%files` in modo non condizionale. Il file è generato da
`create_icon.py` solo come parte del flusso macOS `.icns`, quindi sul
runner Linux della CI manca e la build si interrompe con `File not
found: ... spendifai.png`.

Workaround attuale: salta RPM, distribuisci via `.deb` (che già
gestisce correttamente la presenza opzionale dell'icona). Tracciato
come item di backlog AI-56.

### MSIX "Editore sconosciuto"

Anche dopo che `dev-install.ps1` importa il cert come trusted, la UI
App Installer può comunque mostrare "Editore: Sconosciuto" brevemente
prima di riconoscere la fiducia. Clicca `Installa` lo stesso —
l'installazione riesce. Il messaggio sparisce al prossimo riavvio.

### L'app "si riapre" durante un download lungo del modello

Sintomo: chiudere la finestra pywebview non uccide davvero l'app;
doppio-cliccando l'icona qualche minuto dopo trovi l'istanza
precedente ancora viva. Il launcher corrente uccide l'albero di
processi Streamlit via `os.killpg` all'uscita, quindi questo non
dovrebbe più accadere dopo il primo install di questa build. Se lo
vedi ancora, kill manuale:

```bash
ps aux | awk '/SpendifAi/ && !/grep/ {print $2}' | xargs kill -9
```

### Scadenza cert self-signed

Il cert generato da `dev-install.ps1` scade dopo 3 anni. Quando
succede, rigenera cancellandolo prima:

```powershell
Get-ChildItem Cert:\CurrentUser\My |
    Where-Object Subject -eq "CN=SpendifAi Dev, O=Spendif.ai, C=IT" |
    Remove-Item
.\dev-install.ps1
```

---

## 7. Riferimento rapido

```bash
# macOS — build + launch in locale
cd sw_artifacts
bash packaging/macos/build-dmg.sh                # ~5-10 min
open dist/SpendifAi.app                           # lancia unpacked
# oppure
open build/SpendifAi-*.dmg                        # monta DMG → trascina in /Applications

# Artifact dalla CI — senza release pubblica
gh workflow run release.yml --ref $(git branch --show-current) -f version=0.1.0
# aspetta ~15 min, poi
gh run download $(gh run list --workflow=release.yml --limit 1 --json databaseId -q '.[0].databaseId') --dir dist/

# VM Windows — installa MSIX
# (in PowerShell, nella cartella con SpendifAi-*.msix e dev-install.ps1)
.\dev-install.ps1

# Log
tail -f ~/Library/Logs/spendifai-launcher.log
tail -f ~/.spendifai/logs/app_*.log
cat ~/.spendifai/model_download.status | python3 -m json.tool

# Simulazione stato fresh
rm -rf ~/.spendifai/
```
