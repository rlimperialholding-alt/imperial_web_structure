from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.growth_ops.catalog import _daily_route_target, _paced_route_target
from app.growth_ops.models import SourceCoverageRoute
from app.growth_ops.processing import _brands


def test_route_pacing_reaches_daily_minimum_before_internal_handoff() -> None:
    zone = ZoneInfo("Europe/Budapest")
    cfg = SimpleNamespace(
        canonical_internal_handoff_at="18:30",
        canonical_route_batch_size=10,
    )
    start = datetime(2026, 8, 23, 8, 0, tzinfo=zone)

    assert _paced_route_target(cfg, datetime(2026, 8, 23, 13, 0, tzinfo=zone), start) == 400
    assert _paced_route_target(cfg, datetime(2026, 8, 23, 18, 0, tzinfo=zone), start) == 800


def test_route_scanning_continues_until_lead_minimum_with_safe_ceiling() -> None:
    assert (
        _daily_route_target(
            attempted_today=800,
            unique_leads_today=99,
            paced_minimum_target=800,
        )
        == 2_000
    )
    assert (
        _daily_route_target(
            attempted_today=800,
            unique_leads_today=100,
            paced_minimum_target=800,
        )
        == 800
    )


def test_question_radar_expands_multi_brand_routes() -> None:
    route = SourceCoverageRoute(brand_fit="Imperial Holding, Bautica, Prefab")

    assert _brands(route) == ("Imperial", "Bautica", "Prefab")


def test_question_radar_preserves_known_brand_aliases() -> None:
    route = SourceCoverageRoute(brand_fit="Property 360; Veritas")

    assert _brands(route) == ("Property360", "Veritas Construct")


if __name__ == "__main__":
    test_route_pacing_reaches_daily_minimum_before_internal_handoff()
    test_route_scanning_continues_until_lead_minimum_with_safe_ceiling()
    test_question_radar_expands_multi_brand_routes()
    test_question_radar_preserves_known_brand_aliases()
    print("growth-hotfix-smoke: PASS")
