from app.growth_ops.models import SourceCoverageRoute
from app.growth_ops.processing import _brands


def test_question_radar_expands_multi_brand_routes() -> None:
    route = SourceCoverageRoute(brand_fit="Imperial Holding, Bautica, Prefab")

    assert _brands(route) == ("Imperial", "Bautica", "Prefab")


def test_question_radar_preserves_known_brand_aliases() -> None:
    route = SourceCoverageRoute(brand_fit="Property 360; Veritas")

    assert _brands(route) == ("Property360", "Veritas Construct")


if __name__ == "__main__":
    test_question_radar_expands_multi_brand_routes()
    test_question_radar_preserves_known_brand_aliases()
    print("growth-hotfix-smoke: PASS")
