from __future__ import annotations

from typing import Any, Protocol


class CoreModelAdapter(Protocol):
    def get_project(self, project_id: str) -> dict[str, Any] | None: ...

    def get_customer(self, customer_id: str) -> dict[str, Any] | None: ...

    def get_user(self, user_id: str) -> dict[str, Any] | None: ...


class ExternalSystemAdapter(Protocol):
    name: str

    def invoke(
        self,
        *,
        action: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]: ...
