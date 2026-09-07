"""Összegző költségvetési csomagok verziózott, immutable allokációs pillanatképei.

Forrás-precedencia: (1) részletes jóváhagyott sorok, (2) verziózott
normatábla, (3) historikus tény vagy szállítói bizonyíték; minden más
ALLOCATION_UNRESOLVED és fail-closed blokk. Az arányok determinisztikusan
pontosan 100.0000 összeget adnak, az allokált nettó HUF pontosan a direct
boríték; a pillanatkép írásvédett, a verziószám monoton nő.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    FinanceAllocationSnapshot,
    FinanceAllocationSnapshotRow,
    ProjectFinanceBudgetLine,
    ProjectFinancePlan,
)
from .tender_margin_gate import (
    APPROVED_ALLOCATION_SOURCES,
    DIRECT_COMPONENTS,
    FULL_COVERAGE_PERCENT,
    FULL_RATIO_TOTAL,
    MIN_ALLOCATION_CONFIDENCE,
    MarginGateBlocked,
    _id,
    _money,
    _package_metrics,
    canonical_json,
    sha256_hex,
    utcnow,
)

DETAILED_LINES = "DETAILED_LINES"
MAX_ALLOCATION_ROWS = 100


def _ratio(value: object) -> Decimal:
    """Arány-parse dedikált Decimal pontossággal, 0.0001 kvantálással; a
    pénz-kvantáló (0.01) tilos az arányokra (Review A HIGH)."""
    try:
        ratio = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MarginGateBlocked(
            "invalid_ratio",
            "Az allokációs arány érvénytelen numerikus érték.",
        ) from exc
    if not ratio.is_finite():
        raise MarginGateBlocked("invalid_ratio", "Az allokációs arány nem lehet NaN/Inf.",)
    return ratio.quantize(Decimal("0.0001"), ROUND_HALF_UP)


def _load_plan(db: Session, plan_id: str, *, for_update: bool = True) -> ProjectFinancePlan:
    stmt = select(ProjectFinancePlan).where(ProjectFinancePlan.plan_id == plan_id)
    if for_update:
        stmt = stmt.with_for_update()
    plan = db.scalar(stmt.execution_options(populate_existing=True))
    if plan is None:
        raise KeyError(plan_id)
    if plan.status in {"rejected", "superseded"}:
        raise MarginGateBlocked("invalid_plan_state", "Visszavont vagy felülírt tervhez allokáció nem rögzíthető.",)
    return plan


def _summary_line(db: Session, plan: ProjectFinancePlan, summary_line_id: str) -> ProjectFinanceBudgetLine:
    line = db.scalar(select(ProjectFinanceBudgetLine) .where( ProjectFinanceBudgetLine.plan_id_fk == plan.id, ProjectFinanceBudgetLine.line_id == summary_line_id,)
        .with_for_update()
    )
    if line is None:
        raise KeyError(summary_line_id)
    if not line.is_summary_package:
        raise MarginGateBlocked("not_summary_package", "Allokáció csak összegző csomagsorhoz rögzíthető.",)
    if line.amount_basis not in ("NET_REVENUE_ENVELOPE", "DIRECT_COST_BASELINE"):
        raise MarginGateBlocked("missing_amount_basis", "Az összegző csomagsorhoz hiányzik az explicit amount_basis; " "allokáció nem rögzíthető.",)
    return line


def _normalized_ratios(ratios: list[Decimal]) -> list[Decimal]:
    """Az arányok determinisztikus normalizálása pontosan 100.0000 összegre."""
    quantized = [ratio.quantize(Decimal("0.0001"), ROUND_HALF_UP) for ratio in ratios]
    total = sum(quantized, Decimal("0"))
    quantized[-1] = quantized[-1] + (FULL_RATIO_TOTAL - total)
    if any(ratio <= 0 for ratio in quantized):
        raise MarginGateBlocked("invalid_ratio", "A normalizált allokációs arányoknak pozitívnak kell maradniuk.",)
    return quantized


def _detailed_rows(
    db: Session, plan: ProjectFinancePlan, line: ProjectFinanceBudgetLine
) -> tuple[list[dict[str, Any]], Decimal]:
    children = sorted(db.scalars( select(ProjectFinanceBudgetLine).where( ProjectFinanceBudgetLine.plan_id_fk == plan.id, ProjectFinanceBudgetLine.parent_summary_line_id == line.line_id,)
        ).all(),
        key=lambda item: item.cost_code,
    )
    if not children:
        raise MarginGateBlocked("no_detailed_children", "A részletes-sor forráshoz a csomagnak gyereksorokkal kell " "rendelkeznie; ellenkező esetben arányforrást kell megadni.",)
    if len(children) > MAX_ALLOCATION_ROWS:
        raise MarginGateBlocked("too_many_allocation_rows", "Az allokációs sorok száma meghaladja a korlátot.")
    # Review B LOW-2: a gyereksorok csak direct besorolásúak lehetnek érvényes
    # költségnemmel — az indirect gyerek explicit fail-closed blokk.
    for child in children:
        if child.cost_class != "direct" or child.direct_cost_component not in DIRECT_COMPONENTS:
            raise MarginGateBlocked("indirect_child_forbidden", "Az összegző csomag gyereksorai csak direct besorolásúak " "lehetnek érvényes költségnemmel; az allokáció nem rögzíthető.",)
    package_net_revenue, package_max_direct = _package_metrics(line)
    children_sum = sum((_money(child.budget_net) for child in children), Decimal("0"))
    if line.amount_basis == "DIRECT_COST_BASELINE" and children_sum != package_max_direct:
        raise MarginGateBlocked("child_sum_mismatch", "A gyereksorok összege nem egyezik a direct költség-alap " "csomagértékkel; az allokáció nem rögzíthető.",)
    if children_sum > package_max_direct:
        raise MarginGateBlocked("child_sum_over_envelope", "A gyereksorok összege meghaladja a csomag direct borítékát; az " "allokáció nem rögzíthető.",)
    if children_sum <= 0:
        raise MarginGateBlocked("empty_detailed_children", "A gyereksorok összege nem pozitív; az allokáció nem rögzíthető.")
    ratios = _normalized_ratios([_money(child.budget_net) / children_sum * 100 for child in children])
    rows: list[dict[str, Any]] = []
    for child, ratio in zip(children, ratios):
        rows.append({ "trade_code": child.cost_code, "direct_cost_component": child.direct_cost_component, "normalized_ratio": ratio, "allocated_net_huf": _money(child.budget_net), })
    return rows, children_sum


def create_allocation_snapshot(
    db: Session,
    *,
    plan_id: str,
    summary_line_id: str,
    source_type: str,
    source_version: str | None = None,
    source_hash: str | None = None,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    confidence_percent: Decimal = Decimal("100"),
    coverage_percent: Decimal = Decimal("100"),
    rows: list[dict[str, Any]] | None = None,
    approver: str,
    rationale: str,
) -> FinanceAllocationSnapshot:
    """Jóváhagyott, verziózott allokációs pillanatkép; DETAILED_LINES-nál a
    gyereksorokból épül (rows tilos), arányforrásnál a rows és a forrás-
    verzió/lenyomat kötelező."""
    if not rationale.strip():
        raise MarginGateBlocked("missing_rationale", "Az allokáció indoklása kötelező.")
    plan = _load_plan(db, plan_id)
    line = _summary_line(db, plan, summary_line_id)
    if source_type not in APPROVED_ALLOCATION_SOURCES:
        raise MarginGateBlocked("unapproved_source_type", "Az allokációs forrás típusa nem engedélyezett; feloldatlan " "forrás nem rögzíthető jóváhagyott pillanatképként.",)
    if confidence_percent < MIN_ALLOCATION_CONFIDENCE:
        raise MarginGateBlocked("allocation_low_confidence", "Az allokáció megbízhatósága a küszöb alatt van.")
    if coverage_percent != FULL_COVERAGE_PERCENT:
        raise MarginGateBlocked("allocation_partial_coverage", "Az allokáció nem teljes lefedettségű.")
    package_net_revenue, package_max_direct = _package_metrics(line)
    plan_hash = plan.content_sha256
    if source_type == DETAILED_LINES:
        if rows:
            raise MarginGateBlocked("detailed_rows_conflict", "DETAILED_LINES forrásnál az aránysorok a gyereksorokból " "számolandók; kézi rows nem adható.",)
        final_rows, children_sum = _detailed_rows(db, plan, line)
        unallocated = max(package_max_direct - children_sum, Decimal("0"))
        effective_source_hash = plan_hash
    else:
        if not rows:
            raise MarginGateBlocked("missing_ratio_rows", "Az arányforrású allokációhoz kötelező a szakágsor-lista.",)
        if len(rows) > MAX_ALLOCATION_ROWS:
            raise MarginGateBlocked("too_many_allocation_rows", "Az allokációs sorok száma meghaladja a korlátot.")
        if not source_hash:
            raise MarginGateBlocked("missing_source_hash", "Az arányforrású allokációhoz kötelező a forrás-verzió/lenyomat.")
        normalized_rows: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        raw_ratios: list[Decimal] = []
        for row in rows:
            trade_code = str(row.get("trade_code") or "").strip()
            component = str(row.get("direct_cost_component") or "").strip()
            if not trade_code or trade_code in seen_codes:
                raise MarginGateBlocked("duplicate_trade_code", "Az allokációs szakágkódoknak egyedinek kell lenniük.")
            if component not in DIRECT_COMPONENTS:
                raise MarginGateBlocked("invalid_direct_component", "Az allokációs sor költségneme érvénytelen.")
            ratio = _ratio(row.get("normalized_ratio"))
            if ratio <= 0:
                raise MarginGateBlocked("invalid_ratio", "Az allokációs arányoknak pozitívnak kell lenniük.")
            seen_codes.add(trade_code)
            raw_ratios.append(ratio)
            normalized_rows.append({"trade_code": trade_code, "direct_cost_component": component})
        ratios = _normalized_ratios(raw_ratios)
        allocated = [
            (package_max_direct * ratio / Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP)
            for ratio in ratios
        ]
        difference = package_max_direct - sum(allocated, Decimal("0"))
        allocated[-1] = allocated[-1] + difference
        for entry, ratio, amount in zip(normalized_rows, ratios, allocated):
            entry["normalized_ratio"] = ratio
            entry["allocated_net_huf"] = amount
        final_rows = normalized_rows
        unallocated = Decimal("0")
        effective_source_hash = source_hash
    # Review B MEDIUM-2: a szakágkódok terven belül csomagonként egyediek
    # (keresztfinanszírozás tilalma).
    other_trade_codes = {
        code
        for code in db.scalars(
            select(FinanceAllocationSnapshotRow.trade_code)
            .join(FinanceAllocationSnapshot, FinanceAllocationSnapshotRow.allocation_id_fk == FinanceAllocationSnapshot.id,)
            .where(FinanceAllocationSnapshot.plan_id_fk == plan.id, FinanceAllocationSnapshot.parent_summary_line_id != line.line_id,)
        ).all()
    }
    proposed_codes = {entry["trade_code"] for entry in final_rows}
    overlap = sorted(other_trade_codes & proposed_codes)
    if overlap:
        raise MarginGateBlocked("trade_code_cross_package_conflict", "A szakágkód más összegző csomaghoz is hozzá van rendelve; " "keresztfinanszírozás tiltott: " + ", ".join(overlap),)
    version = 1 + int(db.scalar( select(FinanceAllocationSnapshot.version) .where( FinanceAllocationSnapshot.plan_id_fk == plan.id, FinanceAllocationSnapshot.parent_summary_line_id == line.line_id,)
            .order_by(desc(FinanceAllocationSnapshot.version))
            .limit(1)
        )
        or 0
    )
    fields = dict(
        plan_id_fk=plan.id,
        parent_summary_line_id=line.line_id,
        summary_work_type=line.category,
        package_net_revenue_huf=package_net_revenue,
        package_max_direct_cost_huf=package_max_direct,
        unallocated_amount=unallocated,
        version=version,
        source_type=source_type,
        source_version=source_version,
        source_hash=effective_source_hash,
        confidence_percent=confidence_percent,
        coverage_percent=coverage_percent,
    )
    payload = {
        "plan_id": plan.plan_id,
        "plan_content_sha256": plan_hash,
        "parent_summary_line_id": line.line_id,
        "summary_work_type": line.category,
        "package_net_revenue_huf": str(package_net_revenue),
        "package_max_direct_cost_huf": str(package_max_direct),
        "unallocated_amount": str(unallocated),
        "version": version,
        "source_type": source_type,
        "source_version": source_version,
        "source_hash": effective_source_hash,
        "confidence_percent": str(confidence_percent),
        "coverage_percent": str(coverage_percent),
        "rows": final_rows,
    }
    snapshot = FinanceAllocationSnapshot(
        allocation_id=_id("ALLOC"),
        status="approved",
        effective_from=effective_from or utcnow(),
        effective_to=effective_to,
        approved_by=approver,
        approved_at=utcnow(),
        rationale=rationale.strip(),
        snapshot_sha256=sha256_hex(canonical_json(payload)),
        created_at=utcnow(),
        **fields,
    )
    db.add(snapshot)
    db.flush()
    for entry in final_rows:
        db.add(
            FinanceAllocationSnapshotRow(
                row_id=_id("ALLOCR"),
                allocation_id_fk=snapshot.id,
                trade_code=entry["trade_code"],
                direct_cost_component=entry["direct_cost_component"],
                normalized_ratio=entry["normalized_ratio"],
                allocated_net_huf=entry["allocated_net_huf"],
                created_at=utcnow(),
            )
        )
    audit(
        db,
        actor=approver,
        action="budget.allocation.snapshot_created",
        entity_type="finance_allocation_snapshot",
        entity_id=snapshot.allocation_id,
        after={
            "plan_id": plan.plan_id,
            "summary_line_id": line.line_id,
            "source_type": source_type,
            "version": version,
            "snapshot_sha256": snapshot.snapshot_sha256,
        },
    )
    db.commit()
    db.refresh(snapshot)
    return snapshot


def build_allocation_from_detailed_lines(
    db: Session,
    *,
    plan_id: str,
    summary_line_id: str,
    approver: str,
    rationale: str,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> FinanceAllocationSnapshot:
    """Precedencia (1): a pillanatkép a részletes jóváhagyott sorokból épül."""
    return create_allocation_snapshot(
        db,
        plan_id=plan_id,
        summary_line_id=summary_line_id,
        source_type=DETAILED_LINES,
        effective_from=effective_from,
        effective_to=effective_to,
        approver=approver,
        rationale=rationale,
    )


def list_allocations(
    db: Session, plan_id: str
) -> list[FinanceAllocationSnapshot]:
    plan = db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.plan_id == plan_id))
    if plan is None:
        raise KeyError(plan_id)
    return list(db.scalars( select(FinanceAllocationSnapshot) .where(FinanceAllocationSnapshot.plan_id_fk == plan.id) .order_by(desc(FinanceAllocationSnapshot.version)) ).all())
