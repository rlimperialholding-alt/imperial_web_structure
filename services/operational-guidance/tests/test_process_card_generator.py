from pathlib import Path

from app.process_cards.domain import ProcessSource, RealRole, assign_real_role
from app.process_cards.service import ProcessCardGenerator


def payload():
    return {
        "process_key": "PC-SAL-001",
        "title": "Ügyfélajánlat elkészítése",
        "trigger": "Amikor minősített leadből ajánlatkérés érkezik",
        "inputs": ["Ügyféligény", "Telekadat", "Árkalkuláció"],
        "steps": ["Validálja az ügyfél adatait", "Készítse el az ajánlatot", "Eszkalálja a túl nagy kedvezményt"],
        "outputs": ["Kiküldött ajánlat"],
        "stop_conditions": ["Hiányos árkalkuláció"],
        "completion_conditions": ["Az ajánlat kiküldése rögzítve van"],
        "source_role": "Értékesítő",
        "policy_refs": ["Értékesítési szabályzat"],
    }


def test_role_assignment():
    assert assign_real_role(ProcessSource(**payload())) == RealRole.ERTEKESITO


def test_full_lifecycle(tmp_path: Path):
    generator = ProcessCardGenerator(tmp_path / "runtime", tmp_path / "published")
    generator.ingest(payload())
    generated = generator.generate("PC-SAL-001")
    assert generated["changed"] is True
    assert Path(generated["artifacts"]["pdf"]).exists()
    assert Path(generated["artifacts"]["png"]).exists()
    unchanged = generator.generate("PC-SAL-001")
    assert unchanged["changed"] is False
    approved = generator.approve("PC-SAL-001", 1, "Ügyvezető")
    assert approved["card"]["status"] == "approved"
    changed_payload = payload()
    changed_payload["steps"].append("Rögzítse a következő utánkövetési dátumot")
    generator.ingest(changed_payload)
    v2 = generator.generate("PC-SAL-001")
    assert v2["card"]["version"] == 2

class FakePublisher:
    def publish_version(self, role, process_key, version, files):
        assert role == "Értékesítő"
        assert process_key == "PC-SAL-001"
        assert version == 1
        assert {p.suffix for p in files} == {".pdf", ".png"}
        return {"pdf": "https://drive.test/card.pdf", "png": "https://drive.test/card.png"}


class FakeNotifier:
    def notify(self, **kwargs):
        assert kwargs["process_key"] == "PC-SAL-001"
        return "mail-123"


def test_publisher_and_notifier_adapters(tmp_path: Path):
    generator = ProcessCardGenerator(tmp_path / "runtime", publisher=FakePublisher(), notifier=FakeNotifier())
    generator.ingest(payload())
    generated = generator.generate("PC-SAL-001")
    assert generated["notification_id"] == "mail-123"
    approved = generator.approve("PC-SAL-001", 1, "Ügyvezető")
    assert approved["published"]["pdf"].endswith("card.pdf")


def test_superseded_process_card_cannot_be_approved(tmp_path: Path):
    import pytest

    generator = ProcessCardGenerator(tmp_path / "runtime", tmp_path / "published")
    generator.ingest(payload())
    generator.generate("PC-SAL-001")
    changed_payload = payload()
    changed_payload["steps"].append("Rögzítsd a következő lépést")
    generator.ingest(changed_payload)
    generator.generate("PC-SAL-001")

    with pytest.raises(ValueError, match="legfrissebb"):
        generator.approve("PC-SAL-001", 1, "Ügyvezető")


def test_concurrent_generation_is_idempotent(tmp_path: Path):
    from concurrent.futures import ThreadPoolExecutor

    generator = ProcessCardGenerator(tmp_path / "runtime", tmp_path / "published")
    generator.ingest(payload())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: generator.generate("PC-SAL-001"), range(2)))

    assert sorted(result["changed"] for result in results) == [False, True]
    assert generator.store.latest_card("PC-SAL-001").version == 1


class FakeReviewPublisher:
    def __init__(self):
        self.draft_calls = []
        self.approved_calls = []
        self.archived = []

    def publish_draft(self, role, process_key, version, files):
        self.draft_calls.append((role, process_key, version, files))
        return {path.name: f"https://drive.test/review/{path.name}" for path in files}

    def publish_version(self, role, process_key, version, files):
        self.approved_calls.append((role, process_key, version, files))
        return {path.name: f"https://drive.test/approved/{path.name}" for path in files}

    def archive_draft(self, role, process_key, version):
        self.archived.append((role, process_key, version))


class CapturingNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, **kwargs):
        self.calls.append(kwargs)
        return "mail-review-1"


class FailingNotifier:
    def notify(self, **kwargs):
        raise RuntimeError("temporary mail failure")


def test_draft_is_published_for_review_and_archived_after_approval(tmp_path: Path):
    publisher = FakeReviewPublisher()
    notifier = CapturingNotifier()
    generator = ProcessCardGenerator(
        tmp_path / "runtime",
        tmp_path / "published",
        publisher=publisher,
        notifier=notifier,
    )
    generator.ingest(payload())
    generated = generator.generate("PC-SAL-001")

    assert publisher.draft_calls
    assert any(key.startswith("review_") for key in generated["artifacts"])
    assert notifier.calls
    assert all(key.startswith("review_") for key in notifier.calls[0]["artifact_links"])

    approved = generator.approve("PC-SAL-001", 1, "Ügyvezető")
    assert approved["card"]["status"] == "approved"
    assert publisher.approved_calls
    assert publisher.archived == [("Értékesítő", "PC-SAL-001", 1)]


def test_failed_approval_notification_remains_retryable(tmp_path: Path):
    generator = ProcessCardGenerator(
        tmp_path / "runtime",
        notifier=FailingNotifier(),
    )
    generator.ingest(payload())
    generated = generator.generate("PC-SAL-001")
    assert generated["notification_id"].startswith("notification-failed")
    assert len(generator.store.pending_approval_records()) == 1

    replacement = CapturingNotifier()
    generator.notifier = replacement
    retried = generator.resend_pending_approvals()
    assert retried[0]["notification_id"] == "mail-review-1"
    assert generator.store.pending_approval_records() == []
