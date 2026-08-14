from __future__ import annotations

from datetime import timedelta
from time import perf_counter

from sqlalchemy import event, insert, inspect

from app.models import MarketCaptureJob, utcnow
from app.services.market_intelligence import MarketActor, create_target, dashboard


def test_market_dashboard_is_bounded_and_indexed_with_more_than_10k_jobs(db):
    actor = MarketActor(
        subject_id="ITEP-MKT-PERF",
        tenant_id="imperial-holding",
        brand_id="imperial",
        market_id="HU",
        can_author=True,
    )
    target = create_target(
        db,
        actor=actor,
        name="Performance target",
        source_type="public_web",
        origin="https://performance.example.test",
        allowed_path="/research",
        rights_status="PUBLIC_RESEARCH",
        capture_mode="public_fetch",
    )
    now = utcnow()
    rows = []
    for sequence in range(10_050):
        status = "QUEUED" if sequence < 25 else "FAILED" if sequence < 50 else "SUCCEEDED"
        rows.append(
            {
                "job_id": f"MCJ-PERF-{sequence:05d}",
                "tenant_id": actor.tenant_id,
                "brand_id": actor.brand_id,
                "market_id": actor.market_id,
                "target_id": target["targetId"],
                "requested_url": f"https://performance.example.test/research/{sequence}",
                "target_revision_no": 1,
                "policy_sha256": "a" * 64,
                "idempotency_key": f"performance-{sequence:05d}",
                "status": status,
                "attempts": 1,
                "error_code": "fixture_failure" if status == "FAILED" else None,
                "created_by": actor.subject_id,
                "created_at": now - timedelta(seconds=sequence),
                "finished_at": now if status in {"FAILED", "SUCCEEDED"} else None,
            }
        )
    rows.extend(
        {
            "job_id": f"MCJ-ALIEN-{sequence:04d}",
            "tenant_id": "other-tenant",
            "brand_id": "other-brand",
            "market_id": "XX",
            "target_id": "MST-ALIEN",
            "requested_url": f"https://other.example.test/{sequence}",
            "target_revision_no": 1,
            "policy_sha256": "b" * 64,
            "idempotency_key": f"alien-{sequence:04d}",
            "status": "QUEUED",
            "attempts": 0,
            "created_by": "ITEP-ALIEN",
            "created_at": now,
        }
        for sequence in range(250)
    )
    db.execute(insert(MarketCaptureJob), rows)
    db.commit()

    index_names = {
        item["name"] for item in inspect(db.get_bind()).get_indexes("market_capture_jobs")
    }
    assert {
        "ix_mkt_capture_scope_created",
        "ix_mkt_capture_scope_status_finished",
        "ix_mkt_capture_target_created",
    } <= index_names

    statements: list[str] = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(str(statement))

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record_statement)
    started_at = perf_counter()
    try:
        view = dashboard(db, actor, public_fetch_enabled=False)
    finally:
        elapsed_seconds = perf_counter() - started_at
        event.remove(engine, "before_cursor_execute", record_statement)

    assert len(view["captureJobs"]) == 100
    assert view["health"]["queueDepth"] == 25
    assert view["health"]["failed"] == 25
    assert view["health"]["publicFetch"] == "DISABLED"
    assert all(item["targetId"] == target["targetId"] for item in view["captureJobs"])
    assert len(statements) <= 24
    assert elapsed_seconds < 5
