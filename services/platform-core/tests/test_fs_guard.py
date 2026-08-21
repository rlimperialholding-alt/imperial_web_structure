"""Path-injection negatív tesztek a konténment-őrre (szintetikus, hálózatmentes)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.services.fs_guard import contained_path, require_contained, safe_segment


def _link_directory(link: Path, target: Path) -> None:
    """Könyvtárlink létrehozása; Windows-on a junction (mklink /J) nem igényel jogosultságot."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError, TypeError) as exc:
        if os.name == "nt":
            try:
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                    check=True,
                    capture_output=True,
                )
            except (OSError, subprocess.CalledProcessError) as junction_exc:
                pytest.skip(f"Sem symlink, sem junction nem hozható létre: {junction_exc}")
        else:
            pytest.skip(f"Symlink nem hozható létre ezen a platformon: {exc}")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "inside").mkdir()
    return tmp_path


class TestSafeSegment:
    @pytest.mark.parametrize(
        "value",
        [
            "",
            None,
            7,
            "..",
            "a/b",
            "a\\b",
            "a b",
            ".hidden",
            "a:colon",
            "a" * 65,
            "C:/abs",
        ],
    )
    def test_unsafe_segments_are_rejected(self, value: object) -> None:
        with pytest.raises(ValueError):
            safe_segment(value, label="teszt")

    def test_safe_segment_is_accepted(self) -> None:
        assert safe_segment("HVS-AB12_34.h") == "HVS-AB12_34.h"


class TestContainedPath:
    def test_simple_segment_stays_under_root(self, root: Path) -> None:
        path = contained_path(root, "job-1")
        assert path == root / "job-1"

    @pytest.mark.parametrize(
        "segment",
        ["../escape", "..", "/abs", "C:/Windows", "a\\b", "a/b"],
    )
    def test_traversal_absolute_and_alt_separator_rejected(self, root: Path, segment: str) -> None:
        with pytest.raises(ValueError):
            contained_path(root, segment)

    def test_parent_matching_prefix_is_not_containment(self, root: Path) -> None:
        sibling = root.parent / f"{root.name}-evil"
        sibling.mkdir(exist_ok=True)
        with pytest.raises(ValueError):
            require_contained(root, sibling / "payload.txt")

    def test_symlink_escape_is_rejected(self, root: Path) -> None:
        # A támadási vektor: a gyökéren BELÜL elhelyezett link, amely kifelé mutat.
        outside = root.parent / "outside-secret-dir"
        outside.mkdir(exist_ok=True)
        (outside / "job-1").mkdir(exist_ok=True)
        (outside / "job-1" / "x.txt").write_text("titkos", encoding="utf-8")
        link = root / "legacy"
        _link_directory(link, outside)
        with pytest.raises(ValueError):
            contained_path(root, "legacy", "job-1")
        with pytest.raises(ValueError):
            require_contained(root, link / "job-1" / "x.txt")

    def test_junction_style_directory_link_escape_is_rejected(self, root: Path) -> None:
        # A Windows-junction megfelelője: a gyökéren belüli könyvtárlink kifelé;
        # a realpath-feloldás mindkét formát követi, és az ellenőrzés fail-closed leáll.
        outside_dir = root.parent / "outside-dir"
        outside_dir.mkdir(exist_ok=True)
        (outside_dir / "job-1").mkdir(exist_ok=True)
        link = root / "linked"
        _link_directory(link, outside_dir)
        with pytest.raises(ValueError):
            contained_path(root, "linked", "job-1")

    def test_provider_storage_ref_outside_root_is_rejected(self, root: Path) -> None:
        outside = root.parent / "outside-ref.txt"
        outside.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError):
            require_contained(root / "inside", outside)

    def test_provider_storage_ref_inside_root_is_accepted(self, root: Path) -> None:
        inside = root / "inside" / "file.txt"
        inside.write_text("x", encoding="utf-8")
        assert require_contained(root / "inside", inside) == inside.resolve()
