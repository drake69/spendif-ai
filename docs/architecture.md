# Spendif.ai — Architecture

> 🇮🇹 [Leggi in italiano](architecture.it.md)

This document describes the runtime architecture of Spendif.ai: the
layered structure, the two ingestion flows, and where each responsibility
lives in the codebase.

---

## Layer diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            app.py  (Streamlit)                           │
│  [onboarding gate] → sidebar → upload │ ledger │ bulk-edit │ analytics  │
│                               review │ rules │ taxonomy │ settings │ chat │
└──────────────────────────┬───────────────────────────────────────────────┘
                           │ services.*  (facade layer)
               core/orchestrator.py
               ProcessingConfig  ·  process_file()
                           │
        ┌──────────────────┼───────────────────┐
        │                  │                   │
 Flow 1 (template)    Flow 2 (schema-on-read)
 DocumentSchema        classifier.py → LLM  → DocumentSchema
 already in DB         (sanitized sample)      invert_sign detection
        │
 normalizer.py          sanitizer.py      llm_backends.py
 ├─ encoding detect     ├─ IBAN/PAN/CF    ├─ OllamaBackend
 ├─ parse_amount()      ├─ owner names    ├─ OpenAIBackend
 ├─ SHA-256 tx_id       └─ assert_sani.. ├─ ClaudeBackend
 ├─ invert_sign                           └─ BackendFactory
 ├─ RF-03 reconcile                          call_with_fallback()
 └─ RF-04 transfers
        │
 categorizer.py  ←── TaxonomyConfig (loaded from DB)
 Step 0: user rules  (subcategory → category resolution)
 Step 1: static regex
 Step 2: ML stub
 Step 3: LLM structured output  (subcategory constrained enum)
 Step 4: fallback "Other"
        │
    db/repository.py   (SQLAlchemy, idempotent)
    └─ Transaction · ImportBatch · DocumentSchemaModel
       ReconciliationLink · InternalTransferLink · CategoryRule
       UserSettings · ImportJob · Account
       TaxonomyCategory · TaxonomySubcategory · TaxonomyDefault
        │
    reports/generator.py
    └─ HTML (Jinja2+Plotly) · CSV · XLSX

 chat_bot/engine.py  ←── adaptive support chatbot
 ├─ RAG Cloud (Claude/OpenAI API)
 ├─ RAG Local (Ollama/vLLM)
 └─ FAQ Match (TF-IDF classifier, no LLM)
     knowledge/<lang>/faq.json · docs/
```

## Layer rules

- **UI → services only** — pages under `ui/` may import only from
  `services/`, never from `core/` or `db/`. Enforced by
  `tools/coupling_check.py --strict` in CI.
- **Services → core + db** — services orchestrate domain logic and
  persistence.
- **Core never imports services or db** — keeps the domain pure.
- **Persistence (`db/`) never imports upward** — no cyclic dependencies.

## Flow 1 vs Flow 2

| | Flow 1 | Flow 2 |
|---|---|---|
| **Trigger** | `DocumentSchema` already in DB for that column fingerprint | First import of a new format |
| **Schema** | Retrieved from DB and applied directly | LLM infers the schema from an anonymized sample |
| **Promotion** | — | Approved Flow 2 template is saved and becomes Flow 1 |
| **Auto-invalidation** | If parse rate < 10 %, schema is deleted and Flow 2 retry is triggered automatically | — |
| **LLM cost** | Zero (categorization only) | One call for classification + one for batch categorization |

### Flow 2 details

`core/classifier.py` runs in three phases:

1. **Phase 0 (Python, pre-LLM)** — deterministic content-type detection
   on actual data. Classifies each column as `date`, `amount`, or `text`
   by inspecting values. Column-name synonyms only as tiebreakers
   within the same content type. Sometimes resolves amount semantics
   (outflow/inflow/debit_positive) and `invert_sign` without ever
   calling the LLM.
2. **Phase 1 (LLM)** — receives Phase 0 findings as facts, focuses on
   genuinely ambiguous fields (doc_type, date_format,
   sign_convention for neutral amounts). Multi-step option splits this
   into three smaller LLM calls for models below 7B parameters.
3. **Post-LLM (Python)** — merge Phase 0 results (Phase 0 wins), coerce
   column names, safety-net re-enforcement of `invert_sign`.

## Native desktop launcher

`desktop/launcher.py` is the entry point for the PyInstaller-frozen
desktop app:

1. Opens a `pywebview` native window with a splash screen.
2. Calls `core.model_manager.ensure_model_available()` which detects
   RAM/VRAM and downloads the largest GGUF that fits (Qwen 2.5, Gemma 3).
3. Writes a per-user `.env` with `LLM_BACKEND=local_llama_cpp`.
4. Starts a Streamlit subprocess on a random free port.
5. Navigates the pywebview window to the Streamlit URL once it responds.

The same `app.py` runs both in the desktop bundle and in standalone
Streamlit (`streamlit run app.py`) — the launcher is just a thin wrapper.

## Multi-database support (pool pattern)

`db/pool.py` provides a unified async interface over multiple SQL dialects.
Currently only SQLite is in production, but the abstraction means a switch
to PostgreSQL would require only a connection-string change and no
repository code changes.

## Async runner

Streamlit is synchronous; the SQLAlchemy async session and any future
async HTTP calls live behind `services/async_runner.py`, which keeps a
persistent event loop in a dedicated thread and exposes `run_async(coro)`
for synchronous call sites.

## Schema migrations

`db/schema.py` uses an **auto-hash** approach: the source of the
`_run_schema()` function is SHA-256 hashed; if the hash matches what is
stored in the `schema_version` table, migrations are skipped (single
lightweight `SELECT`). On mismatch, the function runs inside a single
atomic transaction. Idempotent: `CREATE TABLE IF NOT EXISTS` everywhere,
`ALTER TABLE ADD COLUMN` errors silently ignored if the column already
exists.

## Where to read next

- [Reference guide](reference_guide.md) — every page, every algorithm
- [Design decisions](design_decisions.md) — `Decimal`, SHA-256, RF-03, etc.
- [Developer guide](developer_guide.md) — service layer, coupling gate, classifier multi-step
- [Configuration](configurazione.en.md)
