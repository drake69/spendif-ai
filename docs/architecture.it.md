# Spendif.ai — Architettura

> 🇬🇧 [Read in English](architecture.md)

Questo documento descrive l'architettura runtime di Spendif.ai:
struttura a layer, i due flussi di ingestione, e dove vive ciascuna
responsabilità nel codice.

---

## Diagramma a layer

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
 già in DB             (sample sanitizzato)    rilevazione invert_sign
        │
 normalizer.py          sanitizer.py      llm_backends.py
 ├─ encoding detect     ├─ IBAN/PAN/CF    ├─ OllamaBackend
 ├─ parse_amount()      ├─ owner names    ├─ OpenAIBackend
 ├─ SHA-256 tx_id       └─ assert_sani.. ├─ ClaudeBackend
 ├─ invert_sign                           └─ BackendFactory
 ├─ RF-03 reconcile                          call_with_fallback()
 └─ RF-04 transfers
        │
 categorizer.py  ←── TaxonomyConfig (caricata dal DB)
 Step 0: regole utente  (subcategory → category resolution)
 Step 1: regex statici
 Step 2: ML stub
 Step 3: LLM structured output  (subcategory constrained enum)
 Step 4: fallback "Altro"
        │
    db/repository.py   (SQLAlchemy, idempotente)
    └─ Transaction · ImportBatch · DocumentSchemaModel
       ReconciliationLink · InternalTransferLink · CategoryRule
       UserSettings · ImportJob · Account
       TaxonomyCategory · TaxonomySubcategory · TaxonomyDefault
        │
    reports/generator.py
    └─ HTML (Jinja2+Plotly) · CSV · XLSX

 chat_bot/engine.py  ←── chatbot di supporto adattivo
 ├─ RAG Cloud (Claude/OpenAI API)
 ├─ RAG Local (Ollama/vLLM)
 └─ FAQ Match (classificatore TF-IDF, no LLM)
     knowledge/<lang>/faq.json · docs/
```

## Regole di layering

- **UI → solo services** — le pagine sotto `ui/` possono importare solo
  da `services/`, mai da `core/` o `db/`. Enforcement via
  `tools/coupling_check.py --strict` in CI.
- **Services → core + db** — i service orchestrano logica di dominio e
  persistenza.
- **Core non importa mai services o db** — mantiene puro il dominio.
- **Persistence (`db/`) non importa mai verso l'alto** — niente dipendenze
  cicliche.

## Flow 1 vs Flow 2

| | Flow 1 | Flow 2 |
|---|---|---|
| **Trigger** | `DocumentSchema` già in DB per quel fingerprint di colonne | Primo import di un formato nuovo |
| **Schema** | Recuperato dal DB e applicato direttamente | LLM deduce lo schema da un sample anonimizzato |
| **Promozione** | — | Template Flow 2 approvato viene salvato e diventa Flow 1 |
| **Auto-invalidazione** | Se parse rate < 10 %, lo schema viene eliminato e Flow 2 ripartirà al prossimo import | — |
| **Costo LLM** | Zero (solo categorizzazione) | Una call per classificazione + una per batch categorizzazione |

### Dettagli Flow 2

`core/classifier.py` lavora in tre fasi:

1. **Phase 0 (Python, pre-LLM)** — content-type detection deterministica
   sui dati reali. Classifica ogni colonna come `date`, `amount` o
   `text` ispezionando i valori. Synonym di nome colonna usati solo
   come tiebreaker tra colonne dello stesso content-type. A volte
   risolve la semantica dell'amount (outflow/inflow/debit_positive) e
   l'`invert_sign` senza mai chiamare l'LLM.
2. **Phase 1 (LLM)** — riceve i risultati di Phase 0 come fatti, si
   concentra sui campi genuinamente ambigui (doc_type, date_format,
   sign_convention per amount neutri). L'opzione multi-step suddivide
   questa fase in tre LLM call più piccole per modelli sotto i 7B
   parametri.
3. **Post-LLM (Python)** — merge dei risultati Phase 0 (Phase 0 vince),
   coerce dei nomi colonna, safety-net re-enforcement di `invert_sign`.

## Launcher desktop nativo

`desktop/launcher.py` è l'entry point dell'app desktop congelata da
PyInstaller:

1. Apre una finestra `pywebview` nativa con uno splash screen.
2. Chiama `core.model_manager.ensure_model_available()` che rileva
   RAM/VRAM e scarica il GGUF più grande compatibile (Qwen 2.5, Gemma 3).
3. Scrive un `.env` per-utente con `LLM_BACKEND=local_llama_cpp`.
4. Avvia un sottoprocesso Streamlit su una porta libera casuale.
5. Naviga la finestra pywebview all'URL Streamlit quando risponde.

Lo stesso `app.py` gira sia nel bundle desktop sia in Streamlit
standalone (`streamlit run app.py`) — il launcher è solo un wrapper
sottile.

## Supporto multi-database (pool pattern)

`db/pool.py` fornisce un'interfaccia asincrona unificata su più dialetti
SQL. Attualmente solo SQLite è in produzione, ma l'astrazione fa sì che
uno switch a PostgreSQL richiederebbe solo un cambio di connection
string e zero modifiche ai repository.

## Async runner

Streamlit è sincrono; la sessione SQLAlchemy async e ogni futura call
HTTP async vivono dietro `services/async_runner.py`, che mantiene un
event loop persistente in un thread dedicato ed espone `run_async(coro)`
per i call site sincroni.

## Migrazioni schema

`db/schema.py` usa un approccio **auto-hash**: il sorgente della
funzione `_run_schema()` viene SHA-256 hashato; se l'hash matcha quello
salvato nella tabella `schema_version`, le migrazioni vengono saltate
(singolo `SELECT` leggero). Su mismatch, la funzione gira in una singola
transazione atomica. Idempotente: `CREATE TABLE IF NOT EXISTS` ovunque,
errori `ALTER TABLE ADD COLUMN` ignorati silenziosamente se la colonna
esiste già.

## Dove leggere dopo

- [Reference guide](reference_guide.md) — ogni pagina, ogni algoritmo
- [Design decisions](design_decisions.it.md) — `Decimal`, SHA-256, RF-03, ecc.
- [Developer guide](developer_guide.md) — service layer, coupling gate, classifier multi-step
- [Configurazione](configurazione.md)
