"""AI-92 aggregator — per-step matrix from existing benchmark + usage-log data.

Reads two sources:

* ``benchmark/results_all_runs.csv`` — accuracy aggregates for the
  two benchmark types (classifier, categorizer) emitted by
  ``benchmark/benchmark_classifier.py`` and ``benchmark_categorizer.py``.
  This is the dimension that already has per-model evidence.

* ``llm_usage_log`` table (optional) — per LLM call timing keyed by
  ``(caller, step, model_id)``, populated automatically by
  ``core.llm_backends._log_usage_to_db``. Provides cleaner and footer
  evidence too, plus actual latency for classifier/categorizer.

Output:

* Matrix MODELLO × FASE with accuracy (when measurable) and latency
  (always when the log is populated) written to
  ``benchmark/results_per_step.csv``.
* A "cherry-pick" recommendation per phase, printed to stdout.

Run:

    uv run python benchmark/aggregate_per_step.py
    uv run python benchmark/aggregate_per_step.py --db ~/.spendifai/ledger.db

Caveats:

* Coverage is only as good as what's already been benchmarked. Phases
  without dedicated benchmark coverage (cleaner, footer) rely entirely
  on llm_usage_log for latency and have no accuracy column yet.
* Numbers in ``results_all_runs.csv`` are scenario ``cold`` (no NSI,
  no history) — they underestimate the production pipeline. Treat as
  worst-case.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

try:
    import pandas as pd
except ImportError:
    print("pandas not installed. Run: uv pip install pandas", file=sys.stderr)
    sys.exit(1)


_ROOT = Path(__file__).resolve().parent.parent
_RESULTS_DIR = _ROOT / "benchmark" / "results"
_LEGACY_AGGREGATE = _ROOT / "benchmark" / "results_all_runs.csv"
_DEFAULT_DB_PATH = Path.home() / ".spendifai" / "ledger.db"
_OUT_PATH = _ROOT / "benchmark" / "results_per_step.csv"

# Map benchmark_type to the canonical phase name used by the runtime
# (mirrors core/orchestrator.py phase keys).
_TYPE_TO_PHASE = {
    "classifier":  "classifier",
    "categorizer": "categorizer",
}

# llm_usage_log.caller → phase
_CALLER_TO_PHASE = {
    "classifier":          "classifier",
    "description_cleaner": "cleaner",
    "categorizer":         "categorizer",
    "normalizer":          "footer",   # caller="normalizer" step="footer_detect"
}


def _load_accuracy(results_dir: Path, legacy_csv: Optional[Path] = None) -> pd.DataFrame:
    """Load benchmark accuracy from EVERY per-run CSV in `results_dir`.

    The legacy `results_all_runs.csv` is a hand-merged aggregate that
    only contains what `aggregate_results.py` ran on at some point in
    the past — it misses recent runs (e.g. the April 2026 Qwen 9B
    batch with 125+108 categorizer observations). Read directly from
    the source-of-truth folder where every `benchmark_categorizer.py`
    and `benchmark_classifier.py` invocation drops its CSV.

    `legacy_csv` is used as a fallback only when `results_dir` is empty
    or missing — useful when bench data has been pulled into a single
    file and the per-run folder hasn't been transferred.

    Returns long-format: model | provider | phase | metric | value.
    """
    csv_files: list[Path] = []
    if results_dir.is_dir():
        # Skip macOS resource-fork shadow files ("._*") that sneak in via
        # USB/SMB transfers — they fail UTF-8 decode and aren't real CSVs.
        csv_files = sorted(p for p in results_dir.glob("*.csv") if not p.name.startswith("._"))
    if not csv_files and legacy_csv is not None and legacy_csv.is_file():
        print(f"[info] {results_dir} empty — falling back to legacy {legacy_csv}", file=sys.stderr)
        csv_files = [legacy_csv]
    if not csv_files:
        print(f"[warn] no benchmark CSVs found (looked in {results_dir} and {legacy_csv}) — skipping accuracy axis", file=sys.stderr)
        return pd.DataFrame(columns=["model", "provider", "phase", "metric", "value"])

    frames = []
    for f in csv_files:
        try:
            d = pd.read_csv(f, low_memory=False)
            # Tolerate per-run CSVs that don't carry these columns (older formats).
            if "model" in d.columns and "benchmark_type" in d.columns:
                frames.append(d)
        except Exception as exc:
            print(f"[warn] {f.name}: read failed — {exc}", file=sys.stderr)
    if not frames:
        return pd.DataFrame(columns=["model", "provider", "phase", "metric", "value"])
    df = pd.concat(frames, ignore_index=True)
    print(f"[info] loaded {len(df)} rows from {len(frames)} CSV(s) in {results_dir}", file=sys.stderr)

    rows = []

    # ── Classifier: 5 KPIs averaged per (model, provider) ────────────────
    clf = df[df.get("benchmark_type") == "classifier"].copy()
    for col in ("doc_type_match", "convention_match", "parse_rate", "amount_accuracy", "date_accuracy"):
        if col in clf.columns:
            clf[col] = pd.to_numeric(clf[col], errors="coerce")
    if not clf.empty:
        clf_agg = clf.groupby(["model", "provider"])[
            ["doc_type_match", "convention_match", "parse_rate", "amount_accuracy", "date_accuracy"]
        ].mean().round(4)
        clf_agg["n"] = clf.groupby(["model", "provider"]).size()
        for (model, provider), row in clf_agg.iterrows():
            for metric, val in row.items():
                if metric == "n":
                    continue
                rows.append({
                    "model": model, "provider": provider,
                    "phase": "classifier", "metric": metric, "value": val,
                })
            rows.append({
                "model": model, "provider": provider,
                "phase": "classifier", "metric": "n_runs", "value": int(row["n"]),
            })

    # ── Categorizer: 3 KPIs averaged per (model, provider) ───────────────
    cat = df[df.get("benchmark_type") == "categorizer"].copy()
    for col in ("cat_exact_accuracy", "cat_fuzzy_accuracy", "cat_fallback_rate"):
        if col in cat.columns:
            cat[col] = pd.to_numeric(cat[col], errors="coerce")
    if not cat.empty:
        cat_agg = cat.groupby(["model", "provider"])[
            ["cat_exact_accuracy", "cat_fuzzy_accuracy", "cat_fallback_rate"]
        ].mean().round(4)
        cat_agg["n"] = cat.groupby(["model", "provider"]).size()
        for (model, provider), row in cat_agg.iterrows():
            for metric, val in row.items():
                if metric == "n":
                    continue
                rows.append({
                    "model": model, "provider": provider,
                    "phase": "categorizer", "metric": metric, "value": val,
                })
            rows.append({
                "model": model, "provider": provider,
                "phase": "categorizer", "metric": "n_runs", "value": int(row["n"]),
            })

    return pd.DataFrame(rows)


def _load_latency(db_path: Path) -> pd.DataFrame:
    """Load per-call latency from llm_usage_log, return long-format:

        model | phase | metric | value     (metric ∈ {mean_latency_s, n_calls, mean_total_tokens})

    Provider column is filled with a placeholder because the log doesn't
    carry it explicitly (could be derived from the model_id naming
    convention later).
    """
    if not db_path.is_file():
        print(f"[warn] {db_path} not found — skipping latency axis", file=sys.stderr)
        return pd.DataFrame(columns=["model", "provider", "phase", "metric", "value"])
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        df = pd.read_sql_query(
            "SELECT caller, model_id, duration_ms, total_tokens "
            "FROM llm_usage_log "
            "WHERE duration_ms IS NOT NULL",
            conn,
        )
    except Exception as exc:
        print(f"[warn] llm_usage_log query failed: {exc}", file=sys.stderr)
        return pd.DataFrame(columns=["model", "provider", "phase", "metric", "value"])
    finally:
        conn.close()

    if df.empty:
        return pd.DataFrame(columns=["model", "provider", "phase", "metric", "value"])

    df["phase"] = df["caller"].map(_CALLER_TO_PHASE).fillna(df["caller"])
    rows = []
    for (phase, model), grp in df.groupby(["phase", "model_id"]):
        mean_ms = grp["duration_ms"].mean()
        n = len(grp)
        mean_tok = pd.to_numeric(grp["total_tokens"], errors="coerce").mean()
        rows.append({"model": model, "provider": "?", "phase": phase, "metric": "mean_latency_s", "value": round(mean_ms / 1000, 3)})
        rows.append({"model": model, "provider": "?", "phase": phase, "metric": "n_calls",        "value": int(n)})
        rows.append({"model": model, "provider": "?", "phase": phase, "metric": "mean_total_tokens", "value": round(mean_tok, 1) if pd.notna(mean_tok) else 0})
    return pd.DataFrame(rows)


def _make_matrix(long_df: pd.DataFrame) -> pd.DataFrame:
    """Pivot long-format into MODEL × (PHASE, METRIC) matrix."""
    if long_df.empty:
        return long_df
    return (
        long_df
        .assign(col=lambda d: d["phase"] + "_" + d["metric"])
        .pivot_table(index=["model", "provider"], columns="col", values="value", aggfunc="first")
        .reset_index()
    )


def _cherry_pick(matrix: pd.DataFrame) -> dict:
    """For each phase, return the top model by the most representative
    accuracy metric (or by latency when accuracy is missing).
    """
    picks = {}

    # Classifier: rank by amount_accuracy (the column whose 100% is
    # the hardest target; doc_type_match saturates trivially).
    if "classifier_amount_accuracy" in matrix.columns:
        rank = (
            matrix[["model", "provider", "classifier_amount_accuracy", "classifier_n_runs"]]
            .dropna(subset=["classifier_amount_accuracy"])
            .sort_values("classifier_amount_accuracy", ascending=False)
        )
        if not rank.empty:
            top = rank.iloc[0]
            picks["classifier"] = {
                "model":    top["model"],
                "provider": top["provider"],
                "metric":   "amount_accuracy",
                "value":    float(top["classifier_amount_accuracy"]),
                "n_runs":   int(top.get("classifier_n_runs", 0) or 0),
            }

    # Categorizer: rank by cat_exact_accuracy.
    if "categorizer_cat_exact_accuracy" in matrix.columns:
        rank = (
            matrix[["model", "provider", "categorizer_cat_exact_accuracy", "categorizer_n_runs"]]
            .dropna(subset=["categorizer_cat_exact_accuracy"])
            .sort_values("categorizer_cat_exact_accuracy", ascending=False)
        )
        if not rank.empty:
            top = rank.iloc[0]
            picks["categorizer"] = {
                "model":    top["model"],
                "provider": top["provider"],
                "metric":   "cat_exact_accuracy",
                "value":    float(top["categorizer_cat_exact_accuracy"]),
                "n_runs":   int(top.get("categorizer_n_runs", 0) or 0),
            }

    # Cleaner / footer: no accuracy column → pick by lowest latency
    # (when llm_usage_log is populated).
    for phase in ("cleaner", "footer"):
        col = f"{phase}_mean_latency_s"
        if col in matrix.columns:
            rank = matrix[["model", col]].dropna(subset=[col]).sort_values(col)
            if not rank.empty:
                top = rank.iloc[0]
                picks[phase] = {
                    "model":  top["model"],
                    "metric": "mean_latency_s",
                    "value":  float(top[col]),
                }

    return picks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--results-dir", type=Path, default=_RESULTS_DIR,
                    help=f"folder with per-run benchmark CSVs (default: {_RESULTS_DIR})")
    ap.add_argument("--legacy-aggregate", type=Path, default=_LEGACY_AGGREGATE,
                    help=("legacy hand-merged CSV used as fallback when results-dir "
                          f"is empty (default: {_LEGACY_AGGREGATE})"))
    ap.add_argument("--db", type=Path, default=None,
                    help=("SQLite DB with llm_usage_log (default: $SPENDIFAI_DB or "
                          f"{_DEFAULT_DB_PATH})"))
    ap.add_argument("--out", type=Path, default=_OUT_PATH,
                    help=f"output CSV path (default: {_OUT_PATH})")
    args = ap.parse_args()

    db_path = args.db
    if db_path is None:
        env = os.environ.get("SPENDIFAI_DB", "")
        if env.startswith("sqlite:///"):
            db_path = Path(env.replace("sqlite:///", "", 1)).expanduser()
        else:
            db_path = _DEFAULT_DB_PATH

    acc = _load_accuracy(args.results_dir, legacy_csv=args.legacy_aggregate)
    lat = _load_latency(db_path)
    long_df = pd.concat([acc, lat], ignore_index=True)
    if long_df.empty:
        print("No data found — neither accuracy CSV nor llm_usage_log was readable.", file=sys.stderr)
        return 1

    matrix = _make_matrix(long_df)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    matrix.to_csv(args.out, index=False)

    print(f"Wrote {args.out} ({len(matrix)} rows, {len(matrix.columns)} columns)\n")

    # Cherry-pick recommendation
    picks = _cherry_pick(matrix)
    if picks:
        print("Cherry-pick by phase (best evidence-based candidate):\n")
        for phase, p in picks.items():
            extra = ""
            if "provider" in p:
                extra += f" ({p['provider']})"
            if "n_runs" in p:
                extra += f"  · n={p['n_runs']}"
            print(f"  {phase:12s} → {p['model']}{extra}")
            print(f"    {p['metric']} = {p['value']}")
            print()
    else:
        print("No cherry-pick possible (insufficient data).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
