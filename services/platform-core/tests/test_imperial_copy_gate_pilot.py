from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from copy_gate_fixtures import (
    canonical_sources,
    editorial_review,
    imperial_asset,
    imperial_brief,
)

from app.copy_gate.engine import evaluate_content
from app.copy_gate.models import ContentBlock, ContentEvaluationRequest, Decision

PILOT_PATH = Path(__file__).resolve().parents[1] / "data" / "copy_gate" / "imperial_pilot_v1.json"


def test_complete_imperial_pilot_has_distinct_publishable_assets():
    pilot = json.loads(PILOT_PATH.read_text(encoding="utf-8"))
    assets = pilot["assets"]

    assert len(assets) == 15
    assert sum(item["assetType"] == "meta_ad" for item in assets) == 7
    assert sum(item["assetType"] == "followup_email" for item in assets) == 3
    assert len({item["title"] for item in assets}) == len(assets)
    assert len({item["layout"] for item in assets}) == len(assets)
    assert pilot["requiresOwnerApprovalBeforePublication"] is True

    scorecards = []
    for item in assets:
        brief = imperial_brief(
            copy_brief_id=f"CB-{item['id'].upper()}",
            asset_type=item["assetType"],
            channel=item["channel"],
        )
        asset = imperial_asset(
            asset_id=f"ASSET-{item['id'].upper()}",
            asset_type=item["assetType"],
        )
        asset.title = item["title"]
        asset.body = (
            f"{item['angle']} A fix ár, fix határidő és rögzített műszaki tartalom "
            "az aktív ajánlati feltételekkel együtt ellenőrizhető. Ha a költségek "
            "elszabadulásától tart, a díjmentes mérnöki konzultáció a döntés előtt "
            "tisztázza a 126 m²-es mintaterv releváns kérdéseit."
        )
        asset.content_blocks = [
            ContentBlock(
                block_id=f"{item['id']}-{index}",
                text=f"{item['title']} – {index}. önálló tartalmi funkció.",
                layout_signature=f"{item['layout']}-{index}",
            )
            for index in range(1, item["blocks"] + 1)
        ]
        result = evaluate_content(
            ContentEvaluationRequest(
                brief=brief,
                sources=canonical_sources(),
                asset=asset,
                editorial_review=editorial_review(asset),
                evaluated_on=date(2026, 7, 26),
            )
        )
        scorecards.append(result)

    assert all(result.total_score >= 92 for result in scorecards)
    assert all(result.final_decision == Decision.APPROVED for result in scorecards)
    assert all(not result.publication_blocked for result in scorecards)
