from app.services.housevision_source_ingest import discover_asset_candidates, _image_identity


def test_discovers_original_gallery_and_classifies_floorplan():
    body = b"""
    <html><head><title>A-frame house</title></head><body>
      <a data-src="content/tipushazak/a-frame/a-frame.jpg"><img
        src="content/tipushazak/a-frame/a-frame.jpg"
        srcset="content_cache/content/tipushazak/a-frame/a-frame-184.jpg 184w"
        alt="A-frame"></a>
      <a data-src="content/tipushazak/a-frame/a-frame-iratozott-alaprajz.jpg"><img
        src="content/tipushazak/a-frame/a-frame-iratozott-alaprajz.jpg" alt="A-frame"></a>
      <img src="content/logo/company-logo.png" alt="logo">
    </body></html>
    """
    rows = discover_asset_candidates(body, "https://imperialholding.hu/termek/a-frame", 12)
    assert len(rows) == 2
    assert {row.asset_type for row in rows} == {"EXTERIOR", "FLOORPLAN"}
    assert all("content_cache" not in row.url for row in rows)
    assert all("logo" not in row.url for row in rows)


def test_png_magic_and_dimensions_are_content_derived():
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1200).to_bytes(4, "big") + (800).to_bytes(4, "big")
    assert _image_identity(payload) == ("image/png", 1200, 800)
