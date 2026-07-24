from __future__ import annotations


def test_public_new_build_calculator_uses_approved_source_and_hides_internal(client):
    response = client.post("/api/calculators/new-build", json={
        "brand": "imperial",
        "technology": "Danish Fabrik",
        "completion_level": "Kulcsrakész",
        "package": "Alap",
        "gross_area_m2": "100",
        "vat_rate": "0.05",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["estimated_gross_total_huf"] == 68_000_000
    assert data["source_version"] == "Kalkuláció_oldalakhoz_frissített_minden_weboldal_2026-07"
    assert "internal_control" not in data


def test_internal_new_build_calculator_returns_margin_gate(client):
    response = client.post("/api/internal/calculators/new-build", json={
        "brand": "imperial",
        "technology": "Danish Fabrik",
        "completion_level": "Kulcsrakész",
        "package": "Alap",
        "gross_area_m2": "100",
        "vat_rate": "0.05",
    })
    assert response.status_code == 200
    assert response.json()["internal_control"]["margin_gate"] in {"pass", "stop"}


def test_renovation_uses_exact_artukor_line(client):
    catalog = client.get("/api/calculators/renovation/catalog?q=építési terület&limit=5")
    assert catalog.status_code == 200
    item = catalog.json()[0]
    result = client.post("/api/calculators/renovation", json={
        "lines": [{"item_id": item["item_id"], "quantity": "2"}],
        "vat_rate": "0.27",
    })
    assert result.status_code == 200
    data = result.json()
    assert data["estimated_net_total_huf"] == item["net_unit_price_huf"] * 2
    assert data["pre_survey_upper_range_huf"] > data["estimated_gross_total_huf"]


def test_housematch_existing_scoring_and_catalog(client):
    catalog = client.get("/api/housematch/catalog")
    assert catalog.status_code == 200
    assert len(catalog.json()) == 45
    response = client.post("/api/housematch/match", json={
        "budget_huf": "70000000",
        "target_area_m2": "110",
        "lifestyle": "fiatal család",
        "allowed_brands": ["Bautica"],
        "score_profile": "Kiegyensúlyozott",
        "limit": 3,
    })
    assert response.status_code == 200
    rows = response.json()
    assert rows
    assert all(row["brand"] == "Bautica" for row in rows)
    assert rows[0]["score"] >= rows[-1]["score"]
