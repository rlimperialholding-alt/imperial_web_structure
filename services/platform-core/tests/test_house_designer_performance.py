from __future__ import annotations

import json
import math
from time import perf_counter

from sqlalchemy import select

from app.models import HouseDesignRevision
from app.services.house_designer import (
    ActorScope,
    _revision_hash,
    apply_session_command,
    create_session,
    session_detail,
)
from app.services.house_designer_geometry import apply_command, empty_geometry
from app.services.regulatory_compliance import evaluate_rules


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def _geometry_with_200_rooms():
    geometry = empty_geometry(20_000, 10_000)
    rooms = geometry["levels"][0]["rooms"]
    for row in range(10):
        for column in range(20):
            x = column * 1_000
            y = row * 1_000
            rooms.append(
                {
                    "id": f"R-{row:02d}-{column:02d}",
                    "name": "Helyiség",
                    "function": "other",
                    "polygon": [
                        {"x": x, "y": y},
                        {"x": x + 1_000, "y": y},
                        {"x": x + 1_000, "y": y + 1_000},
                        {"x": x, "y": y + 1_000},
                        {"x": x, "y": y},
                    ],
                }
            )
    return geometry


def _performance_rule(index: int):
    return {
        "code": f"PERF_HEIGHT_{index:03d}",
        "category": "height_storeys",
        "fact": "building.height_m",
        "operator": "lte",
        "expected": "3",
        "severity": "BLOCKER",
        "sourceRef": "SRC-PERF",
        "ruleRef": f"PERF-{index:03d}",
        "explanation": "A magassági feltétel nem teljesült.",
        "remediation": "Csökkentse az épület magasságát.",
    }


def test_editor_command_p95_is_below_250_ms_with_200_objects():
    geometry = _geometry_with_200_rooms()
    apply_command(geometry, "set_north", {"northAngleDeg": 1})
    samples = []
    for angle in range(2, 32):
        started = perf_counter()
        apply_command(geometry, "set_north", {"northAngleDeg": angle})
        samples.append(perf_counter() - started)
    p95 = _p95(samples)
    assert p95 < 0.250, {
        "p95_ms": round(p95 * 1_000, 3),
        "samples_ms": [round(sample * 1_000, 3) for sample in samples],
    }


def test_editor_service_p95_includes_revision_audit_and_db_with_200_objects(db):
    actor = ActorScope("perf-customer", "imperial-holding", frozenset({"imperial"}))
    design = create_session(
        db,
        actor=actor,
        brand_id="imperial",
        title="200 object performance fixture",
        command_id="perf-editor-create",
        width_mm=20_000,
        depth_mm=10_000,
    )
    revision = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == design["revision"]["revisionId"]
        )
    )
    assert revision is not None
    geometry = _geometry_with_200_rooms()
    revision.geometry_json = json.dumps(
        geometry, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    revision.canonical_sha256 = _revision_hash(geometry, {}, {})
    db.commit()
    design = session_detail(db, design["sessionId"], actor)
    samples = []
    for angle in range(30):
        current = design["revision"]
        started = perf_counter()
        design = apply_session_command(
            db,
            session_id=design["sessionId"],
            actor=actor,
            base_revision_id=current["revisionId"],
            base_canonical_sha256=current["canonicalSha256"],
            command_id=f"perf-editor-{angle:02d}",
            command_type="set_north",
            payload={"northAngleDeg": angle},
        )
        samples.append(perf_counter() - started)
    p95 = _p95(samples)
    assert p95 < 0.250, {
        "p95_ms": round(p95 * 1_000, 3),
        "samples_ms": [round(sample * 1_000, 3) for sample in samples],
    }


def test_compliance_p95_is_below_3_seconds_with_500_rules():
    geometry = empty_geometry()
    site = {"verificationStatus": "verified"}
    rules = {
        "schemaVersion": "regulatory-rules-v2",
        "checks": [_performance_rule(index) for index in range(500)],
    }
    outcome, findings = evaluate_rules(geometry, site, rules)
    assert outcome == "PASS"
    assert len(findings) == 500
    samples = []
    for _ in range(10):
        started = perf_counter()
        outcome, findings = evaluate_rules(geometry, site, rules)
        samples.append(perf_counter() - started)
    assert outcome == "PASS"
    assert len(findings) == 500
    assert _p95(samples) < 3.0
