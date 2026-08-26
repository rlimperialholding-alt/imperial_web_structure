from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.growth_ops import processing
from app.growth_ops.canonical_policy import ACTIVE_CONTENT_BRANDS, IORA_EXECUTIVE_EMAIL
from app.growth_ops.models import (
    CanonicalInternalHandoff,
    DailyContentObligation,
    GrowthSignal,
    QuestionRadarAnswer,
    QuestionRadarTopic,
    SourceCoverageAttempt,
    SourceCoverageRoute,
)


def _route() -> SourceCoverageRoute:
    return SourceCoverageRoute(
        route_key="test-route",
        route_id="TEST-ROUTE",
        catalog_sha256="a" * 64,
        motor="construction",
        category="projekt",
        source_name="Teszt forrás",
        search_signal="építési projekt",
        route_url="https://source.test/project",
        source_row_sha256="b" * 64,
        source_record_json="{}",
    )


def _attempt() -> SourceCoverageAttempt:
    return SourceCoverageAttempt(
        attempt_id="SCA-TEST",
        route_key="test-route",
        catalog_sha256="a" * 64,
        status="succeeded",
        response_sha256="c" * 64,
        started_at=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
        completed_at=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
    )


def _settings(**overrides):
    values = {
        "timezone": "Europe/Budapest",
        "canonical_content_factory_enabled": True,
        "canonical_internal_handoff_at": "18:30",
        "canonical_internal_handoff_enabled": True,
        "canonical_internal_handoff_secret_file": "unused-by-test",
        "canonical_publication_digest_enabled": True,
        "canonical_publication_digest_at": "10:00",
        "canonical_publication_digest_recipient": "molnar.andrea@imperialholding.hu",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_hash_bound_quality_gate_blocks_every_public_route_without_image(db, monkeypatch):
    local_day = date(2026, 8, 21)
    monkeypatch.setattr(processing, "_quality_release_secret", lambda: b"q" * 32)
    package = {
        "brand_id": "Bautica",
        "title": "Felújítási útmutató",
        "body": "A jól előkészített felújítás átláthatóbb döntéseket tesz lehetővé. " * 12,
        "facebook_post": "A felújítás jó előkészítéssel átláthatóbb és nyugodtabb folyamat. #felujitas #otthon #szakma",
        "cta": {"label": "Kapcsolat"},
        "source_urls": [],
        "publication_state": "RELEASE_APPROVED",
        "delivery_plan": {
            "cms": {"mode": "LIVE_IMAGE_OPTIONAL", "site_brand_id": "bautica"},
            "facebook": {"mode": "TEXT_ONLY", "page_brand_ids": ["bautica"]},
        },
    }
    reviewed_at = datetime(2026, 8, 21, 7, 50, tzinfo=UTC)
    unsigned = {
        "gate_version": processing.QUALITY_GATE_VERSION,
        "brand_id": "Bautica",
        "artifact_sha256": processing._sha(processing._quality_artifact(package)),
        "generator_request_id": "DS-GENERATOR",
        "generator_model": "routine-model",
        "review_request_id": "DS-REVIEW",
        "review_model": "high-stakes-model",
        "reviewer_identity": "deepseek-high-stakes-independent-release-reviewer",
        "gate_decisions": {gate: "PASS" for gate in processing.MANDATORY_GATES},
        "scores": {
            "natural_hungarian": 90,
            "brand_distinctiveness": 90,
            "conversion_strength": 90,
            "claim_safety": 90,
        },
        "reviewed_at": reviewed_at.isoformat(),
        "valid_until": (reviewed_at + timedelta(hours=30)).isoformat(),
    }
    package["quality_gate_manifest"] = unsigned | {
        "hmac_sha256": processing._sign_quality_manifest(unsigned)
    }
    obligation = DailyContentObligation(
        local_date=local_day,
        brand_id="Bautica",
        status="quarantined",
        content_asset_id="QCA-OWNER-GATE-1",
        evidence_json=json.dumps(package),
    )
    db.add(obligation)
    db.commit()
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    monkeypatch.setattr(processing, "_facebook_token_valid", lambda _brand_id: True)
    captured = []

    def fake_submit(_db, job):
        captured.append(job)
        return SimpleNamespace(job_id=job.job_id, status="QUEUED", idempotent=False)

    monkeypatch.setattr(processing, "submit_job", fake_submit)

    result = processing.enqueue_daily_publications(
        db, now=datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
    )

    assert result["queued"] == 0
    assert result["facebook_queued"] == 0
    assert result["skipped"] == 1
    assert captured == []
    assert obligation.status == "quarantined"
    assert "WAITING_FOR_IMAGE" in obligation.evidence_json


def test_legacy_text_only_payload_conflicts_with_the_new_image_bound_identity():
    job = SimpleNamespace(
        brand_id="bautica",
        content_asset_id="QCA-1",
        content_version_id="VERSION-1",
        content_hash="a" * 64,
        channels=["facebook"],
        visual_asset_package_id="IMGF-APPROVED-1",
    )
    legacy = {
        "brand_id": job.brand_id,
        "content_asset_id": job.content_asset_id,
        "content_version_id": job.content_version_id,
        "content_hash": job.content_hash,
        "channels": job.channels,
        "visual_asset_package_id": None,
    }

    assert processing._same_publication_identity(json.dumps(legacy), job) is False
    legacy["visual_asset_package_id"] = job.visual_asset_package_id
    assert processing._same_publication_identity(json.dumps(legacy), job) is True


@pytest.mark.parametrize(
    ("available_channel", "expected_channel", "expected_cms", "expected_facebook"),
    [
        ("facebook", "facebook", "SKIPPED_ROUTE_NOT_AVAILABLE", "QUEUED"),
        ("nim_cms", "nim_cms", "QUEUED", "SKIPPED_ROUTE_NOT_AVAILABLE"),
    ],
)
def test_unavailable_publication_route_does_not_block_the_available_route(
    db,
    monkeypatch,
    available_channel,
    expected_channel,
    expected_cms,
    expected_facebook,
):
    local_day = date(2026, 8, 21)
    monkeypatch.setattr(processing, "_quality_release_secret", lambda: b"q" * 32)
    package = {
        "brand_id": "Bautica",
        "title": "Felújítási útmutató",
        "body": "A jól előkészített felújítás átláthatóbb döntéseket tesz lehetővé. "
        * 12,
        "facebook_post": (
            "A felújítás jó előkészítéssel átláthatóbb és nyugodtabb. "
            "#felujitas #otthon #szakma"
        ),
        "cta": {"label": "Kapcsolat"},
        "source_urls": [],
        "publication_state": "RELEASE_APPROVED",
        "delivery_plan": {
            "cms": {"mode": "LIVE_IMAGE_REQUIRED", "site_brand_id": "bautica"},
            "facebook": {
                "mode": "LIVE_IMAGE_REQUIRED",
                "page_brand_ids": ["bautica"],
            },
        },
    }
    reviewed_at = datetime(2026, 8, 21, 7, 50, tzinfo=UTC)
    unsigned = {
        "gate_version": processing.QUALITY_GATE_VERSION,
        "brand_id": "Bautica",
        "artifact_sha256": processing._sha(processing._quality_artifact(package)),
        "generator_request_id": "DS-GENERATOR",
        "generator_model": "routine-model",
        "review_request_id": "DS-REVIEW",
        "review_model": "high-stakes-model",
        "reviewer_identity": "deepseek-high-stakes-independent-release-reviewer",
        "gate_decisions": {gate: "PASS" for gate in processing.MANDATORY_GATES},
        "scores": {
            "natural_hungarian": 90,
            "brand_distinctiveness": 90,
            "conversion_strength": 90,
            "claim_safety": 90,
        },
        "reviewed_at": reviewed_at.isoformat(),
        "valid_until": (reviewed_at + timedelta(hours=30)).isoformat(),
    }
    package["quality_gate_manifest"] = unsigned | {
        "hmac_sha256": processing._sign_quality_manifest(unsigned)
    }
    obligation = DailyContentObligation(
        local_date=local_day,
        brand_id="Bautica",
        status="quarantined",
        content_asset_id="QCA-INDEPENDENT-ROUTES-1",
        evidence_json=json.dumps(package),
    )
    db.add(obligation)
    db.commit()

    image_state = {
        "job_id": "image-job-independent-routes",
        "web_hero": {"content_sha256": "1" * 64},
        "facebook": {"content_sha256": "2" * 64},
    }
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    monkeypatch.setattr(
        processing,
        "sync_canonical_image",
        lambda *_args, **_kwargs: ("ready", image_state),
    )
    monkeypatch.setattr(
        processing,
        "_publishing_route_available",
        lambda _brand_id, channel: channel == available_channel,
    )
    monkeypatch.setattr(processing, "_facebook_token_valid", lambda _brand_id: True)
    captured = []

    def fake_submit(_db, job):
        captured.append(job)
        return SimpleNamespace(job_id=job.job_id, status="QUEUED", idempotent=False)

    monkeypatch.setattr(processing, "submit_job", fake_submit)

    result = processing.enqueue_daily_publications(
        db, now=datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
    )

    stored = json.loads(obligation.evidence_json)
    assert result["queued"] == 1
    assert [job.channels for job in captured] == [[expected_channel]]
    assert stored["cms_delivery"] == expected_cms
    assert stored["facebook_delivery"]["bautica"] == expected_facebook


def test_source_extraction_accepts_only_literal_evidence(db, monkeypatch):
    source_permalink = "https://source.test/project/liget-projekt-123"
    text = (
        "A Minta Építő Kft. bejelentette a Liget projekt előkészítését. "
        f"Mikor indulhat el a kivitelezés? {source_permalink}"
    )
    response = {
        "leads": [
            {
                "organization_name": "Minta Építő Kft.",
                "project_title": "Liget projekt",
                "summary": "A Liget projekt előkészítése megjelent a forrásban.",
                "evidence_excerpt": (
                    "A Minta Építő Kft. bejelentette a Liget projekt előkészítését."
                ),
                "confidence": 91,
                "urgency": 65,
            },
            {
                "organization_name": "Kitalált Kft.",
                "summary": "Nincs a forrásban.",
                "evidence_excerpt": "Kitalált bizonyíték.",
                "confidence": 99,
                "urgency": 99,
            },
        ],
        "questions": [
            {
                "question": "Mikor indulhat el a kivitelezés?",
                "question_kind": "literal",
                "evidence_excerpt": "Mikor indulhat el a kivitelezés?",
                "source_permalink": source_permalink,
            },
            {
                "question": "Mennyi lesz az ára?",
                "evidence_excerpt": "Mennyi lesz az ára?",
            },
        ],
    }
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    monkeypatch.setattr(
        processing,
        "complete_json",
        lambda *args, **kwargs: SimpleNamespace(request_id="DS-TEST", content=json.dumps(response)),
    )
    route = _route()
    attempt = _attempt()
    db.add_all([route, attempt])
    db.flush()

    result = processing.process_source_attempt(db, route=route, attempt=attempt, text=text)
    db.commit()

    assert result == {"status": "completed", "leads": 1, "questions": 1}
    signal = db.scalar(select(GrowthSignal))
    assert signal.company_name == "Minta Építő Kft."
    assert signal.subject_type == "organization"
    assert signal.recipient_email is None
    assert signal.status == "blocked"
    assert "internal_review_only" in signal.rejection_reasons_json
    topic = db.scalar(select(QuestionRadarTopic))
    assert topic.question == "Mikor indulhat el a kivitelezés?"
    assert topic.source_url == source_permalink


def test_question_permalink_is_preserved_only_for_exact_forum_candidate(db, monkeypatch):
    text = "Milyen falazatot érdemes választani egy családi házhoz?"
    permalink = "https://forum.source.test/kerdesek/12345-milyen-falazat"
    response = {
        "leads": [],
        "questions": [
            {
                "question": text,
                "question_kind": "literal",
                "evidence_excerpt": text,
                "source_permalink": permalink,
            }
        ],
    }
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    monkeypatch.setattr(
        processing,
        "complete_json",
        lambda *args, **kwargs: SimpleNamespace(request_id="DS-FORUM", content=json.dumps(response)),
    )
    route = _route()
    route.source_type = "fórum"
    route.route_url = "https://forum.source.test/kerdesek"
    attempt = _attempt()
    db.add_all([route, attempt])
    db.flush()

    processing.process_source_attempt(
        db,
        route=route,
        attempt=attempt,
        text=text,
        link_candidates=[{"url": permalink, "label": text}],
    )
    db.commit()

    topic = db.scalar(select(QuestionRadarTopic))
    assert topic.use_case == "exact_source_reply_candidate"
    assert topic.source_url == permalink
    assert processing._reply_eligibility(topic)["eligible"] is True


def test_joszaki_profession_category_is_not_treated_as_a_question_permalink() -> None:
    assert (
        processing._specific_reply_permalink(
            "https://joszaki.hu/szakivalaszol/szakma/konyveles"
        )
        is False
    )
    assert (
        processing._specific_reply_permalink(
            "https://joszaki.hu/szakivalaszol/5mm-es-spc-vinyl-aljzat"
        )
        is True
    )


def test_qjob_card_label_is_evidence_and_creates_one_brand_reply(db, monkeypatch):
    question = "Milyen alapozás kell a tervezett családi házhoz?"
    permalink = "https://qjob.hu/tasks/214543"
    response = {
        "leads": [],
        "questions": [
            {
                "question": question,
                "question_kind": "literal",
                "evidence_excerpt": question,
                "source_permalink": permalink,
            }
        ],
    }
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    monkeypatch.setattr(
        processing,
        "complete_json",
        lambda *args, **kwargs: SimpleNamespace(
            request_id="DS-QJOB", content=json.dumps(response)
        ),
    )
    route = _route()
    route.route_url = "https://qjob.hu/budapest/munka/epitesz-munka"
    route.brand_fit = "Imperial Holding, BauFreund"
    attempt = _attempt()
    db.add_all([route, attempt])
    db.flush()

    result = processing.process_source_attempt(
        db,
        route=route,
        attempt=attempt,
        text="Építési és felújítási feladatok Budapesten.",
        link_candidates=[{"url": permalink, "label": question}],
    )
    db.commit()

    topics = db.scalars(select(QuestionRadarTopic)).all()
    assert result["questions"] == 1
    assert len(topics) == 1
    assert topics[0].brand_id == "BauFreund"
    assert topics[0].source_url == permalink


def test_qjob_lead_requires_and_preserves_exact_task_permalink(db, monkeypatch):
    permalink = "https://qjob.hu/tasks/214543"
    evidence = "Kültéri betonlépcső kivitelezéséhez keresek szakembert."
    response = {
        "leads": [
            {
                "organization_name": None,
                "project_title": "Kültéri betonlépcső kivitelezéséhez",
                "summary": evidence,
                "location": "Budapest",
                "evidence_excerpt": evidence,
                "source_permalink": permalink,
                "confidence": 90,
                "urgency": 70,
            }
        ],
        "questions": [],
    }
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    monkeypatch.setattr(
        processing,
        "complete_json",
        lambda *args, **kwargs: SimpleNamespace(
            request_id="DS-QJOB-LEAD", content=json.dumps(response)
        ),
    )
    route = _route()
    route.route_url = "https://qjob.hu/budapest/munka/epitesz-munka"
    route.brand_fit = "BauFreund"
    attempt = _attempt()
    db.add_all([route, attempt])
    db.flush()

    result = processing.process_source_attempt(
        db,
        route=route,
        attempt=attempt,
        text="Építési feladatok.",
        link_candidates=[{"url": permalink, "label": evidence}],
    )
    db.commit()

    signal = db.scalar(select(GrowthSignal))
    assert result["leads"] == 1
    assert signal.evidence_url == permalink


def test_question_answer_generator_quarantines_exact_artifact(db, monkeypatch):
    topic = QuestionRadarTopic(
        topic_id="QRT-ELIGIBLE",
        local_date=date(2026, 8, 21),
        question="Milyen falazatot érdemes választani egy családi házhoz?",
        brand_id="Bautica",
        use_case="exact_source_reply_candidate",
        source_url="https://forum.source.test/kerdesek/12345-milyen-falazat",
        classification="observed_literal",
        dedupe_hash="d" * 64,
    )
    db.add(topic)
    db.commit()
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    disclosure = "A Bautica csapatának nevében válaszolok."
    answer = disclosure + " " + (
        "A falazatot a statikai terv, a hőtechnikai cél, a kivitelezési rendszer és a teljes rétegrend alapján érdemes kiválasztani. "
        "Előbb rögzítsék a követelményeket, majd azonos feltételekkel hasonlítsák össze a szóba jövő szerkezeteket. "
    ) * 3
    monkeypatch.setattr(
        processing,
        "complete_json",
        lambda *args, **kwargs: SimpleNamespace(
            request_id="DS-ANSWER", content=json.dumps({"answer": answer})
        ),
    )

    result = processing.generate_question_radar_answers(
        db, now=datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
    )

    row = db.scalar(select(QuestionRadarAnswer))
    assert result["quarantined"] == 1
    assert row.status == "quarantined"
    assert row.answer_sha256 == processing.hashlib.sha256(answer.strip().encode()).hexdigest()
    assert "independent_review_quorum_missing" in row.review_manifest_json


def test_construction_marketplace_rejects_accounting_question() -> None:
    topic = QuestionRadarTopic(
        topic_id="QRT-OFFTOPIC",
        local_date=date(2026, 8, 21),
        question="Hogyan váltsak könyvelőt és milyen díjakkal számoljak?",
        brand_id="BauFreund",
        use_case="exact_source_reply_candidate",
        source_url="https://joszaki.hu/szakivalaszol/konyvelovaltas",
        classification="observed_literal",
        dedupe_hash="1" * 64,
    )

    eligibility = processing._reply_eligibility(topic)

    assert eligibility["eligible"] is False
    assert "brand_topic_mismatch" in eligibility["reasons"]


def test_construction_marketplace_accepts_specific_building_question() -> None:
    topic = QuestionRadarTopic(
        topic_id="QRT-ONTOPIC",
        local_date=date(2026, 8, 21),
        question="Milyen vastag hőszigetelés kell egy lapostetőre?",
        brand_id="BauFreund",
        use_case="exact_source_reply_candidate",
        source_url="https://joszaki.hu/szakivalaszol/laposteto-hoszigeteles",
        classification="observed_literal",
        dedupe_hash="2" * 64,
    )

    assert processing._reply_eligibility(topic)["eligible"] is True


def test_ineligible_question_is_committed_and_not_reprocessed(db, monkeypatch):
    db.add(
        QuestionRadarTopic(
            topic_id="QRT-INELIGIBLE",
            local_date=date(2026, 8, 21),
            question="Szeretné visszaszerezni a domainnevét?",
            brand_id="Imperial",
            use_case="source_observed_question",
            source_url="https://source.test/",
            classification="observed_literal",
            dedupe_hash="e" * 64,
        )
    )
    db.commit()
    monkeypatch.setattr(processing, "settings", lambda: _settings())

    first = processing.generate_question_radar_answers(
        db, now=datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
    )
    second = processing.generate_question_radar_answers(
        db, now=datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
    )

    assert first["ineligible"] == 1
    assert second["processed"] == 0
    assert db.scalar(select(QuestionRadarAnswer)).status == "ineligible"


def test_question_answer_generator_skips_topic_reserved_by_another_worker(db, monkeypatch):
    db.add(
        QuestionRadarTopic(
            topic_id="QRT-CONCURRENT",
            local_date=date(2026, 8, 21),
            question="Milyen alapozást válasszak a családi házhoz?",
            brand_id="Bautica",
            use_case="exact_source_reply_candidate",
            source_url="https://forum.source.test/kerdesek/999-alapozas",
            classification="observed_literal",
            dedupe_hash="f" * 64,
        )
    )
    db.commit()
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    model_called = False

    def duplicate_reservation(*args, **kwargs):
        raise processing.IntegrityError("insert", {}, Exception("duplicate topic"))

    def fail_if_called(*args, **kwargs):
        nonlocal model_called
        model_called = True
        raise AssertionError("a topic reserved elsewhere must not reach the model")

    monkeypatch.setattr(db, "flush", duplicate_reservation)
    monkeypatch.setattr(processing, "complete_json", fail_if_called)

    result = processing.generate_question_radar_answers(
        db, now=datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
    )

    assert result["reserved_elsewhere"] == 1
    assert model_called is False


def test_publication_digest_includes_hash_bound_blocked_forum_draft(db, monkeypatch):
    topic = QuestionRadarTopic(
        topic_id="QRT-DIGEST",
        local_date=date(2026, 8, 21),
        question="Milyen hőszigetelés kerüljön a lapostetőre?",
        brand_id="BauFreund",
        use_case="exact_source_reply_candidate",
        source_url="https://joszaki.hu/szakivalaszol/laposteto-hoszigeteles",
        classification="observed_literal",
        dedupe_hash="3" * 64,
    )
    answer = QuestionRadarAnswer(
        answer_id="QRA-DIGEST",
        topic_id=topic.topic_id,
        local_date=date(2026, 8, 21),
        brand_id="BauFreund",
        source_url=topic.source_url,
        source_host="joszaki.hu",
        disclosure_text="A BauFreund csapatának nevében válaszolok.",
        answer_text="Ez egy belső ellenőrzésre váró szakmai választervezet.",
        answer_sha256="4" * 64,
        status="quarantined",
        eligibility_json="{}",
        review_manifest_json="{}",
    )
    db.add_all([topic, answer])
    db.commit()
    captured = {}

    class FakeMailer:
        def __init__(self, _binding):
            pass

        def send(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(provider_message_id="MSG-DIGEST")

    monkeypatch.setattr(processing, "settings", lambda: _settings())
    monkeypatch.setattr(processing, "_smtp_binding", lambda: SimpleNamespace())
    monkeypatch.setattr(processing, "SMTPEmailAdapter", FakeMailer)

    result = processing.send_publication_digest(
        db, now=datetime(2026, 8, 21, 10, 5, tzinfo=UTC)
    )

    assert result["status"] == "sent"
    assert "BLOKKOLT TERVEZET" in captured["body_text"]
    assert topic.question in captured["body_text"]
    assert answer.answer_sha256 in captured["body_text"]
    assert answer.answer_text in captured["body_text"]
    assert captured["delivery_scope"] == "internal"


def test_publication_digest_contains_every_quarantined_forum_draft(db, monkeypatch):
    for index in range(27):
        topic = QuestionRadarTopic(
            topic_id=f"QRT-DIGEST-{index}",
            local_date=date(2026, 8, 21),
            question=f"Szakmai kérdés {index}",
            brand_id="BauFreund",
            use_case="exact_source_reply_candidate",
            source_url=f"https://joszaki.hu/szakivalaszol/kerdes-{index}",
            classification="observed_literal",
            dedupe_hash=f"{index:064x}",
        )
        db.add(topic)
        db.add(
            QuestionRadarAnswer(
                answer_id=f"QRA-DIGEST-{index}",
                topic_id=topic.topic_id,
                local_date=date(2026, 8, 21),
                brand_id="BauFreund",
                source_url=topic.source_url,
                source_host="joszaki.hu",
                disclosure_text="A BauFreund csapatának nevében válaszolok.",
                answer_text=f"Teljes szakmai választervezet {index}",
                answer_sha256=f"{index + 100:064x}",
                status="quarantined",
                eligibility_json="{}",
                review_manifest_json="{}",
            )
        )
    db.commit()
    captured = {}

    class FakeMailer:
        def __init__(self, _binding):
            pass

        def send(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(provider_message_id="MSG-DIGEST-ALL")

    monkeypatch.setattr(processing, "settings", lambda: _settings())
    monkeypatch.setattr(processing, "_smtp_binding", lambda: SimpleNamespace())
    monkeypatch.setattr(processing, "SMTPEmailAdapter", FakeMailer)

    result = processing.send_publication_digest(
        db, now=datetime(2026, 8, 21, 10, 5, tzinfo=UTC)
    )

    assert result["status"] == "sent"
    assert captured["body_text"].count("BLOKKOLT TERVEZET") == 27
    assert "Teljes szakmai választervezet 26" in captured["body_text"]


def test_source_hard_gate_blocks_before_model(db, monkeypatch):
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("model must not be called")

    monkeypatch.setattr(processing, "settings", lambda: _settings())
    monkeypatch.setattr(processing, "complete_json", fail_if_called)
    route = _route()
    attempt = _attempt()
    result = processing.process_source_attempt(
        db, route=route, attempt=attempt, text="Homes4you projektinformáció"
    )

    assert result["status"] == "skipped"
    assert called is False
    assert "no_monitoring_hard_gate" in attempt.analysis_json


def test_anonymous_project_is_retained_but_inferred_question_is_rejected(db, monkeypatch):
    text = "Új projekt: 140 m2 családi ház generálkivitelezése Győrben."
    response = {
        "leads": [
            {
                "organization_name": None,
                "project_title": "140 m2 családi ház generálkivitelezése",
                "summary": "Projektjelzés.",
                "location": "Győr",
                "evidence_excerpt": text,
                "confidence": 82,
                "urgency": 60,
            }
        ],
        "questions": [
            {
                "question": "Milyen kivitelezési kapacitás szükséges a 140 m2-es házhoz?",
                "question_kind": "inferred_from_evidence",
                "evidence_excerpt": text,
            }
        ],
    }
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    captured = {}

    def fake_complete(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(request_id="DS-PROJECT", content=json.dumps(response))

    monkeypatch.setattr(processing, "complete_json", fake_complete)
    route = _route()
    route.route_key = "project-route"
    route.route_id = "PROJECT-ROUTE"
    attempt = _attempt()
    attempt.attempt_id = "SCA-PROJECT"
    attempt.route_key = route.route_key
    db.add_all([route, attempt])
    db.flush()

    result = processing.process_source_attempt(db, route=route, attempt=attempt, text=text)
    db.commit()

    signal = db.scalar(select(GrowthSignal))
    topic = db.scalar(select(QuestionRadarTopic))
    assert result == {"status": "completed", "leads": 1, "questions": 0}
    assert signal.subject_type == "project"
    assert signal.company_name is None
    assert signal.status == "blocked"
    assert topic is None
    assert "question_kind=inferred_from_evidence" in captured["system_prompt"]
    assert "kikövetkeztetett kérdést ne adj vissza" not in captured["system_prompt"]


def test_content_factory_quarantines_all_nineteen_brands(db, monkeypatch):
    local_day = date(2026, 8, 21)
    for brand in ACTIVE_CONTENT_BRANDS:
        db.add(DailyContentObligation(local_date=local_day, brand_id=brand))
    db.commit()
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    monkeypatch.setattr(processing, "_quality_release_secret", lambda: b"q" * 32)
    calls = []

    def fake_complete(*args, **kwargs):
        request = json.loads(kwargs["user_prompt"])
        if kwargs["purpose"].startswith("canonical_daily_content_release_review:"):
            return SimpleNamespace(
                request_id="DS-REVIEW",
                model="review-model",
                content=json.dumps(
                    {
                        "artifact_sha256": request["artifact_sha256"],
                        "overall_decision": "PASS",
                        "gate_results": {
                            gate: {"decision": "PASS", "reason": "ok"}
                            for gate in request["required_gate_ids"]
                        },
                        "scores": {
                            "natural_hungarian": 90,
                            "brand_distinctiveness": 90,
                            "conversion_strength": 90,
                            "claim_safety": 90,
                        },
                        "findings": [],
                    }
                ),
            )
        brand_id = request["brand_id"]
        calls.append(brand_id)
        focus = processing.content_focus_for_brand(brand_id)[0]
        return SimpleNamespace(
            request_id=f"DS-CONTENT-{brand_id}",
            model="generator-model",
            content=json.dumps(
                {
                    "package": {
                        "brand_id": brand_id,
                        "title": f"{brand_id}: napi szakmai téma",
                        "format": "professional_article",
                        "body": (f"{brand_id} {focus} témájú belső szakmai vázlata. " * 30),
                        "facebook_post": (
                            f"{brand_id} {focus} témájú Facebook-terve, ellenőrzött "
                            "állításokkal és egyértelmű következő lépéssel. " * 3
                        ) + "#epites #otthon #szakma",
                        "cta": {"label": "Kapcsolat", "intent": "lead"},
                        "source_urls": [],
                    }
                }
            ),
        )

    monkeypatch.setattr(processing, "complete_json", fake_complete)

    result = processing.generate_daily_content(db, now=datetime(2026, 8, 21, 8, 0, tzinfo=UTC))

    rows = db.scalars(select(DailyContentObligation)).all()
    assert result["status"] == "complete"
    assert result["generated"] == result["required"] == result["completed"] == 19
    assert result["failed_brands"] == result["unresolved_brands"] == []
    assert calls == list(ACTIVE_CONTENT_BRANDS)
    assert len(rows) == 19
    assert all(row.status == "release_passed" for row in rows)
    assert all("RELEASE_APPROVED" in row.evidence_json for row in rows)
    assert all("quality_gate_manifest" in row.evidence_json for row in rows)
    assert all(row.release_token_hash is None for row in rows)
    plans = [json.loads(row.evidence_json)["delivery_plan"] for row in rows]
    assert sum(plan["facebook"]["mode"] == "LIVE_IMAGE_REQUIRED" for plan in plans) == 12
    assert sum(plan["cms"]["mode"] == "LIVE_IMAGE_REQUIRED" for plan in plans) == 6


def test_internal_handoff_is_fixed_recipient_and_idempotent(db, monkeypatch):
    db.add(
        GrowthSignal(
            signal_id="SIG-HANDOFF",
            run_id="RUN-HANDOFF",
            motor_key="construction",
            source_id="catalog:SRC-HANDOFF",
            source_bucket="marketplace",
            external_key="lead-handoff",
            signal_type="project_opportunity",
            detected_at=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
            company_name="Minta Építő Kft.",
            subject_type="organization",
            recipient_email_type="none",
            contact_basis="internal_review_only",
            location="Budapest",
            summary="Konkrét kivitelezési projekt szakmai segítséget keres.",
            evidence_url="https://source.test/lead-handoff",
            brand_id="Bautica",
            score=82,
            urgency=70,
            confidence=90,
            dedupe_hash="9" * 64,
            source_payload_hash="8" * 64,
            status="blocked",
            created_at=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
        )
    )
    db.commit()
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    monkeypatch.setattr(processing, "_smtp_binding", lambda: SimpleNamespace())
    sent = []

    class FakeAdapter:
        def __init__(self, _binding):
            pass

        def send(self, **kwargs):
            sent.append(kwargs)
            return SimpleNamespace(provider_message_id="message-1")

    monkeypatch.setattr(processing, "SMTPEmailAdapter", FakeAdapter)
    now = datetime(2026, 8, 21, 18, 0, tzinfo=UTC)  # 20:00 Budapest

    first = processing.send_internal_handoff(db, now=now)
    second = processing.send_internal_handoff(db, now=now)

    row = db.scalar(select(CanonicalInternalHandoff))
    assert first["status"] == second["status"] == "sent"
    assert second["idempotent"] is True
    assert len(sent) == 1
    assert sent[0]["to_email"] == IORA_EXECUTIVE_EMAIL
    assert sent[0]["delivery_scope"] == "internal"
    assert row.recipient_email == IORA_EXECUTIVE_EMAIL
    assert "IORA" in row.body_text
    assert "nem indult közvetlen megkeresés" in row.body_text
    assert "Minta Építő Kft." in row.body_text
    assert "https://source.test/lead-handoff" in row.body_text
    assert "Konkrét kivitelezési projekt" in row.body_text


def test_source_extraction_retries_one_transient_model_failure(db, monkeypatch):
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    calls = 0

    def flaky_complete(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise processing.GrowthRegistryError("transient invalid model JSON")
        return SimpleNamespace(request_id="DS-RETRY", content='{"leads":[],"questions":[]}')

    monkeypatch.setattr(processing, "complete_json", flaky_complete)
    route = _route()
    attempt = _attempt()

    result = processing.process_source_attempt(
        db, route=route, attempt=attempt, text="Érvényes forrásszöveg egy projektről."
    )

    assert calls == 2
    assert result == {"status": "completed", "leads": 0, "questions": 0}
