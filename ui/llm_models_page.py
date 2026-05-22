"""LLM Models page — dedicated configuration for the 4 phase-specific backends.

AI-96: promotes LLM configuration from a Settings sub-section to a top-level
navigation entry. Each pipeline phase (classifier, cleaner, categorizer,
footer) gets its own backend slot; account-level credentials (API keys,
base URLs) are shared across phases and live in a single section at the top.

PR-1 (this file): minimum-viable structure — current status, account
credentials, four per-phase configuration cards, persistence to user_settings.
Operations (test, calibrate, stats, download) and Settings cleanup are
follow-ups.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from services.settings_service import SettingsService
from support.logging import setup_logging
from ui.i18n import t

logger = setup_logging()


# Backends supported by the runtime (`_build_phase_backend` in
# core/orchestrator.py). Order chosen so the most-common-locally first.
_SUPPORTED_BACKENDS = (
    "local_llama_cpp",
    "local_ollama",
    "openai",
    "claude",
    "openai_compatible",
    "vllm",
    "vllm_offline",
)

_PHASES = (
    ("classifier",  "🔍"),
    ("cleaner",     "✂️"),
    ("categorizer", "🏷️"),
    ("footer",      "📐"),
)


def _backend_label(b: str) -> str:
    return t(f"llm_models.backend.{b}")


def _backend_options_inherit_first() -> list[str]:
    # Empty string = "inherit from main backend".
    return ["", *_SUPPORTED_BACKENDS]


def _current_phase_backend(settings: dict, phase: str) -> str:
    """Resolve the effective backend for a phase, with legacy fallbacks.

    Mirrors the logic of `_build_phase_backend` so the UI shows what the
    runtime will actually use.
    """
    val = settings.get(f"{phase}_llm_backend", "") or ""
    if not val and phase == "categorizer":
        val = settings.get("cat_llm_backend", "") or ""
    if not val:
        val = settings.get("llm_backend", "") or ""
    return val


def _render_current_status(settings: dict) -> None:
    st.subheader(t("llm_models.status.title"))
    rows = []
    for phase, icon in _PHASES:
        backend = _current_phase_backend(settings, phase)
        rows.append(
            f"- {icon} **{t(f'llm_models.phase.{phase}')}** — "
            f"`{_backend_label(backend) if backend else '—'}`"
        )
    st.markdown("\n".join(rows))


def _render_account_credentials(svc: SettingsService, settings: dict) -> None:
    st.subheader(t("llm_models.credentials.title"))
    st.caption(t("llm_models.credentials.caption"))

    new_vals: dict[str, str] = {}
    with st.expander(t("llm_models.credentials.openai"), expanded=False):
        new_vals["openai_api_key"] = st.text_input(
            t("llm_models.credentials.api_key"),
            value=settings.get("openai_api_key", ""),
            type="password",
            key="_llmpage_openai_key",
        )
    with st.expander(t("llm_models.credentials.anthropic"), expanded=False):
        new_vals["anthropic_api_key"] = st.text_input(
            t("llm_models.credentials.api_key"),
            value=settings.get("anthropic_api_key", ""),
            type="password",
            key="_llmpage_anthropic_key",
        )
    with st.expander(t("llm_models.credentials.compat"), expanded=False):
        new_vals["compat_base_url"] = st.text_input(
            t("llm_models.credentials.base_url"),
            value=settings.get("compat_base_url", ""),
            key="_llmpage_compat_url",
        )
        new_vals["compat_api_key"] = st.text_input(
            t("llm_models.credentials.api_key"),
            value=settings.get("compat_api_key", ""),
            type="password",
            key="_llmpage_compat_key",
        )
    with st.expander(t("llm_models.credentials.ollama"), expanded=False):
        new_vals["ollama_base_url"] = st.text_input(
            t("llm_models.credentials.base_url"),
            value=settings.get("ollama_base_url", "http://localhost:11434"),
            key="_llmpage_ollama_url",
        )

    if st.button(
        t("llm_models.credentials.save"),
        key="_llmpage_creds_save",
        type="primary",
    ):
        svc.set_bulk({k: v for k, v in new_vals.items() if v is not None})
        st.success(t("llm_models.credentials.saved"))
        logger.info("llm_models_page: account credentials saved")


def _run_phase_test(phase: str, new_vals: dict, settings: dict) -> None:
    """Send a tiny test prompt through the phase's backend, show outcome inline.

    Reuses `services.llm_service.test_llm_backend`. Resolves account-level
    credentials (api_key, base_url) from the current settings dict because
    they aren't duplicated per phase by design.
    """
    from services.llm_service import test_llm_backend

    backend = new_vals.get(f"{phase}_llm_backend", "")
    if not backend:
        st.warning(t("llm_models.phase.test_no_backend"))
        return

    kwargs: dict = {"backend": backend}
    if backend == "local_llama_cpp":
        kwargs["model_path"] = new_vals.get(f"{phase}_llama_cpp_model_path", "") or settings.get("llama_cpp_model_path", "")
        try:
            kwargs["n_gpu_layers"] = int(new_vals.get(f"{phase}_llama_cpp_n_gpu_layers", "-1") or "-1")
            kwargs["n_ctx"] = int(new_vals.get(f"{phase}_llama_cpp_n_ctx", "0") or "0")
        except (TypeError, ValueError):
            pass
    elif backend == "local_ollama":
        kwargs["base_url"] = settings.get("ollama_base_url", "http://localhost:11434")
        kwargs["model"] = new_vals.get(f"{phase}_ollama_model", "") or settings.get("ollama_model", "")
    elif backend == "openai":
        kwargs["api_key"] = settings.get("openai_api_key", "")
        kwargs["model"] = new_vals.get(f"{phase}_openai_model", "") or settings.get("openai_model", "")
    elif backend == "claude":
        kwargs["api_key"] = settings.get("anthropic_api_key", "")
        kwargs["model"] = new_vals.get(f"{phase}_anthropic_model", "") or settings.get("anthropic_model", "")
    elif backend == "openai_compatible":
        kwargs["base_url"] = settings.get("compat_base_url", "")
        kwargs["api_key"] = settings.get("compat_api_key", "")
        kwargs["model"] = new_vals.get(f"{phase}_compat_model", "") or settings.get("compat_model", "")
    elif backend in ("vllm", "vllm_offline"):
        kwargs["base_url"] = settings.get("vllm_base_url", "")
        kwargs["model"] = settings.get("vllm_model", "")
        kwargs["api_key"] = settings.get("vllm_api_key", "") or "none"

    with st.spinner(t("llm_models.phase.test_running")):
        import time as _time
        _t0 = _time.monotonic()
        ok, msg = test_llm_backend(**kwargs)
        elapsed = _time.monotonic() - _t0
    if ok:
        st.success(t("llm_models.phase.test_ok", elapsed=f"{elapsed:.1f}"))
    else:
        st.error(t("llm_models.phase.test_fail", error=msg[:200]))
    logger.info(f"llm_models_page: phase {phase} test backend={backend} ok={ok} elapsed={elapsed:.2f}s")


def _render_phase_card(svc: SettingsService, settings: dict, phase: str, icon: str) -> None:
    """Render one configuration card for a single pipeline phase."""
    st.markdown(f"#### {icon} {t(f'llm_models.phase.{phase}')}")
    st.caption(t(f"llm_models.phase.{phase}.caption"))

    # "Use main backend" toggle — when on, the phase keeps no override
    # and the runtime falls back to llm_backend / cat_llm_backend.
    current_backend = settings.get(f"{phase}_llm_backend", "") or ""
    use_main = (current_backend == "")
    use_main = st.checkbox(
        t("llm_models.phase.use_main"),
        value=use_main,
        key=f"_llmpage_{phase}_usemain",
        help=t("llm_models.phase.use_main_help"),
    )

    new_vals: dict[str, str] = {}
    if use_main:
        new_vals[f"{phase}_llm_backend"] = ""
        st.info(t("llm_models.phase.using_main"))
    else:
        # Default to local_llama_cpp if nothing set — most common on first override.
        default_backend = current_backend or "local_llama_cpp"
        idx = _SUPPORTED_BACKENDS.index(default_backend) if default_backend in _SUPPORTED_BACKENDS else 0
        sel = st.selectbox(
            t("llm_models.phase.backend"),
            options=_SUPPORTED_BACKENDS,
            format_func=_backend_label,
            index=idx,
            key=f"_llmpage_{phase}_backend",
        )
        new_vals[f"{phase}_llm_backend"] = sel

        # Backend-specific fields. Account credentials live in the section above
        # and are reused — we only ask for the model identifier here.
        if sel == "local_llama_cpp":
            new_vals[f"{phase}_llama_cpp_model_path"] = st.text_input(
                t("llm_models.phase.local_llama_cpp.model_path"),
                value=settings.get(f"{phase}_llama_cpp_model_path", ""),
                placeholder=t("llm_models.phase.local_llama_cpp.model_path_placeholder"),
                key=f"_llmpage_{phase}_lcpp_path",
            )
            with st.expander(t("llm_models.phase.advanced"), expanded=False):
                new_vals[f"{phase}_llama_cpp_n_gpu_layers"] = str(st.number_input(
                    t("llm_models.phase.local_llama_cpp.n_gpu_layers"),
                    value=int(settings.get(f"{phase}_llama_cpp_n_gpu_layers", "-1") or "-1"),
                    min_value=-1, max_value=999, step=1,
                    key=f"_llmpage_{phase}_lcpp_layers",
                ))
                new_vals[f"{phase}_llama_cpp_n_ctx"] = str(st.number_input(
                    t("llm_models.phase.local_llama_cpp.n_ctx"),
                    value=int(settings.get(f"{phase}_llama_cpp_n_ctx", "0") or "0"),
                    min_value=0, max_value=131072, step=1024,
                    help=t("llm_models.phase.local_llama_cpp.n_ctx_help"),
                    key=f"_llmpage_{phase}_lcpp_ctx",
                ))
        elif sel == "local_ollama":
            new_vals[f"{phase}_ollama_model"] = st.text_input(
                t("llm_models.phase.local_ollama.model"),
                value=settings.get(f"{phase}_ollama_model", ""),
                placeholder="qwen2.5:3b",
                key=f"_llmpage_{phase}_ollama_model",
            )
        elif sel == "openai":
            new_vals[f"{phase}_openai_model"] = st.text_input(
                t("llm_models.phase.openai.model"),
                value=settings.get(f"{phase}_openai_model", ""),
                placeholder="gpt-4o-mini",
                key=f"_llmpage_{phase}_openai_model",
            )
        elif sel == "claude":
            new_vals[f"{phase}_anthropic_model"] = st.text_input(
                t("llm_models.phase.claude.model"),
                value=settings.get(f"{phase}_anthropic_model", ""),
                placeholder="claude-haiku-4-5-20251001",
                key=f"_llmpage_{phase}_anthropic_model",
            )
        elif sel == "openai_compatible":
            new_vals[f"{phase}_compat_model"] = st.text_input(
                t("llm_models.phase.compat.model"),
                value=settings.get(f"{phase}_compat_model", ""),
                placeholder=t("llm_models.phase.compat.model_placeholder"),
                key=f"_llmpage_{phase}_compat_model",
            )
        elif sel in ("vllm", "vllm_offline"):
            st.caption(t("llm_models.phase.vllm.note"))

        # Privacy banner for hosted backends — AI-55 alignment.
        if sel in ("openai", "claude", "openai_compatible"):
            st.warning(t("llm_models.phase.hosted_privacy_warning"))

    col_save, col_test = st.columns(2)
    with col_save:
        if st.button(
            t("llm_models.phase.save"),
            key=f"_llmpage_{phase}_save",
            type="primary",
            width="stretch",
        ):
            svc.set_bulk(new_vals)
            st.success(t("llm_models.phase.saved"))
            logger.info(f"llm_models_page: phase {phase} saved — backend={new_vals.get(f'{phase}_llm_backend','')!r}")
            st.rerun()
    with col_test:
        test_disabled = use_main  # no override = nothing to test for this phase
        if st.button(
            t("llm_models.phase.test"),
            key=f"_llmpage_{phase}_test",
            disabled=test_disabled,
            help=t("llm_models.phase.test_disabled_help") if test_disabled else t("llm_models.phase.test_help"),
            width="stretch",
        ):
            _run_phase_test(phase, new_vals, settings)


def render_llm_models_page(engine) -> None:
    st.header(t("llm_models.title"))
    st.caption(t("llm_models.caption"))

    svc = SettingsService(engine)
    settings = svc.get_all()

    _render_current_status(settings)
    st.divider()
    _render_account_credentials(svc, settings)
    st.divider()

    st.subheader(t("llm_models.phases.title"))
    st.caption(t("llm_models.phases.caption"))
    cols = st.columns(2)
    for i, (phase, icon) in enumerate(_PHASES):
        with cols[i % 2]:
            with st.container(border=True):
                _render_phase_card(svc, settings, phase, icon)

    st.divider()
    st.subheader(t("llm_models.operations.title"))
    _render_stats_7d(engine)
    st.divider()
    _render_calibrate_stub()
    st.divider()
    _render_download()


def _render_stats_7d(engine) -> None:
    """Aggregate llm_usage_log over the last 7 days, group by caller × model."""
    from sqlalchemy import text as _sql

    st.markdown(f"**{t('llm_models.stats.title')}**")
    st.caption(t("llm_models.stats.caption"))

    since = datetime.now(timezone.utc) - timedelta(days=7)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                _sql(
                    "SELECT caller, model_id, "
                    "COUNT(*) AS n_calls, "
                    "AVG(duration_ms) AS mean_ms, "
                    "SUM(total_tokens) AS tokens "
                    "FROM llm_usage_log "
                    "WHERE timestamp >= :since "
                    "GROUP BY caller, model_id "
                    "ORDER BY n_calls DESC"
                ),
                {"since": since.isoformat()},
            ).fetchall()
    except Exception as exc:
        # Most likely cause: table missing on a freshly created DB.
        st.info(t("llm_models.stats.unavailable"))
        logger.debug(f"llm_models_page: stats query failed: {exc}")
        return

    if not rows:
        st.info(t("llm_models.stats.empty"))
        return

    df = pd.DataFrame(rows, columns=["caller", "model", "n_calls", "mean_ms", "tokens"])
    df["mean_s"]   = (df["mean_ms"].astype(float) / 1000.0).round(2)
    df["n_calls"]  = df["n_calls"].astype(int)
    df["tokens"]   = df["tokens"].fillna(0).astype(int)
    st.dataframe(
        df[["caller", "model", "n_calls", "mean_s", "tokens"]],
        hide_index=True,
        width="stretch",
        column_config={
            "caller":  st.column_config.TextColumn(t("llm_models.stats.col.caller")),
            "model":   st.column_config.TextColumn(t("llm_models.stats.col.model")),
            "n_calls": st.column_config.NumberColumn(t("llm_models.stats.col.n_calls"), format="%d"),
            "mean_s":  st.column_config.NumberColumn(t("llm_models.stats.col.mean_s"), format="%.2f s"),
            "tokens":  st.column_config.NumberColumn(t("llm_models.stats.col.tokens"), format="%d"),
        },
    )


def _render_calibrate_stub() -> None:
    st.markdown(f"**{t('llm_models.calibrate.title')}**")
    st.caption(t("llm_models.calibrate.caption"))
    st.button(
        t("llm_models.calibrate.btn"),
        key="_llmpage_calibrate",
        disabled=True,
        help=t("llm_models.calibrate.coming_soon"),
    )


def _render_download() -> None:
    """List predefined GGUF models, exclude already-installed ones, allow download.

    Synchronous download with a live progress bar driven by the callback
    of `LlamaCppBackend.download_model`. The Streamlit script blocks
    during the transfer (matches the existing UX from the old Settings
    download widget); a deferred background-thread version with the
    `~/.spendifai/model_download.status` file used by the launcher is
    follow-up work.
    """
    from pathlib import Path

    from core.llm_backends import LlamaCppBackend
    from services.llm_service import download_gguf_model, get_default_gguf_models

    st.markdown(f"**{t('llm_models.download.title')}**")
    st.caption(t("llm_models.download.caption"))

    catalog = get_default_gguf_models() or {}
    local = LlamaCppBackend.list_local_models()
    local_stems = {item["name"] for item in local} if local else set()
    available = {k: v for k, v in catalog.items() if k not in local_stems}

    if not available:
        st.success(t("llm_models.download.all_present"))
        # Still surface what's installed, for orientation.
        if local:
            with st.expander(t("llm_models.download.installed_label"), expanded=False):
                for item in local:
                    size_mb = item.get("size_mb")
                    size_label = f"{size_mb:.0f} MB" if isinstance(size_mb, (int, float)) else ""
                    st.markdown(f"- `{item['name']}` {size_label}")
        return

    options = list(available.keys())
    sel = st.selectbox(
        t("llm_models.download.choose"),
        options=options,
        format_func=lambda k: f"{k} — {available[k].get('size_gb', '?')} GB",
        key="_llmpage_dl_choice",
    )
    if sel:
        st.caption(available[sel].get("description", ""))

    if st.button(
        t("llm_models.download.btn"),
        type="primary",
        key="_llmpage_dl_btn",
    ):
        url = available[sel]["url"]
        # Save under ~/.spendifai/models/<stem>.gguf (mirrors registry naming).
        dest = str(Path.home() / ".spendifai" / "models" / f"{sel}.gguf")
        prog = st.progress(0.0)
        status = st.empty()

        def _cb(bytes_done: int, total_size: int) -> None:
            if total_size and total_size > 0:
                pct = min(bytes_done / total_size, 1.0)
                prog.progress(pct)
                status.text(
                    t("llm_models.download.in_progress",
                      pct=int(pct * 100),
                      done_mb=bytes_done // (1024 * 1024),
                      total_mb=total_size // (1024 * 1024))
                )

        try:
            with st.spinner(t("llm_models.download.starting")):
                final_path = download_gguf_model(url, dest, progress_callback=_cb)
            prog.progress(1.0)
            st.success(t("llm_models.download.done", path=final_path))
            logger.info(f"llm_models_page: downloaded {sel} to {final_path}")
            st.rerun()
        except Exception as exc:
            st.error(t("llm_models.download.error", error=str(exc)[:200]))
            logger.warning(f"llm_models_page: download {sel} failed: {exc}")
