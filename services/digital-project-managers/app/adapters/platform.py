from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any


class PlatformModelAdapter:
    """Read-only adapter for the repository's canonical prototype entities."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = RLock()
        self._mtime_ns: int | None = None
        self._data: dict[str, Any] = {}

    def _load(self) -> dict[str, Any]:
        with self._lock:
            stat = self._path.stat()
            if stat.st_mtime_ns != self._mtime_ns:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                meta = data.get("meta", {})
                if meta.get("containsCustomerData") is not False:
                    raise RuntimeError("Platform adapter refuses unclassified customer data")
                self._data = data
                self._mtime_ns = stat.st_mtime_ns
            return self._data

    def _find(self, collection: str, entity_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self._load().get(collection, []) if item.get("id") == entity_id),
            None,
        )

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return self._find("projects", project_id)

    def get_customer(self, customer_id: str) -> dict[str, Any] | None:
        return self._find("customers", customer_id)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self._find("users", user_id)

    def project_context(self, project_id: str) -> dict[str, Any] | None:
        project = self.get_project(project_id)
        if project is None:
            return None
        customer = self.get_customer(project["customerId"])
        return {"project": project, "customer": customer}
