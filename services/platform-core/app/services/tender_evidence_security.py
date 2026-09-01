from __future__ import annotations

import io
import os
import socket
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path


class TenderScannerUnavailable(RuntimeError):
    """The configured malware scanner cannot provide a trustworthy decision."""


class TenderMalwareDetected(ValueError):
    """The uploaded payload was positively identified as malicious."""


class TenderEvidenceUnavailable(RuntimeError):
    """Stored evidence is not clean and integrity-verified for download."""


@dataclass(frozen=True)
class TenderScanResult:
    status: str
    engine: str
    engine_version: str
    signature: str | None = None


_EICAR_MARKER = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
_MAX_RESPONSE_BYTES = 16 * 1024
_MAX_OFFICE_ENTRIES = 2_000
_MAX_OFFICE_EXPANDED_BYTES = 100 * 1024 * 1024
_MIME_SUFFIXES = {
    "application/pdf": {".pdf"},
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {".xlsx"},
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {".docx"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
}


def validate_tender_evidence_content(file_name: str, mime_type: str, raw: bytes) -> None:
    suffix = Path(file_name).suffix.lower()
    if suffix not in _MIME_SUFFIXES.get(mime_type, set()):
        raise ValueError("A fájlkiterjesztés és a megadott dokumentumtípus nem egyezik.")
    if mime_type == "application/pdf":
        if not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-2048:]:
            raise ValueError("A PDF szerkezete hiányos vagy érvénytelen.")
        return
    if mime_type == "image/jpeg":
        if not raw.startswith(b"\xff\xd8\xff") or not raw.endswith(b"\xff\xd9"):
            raise ValueError("A JPEG szerkezete hiányos vagy érvénytelen.")
        return
    if mime_type == "image/png":
        if not raw.startswith(b"\x89PNG\r\n\x1a\n") or b"IEND" not in raw[-32:]:
            raise ValueError("A PNG szerkezete hiányos vagy érvénytelen.")
        return
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > _MAX_OFFICE_ENTRIES:
                raise ValueError("Az Office dokumentum túl sok bejegyzést tartalmaz.")
            if any(entry.flag_bits & 0x1 for entry in entries):
                raise ValueError("Titkosított Office melléklet nem fogadható el.")
            expanded = sum(entry.file_size for entry in entries)
            if expanded > _MAX_OFFICE_EXPANDED_BYTES:
                raise ValueError("Az Office dokumentum kibontott mérete túl nagy.")
            names = {entry.filename for entry in entries}
    except zipfile.BadZipFile as exc:
        raise ValueError("Az Office dokumentum ZIP-szerkezete érvénytelen.") from exc
    required = (
        {"[Content_Types].xml", "xl/workbook.xml"}
        if mime_type.endswith("spreadsheetml.sheet")
        else {"[Content_Types].xml", "word/document.xml"}
    )
    if not required.issubset(names):
        raise ValueError("Az Office dokumentum belső típusa nem egyezik a megadott formátummal.")


