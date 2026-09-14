"""TENDER-kapu: kanonikus 35% direct-margin hard gate (Task75–81).

Az EGYETLEN kanonikus, tranzakcióba ágyazott, fail-closed kapu a tender-
odaítélés, megrendelés/visszaigazolás, finance-commitment outbox és
alvállalkozói szerződés-átmenetek commitment-mutatóihoz. Nincs admin/owner
override. Kizárólag szintetikus fixture-ek; éles tender/megrendelés kizárt.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (FinanceAllocationSnapshot,
    FinanceAllocationSnapshotRow,
    FinanceCommitment,
    MarginGateDecision,
    MarginGateVatRule,
    ProjectFinanceBudgetLine,
    ProjectFinancePlan,)

MIN_DIRECT_MARGIN_PERCENT = Decimal("35.00")
DIRECT_COST_ENVELOPE_RATIO = Decimal("0.65")
REQUIRED_CURRENCY = "HUF"
DIRECT_COMPONENTS = ("material", "labour", "machinery", "other")
COST_CLASSES = ("direct", "indirect")
AMOUNT_BASES = ("NET_REVENUE_ENVELOPE", "DIRECT_COST_BASELINE")
APPROVED_ALLOCATION_SOURCES = ("DETAILED_LINES", "NORM_TABLE", "HISTORICAL_ACTUAL", "SUPPLIER_EVIDENCE",)
MIN_ALLOCATION_CONFIDENCE = Decimal("50.00")
FULL_COVERAGE_PERCENT = Decimal("100.00")
FULL_RATIO_TOTAL = Decimal("100.0000")
REMEDIATION_LINK = "/financial"


def utcnow() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _money(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MarginGateBlocked("invalid_numeric",
            "A költségvetési terv érvénytelen numerikus értéket tartalmaz; "
            f"a TENDER-kapu zárol. Elhárítás: {REMEDIATION_LINK} tervjavítás.",) from exc
    return result.quantize(Decimal("0.01"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class MarginGateBlocked(ValueError):
    """Tipizált fail-closed kapuhiba; az üzenet csak aggregált adatot
    tartalmazhat (fedezet %, tervverzió, kód, link) — soronkénti összeget soha."""

    def __init__(self,
        reason_code: str,
        message_hu: str,
        *,
        margin_percent: Decimal | None = None,
        required_margin_percent: Decimal = MIN_DIRECT_MARGIN_PERCENT,
        plan_version: int | None = None,
        plan_id: str | None = None,
        evidence_persisted: bool = False,) -> None:
        super().__init__(message_hu)
        self.reason_code = reason_code
        self.message_hu = message_hu
        self.margin_percent = margin_percent
        self.required_margin_percent = required_margin_percent
        self.plan_version = plan_version
        self.plan_id = plan_id
        self.evidence_persisted = evidence_persisted


class MarginGateStalePlan(ValueError):
    """A terv a kapuellenőrzés és a commit között megváltozott (TOCTOU)."""


def plan_content_sha256(plan: ProjectFinancePlan) -> str:
    """A jóváhagyott terv kanonikus tartalomlenyomata (terv + sorok) —
    a kapu stale/provenance-detekciójának alapja."""
    lines = []
    for line in sorted(plan.budget_lines, key=lambda item: item.cost_code):
        lines.append({
                "cost_code": line.cost_code,
                "category": line.category,
                "description": line.description,
                "budget_net": str(line.budget_net),
                "committed_net": str(line.committed_net),
                "actual_net": str(line.actual_net),
                "estimate_to_complete_net": str(line.estimate_to_complete_net),
                "cost_class": line.cost_class,
                "direct_cost_component": line.direct_cost_component,
                "amount_basis": line.amount_basis,
                "is_summary_package": bool(line.is_summary_package),
                "parent_summary_line_id": line.parent_summary_line_id,
                "currency": line.currency,
            })
    payload = {
        "plan_id": plan.plan_id,
        "version": plan.version,
        "status": plan.status,
        "currency": plan.currency,
        "contract_revenue_net": str(plan.contract_revenue_net),
        "approved_change_revenue_net": str(plan.approved_change_revenue_net),
        "contingency_net": str(plan.contingency_net),
        "target_margin_percent": str(plan.target_margin_percent),
        "lines": lines,
    }
    return sha256_hex(canonical_json(payload))


def _block(reason_code: str,
    message_hu: str,
    *,
    margin_percent: Decimal | None = None,
    plan_version: int | None = None,
    plan_id: str | None = None,
    evidence_persisted: bool = False,) -> MarginGateBlocked:
    return MarginGateBlocked(reason_code, message_hu, margin_percent=margin_percent, plan_version=plan_version, plan_id=plan_id, evidence_persisted=evidence_persisted,)


def _block_unallocated() -> MarginGateBlocked:
    """Fel nem osztott allokációs maradék — a kapu minden formában zárol."""
    return _block("allocation_unallocated",
        "Az összegző csomag allokációja nem nulla felosztatlan "
        f"összeget hagy; a TENDER-kapu zárol. Elhárítás: auditált "
        f"revízió a {REMEDIATION_LINK} modulban.",)


def load_approved_plan(db: Session, project_id: str, *, for_update: bool = True) -> ProjectFinancePlan:
    """A projekt aktuális, jóváhagyott tervverziója, sorzárral; hiányzó/
    superseded terv fail-closed blokk."""
    stmt = (select(ProjectFinancePlan)
        .where(ProjectFinancePlan.project_id == project_id, ProjectFinancePlan.status == "approved",)
        .order_by(desc(ProjectFinancePlan.version))
        .limit(1))
    if for_update:
        stmt = stmt.with_for_update()
    plan = db.scalar(stmt.execution_options(populate_existing=True))
    if plan is None:
        any_ever = db.scalar(select(ProjectFinancePlan.id) .where(ProjectFinancePlan.project_id == project_id) .limit(1))
        if any_ever is not None:
            raise _block("stale_superseded_budget",
                "A projekthez nincs aktuális, jóváhagyott költségvetési terv: "
                "a korábbi verziók visszavont vagy felülírt állapotúak. A "
                f"TENDER-kapu zárol. Elhárítás: {REMEDIATION_LINK} új verzió "
                "jóváhagyása.",)
        raise _block("missing_approved_budget", "A projekthez nincs jóváhagyott, érvényes költségvetési terv; a " f"TENDER-kapu zárol. Elhárítás: {REMEDIATION_LINK} tervkészítés és jóváhagyás.",)
    if not plan.content_sha256:
        raise _block("missing_provenance",
            "A jóváhagyott tervhez hiányzik a tartalomlenyomat "
            f"(provenance-hash); a TENDER-kapu zárol. Elhárítás: a terv "
            f"újrajóváhagyása a {REMEDIATION_LINK} modulban.",
            plan_version=plan.version,
            plan_id=plan.plan_id,)
    return plan


def _validate_plan_basics(plan: ProjectFinancePlan) -> Decimal:
    if (plan.currency or "") != REQUIRED_CURRENCY:
        raise _block("currency_mismatch", "A költségvetési terv devizaneme nem HUF; a TENDER-kapu csak " "nettó HUF tervet fogad el.", plan_version=plan.version, plan_id=plan.plan_id,)
    revenue = _money(plan.contract_revenue_net) + _money(plan.approved_change_revenue_net)
    if revenue <= 0:
        raise _block("zero_or_negative_revenue", "A jóváhagyott nettó bevétel nem pozitív; a TENDER-kapu zárol. " f"Elhárítás: {REMEDIATION_LINK} bevételegyeztetés.",)
    return revenue


def _direct_lines(plan: ProjectFinancePlan,) -> tuple[list[ProjectFinanceBudgetLine], Decimal, ProjectFinanceBudgetLine | None]:
    """Validálja a sorokat; visszaadja (direct sorok, tartalék-összeg, tartalék-sor).

    Besorolatlan sor, érvénytelen direct komponens, negatív érték, deviza-
    eltérés, indirect gyereksor fail-closed blokk. Az összegző csomagsorok
    nem kerülnek a listába (a direct vetületet a gyereksorok vagy a roll-down
    boríték adják); explicit tartalék-allokációs sor bekerül, a fel nem
    osztott tartalékkeret konzervatívan direct.
    """
    direct: list[ProjectFinanceBudgetLine] = []
    contingency_lines: list[ProjectFinanceBudgetLine] = []
    for line in plan.budget_lines:
        if (line.currency or "") != REQUIRED_CURRENCY:
            raise _block("currency_mismatch", "A költségvetési terv vegyes devizanemű sort tartalmaz; a " "TENDER-kapu zárol. Elhárítás: minden sor HUF-ban.",)
        for field in ("budget_net", "committed_net", "actual_net", "estimate_to_complete_net"):
            if _money(getattr(line, field)) < 0:
                raise _block("negative_value", "A költségvetési terv negatív összeget tartalmaz; a " "TENDER-kapu zárol. Elhárítás: tervjavítás.",)
        if line.cost_class not in COST_CLASSES:
            raise _block("unclassified_budget_line",
                "A költségvetési terv besorolatlan (direct/indirect) sort "
                f"tartalmaz; a TENDER-kapu zárol. Elhárítás: minden sor "
                f"besorolása a {REMEDIATION_LINK} modulban.",)
        if line.parent_summary_line_id and line.cost_class != "direct":
            # Review A MEDIUM: indirect/besorolatlan gyereksor némán kiesne a direct vetületből — blokk.
            raise _block("indirect_child_forbidden",
                "Egy összegző csomag gyereksora csak direct besorolású lehet "
                f"érvényes költségnemmel; a TENDER-kapu zárol. Elhárítás: "
                f"{REMEDIATION_LINK} sorbesorolás.",)
        if line.cost_class == "direct":
            if line.direct_cost_component not in DIRECT_COMPONENTS:
                raise _block("invalid_direct_component", "Egy direct költségvetési sorhoz hiányzik az érvényes " f"költségnem; a TENDER-kapu zárol. Elhárítás: " f"{REMEDIATION_LINK} sorbesorolás.",)
            if "contingency" in (line.category or "").lower():
                contingency_lines.append(line)
                continue
            # Összegző csomagsorok nem kerülnek a per-line ciklusba (a direct vetületet a gyereksorok adják).
            if line.is_summary_package:
                continue
            direct.append(line)
    if not contingency_lines:
        # Konzervatív szabály: a tartalékkeret direct, amíg explicit revízió
        # sorra nem allokálja.
        return direct, _money(plan.contingency_net), None
    if len(contingency_lines) > 1:
        raise _block("duplicate_contingency_allocation", "A tartalékkeret explicit allokációja több soron is szerepel; a " "TENDER-kapu zárol. Elhárítás: egyetlen tartalék-allokációs sor.",)
    contingency_line = contingency_lines[0]
    if _money(contingency_line.budget_net) != _money(plan.contingency_net):
        # A konzervatív szabály csak TELJES allokációnál kapcsol át (részlegesnél a maradék kiesne — Review A M1).
        raise _block("partial_contingency_allocation",
            "A tartalék-allokációs sor nem fedi le pontosan a jóváhagyott "
            "tartalékkeretet; a TENDER-kapu zárol. Elhárítás: auditált "
            "revízió a teljes keret felosztásával.",)
    direct.append(contingency_line)
    return direct, Decimal("0"), contingency_line


def _package_metrics(line: ProjectFinanceBudgetLine) -> tuple[Decimal, Decimal]:
    """(package_net_revenue, package_max_direct_cost) az amount_basis alapján."""
    basis = line.amount_basis
    if basis == "NET_REVENUE_ENVELOPE":
        package_net_revenue = _money(line.budget_net)
        return package_net_revenue, (package_net_revenue * DIRECT_COST_ENVELOPE_RATIO).quantize(Decimal("0.01"), ROUND_HALF_UP)
    if basis == "DIRECT_COST_BASELINE":
        direct_cost = _money(line.budget_net)
        required_revenue = (direct_cost / DIRECT_COST_ENVELOPE_RATIO).quantize(Decimal("0.01"), ROUND_HALF_UP)
        return required_revenue, direct_cost
    raise _block("missing_amount_basis", "Egy összegző csomagsorhoz hiányzik az explicit amount_basis " "(NET_REVENUE_ENVELOPE vagy DIRECT_COST_BASELINE); a TENDER-kapu zárol.",)


def _latest_snapshot(db: Session, plan: ProjectFinancePlan, summary_line_id: str) -> FinanceAllocationSnapshot | None:
    return db.scalar(select(FinanceAllocationSnapshot)
        .where(FinanceAllocationSnapshot.plan_id_fk == plan.id, FinanceAllocationSnapshot.parent_summary_line_id == summary_line_id, FinanceAllocationSnapshot.status == "approved",)
        .order_by(desc(FinanceAllocationSnapshot.version))
        .limit(1)
        .with_for_update())


def resolve_allocations(db: Session, plan: ProjectFinancePlan) -> dict[str, FinanceAllocationSnapshot]:
    """Összegző csomagok allokációinak feloldása és konzisztencia-vizsgálata;
    hiányzó/feloldatlan/lejárt/alacsony megbízhatóságú/inkonzisztens
    pillanatkép és nem nulla unallocated (roll-down) fail-closed."""
    snapshots: dict[str, FinanceAllocationSnapshot] = {}
    child_line_ids = {
        line.parent_summary_line_id
        for line in plan.budget_lines
        if line.parent_summary_line_id
    }
    for line in plan.budget_lines:
        if not line.is_summary_package:
            continue
        snapshot = _latest_snapshot(db, plan, line.line_id)
        if snapshot is None:
            raise _block("allocation_unresolved",
                "Az összegző csomaghoz nincs jóváhagyott allokációs "
                f"pillanatkép; a TENDER-kapu zárol. Elhárítás: allokáció "
                f"rögzítése a {REMEDIATION_LINK} modulban.",)
        if snapshot.source_type not in APPROVED_ALLOCATION_SOURCES:
            raise _block("allocation_unresolved", "Az összegző csomag allokációja feloldatlan forrású " "(ALLOCATION_UNRESOLVED); a TENDER-kapu zárol.",)
        if snapshot.confidence_percent < MIN_ALLOCATION_CONFIDENCE:
            raise _block("allocation_low_confidence", "Az összegző csomag allokációjának megbízhatósága a " "küszöb alatt van; a TENDER-kapu zárol.",)
        if snapshot.coverage_percent != FULL_COVERAGE_PERCENT:
            raise _block("allocation_partial_coverage", "Az összegző csomag allokációja nem teljes lefedettségű; a " "TENDER-kapu zárol.",)
        now = utcnow()
        if snapshot.effective_to is not None and snapshot.effective_to < now:
            raise _block("allocation_expired", "Az összegző csomag allokációs pillanatképe lejárt; a " "TENDER-kapu zárol.",)
        package_net_revenue, package_max_direct = _package_metrics(line)
        if (snapshot.package_net_revenue_huf != package_net_revenue or snapshot.package_max_direct_cost_huf != package_max_direct):
            raise _block("allocation_inconsistent", "Az összegző csomag allokációs pillanatképe nem egyezik a " "terv aktuális csomagértékeivel; a TENDER-kapu zárol.",)
        rows = list(db.scalars(select(FinanceAllocationSnapshotRow).where(FinanceAllocationSnapshotRow.allocation_id_fk == snapshot.id)).all())
        if line.line_id in child_line_ids:
            # Részletes gyereksorok: a stale-detekció a terv lenyomatához kötött.
            if snapshot.source_type == "DETAILED_LINES" and (snapshot.source_hash != plan.content_sha256):
                raise _block("allocation_stale_snapshot",
                    "Az összegző csomag allokációs pillanatképe a terv egy "
                    f"korábbi állapotához tartozik; a TENDER-kapu zárol. "
                    f"Elhárítás: {REMEDIATION_LINK} allokáció újrarögzítése.",)
            # Task78: a fel nem osztott boríték-maradék soha nem tűnhet el némán.
            if snapshot.unallocated_amount != 0:
                raise _block_unallocated()
        else:
            # Roll-down: a teljes borítéknak allokáltnak kell lennie.
            ratio_sum = sum((row.normalized_ratio for row in rows), Decimal("0"))
            if ratio_sum != FULL_RATIO_TOTAL:
                raise _block("allocation_ratios_invalid", "Az összegző csomag allokációs arányai nem adnak ki " "pontosan 100%-ot; a TENDER-kapu zárol.",)
            if snapshot.unallocated_amount != 0:
                raise _block_unallocated()
        snapshots[line.line_id] = snapshot
    return snapshots


def _commitment_rows(db: Session, plan: ProjectFinancePlan) -> list[FinanceCommitment]:
    return list(db.scalars(select(FinanceCommitment) .where(FinanceCommitment.plan_id_fk == plan.id, FinanceCommitment.status == "committed",)
            .with_for_update()).all())


def _upsert_commitment(db: Session,
    plan: ProjectFinancePlan,
    *,
    subject_type: str,
    subject_id: str,
    cost_code: str,
    proposed_net_huf: Decimal,
    actor: str,) -> FinanceCommitment:
    """Idempotens elköteleződés-nyilvántartás a hívó tranzakciójában:
    ugyanaz a (subject_type, subject_id) kulcs mindig ugyanahhoz a
    cost_code-hoz tartozik (kódváltás fail-closed, kettős számolás kizárt),
    az ismételt beküldés ugyanazt a sort írja felül."""
    if proposed_net_huf <= 0:
        raise _block("invalid_commitment_amount", "A javasolt elköteleződés nettó HUF összege nem pozitív; a " "TENDER-kapu zárol.",)
    existing = db.scalar(select(FinanceCommitment).where(FinanceCommitment.subject_type == subject_type, FinanceCommitment.subject_id == subject_id,))
    if existing is not None and existing.cost_code != cost_code:
        raise _block("commitment_cost_code_changed",
            "A meglévő elköteleződés költségkódja nem változtatható meg "
            f"újrabeküldéssel; a TENDER-kapu zárol. Elhárítás: auditált "
            f"költségvetési revízió a {REMEDIATION_LINK} modulban.",)
    row = db.scalar(select(FinanceCommitment).where(FinanceCommitment.subject_type == subject_type, FinanceCommitment.subject_id == subject_id, FinanceCommitment.cost_code == cost_code,))
    if row is None:
        row = FinanceCommitment(commitment_id=_id("FCOMMIT"),
            plan_id_fk=plan.id,
            cost_code=cost_code,
            subject_type=subject_type,
            subject_id=subject_id,
            net_huf=proposed_net_huf,
            currency=REQUIRED_CURRENCY,
            status="committed",
            created_by=actor,)
        db.add(row)
    else:
        # Idempotens csere: a lekötés az aktuális tervre kötődik.
        if row.plan_id_fk != plan.id:
            row.plan_id_fk = plan.id
        if row.net_huf != proposed_net_huf:
            row.net_huf = proposed_net_huf
        if row.currency != REQUIRED_CURRENCY:
            row.currency = REQUIRED_CURRENCY
        row.updated_at = utcnow()
    return row


def _decision_row(*,
    plan: ProjectFinancePlan | None,
    project_id: str,
    action_type: str,
    subject_type: str,
    subject_id: str,
    cost_code: str,
    proposed_net_huf: Decimal,
    revenue_net_huf: Decimal | None,
    projected_direct_cost_huf: Decimal | None,
    margin_percent: Decimal | None,
    decision: str,
    block_reason_code: str | None,
    block_reason_hu: str | None,
    input_snapshot: dict[str, Any],
    calculation: dict[str, Any],
    actor: str,
    plan_fk: bool = True,
    plan_id_override: str | None = None,
    plan_version_override: int | None = None,) -> MarginGateDecision:
    # A BLOCK-bizonyíték független tranzakciója nem hivatkozhatja az FK-n a tervsort
    # (a hívó FOR UPDATE zárja alatt a PG FK-ellenőrzés holtpontra futna); a PASS a hívó tranzakcióban commitol.
    input_snapshot_json = canonical_json(input_snapshot)
    return MarginGateDecision(decision_id=_id("MGATE"),
        project_id=project_id,
        plan_id_fk=plan.id if plan is not None and plan_fk else None,
        plan_id=plan.plan_id if plan is not None else plan_id_override,
        plan_version=plan.version if plan is not None else plan_version_override,
        plan_status=plan.status if plan is not None else None,
        plan_content_sha256=plan.content_sha256 if plan is not None else None,
        action_type=action_type,
        subject_type=subject_type,
        subject_id=subject_id,
        cost_code=cost_code,
        proposed_net_huf=proposed_net_huf,
        revenue_net_huf=revenue_net_huf,
        projected_direct_cost_huf=projected_direct_cost_huf,
        margin_percent=margin_percent,
        required_margin_percent=MIN_DIRECT_MARGIN_PERCENT,
        decision=decision,
        block_reason_code=block_reason_code,
        block_reason_hu=block_reason_hu,
        input_snapshot_json=input_snapshot_json,
        calculation_json=canonical_json(calculation),
        input_sha256=sha256_hex(input_snapshot_json),
        created_by=actor,)


def _commit_block_evidence(row: MarginGateDecision, actor: str) -> None:
    """BLOCK-bizonyíték + audit független tranzakcióban (visszagördülés után is
    megmarad)."""
    from ..database import SessionLocal

    with SessionLocal() as session:
        session.add(row)
        audit(session,
            actor=actor,
            action="margin_gate.blocked",
            entity_type="margin_gate_decision",
            entity_id=row.decision_id,
            after={"reason_code": row.block_reason_code, "decision": row.decision,
                   "subject_type": row.subject_type, "subject_id": row.subject_id,
                   "plan_version": row.plan_version},)
        session.commit()


def _persist_minimal_block_evidence(exc: MarginGateBlocked,
    *,
    project_id: str,
    action_type: str,
    subject_type: str,
    subject_id: str,
    cost_code: str,
    proposed_net_huf: Decimal,
    actor: str,) -> None:
    """Minimális, immutable BLOCK-bizonyíték a korai (terv nélküli) blokkokhoz."""
    row = _decision_row(plan=None,
        project_id=project_id,
        action_type=action_type,
        subject_type=subject_type,
        subject_id=subject_id,
        cost_code=cost_code,
        proposed_net_huf=proposed_net_huf,
        revenue_net_huf=None,
        projected_direct_cost_huf=None,
        margin_percent=exc.margin_percent,
        decision="BLOCK",
        block_reason_code=exc.reason_code,
        block_reason_hu=exc.message_hu,
        input_snapshot={},
        calculation={},
        actor=actor,
        plan_fk=False,
        plan_id_override=exc.plan_id,
        plan_version_override=exc.plan_version,)
    _commit_block_evidence(row, actor)


def blocked_with_evidence(db: Session,
    *,
    reason_code: str,
    message_hu: str,
    project_id: str,
    action_type: str,
    subject_type: str,
    subject_id: str,
    cost_code: str,
    proposed_net_huf: Decimal,
    actor: str,) -> MarginGateBlocked:
    """Wrapper-szintű blokk immutable bizonyítékkal (Review A LOW-3): a kapu
    ELÉ helyezett ellenőrzések is döntési bizonyítékot rögzítenek."""
    exc = MarginGateBlocked(reason_code, message_hu, evidence_persisted=True)
    _persist_minimal_block_evidence(exc,
        project_id=project_id,
        action_type=action_type,
        subject_type=subject_type,
        subject_id=subject_id,
        cost_code=cost_code,
        proposed_net_huf=_money(proposed_net_huf),
        actor=actor,)
    return exc


def evaluate_commitment_gate(db: Session,
    *,
    project_id: str,
    action_type: str,
    subject_type: str,
    subject_id: str,
    cost_code: str,
    proposed_net_huf: Decimal,
    actor: str,) -> MarginGateDecision:
    """A kanonikus TENDER-kapu egy javasolt elköteleződésre. PASS: pillanatkép
    + audit a hívó tranzakciójában; BLOCK: bizonyíték független tranzakcióban,
    majd MarginGateBlocked — a mutáció visszagördül, outbox nem születik."""
    try:
        return _evaluate_commitment_gate_inner(db,
            project_id=project_id,
            action_type=action_type,
            subject_type=subject_type,
            subject_id=subject_id,
            cost_code=cost_code,
            proposed_net_huf=proposed_net_huf,
            actor=actor,)
    except MarginGateBlocked as exc:
        if not exc.evidence_persisted:
            _persist_minimal_block_evidence(exc,
                project_id=project_id,
                action_type=action_type,
                subject_type=subject_type,
                subject_id=subject_id,
                cost_code=cost_code,
                proposed_net_huf=proposed_net_huf,
                actor=actor,)
        raise


def _evaluate_commitment_gate_inner(db: Session,
    *,
    project_id: str,
    action_type: str,
    subject_type: str,
    subject_id: str,
    cost_code: str,
    proposed_net_huf: Decimal,
    actor: str,) -> MarginGateDecision:
    """A kanonikus TENDER-kapu belső kiértékelése (lásd az outer wrapper)."""
    plan = load_approved_plan(db, project_id, for_update=True)
    if not (cost_code or "").strip():
        raise _block("missing_cost_code_mapping", "A művelethez kötelező a jóváhagyott finance-költségkód-" "hozzárendelés; a TENDER-kapu zárol.",)
    proposed_net_huf = _money(proposed_net_huf)
    revenue = _validate_plan_basics(plan)
    direct, contingency_direct, _contingency_line = _direct_lines(plan)
    snapshots = resolve_allocations(db, plan)
    if not direct and not snapshots:
        raise _block("empty_budget", "A jóváhagyott költségvetési terv nem tartalmaz direct sort vagy " "összegző csomagot; a TENDER-kapu zárol.",)
    approved_vat_rule_ids = [
        rule.rule_id
        for rule in db.scalars(select(MarginGateVatRule).where(MarginGateVatRule.status == "approved")).all()
    ]
    commitments_before = _commitment_rows(db, plan)
    known_codes = {line.cost_code for line in direct}
    for snapshot in snapshots.values():
        for trade_row in snapshot.rows:
            known_codes.add(trade_row.trade_code)
    if cost_code not in known_codes:
        raise _block("unknown_cost_code", "A javasolt elköteleződés költségkódja nem szerepel a " "jóváhagyott terv direct sorai között; a TENDER-kapu zárol.",)
    commitment = _upsert_commitment(db, plan, subject_type=subject_type, subject_id=subject_id, cost_code=cost_code, proposed_net_huf=proposed_net_huf, actor=actor,)
    committed_by_code: dict[str, Decimal] = {}
    for commit_row in commitments_before:
        if commit_row.commitment_id != commitment.commitment_id:
            committed_by_code[commit_row.cost_code] = (committed_by_code.get(commit_row.cost_code, Decimal("0")) + _money(commit_row.net_huf))
    committed_by_code[cost_code] = committed_by_code.get(cost_code, Decimal("0")) + (proposed_net_huf)
    # Review A CRITICAL: az árva lekötések a várható direct költségbe számítanak.
    orphan_codes = sorted(code for code in committed_by_code if code not in known_codes)
    orphan_committed = sum((committed_by_code[code] for code in orphan_codes), Decimal("0"))
    # Soronkénti várható akció utáni direct költség.
    per_line: dict[str, dict[str, Any]] = {}
    projected_direct = Decimal("0")
    child_line_ids = {
        line.parent_summary_line_id
        for line in plan.budget_lines
        if line.parent_summary_line_id
    }
    child_sum_by_parent: dict[str, Decimal] = {}
    for line in direct:
        child_sum_by_parent[line.parent_summary_line_id or ""] = (child_sum_by_parent.get(line.parent_summary_line_id or "", Decimal("0")) + _money(line.budget_net))
        committed_after = committed_by_code.get(line.cost_code, Decimal("0"))
        actual_plus_etc = _money(line.actual_net) + _money(line.estimate_to_complete_net)
        baseline_committed = _money(line.committed_net)
        post = max(_money(line.budget_net), actual_plus_etc, baseline_committed + committed_after,)
        per_line[line.cost_code] = {
            "budget_net": str(line.budget_net),
            "actual_plus_etc": str(actual_plus_etc),
            "committed_baseline": str(baseline_committed),
            "committed_after": str(baseline_committed + committed_after),
            "post_direct": str(post),
        }
        projected_direct += post
    # Összegző csomagok projekt-szintű vetülete és csomag-boríték-kapu.
    packages: dict[str, dict[str, Any]] = {}
    for line in plan.budget_lines:
        if not line.is_summary_package:
            continue
        package_net_revenue, package_max_direct = _package_metrics(line)
        snapshot = snapshots[line.line_id]
        trade_rows = {row.trade_code: row for row in snapshot.rows}
        if line.line_id in child_line_ids:
            child_codes = [
                child.cost_code
                for child in direct
                if child.parent_summary_line_id == line.line_id
            ]
            # Review B CRITICAL: a snapshot-only szakágkódok is a csomag-elköteleződésbe számítanak — különben a lekötés eltűnne.
            snapshot_only = [code for code in trade_rows if code not in child_codes]
            package_codes = child_codes + snapshot_only
        else:
            snapshot_only = []
            package_codes = list(trade_rows)
        package_committed = sum((committed_by_code.get(code, Decimal("0")) for code in package_codes), Decimal("0"),)
        if package_committed > package_max_direct:
            raise _block("package_envelope_exceeded",
                "A javasolt elköteleződéssel az összegző csomag "
                "elköteleződése meghaladná a 65%-os csomag-borítékot; a "
                f"TENDER-kapu zárol. Elhárítás: auditált költségvetési "
                f"revízió a {REMEDIATION_LINK} modulban.",)
        if line.line_id in child_line_ids:
            # A gyereksorok a per_line ciklusban már a vetületben vannak.
            children_sum = child_sum_by_parent.get(line.line_id, Decimal("0"))
            if (line.amount_basis == "DIRECT_COST_BASELINE" and children_sum != package_max_direct):
                raise _block("child_sum_mismatch", "Az összegző csomag gyereksorainak összege nem egyezik " "a direct költség-alap csomagértékkel; a TENDER-kapu zárol.",)
            if children_sum > package_max_direct:
                raise _block("child_sum_over_envelope", "Az összegző csomag gyereksorainak összege meghaladja a " "csomag direct borítékát; a TENDER-kapu zárol.",)
            # Task78/Task81: a snapshot-only lekötés a fedetlen maradékon belül EGYSZER számít,
            # fölötte EGYSZER a vetületbe — csomag-vetület = max(boríték, gyerek + snapshot-only) − gyerek (Review-1 HIGH Task81).
            children_post_sum = sum((Decimal(per_line[code]["post_direct"]) for code in child_codes), Decimal("0"))
            snapshot_only_committed_total = sum((committed_by_code.get(code, Decimal("0")) for code in snapshot_only), Decimal("0"))
            package_projected = max(package_max_direct - children_post_sum, snapshot_only_committed_total)
        else:
            # Roll-down: a teljes boríték konzervatívan várható direct költség (a feletti elköteleződés blokkolt).
            package_projected = package_max_direct
        projected_direct += package_projected
        for code in snapshot_only:
            snapshot_only_committed = committed_by_code.get(code, Decimal("0"))
            if snapshot_only_committed > 0:
                # Bizonyíték-sor a naplóhoz; a vetületbe a csomag-képlet fent EGYSZER számította be.
                per_line[code] = {
                    "budget_net": "0.00",
                    "actual_plus_etc": "0.00",
                    "committed_baseline": "0.00",
                    "committed_after": str(snapshot_only_committed),
                    "post_direct": str(snapshot_only_committed),
                }
        trade_margins = {}
        for trade_code, row in trade_rows.items():
            trade_envelope = (package_max_direct * _money(row.normalized_ratio) / Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP)
            trade_committed = committed_by_code.get(trade_code, Decimal("0"))
            trade_margins[trade_code] = {
                "envelope": str(trade_envelope),
                "committed_after": str(trade_committed),
                "margin_percent": str(((package_net_revenue - max(trade_envelope, trade_committed))
                        / package_net_revenue
                        * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)),
            }
        packages[line.line_id] = {
            "summary_work_type": snapshot.summary_work_type,
            "package_net_revenue": str(package_net_revenue),
            "package_max_direct": str(package_max_direct),
            "committed_after": str(package_committed),
            "projected_direct": str(package_projected),
            "allocation_id": snapshot.allocation_id,
            "trade_margins": trade_margins,
        }
    projected_total = (projected_direct + contingency_direct + orphan_committed).quantize(Decimal("0.01"), ROUND_HALF_UP)
    # A kapu a kerekítetlen hányadossal dönt (34.995 blokk).
    margin_exact = (revenue - projected_total) / revenue * 100
    margin_display = margin_exact.quantize(Decimal("0.01"), ROUND_HALF_UP)
    input_snapshot: dict[str, Any] = {
        "plan": {
            "plan_id": plan.plan_id,
            "version": plan.version,
            "status": plan.status,
            "content_sha256": plan.content_sha256,
            "currency": plan.currency,
            "contract_revenue_net": str(plan.contract_revenue_net),
            "approved_change_revenue_net": str(plan.approved_change_revenue_net),
            "contingency_net": str(plan.contingency_net),
            "target_margin_percent": str(plan.target_margin_percent),
        },
        "action": {
            "action_type": action_type,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "cost_code": cost_code,
            "proposed_net_huf": str(proposed_net_huf),
        },
        "lines": [
            {
                "cost_code": line.cost_code,
                "cost_class": line.cost_class,
                "direct_cost_component": line.direct_cost_component,
                "amount_basis": line.amount_basis,
                "is_summary_package": bool(line.is_summary_package),
                "parent_summary_line_id": line.parent_summary_line_id,
                "budget_net": str(line.budget_net),
                "committed_net": str(line.committed_net),
                "actual_net": str(line.actual_net),
                "estimate_to_complete_net": str(line.estimate_to_complete_net),
                "currency": line.currency,
            }
            for line in sorted(plan.budget_lines, key=lambda item: item.cost_code)
        ],
        "allocations": [
            {
                "allocation_id": snapshot.allocation_id,
                "snapshot_sha256": snapshot.snapshot_sha256,
                "source_type": snapshot.source_type,
                "source_hash": snapshot.source_hash,
                "version": snapshot.version,
                "unallocated_amount": str(snapshot.unallocated_amount),
            }
            for snapshot in sorted(snapshots.values(), key=lambda item: item.allocation_id)
        ],
        "commitments_before": sorted(({
                    "subject_type": commit_row.subject_type,
                    "subject_id": commit_row.subject_id,
                    "cost_code": commit_row.cost_code,
                    "net_huf": str(commit_row.net_huf),
                }
                for commit_row in commitments_before),
            key=lambda item: (item["subject_type"], item["subject_id"], item["cost_code"]),),
        "approved_vat_rule_ids": sorted(approved_vat_rule_ids),
    }
    calculation: dict[str, Any] = {
        "revenue_net_huf": str(revenue),
        "contingency_direct": str(contingency_direct),
        "per_line": per_line,
        "packages": packages,
        "orphan_codes": orphan_codes,
        "orphan_committed_direct": str(orphan_committed),
        "projected_total_direct": str(projected_total),
        "margin_exact_percent": str(margin_exact),
        "margin_percent": str(margin_display),
        "required_margin_percent": str(MIN_DIRECT_MARGIN_PERCENT),
        "vat_applied_in_math": False,
    }
    if margin_exact >= MIN_DIRECT_MARGIN_PERCENT:
        pass_row = _decision_row(plan=plan,
            project_id=project_id,
            action_type=action_type,
            subject_type=subject_type,
            subject_id=subject_id,
            cost_code=cost_code,
            proposed_net_huf=proposed_net_huf,
            revenue_net_huf=revenue,
            projected_direct_cost_huf=projected_total,
            margin_percent=margin_display,
            decision="PASS",
            block_reason_code=None,
            block_reason_hu=None,
            input_snapshot=input_snapshot,
            calculation=calculation,
            actor=actor,)
        db.add(pass_row)
        audit(db,
            actor=actor,
            action="margin_gate.passed",
            entity_type="margin_gate_decision",
            entity_id=pass_row.decision_id,
            after={
                "action_type": action_type,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "plan_version": plan.version,
            },)
        return pass_row
    block_reason = (f"A TENDER-kapu blokkol: a számított projektfedezet {margin_display}% a "
        f"tervezett elköteleződéssel, a kötelező minimum {MIN_DIRECT_MARGIN_PERCENT}% "
        f"(tervverzió: {plan.version}, költségkód: {cost_code}). Elhárítás: "
        f"{REMEDIATION_LINK} jóváhagyott költségvetési revízió, majd újraindítás.")
    decision_fields: dict[str, Any] = {
        "plan": plan,
        "project_id": project_id,
        "action_type": action_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "cost_code": cost_code,
        "proposed_net_huf": proposed_net_huf,
        "revenue_net_huf": revenue,
        "projected_direct_cost_huf": projected_total,
        "margin_percent": margin_display,
        "decision": "BLOCK",
        "block_reason_code": "margin_below_minimum",
        "block_reason_hu": block_reason,
        "calculation": calculation,
    }
    _commit_block_evidence(_decision_row(**decision_fields, actor=actor, input_snapshot=input_snapshot, plan_fk=False), actor,)
    raise _block("margin_below_minimum", block_reason, margin_percent=margin_display, plan_version=plan.version, plan_id=plan.plan_id, evidence_persisted=True,)


def verify_plan_unchanged(db: Session, decision: MarginGateDecision) -> None:
    """TOCTOU-őr: a kapuellenőrzés óta a terv nem változhatott meg; eltérés
    esetén a teljes tranzakció visszagördül."""
    if decision.plan_id is None:
        return
    stmt = (select(ProjectFinancePlan)
        .where(ProjectFinancePlan.project_id == decision.project_id, ProjectFinancePlan.status == "approved",)
        .order_by(desc(ProjectFinancePlan.version))
        .limit(1)
        .with_for_update())
    plan = db.scalar(stmt.execution_options(populate_existing=True))
    if (plan is None or plan.id != decision.plan_id_fk or plan.version != decision.plan_version or plan.content_sha256 != decision.plan_content_sha256):
        raise MarginGateStalePlan("A költségvetési terv a kapuellenőrzés óta megváltozott; a " "művelet visszavonva. Indítsa újra az ellenőrzést az aktuális " "tervvel.")


def list_decisions(db: Session, *, project_id: str | None = None, limit: int = 200, allowed_project_ids: set[str] | None = None,) -> list[MarginGateDecision]:
    """Döntésnapló-lekérdezés; ``allowed_project_ids`` nem-None esetén csak az
    actor számára elérhető projektek döntéseit adja vissza (Task77 Gate7)."""
    stmt = select(MarginGateDecision).order_by(desc(MarginGateDecision.created_at)).limit(limit)
    if allowed_project_ids is not None:
        stmt = stmt.where(MarginGateDecision.project_id.in_(sorted(allowed_project_ids)))
    if project_id:
        stmt = stmt.where(MarginGateDecision.project_id == project_id)
    return list(db.scalars(stmt).all())
