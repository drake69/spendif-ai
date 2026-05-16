# Spendif.ai v3.0

[![CI](https://github.com/drake69/spendify/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/drake69/spendify/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/drake69/spendify/graph/badge.svg)](https://codecov.io/gh/drake69/spendify)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: PolyForm NC](https://img.shields.io/badge/license-PolyForm%20Noncommercial-orange)](LICENSE)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-ff4b4b?logo=streamlit&logoColor=white)](https://streamlit.io)
[![Issues](https://img.shields.io/github/issues/drake69/spendify)](https://github.com/drake69/spendify/issues)
[![Last commit](https://img.shields.io/github/last-commit/drake69/spendify)](https://github.com/drake69/spendify/commits/main)
[![Supporta su Patreon](https://img.shields.io/badge/Patreon-offrimi%20un%20caffè%20☕-F96854?logo=patreon&logoColor=white)](https://patreon.com/drake69)

> 🇬🇧 [Read in English](README.md)

Registro finanziario personale unificato con pipeline ibrida deterministica + LLM. Aggrega export bancari eterogenei (conti correnti, carte di credito/debito/prepagate, conti deposito) in un unico ledger cronologico, eliminando il double-counting da addebiti carta periodici e giroconti interni. Offline-first; backend LLM remoti opt-in con sanitizzazione PII obbligatoria.

---

> 👋 **Utente finale — vuoi installare Spendif.ai?**
> Vai alla [pagina Primo avvio](https://drake69.github.io/spendify/getting-started.html) per la guida illustrata di installazione + primo avvio. Questo README è per sviluppatori e contributor.

---

## Cos'è (tecnicamente)

- **Python 3.13 · Streamlit · SQLAlchemy · Pydantic · Pandas**
- **Pipeline ibrida**: normalizer deterministico + classifier LLM + categorizer a cascata
- **LLM multi-backend** con circuit breaker: llama.cpp (default per desktop), Ollama, OpenAI, Claude — uso diretto dell'SDK, niente LangChain
- **Launcher desktop nativo**: pywebview + PyInstaller → DMG / MSIX / .deb / .rpm
- **UI Streamlit a 14 pagine**, i18n IT+EN completo (760+ chiavi di traduzione)

## Cosa è implementato

- **Pipeline ibrida (deterministica + LLM)** — `core/normalizer.py` parsa qualunque export bancario tabellare; `core/classifier.py` deduce `DocumentSchema` via LLM; `core/categorizer.py` esegue una cascata a 4 step (regole utente → regex → LLM → fallback)
- **LLM multi-backend con circuit breaker** — factory in `core/llm_backends.py`: llama.cpp, Ollama, OpenAI, Claude. Fallback automatico + quarantena su fallimento
- **PII sanitization (RF-10)** — redazione di IBAN / PAN / codice fiscale / nomi titolari in `core/sanitizer.py`, obbligatoria prima di qualsiasi call remota (`assert_sanitized()` è una precondizione, non best-effort)
- **Tassonomia multilingua** — 2 livelli in DB, 5 lingue (it/en/fr/de/es), configurabile dall'UI Streamlit
- **Riconciliazione carta-conto (RF-03, beta)** — algoritmo a 3 fasi in `core/normalizer.py`: appaia gli addebiti carta con le spese sottostanti per eliminare il double-counting *(edge cases ancora in raffinamento)*
- **Rilevazione giroconti interni (RF-04, beta)** — matching su importo simbolico + finestra di ±7 giorni, con permutazioni dei nomi titolare per intercettare export tipo "Cognome Nome" *(edge cases ancora in raffinamento)*

## 👩‍💻 Sviluppo locale

```bash
git clone https://github.com/drake69/spendify.git
cd spendify
uv sync --extra desktop

# LLM locale (scelta dello sviluppatore — l'installer desktop gestisce
# questo automaticamente):
#   → se hai già Ollama attivo:   ollama pull gemma3:12b
#   → altrimenti: `uv sync` installa llama-cpp-python e il launcher
#     scarica automaticamente un modello GGUF al primo avvio

./start.sh                    # oppure: streamlit run app.py
```

Prerequisiti: **Python 3.13+**, **[uv](https://github.com/astral-sh/uv)**, e in alternativa Ollama o nulla (llama.cpp è bundle). Setup completo → [CONTRIBUTING.md](CONTRIBUTING.md).

### Eseguire come app desktop nativa da sorgente

```bash
uv run python -m desktop.launcher
```

Apre una finestra pywebview, scarica un modello AI al primo avvio, e avvia Streamlit dentro la stessa finestra. Identico all'esperienza DMG/MSIX confezionata.

## Eseguire i test

```bash
uv run pytest -v                                  # suite completa (no mock LLM)
uv run pytest --cov=. --cov-report=term-missing   # con coverage (target ≥ 90%)
uv run pytest -k "architecture"                   # gate separazione layer
uv run pytest -k "security"                       # forbidden pattern + SQL injection
```

I test architetturali e di sicurezza sono gate CI obbligatori e devono restare verdi su `main`.

## Architettura

```
ui/  →  services/  →  core/  →  db/  →  SQLite
                ↑       ↑
       async_runner  llm_backends · sanitizer · normalizer · classifier · categorizer
```

L'UI può importare solo da `services/`; `core/` non può importare `db/`; `db/` non importa mai verso l'alto. Il coupling gate (`tools/coupling_check.py --strict`) blocca le PR che violano la regola.

Diagramma completo e Flow 1 vs Flow 2 → [docs/architecture.it.md](docs/architecture.it.md).

## Struttura del repository

```
sw_artifacts/
├── app.py                  # Entry point Streamlit (onboarding gate + 14 pagine)
├── core/                   # Pipeline: orchestrator, normalizer, classifier, categorizer, sanitizer, llm_backends
├── services/               # Facade layer per l'UI; async runner; settings; import
├── ui/                     # Pagine Streamlit + i18n + widgets
├── db/                     # SQLAlchemy ORM, repository pattern, schema con auto-hash migrations
├── api/                    # Endpoint REST FastAPI (opzionale)
├── desktop/                # Launcher nativo (pywebview) + splash
├── packaging/              # Build script: macos/, windows/, linux/, homebrew/, winget/
├── docker/                 # Containerizzazione
├── prompts/                # Template prompt LLM (JSON versionato)
├── reports/                # Export HTML + CSV + XLSX
├── tests/                  # Suite pytest (target coverage ≥ 90%)
├── benchmark/              # Suite benchmark LLM (multi-provider)
└── docs/                   # Documentazione utente e sviluppatore
```

Dettagli → [docs/developer_guide.md](docs/developer_guide.md).

## 📚 Documentazione

| Argomento | Lingue |
|---|---|
| Installazione e primo avvio | [EN](docs/installazione.en.md) · [IT](docs/installazione.md) |
| Guida utente (ogni pagina) | [EN](docs/guida_utente.en.md) · [IT](docs/guida_utente.md) |
| Reference guide (pipeline, tassonomia, RF-03/04) | [EN](docs/reference_guide.en.md) · [IT](docs/reference_guide.md) |
| Architettura | [EN](docs/architecture.md) · [IT](docs/architecture.it.md) |
| Design decisions | [EN](docs/design_decisions.md) · [IT](docs/design_decisions.it.md) |
| Configurazione | [EN](docs/configurazione.en.md) · [IT](docs/configurazione.md) |
| Developer guide | [EN](docs/developer_guide.en.md) · [IT](docs/developer_guide.md) |
| Guida alla categorizzazione | [EN](docs/guida_classificazione.en.md) · [IT](docs/guida_classificazione.md) |
| Schema database | [EN](docs/database.en.md) · [IT](docs/database.md) |
| Deployment | [EN](docs/deployment.en.md) · [IT](docs/deployment.md) |
| Processo di rilascio | [EN](docs/release_process.md) · [IT](docs/release_process.it.md) |
| Contribuire | [EN](CONTRIBUTING.en.md) · [IT](CONTRIBUTING.md) |
| Politica di sicurezza | [EN](SECURITY.md) · [IT](SECURITY.it.md) |
| Changelog | [EN](CHANGELOG.md) · [IT](CHANGELOG.it.md) |

## Contribuire

Segnalazioni di bug, idee di feature e PR sono benvenute. Vedi [CONTRIBUTING.md](CONTRIBUTING.md) per workflow, policy di branching, framework delle priorità e gate CI.

## Licenza

**PolyForm Noncommercial 1.0.0** — vedi [LICENSE](LICENSE). Uso personale libero; l'uso commerciale richiede una licenza separata.

---

### Cosa lascia la macchina — onestà

Tutti i dati finanziari sono memorizzati localmente in `~/.spendifai/ledger.db`.

**Backend LLM locale (default — llama.cpp, Ollama)**: nulla lascia la macchina.

**Backend LLM remoto (opt-in — OpenAI, Claude)**: il payload contiene
descrizioni sanitizzate **insieme a** **importi**, **date** e **metadati
delle colonne**.

#### Esempio di redazione — categorizer (`core/categorizer.py:303`)

Riga grezza della transazione dal CSV:

```
date:        2026-03-15
description: "BONIFICO da MARIO ROSSI IT60X0542811101000000123456 CAU 12345 STIPENDIO MENSILE"
amount:      1500.00
```

Cosa l'LLM remoto riceve effettivamente:

```json
{
  "amount": "1500.00",
  "description": "BONIFICO da Carlo Brambilla <ACCOUNT_ID> <TX_CODE> STIPENDIO MENSILE"
}
```

Cosa è cambiato:
- `MARIO ROSSI` (nome titolare configurato) → `Carlo Brambilla` (nome finto dal pool italiano, ripristinato dopo la risposta LLM)
- `IT60X...` (IBAN) → `<ACCOUNT_ID>`
- `CAU 12345` (codice transazione bancaria) → `<TX_CODE>`
- `amount` e metadati di data: **inviati in chiaro**

Il prompt del categorizer dice al modello di "basare la decisione su
descrizione, importo e contesto" (`prompts/categorizer.json`). Se
l'importo influisca davvero sull'accuracy in pratica non è stato
misurato contro una baseline senza importi — il default conservativo
lo lascia nel payload finché non sarà misurato.

#### Roadmap

Le modalità di redazione di importi e date per i backend remoti
(`none` / `buckets` / `strip`) sono in roadmap — item di backlog **AI-55**.
