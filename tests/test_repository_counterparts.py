"""Case-insensitive behaviour of counterpart grouping and rule upsert.

These lock the contract that storage casing no longer matters: descriptions
that differ only by case collapse into a single counterpart, and rule patterns
are stored verbatim while the upsert dedup is case-insensitive.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from db.models import Base, Transaction, get_session
from db.repository import create_category_rule, get_counterpart_stats


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with get_session(engine) as s:
        yield s


def _tx(session, *, tx_id: str, description: str, amount: float = -10.0) -> None:
    session.add(
        Transaction(
            id=tx_id,
            date="2025-01-01",
            description=description,
            amount=amount,
            currency="EUR",
            tx_type="expense",
            category="Spesa",
            subcategory="Supermercato",
            category_source="llm",
            category_confidence="medium",
            account_label="test",
        )
    )
    session.flush()


def test_counterpart_grouping_is_case_insensitive(session):
    _tx(session, tx_id="t1", description="Coop Roma")
    _tx(session, tx_id="t2", description="COOP ROMA")
    _tx(session, tx_id="t3", description="coop roma")

    stats = get_counterpart_stats(session)

    assert len(stats) == 1
    group = stats[0]
    assert group["tx_count"] == 3
    # First-seen original casing is preserved for display.
    assert group["description"] == "Coop Roma"


def test_rule_upsert_is_case_insensitive_and_keeps_verbatim_pattern(session):
    rule, created = create_category_rule(
        session, pattern="coop", match_type="contains",
        category="Spesa", subcategory="Supermercato",
    )
    assert created is True
    assert rule.pattern == "coop"

    # Same pattern, different casing → updates the existing rule, no duplicate.
    rule2, created2 = create_category_rule(
        session, pattern="COOP", match_type="contains",
        category="Spesa", subcategory="Altro",
    )
    assert created2 is False
    assert rule2.id == rule.id
    # Stored pattern stays as originally entered.
    assert rule2.pattern == "coop"
