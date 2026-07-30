from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
import uuid
from urllib.error import HTTPError

CRM = os.environ.get("CRM_API_BASE_URL", "http://127.0.0.1:8787").rstrip("/")
MIGRATION_TOKEN = os.environ["CRM_MIGRATION_TOKEN"]
READ_TOKEN = os.environ["ITEP_CRM_READ_TOKEN"]
EXPECT_NEW = int(os.environ.get("EXPECT_NEW", "5"))
WORKSPACE = "imperial-test"
BATCH_ID = os.environ.get(
    "MIGRATION_PILOT_BATCH_ID",
    "synthetic-five-document-pilot-v1",
)


def synthetic_pdf(number: int) -> bytes:
    body = (
        "%PDF-1.4\n"
        "1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        f"% Synthetic Imperial migration pilot document {number}; no customer data.\n"
        "%%EOF\n"
    )
    return body.encode("ascii")


documents = [
    {
        # A synthetic rerun represents a new source document set. Include the
        # unique batch ID so the CRM source identity constraint is exercised
        # without colliding with an earlier pilot run.
        "externalId": f"{BATCH_ID}-doc-{number:02d}",
        "title": f"Szintetikus migrációs próbadokumentum {number}",
        "metadata": {
            "synthetic": True,
            "pilot": "five-document",
            "sequence": number,
        },
    }
    for number in range(1, 6)
]
files = [
    (f"synthetic-pilot-{number:02d}.pdf", synthetic_pdf(number))
    for number in range(1, 6)
]
manifest = {
    "idempotencyKey": BATCH_ID,
    "workspaceId": WORKSPACE,
    "sourceSystem": "imperial-migration-engine-test",
    "documents": documents,
}


def multipart_body() -> tuple[str, bytes]:
    boundary = f"imperial-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def field(headers: list[str], payload: bytes) -> None:
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(("\r\n".join(headers) + "\r\n\r\n").encode())
        chunks.append(payload)
        chunks.append(b"\r\n")

    field(
        ['Content-Disposition: form-data; name="manifest"'],
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode(),
    )
    for file_name, payload in files:
        field(
            [
                f'Content-Disposition: form-data; name="documents"; filename="{file_name}"',
                "Content-Type: application/pdf",
            ],
            payload,
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


def request_json(
    path: str,
    *,
    token_header: tuple[str, str],
    method: str = "GET",
    data: bytes | None = None,
    content_type: str | None = None,
) -> tuple[int, dict]:
    headers = {token_header[0]: token_header[1], "Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(
        f"{CRM}{path}",
        headers=headers,
        method=method,
        data=data,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode())
    except HTTPError as error:
        response_body = error.read().decode(errors="replace")
        raise RuntimeError(
            f"{method} {path} returned HTTP {error.code}: {response_body}"
        ) from error


content_type, body = multipart_body()
status, imported = request_json(
    "/api/integrations/migration/import",
    token_header=("X-CRM-Migration-Token", MIGRATION_TOKEN),
    method="POST",
    data=body,
    content_type=content_type,
)
if status not in (200, 201):
    raise RuntimeError(f"Import returned HTTP {status}")
if imported["batch"]["status"] != "completed":
    raise RuntimeError(f"Batch did not complete: {imported}")
if imported["batch"]["storedCount"] != 5:
    raise RuntimeError(f"Expected 5 stored documents: {imported}")
if imported["newlyStored"] != EXPECT_NEW:
    raise RuntimeError(
        f"Expected {EXPECT_NEW} new documents, got {imported['newlyStored']}"
    )

quoted_batch = urllib.parse.quote(BATCH_ID, safe="")
status, batch = request_json(
    f"/api/integrations/migration/batches/{quoted_batch}",
    token_header=("X-CRM-Migration-Token", MIGRATION_TOKEN),
)
if status != 200 or len(batch["documents"]) != 5:
    raise RuntimeError(f"Stored batch cannot be read back: {batch}")

expected_by_external_id = {
    item["externalId"]: payload
    for item, (_, payload) in zip(documents, files, strict=True)
}
for document in batch["documents"]:
    request = urllib.request.Request(
        f"{CRM}{document['downloadUrl']}",
        headers={"X-CRM-Migration-Token": MIGRATION_TOKEN},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != document["sha256"]:
            raise RuntimeError(f"SHA-256 mismatch for document {document['id']}")
        if payload != expected_by_external_id[document["externalId"]]:
            raise RuntimeError(f"Stored bytes differ for document {document['id']}")

query = urllib.parse.urlencode({"workspace": WORKSPACE, "limit": "100"})
status, activities = request_json(
    f"/api/integrations/itep/activities?{query}",
    token_header=("X-ITEP-Token", READ_TOKEN),
)
expected_external_ids = set(expected_by_external_id)
visible_pilot_activities = [
    activity
    for activity in activities["activities"]
    if activity.get("leadId") in expected_external_ids
]
if status != 200 or len(visible_pilot_activities) != 5:
    raise RuntimeError(f"ITEP cannot read the five stored records: {activities}")

print(
    json.dumps(
        {
            "ok": True,
            "synthetic_only": True,
            "batch": BATCH_ID,
            "newly_stored": imported["newlyStored"],
            "durably_read_back": len(batch["documents"]),
            "binary_sha256_verified": len(batch["documents"]),
            "itep_activities_visible": len(visible_pilot_activities),
        },
        ensure_ascii=False,
    )
)
