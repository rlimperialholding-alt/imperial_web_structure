"""A kanonikus TENDER-kapu (35% direct-margin hard gate) tesztjei — Task75.

Pozitív, negatív, határ-, idempotencia-, konkurencia- és szivárgásgátló
esetek. Kizárólag szintetikus fixture-ek; a seedelt tervek nem könyvelési
bizonylatok.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import ( AuditLog, FinanceAllocationSnapshot, FinanceCommitment, MarginGateDecision, MarginGateVatRule, ProjectFinancePlan, )
from app.services.budget_allocation import ( build_allocation_from_detailed_lines, create_allocation_snapshot, )
from app.services.tender_margin_gate import (
    MarginGateBlocked,
    MarginGateStalePlan,
    evaluate_commitment_gate,
    list_decisions,
    plan_content_sha256,
    sha256_hex,
    verify_plan_unchanged,
)
from margin_gate_fixtures import add_child_line, get_line, seed_gate_plan

PROJECT = "GATE-TEST-001"


def _evaluate(db, *, cost_code="MAT-A", amount="500000", subject_id="S-1", action="tender_award", subject_type="tender_bid", project=PROJECT):
    return evaluate_commitment_gate(db, project_id=project, action_type=action, subject_type=subject_type, subject_id=subject_id, cost_code=cost_code, proposed_net_huf=Decimal(amount), actor="fixture@imperial.local",)


def _foundation_plan(db, *, revenue="6000000", amount="6000000"):
    plan = seed_gate_plan(db, project_id=PROJECT, revenue=revenue, summary_lines=[{"cost_code": "FOUNDATION", "amount": amount, "amount_basis": "NET_REVENUE_ENVELOPE", "component": "other"}],)
    return plan


def _foundation_snapshot(db, plan, *, source_type="NORM_TABLE"):
    create_allocation_snapshot(
        db,
        plan_id=plan.plan_id,
        summary_line_id=get_line(db, plan, "FOUNDATION").line_id,
        source_type=source_type,
        source_version="NORM-FOUND-2026-1",
        source_hash="b" * 64,
        approver="fixture-finance@imperial.local",
        rationale="Szintetikus alapozási normatábla a kapu tesztjéhez.",
        rows=[
            {"trade_code": "REINFORCING", "direct_cost_component": "material", "normalized_ratio": Decimal("30")},
            {"trade_code": "CONCRETE", "direct_cost_component": "material", "normalized_ratio": Decimal("40")},
            {"trade_code": "FORMWORK", "direct_cost_component": "other", "normalized_ratio": Decimal("15")},
            {"trade_code": "PUMPIX", "direct_cost_component": "machinery", "normalized_ratio": Decimal("10")},
            {"trade_code": "OTHER-DIRECT", "direct_cost_component": "other", "normalized_ratio": Decimal("5")},
        ],
    )


def _snapshot_rows(db, plan, cost_code="FOUNDATION"):
    line_id = get_line(db, plan, cost_code).line_id
    snapshot = db.scalar(select(FinanceAllocationSnapshot).where( FinanceAllocationSnapshot.plan_id_fk == plan.id, FinanceAllocationSnapshot.parent_summary_line_id == line_id,)
    )
    return snapshot




@pytest.mark.parametrize(
    "direct_amount,proposed,expected",
    [
        ("6500000", "500000", ("PASS", "35.00")),
        ("6501000", "100", ("margin_below_minimum", "34.99")),
        ("6500005", "1", ("margin_below_minimum", None)),  # 34.99995 → kerekítve 35.00, de BLOCK
        ("6499999999999999", "1", ("PASS", None)),  # nagy decimálisok, determinisztikus
    ],
)
def test_margin_boundaries(db, direct_amount, proposed, expected):
    revenue = "10000000" if direct_amount != "6499999999999999" else "10000000000000000"
    seed_gate_plan(db, project_id=PROJECT, revenue=revenue, direct_lines=[("MAT-A", direct_amount, "material")])
    expected_decision, expected_margin = expected
    if expected_decision == "PASS":
        decision = _evaluate(db, amount=proposed)
        assert decision.decision == "PASS"
        db.commit()
        return
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, amount=proposed)
    error = excinfo.value
    assert error.reason_code == "margin_below_minimum"
    if expected_margin is not None:
        assert error.margin_percent == Decimal(expected_margin)
        assert error.plan_version == 1
        message = error.message_hu
        assert "35.00" in message and "34.99" in message and "/financial" in message
        # Költségadat-szivárgás tilalma: soronkénti összeg nem lehet a hibaüzenetben.
        assert direct_amount not in message and revenue not in message




@pytest.mark.parametrize(
    "mutator,expected_code",
    [
        (None, "missing_approved_budget"),
        (lambda plan: setattr(plan, "status", "superseded"), "stale_superseded_budget"),
        (lambda plan: setattr(plan, "content_sha256", None), "missing_provenance"),
    ],
)
def test_missing_approved_budget_blocks(db, mutator, expected_code):
    if mutator is None:
        with pytest.raises(MarginGateBlocked) as excinfo:
            _evaluate(db)
    else:
        plan = seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")])
        mutator(plan)
        db.commit()
        with pytest.raises(MarginGateBlocked) as excinfo:
            _evaluate(db)
    assert excinfo.value.reason_code == expected_code


def test_zero_and_negative_revenue_block(db):
    for revenue in ("0", "-1000000"):
        seed_gate_plan(db, project_id=PROJECT, revenue=revenue, direct_lines=[("MAT-A", "6500000", "material")], plan_id=f"FIN-ZERO-{revenue}", version=abs(int(Decimal(revenue))) or 9,)
        with pytest.raises(MarginGateBlocked) as excinfo:
            _evaluate(db)
        assert excinfo.value.reason_code == "zero_or_negative_revenue"
        db.rollback()


@pytest.mark.parametrize(
    "mutator,expected_code",
    [
        (lambda plan, line: setattr(plan, "currency", "EUR"), "currency_mismatch"),
        (lambda plan, line: setattr(line, "cost_class", None), "unclassified_budget_line"),
        (lambda plan, line: setattr(line, "direct_cost_component", "overhead"), "invalid_direct_component"),
        (lambda plan, line: setattr(line, "actual_net", Decimal("-1")), "negative_value"),
        (lambda plan, line: setattr(line, "currency", "EUR"), "currency_mismatch"),
    ],
)
def test_invalid_plan_or_line_states_block(db, mutator, expected_code):
    plan = seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")])
    mutator(plan, get_line(db, plan, "MAT-A"))
    plan.content_sha256 = plan_content_sha256(plan)
    db.commit()
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db)
    assert excinfo.value.reason_code == expected_code


@pytest.mark.parametrize( "cost_code,expected_code", [("NEM-LETEZO", "unknown_cost_code"), ("", "missing_cost_code_mapping")], )
def test_unknown_or_missing_cost_code_blocks(db, cost_code, expected_code):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")])
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code=cost_code)
    assert excinfo.value.reason_code == expected_code


def test_non_positive_proposed_amount_blocks(db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")])
    for amount in ("0", "-100"):
        with pytest.raises(MarginGateBlocked) as excinfo:
            _evaluate(db, amount=amount)
        assert excinfo.value.reason_code == "invalid_commitment_amount"
        db.rollback()


def test_commitment_to_indirect_cost_code_blocks(db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")], indirect_lines=[("OVERHEAD-1", "1000000")],)
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="OVERHEAD-1", amount="100")
    assert excinfo.value.reason_code == "unknown_cost_code"


# --- Tartalék (contingency) ---


def test_contingency_counts_as_direct_cost_conservatively(db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "5500000", "material")], contingency="1000000")
    decision = _evaluate(db, amount="100")
    assert decision.decision == "PASS"
    # (10M − (5.5M + 1M)) / 10M = 35.00
    assert decision.margin_percent == Decimal("35.00")
    db.commit()


def test_contingency_over_budget_blocks(db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "5500000", "material")], contingency="1100000")
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, amount="100")
    assert excinfo.value.reason_code == "margin_below_minimum"


def test_explicit_contingency_line_replaces_conservative_bucket(db):
    plan = seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")], contingency="1000000")
    # A tartalék-allokáció csak TELJES lehet — a részleges sor fail-closed
    from app.models import ProjectFinanceBudgetLine
    line = ProjectFinanceBudgetLine(
        line_id="FIN-LINE-CONTINGENCY",
        plan_id_fk=plan.id, cost_code="CONTINGENCY-EXPLICIT",
        category="contingency", description="Részleges tartalék-allokáció",
        budget_net=Decimal("500000"), cost_class="direct",
        direct_cost_component="other", currency="HUF",
    )
    db.add(line)
    db.flush()
    db.expire(plan, ["budget_lines"])
    plan.content_sha256 = plan_content_sha256(plan)
    db.commit()
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="CONTINGENCY-EXPLICIT", amount="100")
    assert excinfo.value.reason_code == "partial_contingency_allocation"
    db.rollback()


def test_duplicate_contingency_lines_block(db):
    plan = seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")], contingency="1000000")
    from app.models import ProjectFinanceBudgetLine
    for index in (1, 2):
        db.add(ProjectFinanceBudgetLine(
            line_id=f"FIN-LINE-CONTINGENCY-{index}",
            plan_id_fk=plan.id, cost_code=f"CONTINGENCY-{index}",
            category="contingency", description="Duplikált tartalék-allokáció",
            budget_net=Decimal("100000"), cost_class="direct",
            direct_cost_component="other", currency="HUF",
        ))
    db.commit()
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="MAT-A", amount="100")
    assert excinfo.value.reason_code == "duplicate_contingency_allocation"


# --- Allokációk: roll-down (Foundation példa, kizárólag teszt-fixture) ---


def test_foundation_roll_down_exactly_35_passes(db):
    plan = _foundation_plan(db)
    _foundation_snapshot(db, plan)
    decision = _evaluate(db, cost_code="REINFORCING", amount="1170000")
    assert decision.decision == "PASS"
    assert decision.margin_percent == Decimal("35.00")
    db.commit()


def test_foundation_commitment_over_envelope_blocks(db):
    plan = _foundation_plan(db)
    _foundation_snapshot(db, plan)
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="REINFORCING", amount="3900000.01")
    assert excinfo.value.reason_code == "package_envelope_exceeded"


def test_foundation_trade_envelope_tracked_in_calculation(db):
    plan = _foundation_plan(db)
    _foundation_snapshot(db, plan)
    decision = _evaluate(db, cost_code="CONCRETE", amount="1560000")
    db.commit()
    import json
    calc = json.loads(decision.calculation_json)
    package = next(iter(calc["packages"].values()))
    assert package["trade_margins"]["CONCRETE"]["envelope"] == "1560000.00"


def test_missing_allocation_snapshot_blocks(db):
    _foundation_plan(db)
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="REINFORCING", amount="100")
    assert excinfo.value.reason_code == "allocation_unresolved"


@pytest.mark.parametrize(
    "mutator,expected_code",
    [
        (lambda s: setattr(s, "unallocated_amount", Decimal("0.01")), "allocation_unallocated"),
        (lambda s: setattr(s.rows[0], "normalized_ratio", Decimal("30.0001")), "allocation_ratios_invalid"),
        (lambda s: setattr(s, "effective_to", datetime.now(UTC) - timedelta(days=1)), "allocation_expired"),
        (lambda s: setattr(s, "confidence_percent", Decimal("49.99")), "allocation_low_confidence"),
        (lambda s: setattr(s, "coverage_percent", Decimal("99.99")), "allocation_partial_coverage"),
        (lambda s: setattr(s, "package_max_direct_cost_huf", Decimal("3900001")), "allocation_inconsistent"),
    ],
)
def test_allocation_snapshot_invalid_states_block(db, mutator, expected_code):
    plan = _foundation_plan(db)
    _foundation_snapshot(db, plan)
    snap = _snapshot_rows(db, plan)
    mutator(snap)
    db.commit()
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="REINFORCING", amount="100")
    assert excinfo.value.reason_code == expected_code


def _dcb_snapshot(db, plan, code="FOUNDATION-DCB"):
    create_allocation_snapshot(
        db,
        plan_id=plan.plan_id,
        summary_line_id=get_line(db, plan, code).line_id,
        source_type="SUPPLIER_EVIDENCE",
        source_version="SUP-1",
        source_hash="c" * 64,
        approver="fixture-finance@imperial.local",
        rationale="Szállítói bizonyítékon alapuló direct költség-alap.",
        rows=[
            {"trade_code": "CONCRETE", "direct_cost_component": "material", "normalized_ratio": Decimal("100")},
        ],
    )


def test_direct_cost_baseline_package_requires_full_revenue(db):
    plan = seed_gate_plan(
        db,
        project_id=PROJECT,
        revenue="9230770.00",
        summary_lines=[{"cost_code": "FOUNDATION-DCB", "amount": "6000000", "amount_basis": "DIRECT_COST_BASELINE", "component": "other"}],
    )
    _dcb_snapshot(db, plan)
    decision = _evaluate(db, cost_code="CONCRETE", amount="6000000")
    # (9,230,770.00 − 6,000,000) / 9,230,770.00 > 35.00 → PASS.
    assert decision.decision == "PASS"
    db.commit()


@pytest.mark.parametrize( "revenue,amount", [("9230769.23", "6000000"), ("9000000", "100")], )
def test_direct_cost_baseline_insufficient_revenue_blocks_fail_closed(db, revenue, amount):
    # Kerekített elvárt bevétel mellett a pontos hányados 35.00 ALATT marad;
    plan = seed_gate_plan(db, project_id=PROJECT, revenue=revenue, summary_lines=[{"cost_code": "FOUNDATION-DCB", "amount": "6000000", "amount_basis": "DIRECT_COST_BASELINE", "component": "other"}],)
    _dcb_snapshot(db, plan)
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="CONCRETE", amount=amount)
    assert excinfo.value.reason_code == "margin_below_minimum"


def test_missing_amount_basis_blocks(db):
    plan = _foundation_plan(db)
    _foundation_snapshot(db, plan)
    line = get_line(db, plan, "FOUNDATION")
    line.amount_basis = None
    plan.content_sha256 = plan_content_sha256(plan)
    db.commit()
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="CONCRETE", amount="100")
    assert excinfo.value.reason_code == "missing_amount_basis"


# --- Részletes gyereksorok (precedencia 1) ---


_FOUNDATION_CHILDREN = (
    ("REINFORCING", "1170000", "material"),
    ("CONCRETE", "1560000", "material"),
    ("FORMWORK", "585000", "other"),
    ("PUMPIX", "390000", "machinery"),
    ("OTHER-DIRECT", "195000", "other"),
)


def _add_foundation_children(db, plan, parent_id, children):
    for (code, _, component), amount in zip(_FOUNDATION_CHILDREN, children):
        add_child_line(db, plan, cost_code=code, amount=amount, component=component, parent_summary_line_id=parent_id)


def _detailed_plan(db, *, children=("1170000", "1560000", "585000", "390000", "195000")):
    plan = _foundation_plan(db)
    parent_id = get_line(db, plan, "FOUNDATION").line_id
    _add_foundation_children(db, plan, parent_id, children)
    build_allocation_from_detailed_lines(
        db,
        plan_id=plan.plan_id,
        summary_line_id=parent_id,
        approver="fixture-finance@imperial.local",
        rationale="Részletes sorokból épülő allokáció a kapu tesztjéhez.",
    )
    return plan


def test_detailed_children_sum_to_envelope_passes(db):
    _detailed_plan(db)
    decision = _evaluate(db, cost_code="REINFORCING", amount="1170000")
    assert decision.decision == "PASS"
    db.commit()


def test_detailed_children_over_envelope_block_build_and_gate(db):
    # A gyerekek boríték fölé nőttek: a részletes pillanatkép létrehozása
    plan = _foundation_plan(db)
    parent_id = get_line(db, plan, "FOUNDATION").line_id
    _add_foundation_children(db, plan, parent_id, ("2000000", "1560000", "585000", "390000", "195000"))
    with pytest.raises(MarginGateBlocked) as excinfo:
        build_allocation_from_detailed_lines(db, plan_id=plan.plan_id, summary_line_id=parent_id, approver="fixture-finance@imperial.local", rationale="Részletes sorokból épülő allokáció.",)
    assert excinfo.value.reason_code == "child_sum_over_envelope"
    _foundation_snapshot(db, plan)
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="REINFORCING", amount="100")
    assert excinfo.value.reason_code == "child_sum_over_envelope"


def test_detailed_direct_baseline_children_mismatch_blocks(db):
    plan = seed_gate_plan(
        db,
        project_id=PROJECT,
        revenue="9230769.23",
        summary_lines=[{"cost_code": "FOUNDATION-DCB", "amount": "6000000", "amount_basis": "DIRECT_COST_BASELINE", "component": "other"}],
    )
    add_child_line(db, plan, cost_code="CONCRETE", amount="5000000", component="material", parent_summary_line_id=get_line(db, plan, "FOUNDATION-DCB").line_id)
    _dcb_snapshot(db, plan)
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="CONCRETE", amount="100")
    assert excinfo.value.reason_code == "child_sum_mismatch"


def test_detailed_stale_snapshot_blocks_after_plan_change(db):
    plan = _detailed_plan(db)
    # A terv megváltozik a pillanatkép rögzítése után (új sor) → stale.
    add_child_line(db, plan, cost_code="EXTRA-TRADE", amount="100", component="other", parent_summary_line_id=get_line(db, plan, "FOUNDATION").line_id)
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="REINFORCING", amount="100")
    assert excinfo.value.reason_code == "allocation_stale_snapshot"


# --- Task78: részleges gyerekallokáció margin-bypass zárása ---


def _partial_detailed_plan(db, *, children=("2000000", "2000000"), project=PROJECT):
    """NRE-csomag (boríték 6.5M) gyerekekkel + 2M külön direct sor: a
    gyerekösszeg < boríték, a fel nem osztott maradék a bypass-célpont."""
    plan = seed_gate_plan(db, project_id=project, revenue="10000000", direct_lines=[("MAT-X", "2000000", "material")], summary_lines=[{"cost_code": "PACK-PART", "amount": "10000000", "amount_basis": "NET_REVENUE_ENVELOPE", "component": "other"}],)
    parent_id = get_line(db, plan, "PACK-PART").line_id
    for code, amount in zip(("CHILD-P1", "CHILD-P2"), children):
        add_child_line(db, plan, cost_code=code, amount=amount, component="labour", parent_summary_line_id=parent_id)
    build_allocation_from_detailed_lines(db, plan_id=plan.plan_id, summary_line_id=parent_id, approver="fixture-finance@imperial.local", rationale="Szintetikus gyerekallokáció a bypass-remediációs teszthez.",)
    return plan


def test_partial_detailed_allocation_unallocated_blocks_before_mutation(db):
    # A korábbi vetület 40% fedezet → PASS lett volna; a fel nem osztott
    plan = _partial_detailed_plan(db)
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="CHILD-P1", amount="100")
    assert excinfo.value.reason_code == "allocation_unallocated"
    assert db.scalars(select(FinanceCommitment)).all() == []
    decisions = list(db.scalars(select(MarginGateDecision)).all())
    assert decisions and decisions[0].decision == "BLOCK"
    assert decisions[0].block_reason_code == "allocation_unallocated"
    snapshot = db.scalar(select(FinanceAllocationSnapshot).where(FinanceAllocationSnapshot.plan_id_fk == plan.id))
    assert snapshot.unallocated_amount == Decimal("2500000.00")


def test_partial_detailed_allocation_remainder_counted_once_not_outperforming(db):
    # Inkonzisztens pillanatkép (unallocated=0, gyerekösszeg < boríték): a
    plan = _partial_detailed_plan(db)
    snapshot = db.scalar(select(FinanceAllocationSnapshot).where(FinanceAllocationSnapshot.plan_id_fk == plan.id))
    snapshot.unallocated_amount = Decimal("0")
    db.commit()
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="CHILD-P1", amount="100")
    assert excinfo.value.reason_code == "margin_below_minimum"
    assert excinfo.value.margin_percent == Decimal("15.00")
    assert db.scalars(select(FinanceCommitment)).all() == []
    evidence = list(db.scalars(select(MarginGateDecision)).all())[-1]
    assert evidence.projected_direct_cost_huf == Decimal("8500000.00")
    import json
    calc = json.loads(evidence.calculation_json)
    parent_id = get_line(db, plan, "PACK-PART").line_id
    # Vetület pontosan a fedetlen maradék (2.5M); gyereksor 4M, direct 2M — dupla számolás nélkül.
    assert calc["packages"][parent_id]["projected_direct"] == "2500000.00"
    assert calc["projected_total_direct"] == "8500000.00"
    # Teljes, pontosan egyeztetett gyerekallokáció: a vetület AZONOS
    complete = _partial_detailed_plan(db, children=("3250000", "3250000"), project="GATE-TEST-CMPL")
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="CHILD-P1", amount="100", project="GATE-TEST-CMPL")
    assert excinfo.value.reason_code == "margin_below_minimum"
    assert excinfo.value.margin_percent == Decimal("15.00")
    complete_evidence = list(db.scalars(select(MarginGateDecision)).all())[-1]
    assert complete_evidence.projected_direct_cost_huf == Decimal("8500000.00")


# --- AC-02: snapshot-only szakágkód gyereksoros csomagnál (Review B CRITICAL) ---


def _detailed_norm_plan(db, *, snapshot_code="EXTRA-TRADE"):
    """Gyereksoros csomag NORM_TABLE pillanatképpel, amely snapshot-only kódot is tartalmaz."""
    plan = _foundation_plan(db)
    parent_id = get_line(db, plan, "FOUNDATION").line_id
    _add_foundation_children(db, plan, parent_id, ("1170000", "1560000", "585000", "390000", "195000"))
    create_allocation_snapshot(
        db,
        plan_id=plan.plan_id,
        summary_line_id=parent_id,
        source_type="NORM_TABLE",
        source_version="NORM-FOUND-2026-2",
        source_hash="b" * 64,
        approver="fixture-finance@imperial.local",
        rationale="Szintetikus normatábla snapshot-only szakágkóddal.",
        rows=[
            {"trade_code": "REINFORCING", "direct_cost_component": "material", "normalized_ratio": Decimal("70")},
            {"trade_code": snapshot_code, "direct_cost_component": "other", "normalized_ratio": Decimal("30")},
        ],
    )
    return plan


def test_snapshot_only_trade_code_commitment_counts_in_projection(db):
    plan = _detailed_norm_plan(db)
    # A gyereksorok pontosan a borítékot (3.9M) fedik; a snapshot-only kódra
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="EXTRA-TRADE", amount="100000")
    assert excinfo.value.reason_code == "margin_below_minimum"
    assert excinfo.value.margin_percent == Decimal("33.33")
    import json
    calc = json.loads(list(db.scalars(select(MarginGateDecision)).all())[-1].calculation_json)
    assert calc["per_line"]["EXTRA-TRADE"]["post_direct"] == "100000.00"
    parent_id = get_line(db, plan, "FOUNDATION").line_id
    assert calc["packages"][parent_id]["committed_after"] == "100000.00"


def test_snapshot_only_trade_code_commitment_respects_envelope(db):
    plan = _detailed_norm_plan(db)
    # A snapshot-only kód a csomag-elköteleződésbe is beleszámít: 3.95M > 3.9M boríték → package_envelope_exceeded.
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="EXTRA-TRADE", amount="3950000")
    assert excinfo.value.reason_code == "package_envelope_exceeded"


# --- Task81 (Review-1 HIGH): snapshot-only lekötés pontosan egyszer ---

def _partial_norm_plan(db, *, children, project=PROJECT):
    """NRE-csomag (boríték 3.9M) részleges gyerekekkel, NORM_TABLE
    pillanatkép snapshot-only szakágkóddal (EXTRA-TRADE, 30%)."""
    plan = seed_gate_plan(db, project_id=project, revenue="6000000", summary_lines=[{"cost_code": "FOUNDATION", "amount": "6000000", "amount_basis": "NET_REVENUE_ENVELOPE", "component": "other"}],)
    parent_id = get_line(db, plan, "FOUNDATION").line_id
    for (_code, _name, _component), amount in zip(_FOUNDATION_CHILDREN[:len(children)], children):
        add_child_line(db, plan, cost_code=_code, amount=amount, component="material", parent_summary_line_id=parent_id)
    create_allocation_snapshot(db, plan_id=plan.plan_id, summary_line_id=parent_id, source_type="NORM_TABLE",
        source_version="NORM-FOUND-2026-2", source_hash="b" * 64, approver="fixture-finance@imperial.local",
        rationale="Szintetikus normatábla snapshot-only szakágkóddal.",
        rows=[{"trade_code": "REINFORCING", "direct_cost_component": "material", "normalized_ratio": Decimal("70")},
              {"trade_code": "EXTRA-TRADE", "direct_cost_component": "other", "normalized_ratio": Decimal("30")}],)
    return plan


@pytest.mark.parametrize(
    "children,proposed,expected_decision,expected_margin,expected_total,expected_package",
    [
        # A lekötés a fedetlen maradékon BELÜL van: a vetület pontosan a boríték
        (("2000000", "1000000"), "100000", "PASS", "35.00", "3900000.00", "900000.00"),
        # A lekötés MEGHALADJA a maradékot: a vetület pontosan gyerekek + 500k
        (("2000000", "1500000"), "500000", "margin_below_minimum", "33.33", "4000000.00", "500000.00"),
    ],
    ids=["inside_remainder_not_double_counted", "beyond_remainder_not_omitted"],
)
def test_snapshot_only_commitment_counted_exactly_once(db, children, proposed, expected_decision, expected_margin, expected_total, expected_package):
    plan = _partial_norm_plan(db, children=children)
    import json
    if expected_decision == "PASS":
        decision = _evaluate(db, cost_code="EXTRA-TRADE", amount=proposed)
        assert decision.decision == "PASS"
        assert decision.margin_percent == Decimal(expected_margin)
        assert decision.projected_direct_cost_huf == Decimal(expected_total)
        calc = json.loads(decision.calculation_json)
        db.commit()
    else:
        with pytest.raises(MarginGateBlocked) as excinfo:
            _evaluate(db, cost_code="EXTRA-TRADE", amount=proposed)
        assert excinfo.value.reason_code == expected_decision
        assert excinfo.value.margin_percent == Decimal(expected_margin)
        calc = json.loads(list(db.scalars(select(MarginGateDecision)).all())[-1].calculation_json)
        assert db.scalars(select(FinanceCommitment)).all() == []
    parent_id = get_line(db, plan, "FOUNDATION").line_id
    assert calc["packages"][parent_id]["projected_direct"] == expected_package
    assert calc["projected_total_direct"] == expected_total
    assert calc["per_line"]["EXTRA-TRADE"]["post_direct"] == f"{proposed}.00"
# --- AC-03: indirect gyereksor blokk a kapu értékelésében ---


def test_indirect_child_line_blocks_gate(db):
    plan = _foundation_plan(db)
    from app.models import ProjectFinanceBudgetLine
    db.add(ProjectFinanceBudgetLine(
        line_id="FIN-LINE-IND-CHILD-GATE",
        plan_id_fk=plan.id,
        cost_code="IND-CHILD-GATE",
        category="indirect",
        description="Indirect gyereksor a kapuhoz",
        budget_net=Decimal("100"),
        cost_class="indirect",
        parent_summary_line_id=get_line(db, plan, "FOUNDATION").line_id,
        currency="HUF",
    ))
    db.commit()
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="REINFORCING", amount="100")
    assert excinfo.value.reason_code == "indirect_child_forbidden"


# --- AC-04: arány-pontosság (dedikált Decimal, 0.0001 kvantálás) ---


def test_allocation_ratios_keep_4_decimal_precision_and_normalize_exactly(db):
    plan = _foundation_plan(db)
    snapshot = create_allocation_snapshot(
        db,
        plan_id=plan.plan_id,
        summary_line_id=get_line(db, plan, "FOUNDATION").line_id,
        source_type="NORM_TABLE",
        source_version="NORM-PREC-1",
        source_hash="b" * 64,
        approver="fixture-finance@imperial.local",
        rationale="Szintetikus nagy pontosságú arányok.",
        rows=[
            {"trade_code": "TRADE-A", "direct_cost_component": "material", "normalized_ratio": "33.33333"},
            {"trade_code": "TRADE-B", "direct_cost_component": "material", "normalized_ratio": "33.33333"},
            {"trade_code": "TRADE-C", "direct_cost_component": "other", "normalized_ratio": "33.33334"},
        ],
    )
    ratios = [row.normalized_ratio for row in snapshot.rows]
    # A pénz-kvantáló nem férhet az arányokhoz: 0.0001 pontosság, 100.0000 összeg.
    assert ratios == [Decimal("33.3333"), Decimal("33.3333"), Decimal("33.3334")]
    assert all(ratio.as_tuple().exponent == -4 for ratio in ratios)
    assert sum(ratios, Decimal("0")) == Decimal("100.0000")


def test_allocation_ratio_below_quantum_blocks(db):
    plan = _foundation_plan(db)
    with pytest.raises(MarginGateBlocked) as excinfo:
        create_allocation_snapshot(
            db,
            plan_id=plan.plan_id,
            summary_line_id=get_line(db, plan, "FOUNDATION").line_id,
            source_type="NORM_TABLE",
            source_version="NORM-PREC-2",
            source_hash="b" * 64,
            approver="fixture-finance@imperial.local",
            rationale="Kvantum alatti arány.",
            rows=[
                {"trade_code": "TRADE-A", "direct_cost_component": "material", "normalized_ratio": "0.00004"},
            ],
        )
    assert excinfo.value.reason_code == "invalid_ratio"


def test_normalized_ratios_replay_is_deterministic():
    from app.services.budget_allocation import _normalized_ratios
    raw = [Decimal("33.33333"), Decimal("33.33333"), Decimal("33.33334")]
    expected = [Decimal("33.3333"), Decimal("33.3333"), Decimal("33.3334")]
    assert _normalized_ratios(raw) == expected
    assert _normalized_ratios(raw) == _normalized_ratios(raw)
    assert sum(_normalized_ratios(raw), Decimal("0")) == Decimal("100.0000")




def test_cost_code_change_on_retry_blocks(db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "3250000", "material"), ("MAT-B", "3250000", "material")],)
    _evaluate(db, subject_id="CODESW", cost_code="MAT-A", amount="500000")
    db.commit()
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, subject_id="CODESW", cost_code="MAT-B", amount="500000")
    assert excinfo.value.reason_code == "commitment_cost_code_changed"
    db.rollback()
    rows = list(db.scalars(select(FinanceCommitment)).all())
    assert len(rows) == 1 and rows[0].cost_code == "MAT-A"




def test_block_evidence_persists_after_rollback(db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6501000", "material")])
    with pytest.raises(MarginGateBlocked):
        _evaluate(db, subject_id="BLOCK-EV", amount="100")
    decisions = list(db.scalars(select(MarginGateDecision)).all())
    assert len(decisions) == 1
    assert decisions[0].decision == "BLOCK"
    assert decisions[0].block_reason_code == "margin_below_minimum"
    assert decisions[0].block_reason_hu
    # A lekötés nem maradhat meg blokkolt kísérletből.
    assert db.scalars(select(FinanceCommitment)).all() == []
    audit_rows = list(db.scalars(select(AuditLog).where(AuditLog.action == "margin_gate.blocked")).all())
    assert len(audit_rows) == 1


def test_pass_decision_is_immutable_and_hash_linked(db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")])
    decision = _evaluate(db, subject_id="PASS-EV", amount="100")
    db.commit()
    assert decision.decision == "PASS"
    assert not hasattr(decision, "updated_at")
    assert decision.input_sha256 == sha256_hex(decision.input_snapshot_json)
    assert decision.plan_content_sha256
    audit_rows = list(db.scalars(select(AuditLog).where(AuditLog.action == "margin_gate.passed")).all())
    assert len(audit_rows) == 1
    # A bemenet-pillanatkép tervet és akciót tartalmaz, titkot soha.
    import json
    snapshot = json.loads(decision.input_snapshot_json)
    assert snapshot["plan"]["plan_id"]
    assert snapshot["action"]["proposed_net_huf"] == "100.00"
    assert snapshot["commitments_before"] == []
    assert set(snapshot["lines"][0]) >= {"cost_code", "cost_class", "budget_net"}


# --- ÁFA: konfiguráció kizárólag, a számítást soha nem módosítja ---


def test_vat_rules_never_affect_gate_math(db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")])
    db.add(MarginGateVatRule(
        rule_id="VAT-1", scope="general", vat_rate_percent=Decimal("27"),
        input_vat_differential_percent=Decimal("22"), status="approved",
        rationale="Szintetikus ÁFA-szabály a kapu teszthez.",
        created_by="fixture@imperial.local",
    ))
    db.commit()
    before = _evaluate(db, subject_id="VAT-A", amount="100")
    db.commit()
    rule = db.scalar(select(MarginGateVatRule).where(MarginGateVatRule.rule_id == "VAT-1"))
    rule.vat_rate_percent = Decimal("5")
    rule.input_vat_differential_percent = Decimal("0")
    db.commit()
    after = _evaluate(db, subject_id="VAT-B", amount="100")
    db.commit()
    assert before.margin_percent == after.margin_percent == Decimal("35.00")
    import json
    calc = json.loads(after.calculation_json)
    assert calc["vat_applied_in_math"] is False
    # A 22 százalékpontos differenciál nem jelenhet meg a számításban (ÁFA-mentes, nettó).
    assert "22" not in after.calculation_json


# --- TOCTOU és konkurencia ---


def test_plan_change_between_check_and_commit_detected(db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")])
    decision = _evaluate(db, subject_id="TOCTOU", amount="100")
    # A kapuellenőrzés után egy másik session új verziót hagy jóvá.
    from app.database import SessionLocal
    with SessionLocal() as other:
        other_plan = other.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.project_id == PROJECT))
        other_plan.status = "superseded"
        seed_gate_plan(other, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6501000", "material")], plan_id="FIN-PLAN-TOCTOU-02", version=2,)
        other.commit()
    with pytest.raises(MarginGateStalePlan):
        verify_plan_unchanged(db, decision)
    db.rollback()


def test_list_decisions_filters_to_allowed_projects_only(db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")])
    _evaluate(db, subject_id="SCOPE-1", amount="100")
    db.commit()
    seed_gate_plan(db, project_id="OTHER-PROJECT", revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")])
    _evaluate(db, subject_id="SCOPE-2", amount="100", project="OTHER-PROJECT")
    db.commit()
    # Task77 Gate7: az allowed_project_ids szűrő csak a kör döntéseit adja vissza.
    rows = list_decisions(db, allowed_project_ids={PROJECT})
    assert {row.project_id for row in rows} == {PROJECT}
    assert list_decisions(db, allowed_project_ids=set()) == []
