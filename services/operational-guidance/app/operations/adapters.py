from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class OperationalRecordSink(Protocol):
    def upsert_process_card(self, payload: dict[str, Any], artifacts: dict[str, str]) -> None: ...

    def upsert_checklist_template(self, payload: dict[str, Any]) -> None: ...

    def upsert_checklist_instance(self, payload: dict[str, Any]) -> None: ...


class NullOperationalRecordSink:
    def upsert_process_card(self, payload: dict[str, Any], artifacts: dict[str, str]) -> None:
        return None

    def upsert_checklist_template(self, payload: dict[str, Any]) -> None:
        return None

    def upsert_checklist_instance(self, payload: dict[str, Any]) -> None:
        return None


@dataclass(slots=True)
class DirectusOperationalRecordSink:
    base_url: str
    token: str
    process_card_collection: str = "process_card_versions"
    checklist_template_collection: str = "checklist_templates"
    checklist_instance_collection: str = "checklist_instances"

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _upsert(
        self,
        collection: str,
        filters: dict[str, str | int],
        payload: dict[str, Any],
    ) -> None:
        url = f"{self.base_url.rstrip('/')}/items/{collection}"
        params: dict[str, Any] = {"limit": 1}
        for field, value in filters.items():
            params[f"filter[{field}][_eq]"] = value
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            rows = response.json().get("data", [])
            if rows:
                saved = client.patch(
                    f"{url}/{rows[0]['id']}", headers=self.headers, json=payload
                )
            else:
                saved = client.post(url, headers=self.headers, json=payload)
            saved.raise_for_status()

    def upsert_process_card(
        self, payload: dict[str, Any], artifacts: dict[str, str]
    ) -> None:
        record_key = f"{payload['process_key']}:v{int(payload['version']):03d}"
        record = {
            "record_key": record_key,
            "status": payload.get("status", "draft"),
            "process_key": payload["process_key"],
            "version": payload["version"],
            "role": payload["role"],
            "checklist_template_id": payload.get("checklist_template_id"),
            "source_checksum": payload["source_checksum"],
            "payload": payload,
            "artifacts": artifacts,
            "approved_by": payload.get("approved_by"),
            "approved_at": payload.get("approved_at"),
        }
        self._upsert(
            self.process_card_collection,
            {"record_key": record_key},
            record,
        )

    def upsert_checklist_template(self, payload: dict[str, Any]) -> None:
        version_key = f"{payload['template_id']}:v{payload['version']}"
        record = dict(payload)
        record["version_key"] = version_key
        self._upsert(
            self.checklist_template_collection,
            {"version_key": version_key},
            record,
        )

    def upsert_checklist_instance(self, payload: dict[str, Any]) -> None:
        record = {
            "status": payload["status"],
            "instance_id": payload["instance_id"],
            "template_id": payload["template_id"],
            "template_version": payload["template_version"],
            "process_key": payload["process_key"],
            "gate_id": payload["gate_id"],
            "role": payload["role"],
            "object_id": payload["object_id"],
            "object_type": payload["object_type"],
            "created_by": payload["created_by"],
            "items": payload.get("items", []),
            "evidence_ids": payload.get("evidence_ids", []),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
            "submitted_at": payload.get("submitted_at"),
            "approved_by": payload.get("approved_by"),
            "approved_at": payload.get("approved_at"),
            "closed_at": payload.get("closed_at"),
            "metadata": payload.get("metadata", {}),
        }
        self._upsert(
            self.checklist_instance_collection,
            {"instance_id": payload["instance_id"]},
            record,
        )
