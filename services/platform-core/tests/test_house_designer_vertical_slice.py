from uuid import uuid4

from app.services.house_designer import ActorScope, apply_session_command, create_session
from app.services.house_designer_estimation import create_sandbox_estimate
from app.services.house_designer_rendering import create_sandbox_render, sandbox_render_svg


def test_house_designer_sandbox_estimate_and_render_are_revision_bound(db):
    actor = ActorScope(
        subject_id="customer-test",
        tenant_id="imperial-holding",
        brand_ids=frozenset({"imperial"}),
    )
    design = create_session(
        db,
        actor=actor,
        brand_id="imperial",
        title="Vertical slice",
        command_id=str(uuid4()),
    )
    revision = design["revision"]
    design = apply_session_command(
        db,
        session_id=design["sessionId"],
        actor=actor,
        base_revision_id=revision["revisionId"],
        base_canonical_sha256=revision["canonicalSha256"],
        command_id=str(uuid4()),
        command_type="set_configuration",
        payload={
            "constructionTechnology": "masonry",
            "completionLevel": "turnkey",
            "technicalPackage": "comfort",
        },
    )
    estimate = create_sandbox_estimate(db, session_id=design["sessionId"], actor=actor)
    replay = create_sandbox_estimate(db, session_id=design["sessionId"], actor=actor)
    render = create_sandbox_render(
        db,
        session_id=design["sessionId"],
        actor=actor,
        prompt="Világos vakolat és természetes fa burkolat.",
    )
    svg = sandbox_render_svg(db, render_id=render["renderId"], actor=actor)

    assert estimate["estimateId"] == replay["estimateId"]
    assert estimate["grossMinHuf"] < estimate["grossMaxHuf"]
    assert estimate["nonProduction"] is True
    assert render["nonProduction"] is True
    assert "NEM ÉPÍTÉSZETI DOKUMENTUM" in svg


def test_partial_site_draft_is_preserved_without_claiming_verification(db):
    actor = ActorScope(
        subject_id="customer-site-draft",
        tenant_id="imperial-holding",
        brand_ids=frozenset({"imperial"}),
    )
    design = create_session(
        db,
        actor=actor,
        brand_id="imperial",
        title="Partial site draft",
        command_id=str(uuid4()),
    )
    revision = design["revision"]
    changed = apply_session_command(
        db,
        session_id=design["sessionId"],
        actor=actor,
        base_revision_id=revision["revisionId"],
        base_canonical_sha256=revision["canonicalSha256"],
        command_id=str(uuid4()),
        command_type="set_site",
        payload={
            "postalCode": "1111",
            "city": "Mintaváros",
            "address": "Minta utca 12.",
        },
    )

    assert changed["revision"]["site"] == {
        "country": "HU",
        "municipalityCode": "",
        "postalCode": "1111",
        "city": "Mintaváros",
        "address": "Minta utca 12.",
        "parcelNumber": "",
        "verificationStatus": "missing",
        "sourceRefs": [],
    }
