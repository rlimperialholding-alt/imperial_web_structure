from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.checklists.service import ChecklistEngine
from app.operations.adapters import NullOperationalRecordSink, OperationalRecordSink
from app.process_cards.adapters import ApprovalNotifier, ArtifactPublisher, NullNotifier
from app.process_cards.domain import ProcessSource, build_human_card, composite_checksum
from app.process_cards.render import render_pdf, render_png
from app.process_cards.store import JsonProcessCardStore


class ProcessCardGenerator:
    """Unified generator for human process cards and their executable checklists."""

    def __init__(
        self,
        runtime_root: Path,
        publish_root: Path | None = None,
        publisher: ArtifactPublisher | None = None,
        notifier: ApprovalNotifier | None = None,
        checklist_engine: ChecklistEngine | None = None,
        record_sink: OperationalRecordSink | None = None,
    ):
        self.runtime_root = runtime_root
        self.store = JsonProcessCardStore(runtime_root)
        self.artifacts = runtime_root / "artifacts"
        self.publish_root = publish_root
        self.publisher = publisher
        self.notifier = notifier or NullNotifier()
        self.checklist_engine = checklist_engine
        self.record_sink = record_sink or NullOperationalRecordSink()
        self.artifacts.mkdir(parents=True, exist_ok=True)

    def ingest(self, payload: dict[str, Any]) -> ProcessSource:
        source = ProcessSource(**payload)
        self.store.save_source(source)
        return source

    def import_catalog(
        self,
        catalog: dict[str, Any] | Path,
        *,
        persist: bool = True,
    ) -> dict[str, int]:
        if isinstance(catalog, Path):
            payload = json.loads(catalog.read_text(encoding="utf-8"))
        else:
            payload = catalog
        imported = 0
        unchanged = 0
        for process_payload in payload.get("processes") or []:
            source = ProcessSource(**process_payload)
            try:
                existing = self.store.load_source(source.process_key)
            except FileNotFoundError:
                existing = None
            if existing and existing.checksum() == source.checksum():
                unchanged += 1
                continue
            self.store.save_source(source)
            imported += 1
        checklist_result = {"imported": 0, "unchanged": 0, "total": 0}
        if self.checklist_engine:
            checklist_result = self.checklist_engine.import_catalog(
                payload, persist=persist
            )
        self.store.audit(
            "operational_catalog_imported",
            {
                "processes": {"imported": imported, "unchanged": unchanged},
                "checklists": checklist_result,
                "catalog_version": payload.get("catalog_version"),
            },
        )
        return {
            "processes_imported": imported,
            "processes_unchanged": unchanged,
            "checklists_imported": checklist_result["imported"],
            "checklists_unchanged": checklist_result["unchanged"],
            "total_processes": imported + unchanged,
            "total_checklists": checklist_result["total"],
        }

    def generate(self, process_key: str, force: bool = False) -> dict[str, Any]:
        with self.store.process_lock(process_key):
            return self._generate_unlocked(process_key, force=force)

    def _generate_unlocked(
        self, process_key: str, force: bool = False
    ) -> dict[str, Any]:
        source = self.store.load_source(process_key)
        checklist = (
            self.checklist_engine.template_for_process(process_key)
            if self.checklist_engine
            else None
        )
        if source.checklist_required and checklist is None:
            raise FileNotFoundError(
                f"Required checklist template missing for {process_key}"
            )
        latest = self.store.latest_card(process_key)
        expected_checksum = composite_checksum(source, checklist)
        changed = latest is None or latest.source_checksum != expected_checksum
        if latest and not changed and not force:
            return {
                "changed": False,
                "card": latest.to_dict(),
                "artifacts": {},
                "checklist_template": checklist.to_dict() if checklist else None,
            }

        version = 1 if latest is None else latest.version + 1
        card = build_human_card(source, version=version, checklist=checklist)
        out_dir = self.artifacts / process_key / f"v{version:03d}"
        pdf = render_pdf(card, out_dir / f"{process_key}_v{version:03d}.pdf")
        png = render_png(pdf, out_dir / f"{process_key}_v{version:03d}.png")
        artifacts: dict[str, str] = {
            "pdf": str(pdf),
            "png": str(png),
            "process_card_pdf": str(pdf),
            "process_card_png": str(png),
        }

        checklist_artifacts: dict[str, str] = {}
        if checklist and self.checklist_engine:
            checklist_artifacts = self.checklist_engine.render_template(checklist, out_dir)
            artifacts.update(checklist_artifacts)
            checklist_json = out_dir / "checklist_template.json"
            checklist_json.write_text(
                json.dumps(checklist.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            artifacts["checklist_json"] = str(checklist_json)

        process_card_json = out_dir / "process_card.json"
        process_card_json.write_text(
            json.dumps(card.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        artifacts["process_card_json"] = str(process_card_json)

        review_links: dict[str, str] = {}
        publish_draft = getattr(self.publisher, "publish_draft", None)
        if callable(publish_draft):
            review_files = sorted(
                {
                    Path(value)
                    for key, value in artifacts.items()
                    if key.endswith(("_pdf", "_png"))
                }
            )
            uploaded = publish_draft(
                card.role.value, process_key, version, review_files
            )
            review_links = {f"review_{name}": url for name, url in uploaded.items()}
            artifacts.update(review_links)

        bundle_path = out_dir / "bundle.json"
        artifacts["bundle_json"] = str(bundle_path)
        bundle = {
            "process_key": process_key,
            "bundle_version": version,
            "source_checksum": expected_checksum,
            "card": card.to_dict(),
            "checklist_template": checklist.to_dict() if checklist else None,
            "artifacts": artifacts,
        }
        bundle_path.write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        self.record_sink.upsert_process_card(card.to_dict(), artifacts)
        queue_file = self.store.queue_for_approval(card, artifacts)
        if checklist and self.checklist_engine:
            self.checklist_engine.store.queue_template_for_approval(
                checklist, checklist_artifacts
            )
        self.store.save_card(card)
        notification_id = self._send_approval_notification(
            process_key=card.process_key,
            title=card.title,
            version=card.version,
            role=card.role.value,
            artifacts=artifacts,
            checklist_template_id=card.checklist_template_id,
        )
        return {
            "changed": True,
            "card": card.to_dict(),
            "checklist_template": checklist.to_dict() if checklist else None,
            "artifacts": artifacts,
            "approval_record": str(queue_file),
            "notification_id": notification_id,
        }

    def _send_approval_notification(
        self,
        *,
        process_key: str,
        title: str,
        version: int,
        role: str,
        artifacts: dict[str, str],
        checklist_template_id: str | None,
    ) -> str:
        review_links = {
            key: value for key, value in artifacts.items() if key.startswith("review_")
        }
        notification_links = review_links or artifacts
        try:
            notification_id = self.notifier.notify(
                process_key=process_key,
                title=title,
                version=version,
                role=role,
                artifact_links=notification_links,
                checklist_template_id=checklist_template_id,
            )
            if notification_id == "notifier-disabled":
                self.store.mark_approval_notification(
                    process_key, version, status="disabled"
                )
                self.store.audit(
                    "approval_notification_disabled",
                    {"process_key": process_key, "version": version},
                )
                return notification_id
            self.store.mark_approval_notification(
                process_key,
                version,
                status="sent",
                notification_id=notification_id,
            )
            self.store.audit(
                "approval_notification_sent",
                {
                    "process_key": process_key,
                    "version": version,
                    "notification_id": notification_id,
                    "checklist_template_id": checklist_template_id,
                },
            )
            return notification_id
        except Exception as exc:  # retry is handled from the approval queue
            error = f"{type(exc).__name__}: {exc}"
            self.store.mark_approval_notification(
                process_key, version, status="failed", error=error
            )
            self.store.audit(
                "approval_notification_failed",
                {
                    "process_key": process_key,
                    "version": version,
                    "error": error,
                },
            )
            return f"notification-failed:{type(exc).__name__}"

    def resend_pending_approvals(self) -> list[dict[str, Any]]:
        if isinstance(self.notifier, NullNotifier):
            return []
        results: list[dict[str, Any]] = []
        for record in self.store.pending_approval_records():
            notification_id = self._send_approval_notification(
                process_key=str(record["process_key"]),
                title=str(record["title"]),
                version=int(record["version"]),
                role=str(record["role"]),
                artifacts=dict(record.get("artifacts") or {}),
                checklist_template_id=record.get("checklist_template_id"),
            )
            results.append(
                {
                    "process_key": record["process_key"],
                    "version": record["version"],
                    "notification_id": notification_id,
                }
            )
        return results

    def approve(
        self, process_key: str, version: int, approved_by: str
    ) -> dict[str, Any]:
        with self.store.process_lock(process_key):
            return self._approve_unlocked(process_key, version, approved_by)

    def _approve_unlocked(
        self, process_key: str, version: int, approved_by: str
    ) -> dict[str, Any]:
        latest = self.store.latest_card(process_key)
        if latest is None:
            raise FileNotFoundError(process_key)
        if latest.version != version:
            raise ValueError(
                f"Csak a legfrissebb Process Card-verzió hagyható jóvá: v{latest.version}."
            )
        if latest.status == "approved":
            return {
                "card": latest.to_dict(),
                "published": {},
                "already_approved": True,
            }

        approved_at = datetime.now(UTC).isoformat()
        latest.status = "approved"
        latest.approved_by = approved_by
        latest.approved_at = approved_at
        source_dir = self.artifacts / process_key / f"v{version:03d}"
        files = [path for path in source_dir.iterdir() if path.is_file()]
        publish_files = [
            file for file in files if file.suffix.lower() in {".pdf", ".png"}
        ]
        published: dict[str, str] = {}

        if self.publisher:
            published.update(
                self.publisher.publish_version(
                    latest.role.value, process_key, version, publish_files
                )
            )

        if self.publish_root:
            target = (
                self.publish_root
                / latest.role.value
                / process_key
                / f"v{version:03d}"
            )
            target.mkdir(parents=True, exist_ok=True)
            for file in files:
                destination = target / file.name
                shutil.copy2(file, destination)
                published[f"local_{file.name}"] = str(destination)
            approved_bundle = {
                "card": latest.to_dict(),
                "checklist_template": (
                    self.checklist_engine.template_for_process(process_key).to_dict()
                    if self.checklist_engine
                    and self.checklist_engine.template_for_process(process_key)
                    else None
                ),
            }
            (target / "approved_bundle.json").write_text(
                json.dumps(approved_bundle, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        if (
            latest.checklist_template_id
            and latest.checklist_version
            and self.checklist_engine
        ):
            self.checklist_engine.approve_template(
                latest.checklist_template_id,
                latest.checklist_version,
                approved_by,
            )

        self.record_sink.upsert_process_card(latest.to_dict(), published)
        card = self.store.approve(
            process_key,
            version,
            approved_by,
            approved_at=approved_at,
        )

        archive_draft = getattr(self.publisher, "archive_draft", None)
        if callable(archive_draft):
            try:
                archive_draft(card.role.value, process_key, version)
            except Exception as exc:
                self.store.audit(
                    "draft_archive_failed",
                    {
                        "process_key": process_key,
                        "version": version,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )

        self.store.audit(
            "published",
            {
                "process_key": process_key,
                "version": version,
                "published": published,
                "checklist_template_id": card.checklist_template_id,
            },
        )
        return {
            "card": card.to_dict(),
            "published": published,
            "already_approved": False,
        }

    def regenerate_changed(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for file in sorted(self.store.sources_dir.glob("*.json")):
            result = self.generate(file.stem)
            if result.get("changed"):
                results.append(result)
        return results

    def start_checklist(
        self,
        process_key: str,
        object_id: str,
        created_by: str,
        *,
        object_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not self.checklist_engine:
            raise RuntimeError("Checklist Engine is not configured")
        source = self.store.load_source(process_key)
        if not source.checklist_required:
            raise ValueError(f"Checklist is not required for {process_key}")
        instance = self.checklist_engine.start_instance(
            process_key,
            object_id,
            created_by,
            object_type=object_type or source.object_type,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )
        return instance.to_dict()
