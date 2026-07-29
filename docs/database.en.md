# Spendif.ai — Database management

> Spendif.ai's database is a single SQLite file (`ledger.db`).
> This guide covers everything related to data: where it is located, how to back it up, how to restore it, and how to move it to another computer.

---

## Table of contents

1. [What the database contains](#1--what-the-database-contains)
2. [Where the database is located](#2--where-the-database-is-located)
3. [Backup](#3--backup)
4. [Restore](#4--restore)
5. [First launch with an existing database](#5--first-launch-with-an-existing-database)
6. [Moving the database to another computer](#6--moving-the-database-to-another-computer)
7. [Direct inspection (sqlite3)](#7--direct-inspection-sqlite3)
8. [Database corruption](#8--database-corruption)

---

## 1 — What the database contains

The `ledger.db` file contains **everything** — there are no other data files to consider for backup:

| Table | Contents |
|-------|----------|
| `transaction` | All imported transactions |
| `category_rule` | Deterministic categorisation rules |
| `description_rule` | Description cleaning rules |
| `document_schema` | CSV/XLSX file schemas (columns, format, etc.). Schemas without `header_sha256` are automatically purged on startup (`_migrate_purge_orphan_schemas` migration). At runtime, schemas with parse rate < 10% are auto-invalidated and deleted. |
| `user_settings` | User settings (LLM, locale, date format, contexts, onboarding flag…) |
| `account` | User-defined bank accounts (name + bank) |
| `taxonomy_category` / `taxonomy_subcategory` | Editable user taxonomy |
| `taxonomy_default` | Built-in taxonomy templates (5 languages — do not modify directly) |
| `reconciliation_link` | Card–account links (RF-03 reconciliation) |
| `internal_transfer_link` | Internal transfers (RF-04) |
| `import_batch` / `import_job` | Import history |

> Built-in taxonomy templates (`taxonomy_default`) are embedded in the source code (`db/taxonomy_defaults.py`) and are recreated from scratch by migrations on every startup. They do not need to be included in a separate backup.

---

## 2 — Where the database is located

| Installation mode | Path |
|-------------------|------|
| **Desktop app** (DMG / Windows installer / AppImage) | `~/.spendifai/ledger.db` — see the per-OS table below |
| **One-liner Docker** (`install.sh` / `install.ps1`) | Docker volume `spendifai_data` → `/app/data/ledger.db` inside the container |
| **Docker Compose from repo** | Docker volume `spendifai_data` → `/app/data/ledger.db` inside the container |
| **Native (Mac/Linux, uv)** | `./ledger.db` in the project folder |

### Desktop app: the `~/.spendifai/` folder

When you install Spendif.ai as a desktop application, all data lives in a single folder in your user home, **with the same name on every operating system**:

| Operating system | Full path |
|------------------|-----------|
| **macOS** | `/Users/<user>/.spendifai/ledger.db` |
| **Linux** | `/home/<user>/.spendifai/ledger.db` |
| **Windows** | `C:\Users\<user>\.spendifai\ledger.db` |

> On macOS/Linux the `.spendifai` folder is **hidden** (it starts with a dot): in Finder press `Cmd+Shift+.` to reveal it, in a Linux file manager press `Ctrl+H`. On Windows the folder is normally visible under your user profile.

Next to `ledger.db`, in the same folder, the app keeps other files:

| File / folder | Contents | In the backup? |
|---------------|----------|----------------|
| `ledger.db` | The SQLite database — all your data | ✅ **Always** |
| `.env` | User configuration and **API keys** (OpenAI/Anthropic) in clear text | ✅ Yes (⚠️ sensitive file) |
| `system_settings.yaml` | System settings overrides | ✅ Yes (if present) |
| `models/` | Downloaded `.gguf` LLM models (several GB) | ⛔ Optional — they re-download |
| `.schema_hash` | Internal DB schema cache | ⛔ No — see section 6 |
| `launcher.lock` | Single-instance lock | ⛔ No — never copy it |
| `logs/` | Application logs | ⛔ No |

> ⚠️ **The `.env` file contains your API keys in clear text** (no encryption): treat it like a password. If you copy the folder onto a USB stick or the cloud, those keys travel with it.

### Why is the Docker volume not a normal folder?

The `spendifai_data` volume is managed by Docker and is not directly accessible from your computer's filesystem like a normal folder. To read from or write to the volume, a temporary container must be used as a "bridge" — the commands in the following sections do exactly this.

---

## 3 — Backup

### 3.1 — Backup (native installation)

```bash
# Create the backup folder (once)
mkdir -p ~/spendifai-backup

# Copy the DB with a name that includes the date
cp ledger.db ~/spendifai-backup/ledger_$(date +%Y%m%d_%H%M%S).db
```

### 3.2 — Backup (Docker — container running)

Direct method with `docker cp`, no additional containers required:

```bash
mkdir -p ~/spendifai-backup

docker cp spendifai_app:/app/data/ledger.db \
  ~/spendifai-backup/ledger_$(date +%Y%m%d_%H%M%S).db
```

> `spendifai_app` is the container name (defined in `docker-compose.yml`).
> The container **must be running** to use `docker cp`.

### 3.3 — Backup (Docker — container stopped)

If the container is stopped, use a temporary Alpine container (lighter than Python):

```bash
mkdir -p ~/spendifai-backup

docker run --rm \
  -v spendifai_data:/data \
  -v ~/spendifai-backup:/backup \
  alpine cp /data/ledger.db /backup/ledger_$(date +%Y%m%d_%H%M%S).db
```

> **Windows (PowerShell):** replace `~/spendifai-backup` with `$env:USERPROFILE\spendifai-backup`
> and `$(date +%Y%m%d_%H%M%S)` with the date written manually, e.g. `20260317_120000`.

### 3.4 — Automatic backup (crontab, Linux/Mac)

```cron
# Backup every day at 03:00
0 3 * * * docker cp spendifai_app:/app/data/ledger.db ~/spendifai-backup/ledger_$(date +\%Y\%m\%d).db

# Delete backups older than 30 days
0 4 * * * find ~/spendifai-backup -name "ledger_*.db" -mtime +30 -delete
```

For native installation:

```cron
0 3 * * * cp /path/to/project/ledger.db ~/spendifai-backup/ledger_$(date +\%Y\%m\%d).db
0 4 * * * find ~/spendifai-backup -name "ledger_*.db" -mtime +30 -delete
```

---

## 4 — Restore

### 4.1 — Restore (native installation)

```bash
# 1. Stop the app
pkill -f "streamlit run app.py"

# 2. Save the current DB (for safety)
cp ledger.db ledger_before_restore_$(date +%Y%m%d_%H%M%S).db

# 3. Restore the chosen backup
cp ~/spendifai-backup/ledger_20260317_030000.db ledger.db

# 4. Restart
uv run streamlit run app.py
```

### 4.2 — Restore (Docker)

```bash
# 1. Stop the container
docker compose -C ~/spendifai down

# 2. Copy the backup into the volume
docker run --rm \
  -v spendifai_data:/data \
  -v ~/spendifai-backup:/backup:ro \
  alpine cp /backup/ledger_20260317_030000.db /data/ledger.db

# 3. Restart
docker compose -C ~/spendifai up -d
```

> If you installed from the repository rather than with the one-liner, replace
> `docker compose -C ~/spendifai` with `docker compose` from the project folder.

### 4.3 — Partial restore (selected tables only)

Useful if you want to recover only the categorisation rules from a backup without overwriting transactions. Requires `sqlite3` installed on the host:

```bash
sqlite3 ledger.db "
ATTACH DATABASE '/path/to/backup/ledger_20260317.db' AS bkp;
DELETE FROM category_rule;
INSERT INTO category_rule SELECT * FROM bkp.category_rule;
DETACH DATABASE bkp;
"
```

Same logic for other tables: `description_rule`, `user_settings`, `taxonomy_category`, `taxonomy_subcategory`.

---

## 5 — First launch with an existing database

If you already have a `ledger.db` (for example created with the native installation) and want to use it in the Docker container, you must copy it into the volume **before** starting the app.

```bash
# 1. Make sure the container is stopped
docker compose -C ~/spendifai down

# 2. Copy the DB into the volume
docker run --rm \
  -v spendifai_data:/data \
  -v "/absolute/path/to/ledger.db":/source/ledger.db:ro \
  alpine cp /source/ledger.db /data/ledger.db

# 3. Verify the file arrived
docker run --rm \
  -v spendifai_data:/data \
  alpine ls -lh /data/

# 4. Start the app
docker compose -C ~/spendifai up -d
```

> **Mac:** the absolute path is `/Users/yourname/spendifai/ledger.db`
> **Linux:** `/home/yourname/spendifai/ledger.db`

---

## 6 — Moving the database to another computer

The SQLite file is **portable**: it works identically on Mac, Linux and Windows, regardless of processor architecture (Intel / ARM). You can therefore go from Windows to Mac, from Linux to Windows, from one Mac to another, etc. with no conversion.

### 6.1 — Desktop app → another computer with the desktop app (the most common case)

This is the procedure for those using Spendif.ai as an installed application (not Docker), whether going from **Windows/Linux to another PC** or from **one Mac to another Mac** or across different operating systems.

**Step 1 — Close Spendif.ai** on the source computer (quit completely, do not leave it running). Copying the database while the app is writing can corrupt it.

**Step 2 — Copy the data.** Go to the `~/.spendifai/` folder (see section 2 for the exact path on your operating system) and copy these three items onto a USB stick or the cloud:

- `ledger.db` — the database, required
- `.env` — configuration and API keys (⚠️ sensitive file, contains the keys in clear text)
- `system_settings.yaml` — only if present

> **Do not copy** `launcher.lock` or `.schema_hash` (see note below). The `models/` folder (the LLM models, several GB) can be left behind: on the other computer they are re-downloaded at first launch. However, if the new machine will be **offline**, or you want to avoid the re-download, copy `models/` as well.

**Step 3 — Install Spendif.ai** on the destination computer and **launch it at least once**, then **close it**. This creates the empty `~/.spendifai/` folder.

**Step 4 — Paste the files** copied in step 2 into `~/.spendifai/` on the destination computer, overwriting the freshly created `ledger.db`.

**Step 5 — Restart Spendif.ai.** All transactions, rules, taxonomy and settings are present.

> **App version change** — If the destination computer has a **newer** version of Spendif.ai than the source, everything is fine: the database schema is upgraded automatically at first launch (just make sure you did **not** copy `.schema_hash`, so the migrations run). The reverse path — bringing a DB from a **newer** version onto an **older** app — is not supported: install the same version (or newer) on the destination first.

### 6.2 — From/to a Docker installation

If one of the two machines uses the Docker installation instead of the desktop app:

1. **Back up** the DB on the source computer (section 3 — use `docker cp` if the source is Docker, or copy `~/.spendifai/ledger.db` if it is the desktop app)
2. **Copy the `ledger.db` file** to the new computer (USB, cloud, scp, etc.)
3. **Install Spendif.ai** on the new computer
4. **Import the DB**: into the Docker volume → section 5; into the desktop app → copy it to `~/.spendifai/ledger.db` (app closed)
5. Open the app: all transactions, rules and settings are present

---

## 7 — Direct inspection (sqlite3)

You can open the database with any SQLite client. Examples:

**From the terminal (sqlite3):**
```bash
# Native installation — from the project folder
sqlite3 ledger.db

# Docker — extract the DB first with docker cp
docker cp spendifai_app:/app/data/ledger.db /tmp/ledger_inspect.db
sqlite3 /tmp/ledger_inspect.db
```

**Useful queries:**
```sql
-- Number of transactions per year
SELECT strftime('%Y', date) AS year, COUNT(*) FROM "transaction" GROUP BY year;

-- Last 10 transactions
SELECT date, description, amount, category FROM "transaction" ORDER BY date DESC LIMIT 10;

-- Active rules
SELECT pattern, category, subcategory FROM category_rule ORDER BY priority;

-- User settings
SELECT key, value FROM user_settings;
```

**GUI clients:** [DB Browser for SQLite](https://sqlitebrowser.org) (free, Mac/Linux/Windows) — open the `.db` file directly.

---

## 8 — Database corruption

SQLite file corruption is rare but can occur in the event of a power cut during a write operation.

### Check

```bash
sqlite3 ledger.db "PRAGMA integrity_check;"
# Expected output: ok
# If the output contains errors, the file is corrupted
```

### Automatic recovery attempt

```bash
sqlite3 ledger.db ".recover" | sqlite3 ledger_recovered.db
mv ledger.db ledger_corrupted_$(date +%Y%m%d).db
mv ledger_recovered.db ledger.db
```

Check again with `PRAGMA integrity_check;`. If recovery fails, restore from the last valid backup (section 4).

### Prevention

- The Docker installation has `restart: unless-stopped` which prevents sudden container shutdowns
- Taking regular backups (section 3.4) always guarantees a recent restore point
