# Build di prova

Come scaricare una build di prova di Spendif.ai, avviarla su ciascun sistema supportato e mandare il resoconto che spunta la tua configurazione nella [matrice di prova](compatibility.it.md#matrice-di-prova).

Le build di prova escono dal branch `develop`, prima di una release. Portano la versione da cui sono state costruite, per esempio `0.3.1+ga3a4c1a`: la parte dopo `+g` è il commit. L'applicazione non propone mai loro un aggiornamento.

> [!NOTE]
> Le build restano disponibili per 14 giorni. Per scaricarle serve un account GitHub (uno qualunque, con l'accesso fatto), perché GitHub consegna i file delle build solo a chi ha fatto l'accesso. Senza il comando `gh`, apri l'[elenco delle build](https://github.com/spendifai/spendif-ai/actions/workflows/build-llama-wheels.yml?query=branch%3Adevelop+is%3Asuccess), scegli la più recente e scarica il file dal fondo della pagina.

## 1. Scegli la tua configurazione

| Sistema | Architettura | Cosa scarichi | Sezione |
|---|---|---|---|
| Debian 12 e 13, Ubuntu 22.04 e successive, Linux Mint 21 e successive | amd64 (x86_64) | `spendifai-deb-amd64` | [2](#2-debian-ubuntu-linux-mint-deb) |
| Debian 12 e 13, Ubuntu 22.04 e successive | arm64 (aarch64) | `spendifai-deb-arm64` | [2](#2-debian-ubuntu-linux-mint-deb) |
| Fedora, Arch Linux, qualunque altra distribuzione con glibc 2.35 o successiva | amd64 | `linux-bundle-amd64` | [3](#3-fedora-arch-linux-e-altre-distribuzioni-cartella) |
| Fedora, Arch Linux, qualunque altra distribuzione con glibc 2.35 o successiva | arm64 | `linux-bundle-arm64` | [3](#3-fedora-arch-linux-e-altre-distribuzioni-cartella) |
| Windows 10 e 11 | x64 | `windows-bundle-x64` | [4](#4-windows-x64-cartella) |

La tua architettura: `uname -m` su Linux (`x86_64` è amd64, `aarch64` è arm64). Windows su ARM non è coperto: lì il modello locale non gira.

Fedora e Arch per ora ricevono la cartella invece di un pacchetto: il loro `.rpm` e il `PKGBUILD` non sono ancora passati alla build autosufficiente.

## 2. Debian, Ubuntu, Linux Mint (.deb)

```bash
# Installa una volta il comando di GitHub e fai l'accesso
sudo apt install gh
gh auth login

# L'ultima build di prova riuscita
REPO=spendifai/spendif-ai
RUN=$(gh run list -R "$REPO" --workflow build-llama-wheels.yml --branch develop \
      --status success -L 1 --json databaseId -q '.[0].databaseId')

# Il pacchetto per questa macchina
ARCH=$(dpkg --print-architecture)          # amd64 oppure arm64
rm -rf /tmp/spendifai && gh run download "$RUN" -R "$REPO" -n "spendifai-deb-$ARCH" -D /tmp/spendifai

# Installa
sudo apt install /tmp/spendifai/spendifai_*.deb
```

**Avvio:** dal menu delle applicazioni, **Spendif.ai**. L'interfaccia si apre nel browser: su Linux non c'è una finestra a parte. Da terminale: `/opt/spendifai/launch.sh`.

**Scheda grafica:** l'accelerazione richiede un driver Vulkan.

```bash
sudo apt install mesa-vulkan-drivers vulkan-tools    # AMD e Intel; il driver proprietario NVIDIA include Vulkan
vulkaninfo --summary                                 # elenca la tua scheda se il driver c'è
```

**Disinstallazione:**

```bash
sudo apt remove spendifai
```

I tuoi dati restano in `~/.spendifai`. Cancella quella cartella solo se contiene soltanto dati di prova.

## 3. Fedora, Arch Linux e altre distribuzioni (cartella)

La cartella funziona dove la metti, senza installazione.

```bash
# Installa una volta il comando di GitHub e fai l'accesso
sudo dnf install gh        # Fedora
sudo pacman -S github-cli  # Arch
gh auth login

REPO=spendifai/spendif-ai
RUN=$(gh run list -R "$REPO" --workflow build-llama-wheels.yml --branch develop \
      --status success -L 1 --json databaseId -q '.[0].databaseId')

case "$(uname -m)" in x86_64) ARCH=amd64 ;; aarch64) ARCH=arm64 ;; esac
rm -rf ~/SpendifAi-test && gh run download "$RUN" -R "$REPO" -n "linux-bundle-$ARCH" -D ~/SpendifAi-test

# Lo scaricamento perde il permesso di esecuzione
chmod +x ~/SpendifAi-test/SpendifAi
```

**Avvio:** `~/SpendifAi-test/SpendifAi`. L'interfaccia si apre nel browser.

**Scheda grafica:**

```bash
# Fedora
sudo dnf install vulkan-loader mesa-vulkan-drivers vulkan-tools
# Arch, AMD
sudo pacman -S vulkan-icd-loader vulkan-radeon vulkan-tools
# Arch, NVIDIA (con il driver nvidia)
sudo pacman -S vulkan-icd-loader nvidia-utils vulkan-tools

vulkaninfo --summary
```

**Disinstallazione:** `rm -rf ~/SpendifAi-test`. I tuoi dati restano in `~/.spendifai`.

Per il resoconto, una cartella conta come installata quando parte, e come disinstallata quando la cancelli. Non c'è una voce di menu: spunta "Started" se è partita dal file.

## 4. Windows x64 (cartella)

In PowerShell:

```powershell
# Installa una volta il comando di GitHub e fai l'accesso
winget install --id GitHub.cli
gh auth login

$REPO = "spendifai/spendif-ai"
$RUN = gh run list -R $REPO --workflow build-llama-wheels.yml --branch develop `
       --status success -L 1 --json databaseId -q '.[0].databaseId'

$DEST = "$HOME\SpendifAi-test"
if (Test-Path $DEST) { Remove-Item -Recurse -Force $DEST }
gh run download $RUN -R $REPO -n windows-bundle-x64 -D $DEST

& "$DEST\SpendifAi.exe"
```

La build non è firmata. Se Windows SmartScreen la blocca: **Ulteriori informazioni**, poi **Esegui comunque**. Se invece hai scaricato lo zip dal browser, tasto destro, **Proprietà**, spunta **Annulla blocco**, poi estrai.

**Scheda grafica:** il driver Vulkan arriva con il driver della scheda (NVIDIA, AMD, Intel). Non c'è niente da installare a parte.

**Disinstallazione:** cancella la cartella, `Remove-Item -Recurse -Force "$HOME\SpendifAi-test"`. I tuoi dati restano in `%USERPROFILE%\.spendifai`.

Non c'è una voce nel menu Start: spunta "Started" se è partita dal file.

## 5. Fai la prova e manda il resoconto

1. Avvia l'applicazione e scarica il modello suggerito, se te lo chiede.
2. Importa un estratto conto della banca o della carta.
3. Apri **Diagnostica** dal menu. Alla voce **Motori di calcolo attivi**, `Vulkan0` vuol dire che lavora la scheda grafica; solo `CPU` vuol dire che lavora il processore.
4. Manda il resoconto, in uno dei due modi:
   - **Con un account GitHub:** **Invia come resoconto di prova su GitHub**. Si apre un modulo con il documento già dentro. Spunta i passi riusciti e invia.
   - **Senza:** **Salva il documento**, poi il link email sotto il pulsante. L'email arriva con un elenco di caselle: metti una `x` tra le parentesi di ogni passo riuscito, così `[x]`, allega il documento salvato e invia.
5. Disinstalla (sezione 2, 3 o 4) e, su GitHub, modifica la issue per spuntare **Uninstalled cleanly**. Via email, rispondi al tuo stesso messaggio con la casella spuntata.

I quattro passi (le etichette restano in inglese, come nel modulo):

| Passo | Si spunta quando |
|---|---|
| Installed | il pacchetto si è installato, o la cartella è partita |
| Started from the application menu or icon | l'interfaccia si è aperta |
| Imported a statement | un estratto conto è passato e i movimenti hanno ricevuto la categoria |
| Uninstalled cleanly | il pacchetto è stato rimosso, o la cartella cancellata, senza errori |

Una configurazione riceve ✅ nella matrice quando un resoconto li ha tutti e quattro, e ◐ quando è arrivato un resoconto con qualche passo mancante.

## Per chi mantiene il progetto: un resoconto arrivato via email

Salva l'email come file `.eml` (trascinala fuori dal client di posta), poi:

```bash
python3 scripts/compat_report.py --mail ~/Downloads/report.eml \
    --store docs/compatibility/reports.jsonl --docs docs
```

Legge il documento allegato e le caselle spuntate con gli stessi controlli del modulo delle issue, e riscrive `docs/compatibility.md` e `docs/compatibility.it.md`. Committali in una pull request verso `develop`. Un documento senza la sua email: `--xml report.xml --outcomes installed,started,imported,uninstalled`.

Le configurazioni della matrice stanno in [`docs/compatibility/matrix.json`](compatibility/matrix.json).
