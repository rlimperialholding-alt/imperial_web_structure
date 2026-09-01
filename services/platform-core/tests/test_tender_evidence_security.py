from __future__ import annotations

import io
import zipfile

import pytest

from app.services import tender_evidence_security as security


def _office_file(*names: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, "<xml />")
    return buffer.getvalue()


def test_office_content_type_is_structurally_verified():
    docx = _office_file("[Content_Types].xml", "word/document.xml")
    security.validate_tender_evidence_content(
        "offer.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        docx,
    )
    with pytest.raises(ValueError, match="belső típusa"):
        security.validate_tender_evidence_content(
            "renamed.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            docx,
        )
    with pytest.raises(ValueError, match="kiterjesztés"):
        security.validate_tender_evidence_content(
            "renamed.pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            docx,
        )


class _FakeSocket:
    def __init__(self, response: bytes):
        self.response = response
        self.sent = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def settimeout(self, timeout: float) -> None:
        assert timeout == 3

    def sendall(self, content: bytes) -> None:
        self.sent.extend(content)

    def recv(self, size: int) -> bytes:
        del size
        response, self.response = self.response, b""
        return response


def test_clamav_instream_clean_and_malware_verdicts(monkeypatch):
    clean_socket = _FakeSocket(b"stream: OK\0")
    monkeypatch.setattr(security, "_clamav_version", lambda *args: "ClamAV 1.4-test")
    monkeypatch.setattr(
        security.socket,
        "create_connection",
        lambda *args, **kwargs: clean_socket,
    )
    result = security._clamav_scan(b"safe", "clamav", 3310, 3)
    assert result.status == "clean" and result.engine_version == "ClamAV 1.4-test"
    assert clean_socket.sent.startswith(b"zINSTREAM\0")
    assert clean_socket.sent.endswith(b"\0\0\0\0")

    infected_socket = _FakeSocket(b"stream: Eicar-Test-Signature FOUND\0")
    monkeypatch.setattr(
        security.socket,
        "create_connection",
        lambda *args, **kwargs: infected_socket,
    )
    with pytest.raises(security.TenderMalwareDetected, match="Eicar-Test-Signature"):
        security._clamav_scan(b"infected", "clamav", 3310, 3)


def test_synthetic_scanner_is_impossible_outside_test_environment(monkeypatch):
    monkeypatch.setenv("TENDER_AV_MODE", "test")
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(security.TenderScannerUnavailable, match="ENVIRONMENT=test"):
        security.scan_tender_evidence(b"safe")
