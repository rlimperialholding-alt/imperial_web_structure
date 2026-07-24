from __future__ import annotations

from app.adapters.platform import PlatformModelAdapter
from app.config import get_settings


def test_existing_models_are_read_through_adapter() -> None:
    adapter = PlatformModelAdapter(get_settings().platform_data_path)
    context = adapter.project_context("P-5001")
    assert context is not None
    assert context["project"]["customerId"] == context["customer"]["id"]
    assert adapter.get_user("USR-03")["role"] == "Project Manager"
    assert adapter.get_project("missing") is None
