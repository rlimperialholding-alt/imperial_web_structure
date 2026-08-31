"""Dedikált regresszió a Quality `integration-hub` job ruff `I001` korrekcióira.

A Task59 official Quality run (33346395581) négy importblokk-sorrend hibát
igazolt a tests/ könyvtárban (ruff `I001 Import block is un-sorted or
un-formatted`). A korrekció valódi kódjavítás volt (sorrendhelyreállítás,
noqa/ignore nélkül). Ez a regresszió az egyes korrigált állításokat AST-szinten,
hálózat nélkül, determinisztikusan rögzíti, így a jövőbeni rendezetlen
importblokk azonnal elbuktatja a lokális és CI tesztfutást is — nem csak a
külön futó ruff lépést.

A teszt a ruff által érvényesített isort-alapú kanonikus sorrendet köti le:
- third-party importok (httpx, pytest, local `synthetic_fixtures`) az első
  szakaszban, a helyi `app.` modulok előtt;
- a lokális test-modulok (`test_connector_http_hardening`,
  `test_safe_http_pinning`) szintén az `app.` importok előtt;
- importlistán belül az abc-sorrend (`_ordered_candidates` a
  `_PinnedNetworkBackend` előtt).
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


def _import_sections(source_file: str) -> dict[str, list[str]]:
    """Visszaadja a fájl top-level import-szakaszait (stdlib/third-party/local)."""
    tree = ast.parse((TESTS_DIR / source_file).read_text(encoding="utf-8"))
    sections: dict[str, list[str]] = {"third_party": [], "local_app": [], "local_test": []}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                _append_section(sections, alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            module = node.module
            _append_section(sections, module)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # modul docstring
        else:
            break  # az importblokk vége
    return sections


def _append_section(sections: dict[str, list[str]], module: str) -> None:
    if module.startswith("app."):
        sections["local_app"].append(module)
    elif module.startswith("test_") or module == "synthetic_fixtures":
        sections["local_test"].append(module)
    else:
        sections["third_party"].append(module)


def _ordered_import_names(source_file: str, from_module: str) -> list[str]:
    """Egy adott `from <from_module> import (...)` lista betűrendi nevei."""
    tree = ast.parse((TESTS_DIR / source_file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == from_module:
            return [alias.name for alias in node.names]
    raise AssertionError(f"{source_file}: nincs `from {from_module} import` blokk")


def test_connector_hardening_synthetic_fixture_import_before_app() -> None:
    """test_connector_http_hardening: a synthetic_fixtures a helyi app-importok előtt áll."""
    sections = _import_sections("test_connector_http_hardening.py")
    assert "synthetic_fixtures" in sections["local_test"]
    assert sections["local_app"], "app-importok hiányoznak"
    assert "synthetic_fixtures" not in sections["third_party"]
    # A harmadik/harmadik-fél szakasz minden app. import előtt zárul:
    # a fájlban a synthetic import a local_app blokk előtt szerepel.
    tree = ast.parse((TESTS_DIR / "test_connector_http_hardening.py").read_text(encoding="utf-8"))
    import_lines: list[tuple[int, str]] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            import_lines.append((node.lineno, node.module or ""))
    synthetic_line = next(ln for ln, mod in import_lines if mod == "synthetic_fixtures")
    first_app_line = next(ln for ln, mod in import_lines if mod and mod.startswith("app."))
    assert synthetic_line < first_app_line


def test_ingatlan_connector_synthetic_fixture_import_before_app() -> None:
    """test_ingatlan_connector: a synthetic_fixtures import a helyi app-importok előtt áll."""
    sections = _import_sections("test_ingatlan_connector.py")
    assert "synthetic_fixtures" in sections["local_test"]
    assert sections["local_app"], "app-importok hiányoznak"
    tree = ast.parse((TESTS_DIR / "test_ingatlan_connector.py").read_text(encoding="utf-8"))
    import_lines: list[tuple[int, str]] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            import_lines.append((node.lineno, node.module or ""))
    synthetic_line = next(ln for ln, mod in import_lines if mod == "synthetic_fixtures")
    first_app_line = next(ln for ln, mod in import_lines if mod and mod.startswith("app."))
    assert synthetic_line < first_app_line


def test_pinned_transport_query_test_imports_before_app_connectors() -> None:
    """test_pinned_transport_query: a lokális test-modul importok az app.connectors előtt állnak."""
    tree = ast.parse((TESTS_DIR / "test_pinned_transport_query.py").read_text(encoding="utf-8"))
    import_lines: list[tuple[int, str]] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            import_lines.append((node.lineno, node.module or ""))
    test_import_lines = [
        ln for ln, mod in import_lines if mod and (mod.startswith("test_") or mod == "synthetic_fixtures")
    ]
    app_lines = [ln for ln, mod in import_lines if mod and mod.startswith("app.")]
    assert test_import_lines, "lokális test-modul importok hiányoznak"
    assert app_lines, "app.connectors importok hiányoznak"
    assert max(test_import_lines) < min(app_lines)


def test_safe_http_pinning_import_name_order() -> None:
    """test_safe_http_pinning: `_ordered_candidates` a `_PinnedNetworkBackend` előtt áll."""
    names = _ordered_import_names("test_safe_http_pinning.py", "app.connectors.safe_http")
    assert "_ordered_candidates" in names
    assert "_PinnedNetworkBackend" in names
    assert names.index("_ordered_candidates") < names.index("_PinnedNetworkBackend")
