"""Home page — landing dashboard with income trend + income→expense Sankey.

Two charts, rolling 12-month window:

  1. Stacked bar of monthly income (categories stacked, only `income` tx_type;
     `internal_in` excluded — transfers between own accounts are not income).
  2. Sankey from "Total income" through expense categories down to
     subcategories, plus a "Sconosciuto" node that absorbs the surplus
     (or supplies the deficit) so the chart balances.

Empty state shows up when the `transaction` table is empty; in production
the routing in app.py keeps the user on Import in that case, but defending
the direct-URL access is cheap.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

import pandas as pd
import streamlit as st

from services.transaction_service import TransactionService
from ui.i18n import t


# ── i18n helper (alias to keep call sites short) ────────────────────────────
def _t(key: str, **kwargs):
    return t(key, **kwargs)


# ── Constants ────────────────────────────────────────────────────────────────

_ROLLING_DAYS = 365  # rolling 12-month window
_INCOME_TYPE = "income"
_EXPENSE_TYPE = "expense"


# ── Data loading ─────────────────────────────────────────────────────────────

def _twelve_months_ago(today: Optional[date] = None) -> date:
    """Return today minus 12 months. Uses replace(year=year-1) when possible,
    falling back to a 365-day delta for Feb-29 corner case."""
    today = today or date.today()
    try:
        return today.replace(year=today.year - 1)
    except ValueError:
        # Feb 29 in a leap year
        return today - timedelta(days=_ROLLING_DAYS)


def _load_transactions(engine, since: Optional[date] = None) -> pd.DataFrame:
    """Load all transactions from `since` (default: 12 months ago) into a
    DataFrame. Returns an empty DataFrame with the right schema if the
    table is empty. Delegates the query to TransactionService to keep
    `ui/` out of `db/` (coupling rule)."""
    since = since or _twelve_months_ago()
    rows = TransactionService(engine).get_recent_for_home(since.isoformat())
    if not rows:
        return pd.DataFrame(columns=["date", "amount", "tx_type", "category", "subcategory", "reconciled"])

    df = pd.DataFrame(rows, columns=["date", "amount", "tx_type", "category", "subcategory", "reconciled"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = df["amount"].apply(lambda v: float(v) if v is not None else 0.0)
    df["reconciled"] = df["reconciled"].astype(bool)
    return df


# ── Empty state ──────────────────────────────────────────────────────────────

def _render_empty_state() -> None:
    st.info(_t("home.empty_state.message"))
    if st.button(_t("home.empty_state.cta"), key="_home_empty_cta"):
        st.session_state["page"] = "import"
        st.rerun()


# ── Chart 1: Stacked bar — income by month ───────────────────────────────────

def _render_income_stacked_bar(df: pd.DataFrame) -> None:
    """Render the monthly-income stacked bar. *df* is the rolling-12-months
    slice; we filter to `tx_type == 'income'` + `amount > 0` + not reconciled."""
    import plotly.graph_objects as go

    inc = df[
        (df["tx_type"] == _INCOME_TYPE)
        & (df["amount"] > 0)
        & (~df["reconciled"])
    ].copy()

    if inc.empty:
        st.caption(_t("home.charts.no_income"))
        return

    inc["category"] = inc["category"].fillna(_t("home.charts.uncategorised"))
    inc["month"] = inc["date"].dt.to_period("M").dt.to_timestamp()

    pivot = (
        inc.groupby(["month", "category"])["amount"]
        .sum()
        .unstack(fill_value=0.0)
        .sort_index()
    )

    fig = go.Figure()
    for cat in pivot.columns:
        fig.add_bar(
            name=str(cat),
            x=pivot.index,
            y=pivot[cat].values,
        )
    fig.update_layout(
        barmode="stack",
        title=_t("home.charts.income_title"),
        xaxis_title=_t("home.charts.month"),
        yaxis_title=_t("home.charts.amount"),
        legend_title_text=_t("home.charts.category"),
        height=420,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Chart 2: Sankey — income → expense category → subcategory ────────────────

def _build_sankey_data(df: pd.DataFrame) -> Optional[dict]:
    """Build node/link arrays for the Sankey. Returns None if there is no
    income AND no expense (chart pointless), otherwise dict with keys:
        nodes: list[str]
        link_source: list[int]
        link_target: list[int]
        link_value:  list[float]
        unknown_kind: 'surplus' | 'deficit' | 'parity'  (informational)
    """
    inc_df = df[
        (df["tx_type"] == _INCOME_TYPE)
        & (df["amount"] > 0)
        & (~df["reconciled"])
    ]
    exp_df = df[
        (df["tx_type"] == _EXPENSE_TYPE)
        & (~df["reconciled"])
    ].copy()

    total_income = float(inc_df["amount"].sum())
    # Expense amounts are negative; we work with abs() for chart legibility.
    exp_df["abs_amount"] = exp_df["amount"].abs()
    total_expense = float(exp_df["abs_amount"].sum())

    if total_income == 0.0 and total_expense == 0.0:
        return None

    # ── Node layout ──────────────────────────────────────────────────────────
    income_label = _t("home.charts.income_total")
    unknown_label = _t("home.charts.unknown")
    uncat_cat_label = _t("home.charts.uncategorised")
    uncat_sub_label = _t("home.charts.uncategorised_sub")

    nodes: list[str] = [income_label]  # 0 = income source
    node_idx: dict[str, int] = {income_label: 0}

    def _node(label: str) -> int:
        if label not in node_idx:
            node_idx[label] = len(nodes)
            nodes.append(label)
        return node_idx[label]

    link_source: list[int] = []
    link_target: list[int] = []
    link_value: list[float] = []

    # Expense category aggregation (with "uncategorised" fallback).
    exp_df["category"] = exp_df["category"].fillna(uncat_cat_label)
    exp_df["subcategory"] = exp_df["subcategory"].fillna(uncat_sub_label)
    cat_totals = exp_df.groupby("category")["abs_amount"].sum().to_dict()

    # Link income → each expense category.
    for cat, amount in cat_totals.items():
        if amount <= 0:
            continue
        cat_idx = _node(f"{cat}")
        link_source.append(0)
        link_target.append(cat_idx)
        link_value.append(amount)

    # Link expense category → subcategory.
    subcat_totals = (
        exp_df.groupby(["category", "subcategory"])["abs_amount"].sum().reset_index()
    )
    for _, row in subcat_totals.iterrows():
        amount = float(row["abs_amount"])
        if amount <= 0:
            continue
        cat_idx = _node(f"{row['category']}")
        sub_idx = _node(f"{row['subcategory']} ({row['category']})")
        link_source.append(cat_idx)
        link_target.append(sub_idx)
        link_value.append(amount)

    # ── Unknown node: surplus → target, deficit → source ────────────────────
    delta = total_income - total_expense
    if delta > 0:
        # Surplus: income flows partly to Unknown.
        unknown_idx = _node(unknown_label)
        link_source.append(0)
        link_target.append(unknown_idx)
        link_value.append(delta)
        unknown_kind = "surplus"
    elif delta < 0:
        # Deficit: Unknown supplies the missing budget.
        unknown_idx = _node(unknown_label)
        # Each category currently gets its abs amount from income (0). Re-balance:
        # Unknown is an extra source; we model it as a separate flow that goes
        # collectively to a virtual "expense pool". Simplest: Unknown → income_label
        # is unsound; Sankey needs Unknown → each category for the deficit slice.
        # We instead add a synthetic flow Unknown → income_label so the balance
        # math reads cleanly (the total entering "income" equals total expenses).
        link_source.append(unknown_idx)
        link_target.append(0)
        link_value.append(-delta)
        unknown_kind = "deficit"
    else:
        unknown_kind = "parity"

    return {
        "nodes": nodes,
        "link_source": link_source,
        "link_target": link_target,
        "link_value": link_value,
        "unknown_kind": unknown_kind,
    }


def _render_sankey(data: dict) -> None:
    import plotly.graph_objects as go

    fig = go.Figure(
        go.Sankey(
            node=dict(
                label=data["nodes"],
                pad=14, thickness=18,
            ),
            link=dict(
                source=data["link_source"],
                target=data["link_target"],
                value=data["link_value"],
            ),
        )
    )
    fig.update_layout(
        title=_t("home.charts.sankey_title"),
        height=520,
        margin=dict(l=10, r=10, t=60, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Entry point ──────────────────────────────────────────────────────────────

def render_home_page(engine) -> None:
    st.title(_t("home.title"))

    if not TransactionService(engine).has_transactions():
        _render_empty_state()
        return

    today = date.today()
    since = _twelve_months_ago(today)
    st.caption(_t("home.range_caption",
                  date_from=since.strftime("%d/%m/%Y"),
                  date_to=today.strftime("%d/%m/%Y")))
    st.divider()

    df = _load_transactions(engine, since=since)

    if df.empty:
        # has_transactions said True but the rolling window is empty (all old).
        st.info(_t("home.charts.no_income"))
        return

    _render_income_stacked_bar(df)
    sankey = _build_sankey_data(df)
    if sankey is not None:
        _render_sankey(sankey)
