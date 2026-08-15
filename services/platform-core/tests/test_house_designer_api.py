import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.models import (
    HouseDesignSession,
    HouseDesignSubmission,
    HouseStudioPermissionGrant,
    User,
)
from app.services.house_designer import ActorScope, create_session
from app.services.house_designer_submission import HOUSE_DESIGN_NOTICE_VERSION


def _login_and_csrf(client, email: str = "platform-admin@imperial.local") -> str:
    login = client.post(
        "/login",
        data={"email": email, "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    page = client.get("/house-designer")
    assert page.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match
    return match.group(1)


def test_submission_queue_html_and_api_execute_scoped_review_action(client, db):
    customer = ActorScope("customer-route-review", "imperial-holding", frozenset({"imperial"}))
    design = create_session(
        db,
        actor=customer,
        brand_id="imperial",
        title="Böngészős submission review",
        command_id=str(uuid4()),
    )
    session = db.scalar(
        select(HouseDesignSession).where(HouseDesignSession.session_id == design["sessionId"])
    )
    assert session is not None
    session.project_id = "PROJECT-HD-ROUTE-REVIEW"
    session.status = "SUBMITTED"
    submission = HouseDesignSubmission(
        submission_id="HDSUB-ROUTE-REVIEW",
        tenant_id="imperial-holding",
        brand_id="imperial",
        session_id=session.session_id,
        snapshot_id="HDA-ROUTE-REVIEW",
        snapshot_sha256="8" * 64,
        submission_type="ORDER_REQUEST",
        status="RECEIVED",
        customer_subject_id=customer.subject_id,
        project_id=session.project_id,
        idempotency_key=str(uuid4()),
        attribution_json="{}",
        notice_version_id=HOUSE_DESIGN_NOTICE_VERSION,
        notice_accepted_at=datetime.now(UTC),
        created_by=customer.subject_id,
    )
    db.add(submission)
    db.commit()

    csrf = _login_and_csrf(client, "owner@imperial.local")
    queue = client.get("/house-designer/submissions")
    assert queue.status_code == 200
    assert submission.submission_id in queue.text
    detail = client.get(f"/house-designer/submissions/{submission.submission_id}/review")
    assert detail.status_code == 200
    assert 'value="start_sales_review"' in detail.text
    assert detail.text.count("<main") == 1
    api_queue = client.get("/api/v1/house-designer/submissions")
    assert api_queue.status_code == 200
    assert [row["submissionId"] for row in api_queue.json()["items"]] == [submission.submission_id]

    transitioned = client.post(
        f"/house-designer/submissions/{submission.submission_id}/review",
        headers={"Origin": "http://testserver"},
        data={
            "csrf_token": csrf,
            "command_id": str(uuid4()),
            "row_version": "1",
            "action": "start_sales_review",
            "note": "Az értékesítési teljességi ellenőrzés elindult.",
        },
        follow_redirects=False,
    )
    assert transitioned.status_code == 303
    db.expire_all()
    stored = db.scalar(
        select(HouseDesignSubmission).where(
            HouseDesignSubmission.submission_id == submission.submission_id
        )
    )
    assert stored is not None and stored.status == "SALES_REVIEW"


def test_house_designer_json_api_enforces_preconditions_and_replays(client):
    csrf = _login_and_csrf(client)
    base_headers = {
        "Origin": "http://testserver",
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
    }
    denied = client.post(
        "/api/v1/house-designer/sessions",
        headers={"Content-Type": "application/json", "Origin": "http://testserver"},
        json={"title": "Denied"},
    )
    assert denied.status_code == 403
    missing_key = client.post(
        "/api/v1/house-designer/sessions",
        headers=base_headers,
        json={"title": "Missing key"},
    )
    assert missing_key.status_code == 428

    key = str(uuid4())
    payload = {"title": "API test house", "origin": "blank", "widthMm": 10_000, "depthMm": 8_000}
    created = client.post(
        "/api/v1/house-designer/sessions",
        headers={**base_headers, "Idempotency-Key": key},
        json=payload,
    )
    assert created.status_code == 200
    replay = client.post(
        "/api/v1/house-designer/sessions",
        headers={**base_headers, "Idempotency-Key": key},
        json=payload,
    )
    assert replay.status_code == 200
    design = created.json()
    assert replay.json()["sessionId"] == design["sessionId"]

    command_url = f"/api/v1/house-designer/sessions/{design['sessionId']}/commands"
    command_payload = {
        "baseRevisionId": design["revision"]["revisionId"],
        "commandType": "add_room",
        "payload": {
            "levelId": "L01",
            "roomId": "R01",
            "name": "Nappali",
            "function": "living",
            "xMm": 0,
            "yMm": 0,
            "widthMm": 4_000,
            "depthMm": 3_500,
        },
    }
    no_match = client.post(
        command_url,
        headers={**base_headers, "Idempotency-Key": str(uuid4())},
        json=command_payload,
    )
    assert no_match.status_code == 428
    changed = client.post(
        command_url,
        headers={
            **base_headers,
            "Idempotency-Key": str(uuid4()),
            "If-Match": design["revision"]["canonicalSha256"],
        },
        json=command_payload,
    )
    assert changed.status_code == 200
    assert len(changed.json()["revision"]["geometry"]["levels"][0]["rooms"]) == 1
    editor = client.get(f"/house-designer/sessions/{design['sessionId']}")
    assert editor.status_code == 200
    assert 'value="move_room"' in editor.text
    assert 'value="resize_room"' in editor.text
    assert 'value="remove_room"' in editor.text
    assert 'value="add_wall"' in editor.text
    assert 'value="clone_level"' in editor.text
    assert 'value="add_furniture"' in editor.text
    assert editor.text.count("<main") == 1
    assert 'class="skip-link" href="#main-content"' in editor.text
    assert 'id="main-content" tabindex="-1"' in editor.text
    assert 'aria-label="Fő navigáció"' in editor.text
    assert 'aria-current="page"' in editor.text
    assert 'aria-controls="sidebar" aria-expanded="false"' in editor.text
    assert 'role="search"' in editor.text
    assert 'for="global-search-input">Központi keresés</label>' in editor.text
    assert 'aria-label="Terv állapota"' in editor.text
    assert 'aria-label="Telek, megfelelőség és tervfolyamat"' in editor.text
    assert 'class="hd-touch-link" href="/house-designer/regulatory-admin"' in editor.text
    assert editor.text.count("data-hd-autosave") == 2
    assert '<script src="/static/house-designer-editor.js"></script>' in editor.text
    assert re.search(r'data-offline-scope="[0-9a-f]{64}"', editor.text)

    browser_runtime = client.get("/static/house-designer-editor.js")
    assert browser_runtime.status_code == 200
    assert "AES-GCM" in browser_runtime.text
    assert "indexedDB" in browser_runtime.text
    assert "localStorage" not in browser_runtime.text
    assert "sessionStorage" not in browser_runtime.text

    shared_css = client.get("/static/style.css")
    assert shared_css.status_code == 200
    assert ":focus-visible" in shared_css.text
    assert ".skip-link:focus" in shared_css.text
    assert (
        ".menu-toggle,.side-nav a,.logout-button,.global-search input"
        "{min-width:44px;min-height:44px}"
    ) in shared_css.text
    assert ".top-action{padding-block:16px}" in shared_css.text
    assert (
        ".hd-touch-link{display:inline-flex;align-items:center;min-height:44px}"
        in shared_css.text
    )

    changed_design = changed.json()
    restore_key = str(uuid4())
    restore_payload = {
        "baseRevisionId": changed_design["revision"]["revisionId"],
        "commandType": "restore_revision",
        "payload": {"targetRevisionId": design["revision"]["revisionId"]},
    }
    restored = client.post(
        command_url,
        headers={
            **base_headers,
            "Idempotency-Key": restore_key,
            "If-Match": changed_design["revision"]["canonicalSha256"],
        },
        json=restore_payload,
    )
    assert restored.status_code == 200
    restored_design = restored.json()
    assert restored_design["revision"]["revisionNo"] == 3
    assert restored_design["revision"]["geometry"]["levels"][0]["rooms"] == []
    assert restored_design["history"][0]["commandType"] == "restore_revision"
    restore_replay = client.post(
        command_url,
        headers={
            **base_headers,
            "Idempotency-Key": restore_key,
            "If-Match": changed_design["revision"]["canonicalSha256"],
        },
        json=restore_payload,
    )
    assert restore_replay.status_code == 200
    assert (
        restore_replay.json()["revision"]["revisionId"] == restored_design["revision"]["revisionId"]
    )


def test_clone_level_html_command_creates_audited_revision(client):
    csrf = _login_and_csrf(client)
    created = client.post(
        "/house-designer/sessions",
        headers={"Origin": "http://testserver"},
        data={
            "csrf_token": csrf,
            "command_id": str(uuid4()),
            "title": "Klónozható ház",
            "origin": "blank",
            "width_mm": "10000",
            "depth_mm": "8000",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    detail_url = created.headers["location"]
    page = client.get(detail_url)
    revision_id = re.search(r'name="base_revision_id" value="([^"]+)"', page.text)
    canonical_hash = re.search(r'name="base_canonical_sha256" value="([^"]+)"', page.text)
    assert revision_id and canonical_hash
    polygon = client.post(
        f"{detail_url}/commands",
        headers={"Origin": "http://testserver"},
        data={
            "csrf_token": csrf,
            "command_id": str(uuid4()),
            "command_type": "set_footprint_polygon",
            "base_revision_id": revision_id.group(1),
            "base_canonical_sha256": canonical_hash.group(1),
            "levelId": "L01",
            "points": "0,0;10000,0;10000,3000;6000,3000;6000,8000;0,8000",
        },
        follow_redirects=False,
    )
    assert polygon.status_code == 303
    assert "error=" not in polygon.headers["location"]
    page = client.get(detail_url)
    assert "10000,3000 6000,3000 6000,8000" in page.text
    revision_id = re.search(r'name="base_revision_id" value="([^"]+)"', page.text)
    canonical_hash = re.search(r'name="base_canonical_sha256" value="([^"]+)"', page.text)
    assert revision_id and canonical_hash

    cloned = client.post(
        f"{detail_url}/commands",
        headers={"Origin": "http://testserver"},
        data={
            "csrf_token": csrf,
            "command_id": str(uuid4()),
            "command_type": "clone_level",
            "base_revision_id": revision_id.group(1),
            "base_canonical_sha256": canonical_hash.group(1),
            "sourceLevelId": "L01",
            "levelType": "full_storey",
        },
        follow_redirects=False,
    )
    assert cloned.status_code == 303
    assert "error=" not in cloned.headers["location"]
    changed = client.get(detail_url)
    assert "L02" in changed.text
    assert "Egy szint másolata új szintként került a tervbe." in changed.text
    changed_revision_id = re.search(
        r'name="base_revision_id" value="([^"]+)"', changed.text
    )
    changed_canonical_hash = re.search(
        r'name="base_canonical_sha256" value="([^"]+)"', changed.text
    )
    assert changed_revision_id and changed_canonical_hash
    furnished = client.post(
        f"{detail_url}/commands",
        headers={"Origin": "http://testserver"},
        data={
            "csrf_token": csrf,
            "command_id": str(uuid4()),
            "command_type": "add_furniture",
            "base_revision_id": changed_revision_id.group(1),
            "base_canonical_sha256": changed_canonical_hash.group(1),
            "levelId": "L02",
            "furnitureKind": "sofa",
            "label": "Próbakanapé",
            "xMm": "1000",
            "yMm": "1000",
            "widthMm": "2000",
            "depthMm": "900",
            "rotationDeg": "0",
        },
        follow_redirects=False,
    )
    assert furnished.status_code == 303
    assert "error=" not in furnished.headers["location"]
    furnished_page = client.get(detail_url)
    assert "Próbakanapé" in furnished_page.text
    assert 'class="hd-furniture"' in furnished_page.text
    assert 'value="undo_revision"' in furnished_page.text
    furnished_revision_id = re.search(
        r'name="base_revision_id" value="([^"]+)"', furnished_page.text
    )
    furnished_canonical_hash = re.search(
        r'name="base_canonical_sha256" value="([^"]+)"', furnished_page.text
    )
    assert furnished_revision_id and furnished_canonical_hash
    roof = client.post(
        f"{detail_url}/commands",
        headers={"Origin": "http://testserver"},
        data={
            "csrf_token": csrf,
            "command_id": str(uuid4()),
            "command_type": "set_roof",
            "base_revision_id": furnished_revision_id.group(1),
            "base_canonical_sha256": furnished_canonical_hash.group(1),
            "levelId": "L02",
            "roofType": "gable",
            "pitchDeg": "30",
        },
        follow_redirects=False,
    )
    assert roof.status_code == 303 and "error=" not in roof.headers["location"]
    roof_page = client.get(detail_url)
    assert 'value="set_roof_footprint"' in roof_page.text
    roof_revision_id = re.search(
        r'name="base_revision_id" value="([^"]+)"', roof_page.text
    )
    roof_canonical_hash = re.search(
        r'name="base_canonical_sha256" value="([^"]+)"', roof_page.text
    )
    assert roof_revision_id and roof_canonical_hash
    roof_footprint = client.post(
        f"{detail_url}/commands",
        headers={"Origin": "http://testserver"},
        data={
            "csrf_token": csrf,
            "command_id": str(uuid4()),
            "command_type": "set_roof_footprint",
            "base_revision_id": roof_revision_id.group(1),
            "base_canonical_sha256": roof_canonical_hash.group(1),
            "levelId": "L02",
            "points": "0,0;10000,0;10000,3000;6000,3000;6000,8000;0,8000",
        },
        follow_redirects=False,
    )
    assert roof_footprint.status_code == 303
    assert "error=" not in roof_footprint.headers["location"]


def test_json_api_undo_redo_is_linear_idempotent_and_fail_closed(client):
    csrf = _login_and_csrf(client)
    headers = {
        "Origin": "http://testserver",
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
    }
    created = client.post(
        "/api/v1/house-designer/sessions",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"title": "Undo redo ház", "origin": "blank"},
    ).json()
    command_url = f"/api/v1/house-designer/sessions/{created['sessionId']}/commands"
    unavailable_undo = client.post(
        command_url,
        headers={
            **headers,
            "Idempotency-Key": str(uuid4()),
            "If-Match": created["revision"]["canonicalSha256"],
        },
        json={
            "baseRevisionId": created["revision"]["revisionId"],
            "commandType": "undo_revision",
            "payload": {},
        },
    )
    assert unavailable_undo.status_code == 409
    assert unavailable_undo.json()["detail"]["code"] == "undo_revision_unavailable"
    added = client.post(
        command_url,
        headers={
            **headers,
            "Idempotency-Key": str(uuid4()),
            "If-Match": created["revision"]["canonicalSha256"],
        },
        json={
            "baseRevisionId": created["revision"]["revisionId"],
            "commandType": "add_room",
            "payload": {
                "levelId": "L01",
                "roomId": "R01",
                "xMm": 0,
                "yMm": 0,
                "widthMm": 4_000,
                "depthMm": 3_000,
            },
        },
    ).json()
    undo_key = str(uuid4())
    undo_request = {
        "baseRevisionId": added["revision"]["revisionId"],
        "commandType": "undo_revision",
        "payload": {},
    }
    undone_response = client.post(
        command_url,
        headers={
            **headers,
            "Idempotency-Key": undo_key,
            "If-Match": added["revision"]["canonicalSha256"],
        },
        json=undo_request,
    )
    assert undone_response.status_code == 200
    undone = undone_response.json()
    assert undone["revision"]["geometry"]["levels"][0]["rooms"] == []
    assert undone["revision"]["commandType"] == "undo_revision"
    undo_replay = client.post(
        command_url,
        headers={
            **headers,
            "Idempotency-Key": undo_key,
            "If-Match": added["revision"]["canonicalSha256"],
        },
        json=undo_request,
    )
    assert undo_replay.status_code == 200
    assert undo_replay.json()["revision"]["revisionId"] == undone["revision"]["revisionId"]

    redone_response = client.post(
        command_url,
        headers={
            **headers,
            "Idempotency-Key": str(uuid4()),
            "If-Match": undone["revision"]["canonicalSha256"],
        },
        json={
            "baseRevisionId": undone["revision"]["revisionId"],
            "commandType": "redo_revision",
            "payload": {},
        },
    )
    assert redone_response.status_code == 200
    redone = redone_response.json()
    assert len(redone["revision"]["geometry"]["levels"][0]["rooms"]) == 1
    assert redone["revision"]["commandType"] == "redo_revision"

    unavailable = client.post(
        command_url,
        headers={
            **headers,
            "Idempotency-Key": str(uuid4()),
            "If-Match": redone["revision"]["canonicalSha256"],
        },
        json={
            "baseRevisionId": redone["revision"]["revisionId"],
            "commandType": "redo_revision",
            "payload": {},
        },
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "redo_revision_unavailable"


def test_geometry_api_rejects_crossing_wall_and_outside_opening_atomically(client):
    csrf = _login_and_csrf(client)
    base_headers = {
        "Origin": "http://testserver",
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
    }
    created = client.post(
        "/api/v1/house-designer/sessions",
        headers={**base_headers, "Idempotency-Key": str(uuid4())},
        json={"title": "Geometry negative API", "origin": "blank"},
    )
    assert created.status_code == 200
    design = created.json()
    command_url = f"/api/v1/house-designer/sessions/{design['sessionId']}/commands"

    wall = client.post(
        command_url,
        headers={
            **base_headers,
            "Idempotency-Key": str(uuid4()),
            "If-Match": design["revision"]["canonicalSha256"],
        },
        json={
            "baseRevisionId": design["revision"]["revisionId"],
            "commandType": "add_wall",
            "payload": {
                "levelId": "L01",
                "x1Mm": 0,
                "y1Mm": 4_000,
                "x2Mm": 10_000,
                "y2Mm": 4_000,
            },
        },
    )
    assert wall.status_code == 200
    wall_design = wall.json()
    wall_id = wall_design["revision"]["geometry"]["levels"][0]["wallSegments"][0]["id"]
    revision_hash = wall_design["revision"]["canonicalSha256"]
    revision_id = wall_design["revision"]["revisionId"]

    crossing = client.post(
        command_url,
        headers={
            **base_headers,
            "Idempotency-Key": str(uuid4()),
            "If-Match": revision_hash,
        },
        json={
            "baseRevisionId": revision_id,
            "commandType": "add_wall",
            "payload": {
                "levelId": "L01",
                "x1Mm": 5_000,
                "y1Mm": 0,
                "x2Mm": 5_000,
                "y2Mm": 8_000,
            },
        },
    )
    assert crossing.status_code == 422
    assert crossing.json()["detail"]["code"] == "wall_self_intersection"

    outside = client.post(
        command_url,
        headers={
            **base_headers,
            "Idempotency-Key": str(uuid4()),
            "If-Match": revision_hash,
        },
        json={
            "baseRevisionId": revision_id,
            "commandType": "add_opening",
            "payload": {
                "levelId": "L01",
                "wallId": wall_id,
                "offsetMm": 9_500,
                "widthMm": 900,
            },
        },
    )
    assert outside.status_code == 422
    assert outside.json()["detail"]["code"] == "opening_outside_wall"

    current = client.get(f"/api/v1/house-designer/sessions/{design['sessionId']}")
    assert current.status_code == 200
    assert current.json()["revision"]["revisionId"] == revision_id
    editor = client.get(f"/house-designer/sessions/{design['sessionId']}")
    assert 'value="add_opening"' in editor.text
    assert 'value="move_wall"' in editor.text
    assert 'value="split_wall"' in editor.text
    assert 'value="remove_wall"' in editor.text


def test_render_api_idempotency_key_is_collision_safe(client):
    csrf = _login_and_csrf(client)
    headers = {
        "Origin": "http://testserver",
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
        "Idempotency-Key": str(uuid4()),
    }
    created = client.post(
        "/api/v1/house-designer/sessions", headers=headers, json={"title": "Render API"}
    ).json()
    render_headers = {**headers, "Idempotency-Key": str(uuid4())}
    url = f"/api/v1/house-designer/sessions/{created['sessionId']}/renders"
    first = client.post(url, headers=render_headers, json={"prompt": "Fehér vakolat"})
    replay = client.post(url, headers=render_headers, json={"prompt": "Fehér vakolat"})
    collision = client.post(url, headers=render_headers, json={"prompt": "Fekete vakolat"})
    assert first.status_code == 200
    assert replay.json()["renderId"] == first.json()["renderId"]
    assert collision.status_code == 409


def test_render_revision_api_tracks_parent_and_rejects_stale_parent(client):
    csrf = _login_and_csrf(client)
    headers = {
        "Origin": "http://testserver",
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
        "Idempotency-Key": str(uuid4()),
    }
    design = client.post(
        "/api/v1/house-designer/sessions", headers=headers, json={"title": "Render revisions"}
    ).json()
    render_url = f"/api/v1/house-designer/sessions/{design['sessionId']}/renders"
    first = client.post(
        render_url,
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"prompt": "Fehér homlokzat"},
    ).json()
    revision_url = f"/api/v1/house-designer/renders/{first['renderId']}/revisions"
    second = client.post(
        revision_url,
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"prompt": "Fehér homlokzat, fa lamellákkal"},
    )
    stale = client.post(
        revision_url,
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"prompt": "Korábbi verzióból indított kérés"},
    )
    assert second.status_code == 200
    assert second.json()["parentRenderId"] == first["renderId"]
    assert second.json()["revisionNo"] == 2
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_render_revision"


def test_staff_read_requires_project_grant_and_deny_wins(client, db):
    project_id = "PROJECT-HD-SCOPE-UAT"
    foreign = create_session(
        db,
        actor=ActorScope("foreign-customer", "imperial-holding", frozenset({"imperial"})),
        brand_id="imperial",
        title="Foreign scoped design",
        command_id="foreign-scoped-create",
    )
    row = db.scalar(
        select(HouseDesignSession).where(HouseDesignSession.session_id == foreign["sessionId"])
    )
    row.project_id = project_id
    db.commit()

    _login_and_csrf(client)
    url = f"/api/v1/house-designer/sessions/{foreign['sessionId']}"
    assert client.get(url).status_code == 404
    assert "Foreign scoped design" not in client.get("/house-designer").text

    user = db.scalar(select(User).where(User.email == "platform-admin@imperial.local"))
    assert user is not None
    assert user.itep_subject_id
    now = datetime.now(UTC)
    db.add(
        HouseStudioPermissionGrant(
            grant_id="HSG-HD-PROJECT-ALLOW",
            subject_id=user.itep_subject_id,
            permission="ii.house-designer.read",
            effect="allow",
            scope_type="project",
            project_id=project_id,
            revision="hd-scope-test-v1",
            claim_sequence=1,
            claim_issuer="test",
            claim_sha256="a" * 64,
            status="active",
            valid_from=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=1),
        )
    )
    db.commit()
    assert client.get(url).status_code == 200
    assert "Foreign scoped design" in client.get("/house-designer").text

    db.add(
        HouseStudioPermissionGrant(
            grant_id="HSG-HD-PROJECT-DENY",
            subject_id=user.itep_subject_id,
            permission="ii.house-designer.read",
            effect="deny",
            scope_type="project",
            project_id=project_id,
            revision="hd-scope-test-v2",
            claim_sequence=2,
            claim_issuer="test",
            claim_sha256="b" * 64,
            status="active",
            valid_from=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=1),
        )
    )
    db.commit()
    assert client.get(url).status_code == 404
    assert "Foreign scoped design" not in client.get("/house-designer").text
