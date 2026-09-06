import json

from sqlalchemy import select

from app.growth_ops.canonical_policy import ACTIVE_CONTENT_BRANDS, DAILY_CONTENT_BRAND_MINIMUM
from app.models import CopySourceRecord


def test_active_brand_scope_excludes_non_brands_and_inventory_is_seeded(db):
    assert "Imperial Intelligence" not in ACTIVE_CONTENT_BRANDS
    assert "Imperial Knowledge" not in ACTIVE_CONTENT_BRANDS
    assert {"Property360", "RED Property", "Venture Studio"}.issubset(ACTIVE_CONTENT_BRANDS)
    assert len(ACTIVE_CONTENT_BRANDS) == DAILY_CONTENT_BRAND_MINIMUM == 17

    rows = db.scalars(
        select(CopySourceRecord).where(
            CopySourceRecord.brand_id.in_(("Property360", "RED Property", "Venture Studio")),
            CopySourceRecord.status == "approved",
            CopySourceRecord.approved.is_(True),
        )
    ).all()
    by_brand = {}
    for row in rows:
        by_brand.setdefault(row.brand_id, []).append(json.loads(row.payload_json))
    assert set(by_brand) == {"Property360", "RED Property", "Venture Studio"}
    assert any(item.get("record_id") == "P360-BRAND-COORDINATION-V1" for item in by_brand["Property360"])
    assert any(item.get("record_id") == "RED-BRAND-TYPESHOUSES-V1" for item in by_brand["RED Property"])
    assert any(item.get("record_id") == "VS-BRAND-SPECIAL-SITUATIONS-V1" for item in by_brand["Venture Studio"])