def _recv_response(sock: socket.socket) -> str:
    chunks: list[bytes] = []
    total = 0
    while total < _MAX_RESPONSE_BYTES:
        chunk = sock.recv(min(4096, _MAX_RESPONSE_BYTES - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if b"\0" in chunk or b"\n" in chunk:
            break
    if total >= _MAX_RESPONSE_BYTES:
        raise TenderScannerUnavailable("A kártevőscanner túlméretes választ adott.")
    return b"".join(chunks).rstrip(b"\0\r\n").decode("utf-8", errors="replace")


def _clamav_version(host: str, port: int, timeout: float) -> str:
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(b"zVERSION\0")
        response = _recv_response(sock).strip()
    if not response:
        raise TenderScannerUnavailable("A ClamAV nem adott verzióválaszt.")
    return response[:255]


def _clamav_scan(raw: bytes, host: str, port: int, timeout: float) -> TenderScanResult:
    version = _clamav_version(host, port, timeout)
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(b"zINSTREAM\0")
        for offset in range(0, len(raw), 64 * 1024):
            chunk = raw[offset : offset + 64 * 1024]
            sock.sendall(struct.pack("!I", len(chunk)))
            sock.sendall(chunk)
        sock.sendall(struct.pack("!I", 0))
        response = _recv_response(sock).strip()
    if response.endswith(" OK"):
        return TenderScanResult("clean", "clamav", version)
    if response.endswith(" FOUND"):
        signature = response.rsplit(":", 1)[-1].removesuffix(" FOUND").strip()
        raise TenderMalwareDetected(
            "A mellékletet a kártevőscanner elutasította"
            + (f": {signature[:160]}" if signature else ".")
        )
    raise TenderScannerUnavailable("A ClamAV nem adott értelmezhető vizsgálati eredményt.")


def _scanner_setting(prefix: str, suffix: str, fallback_prefix: str | None = None) -> str:
    value = os.getenv(f"{prefix}_{suffix}")
    if value is None and fallback_prefix:
        value = os.getenv(f"{fallback_prefix}_{suffix}")
    return (value or "").strip()


def _scan_evidence(
    raw: bytes,
    *,
    prefix: str,
    label: str,
    fallback_prefix: str | None = None,
) -> TenderScanResult:
    mode = _scanner_setting(prefix, "AV_MODE", fallback_prefix).lower() or "disabled"
    environment = os.getenv("ENVIRONMENT", "development").strip().lower()
    if mode == "test":
        if environment != "test":
            raise TenderScannerUnavailable(
                "A teszt-scanner csak ENVIRONMENT=test mellett használható."
            )
        if _EICAR_MARKER in raw:
            raise TenderMalwareDetected(
                "A mellékletet a teszt-scanner EICAR mintaként elutasította."
            )
        return TenderScanResult("clean", "deterministic-test-scanner", "1")
    if mode != "clamav":
        raise TenderScannerUnavailable(f"A {label} AV-vizsgálat nincs engedélyezve.")
    host = _scanner_setting(prefix, "CLAMAV_HOST", fallback_prefix)
    if not host:
        raise TenderScannerUnavailable(f"A {prefix}_CLAMAV_HOST nincs konfigurálva.")
    try:
        port = int(_scanner_setting(prefix, "CLAMAV_PORT", fallback_prefix) or "3310")
        timeout = float(
            _scanner_setting(prefix, "CLAMAV_TIMEOUT_SECONDS", fallback_prefix) or "10"
        )
    except ValueError as exc:
        raise TenderScannerUnavailable(
            "Érvénytelen ClamAV port vagy timeout konfiguráció."
        ) from exc
    if not 1 <= port <= 65535 or not 1 <= timeout <= 60:
        raise TenderScannerUnavailable(
            "A ClamAV port vagy timeout kívül esik a megengedett tartományon."
        )
    try:
        return _clamav_scan(raw, host, port, timeout)
    except TenderMalwareDetected:
        raise
    except (OSError, TenderScannerUnavailable) as exc:
        raise TenderScannerUnavailable(
            f"A {label} kártevőscanner nem érhető el megbízhatóan."
        ) from exc


def scan_tender_evidence(raw: bytes) -> TenderScanResult:
    """Return a clean Tender verdict or fail closed."""

    return _scan_evidence(raw, prefix="TENDER", label="Tender")


def scan_care_evidence(raw: bytes) -> TenderScanResult:
    """Return a clean Care verdict, reusing shared Tender AV settings by default."""

    return _scan_evidence(
        raw,
        prefix="CARE",
        label="Care",
        fallback_prefix="TENDER",
    )


def tender_av_configuration() -> dict[str, object]:
    mode = os.getenv("TENDER_AV_MODE", "disabled").strip().lower()
    environment = os.getenv("ENVIRONMENT", "development").strip().lower()
    host_configured = bool(os.getenv("TENDER_CLAMAV_HOST", "").strip())
    if mode == "clamav" and host_configured:
        status = "configured"
    elif mode == "test" and environment == "test":
        status = "synthetic_test_only"
    else:
        status = "disabled"
    return {
        "mode": mode,
        "status": status,
        "production_configured": status == "configured",
    }
