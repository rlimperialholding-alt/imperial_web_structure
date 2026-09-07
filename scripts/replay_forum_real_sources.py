"""Replay anonymized forum evidence in an isolated in-memory test database.

This does not contact sources, model providers, the server database, email, or
publishing services. The report explicitly identifies the model stub. Original
HTTPS access evidence and source timestamps are documented with the fixtures.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON evidence file.")
    args = parser.parse_args()
    service = Path(__file__).resolve().parents[1] / "services" / "platform-core"
    # Set these before importing any application code. The replay never uses
    # the operator's existing DATABASE_URL or production runtime settings.
    os.environ["DATABASE_URL"] = "sqlite://"
    os.environ["ENVIRONMENT"] = "test"
    sys.path[:0] = [str(service / "tests"), str(service)]
    import conftest  # noqa: F401
    import pytest
    from app.database import Base, SessionLocal, engine
    from app.growth_ops import processing
    from app.growth_ops.models import QuestionRadarTopic
    from app.seed import seed_database
    from sqlalchemy import select
    from test_forum_real_source_replay import (
        OBSERVED_AT,
        test_real_useful_questions_survive_and_repeated_scan_does_not_duplicate,
    )

    report = {
        "verified_at": datetime.now(UTC).isoformat(),
        "mode": "local_original_source_replay",
        "model": "stub; no live provider generation",
        "network_during_replay": False,
        "external_send_or_publication": False,
        "replay_clock": OBSERVED_AT.isoformat(),
        "source_capture_date": "2026-09-07",
        "clock_note": "Fixed test clock; original source publication dates are unchanged.",
        "source_fixture_candidates": 8,
        "useful_expected": 7,
        "irrelevant_control_count": 1,
        "scans_per_scenario": 2,
        "scenarios": [],
    }
    for scenario in ("empty", "short_title", "literal_question", "old_sources"):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            seed_database(db)
            with pytest.MonkeyPatch.context() as monkeypatch:
                test_real_useful_questions_survive_and_repeated_scan_does_not_duplicate(
                    db, monkeypatch, scenario,
                )
                topics = db.scalars(select(QuestionRadarTopic)).all()
                item = {
                    "scenario": scenario,
                    "passed": True,
                    "retained": len(topics),
                    "unique_sources": len({topic.source_url for topic in topics}),
                    "queues": dict(Counter(topic.freshness_decision for topic in topics)),
                    "direct_replies_eligible": sum(
                        bool(processing._reply_eligibility(topic)["eligible"]) for topic in topics
                    ),
                }
                if scenario == "empty":
                    item["decisions"] = [
                        {
                            "source_url": topic.source_url,
                            "question": topic.question,
                            "published_at_utc": topic.published_at.isoformat(),
                            "source_date_raw": topic.published_at_raw,
                            "queue": topic.freshness_decision,
                            "answer_count": topic.existing_answer_count,
                            "source_status": topic.active_status,
                            "brand": topic.brand_id,
                        }
                        for topic in topics
                    ]
                report["scenarios"].append(item)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        print(args.output.resolve())
    else:
        print(serialized)


if __name__ == "__main__":
    main()
