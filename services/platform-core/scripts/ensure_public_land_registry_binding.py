from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import os
import stat
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.growth_ops.registry import (
    GrowthRegistry,
    GrowthRegistryError,
)  # noqa: E402
from app.growth_ops.registry import settings as growth_settings  # noqa: E402
from app.land_acquisition.registry import LandRegistryError, PortalRegistry  # noqa: E402
from app.land_acquisition.service import (  # noqa: E402
    managed_public_land_route_set_sha256,
)

SOURCE_ID = "construction_public_land_html"


class RegistryBindingUpdateError(RuntimeError):
    """Apply failed after mutation; ``summary`` is safe to print as JSON."""

    def __init__(self, summary: dict[str, Any]) -> None:
        super().__init__(str(summary.get("error_code") or "registry_binding_update_failed"))
        self.summary = summary


@dataclass(frozen=True)
class _JsonMember:
    key: str
    key_start: int
    value_start: int
    value_end: int


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _skip_whitespace(text: str, position: int) -> int:
    while position < len(text) and text[position] in " \t\r\n":
        position += 1
    return position


def _skip_string(text: str, position: int) -> int:
    if position >= len(text) or text[position] != '"':
        raise ValueError("Expected a JSON string")
    position += 1
    while position < len(text):
        character = text[position]
        if character == '"':
            return position + 1
        if character == "\\":
            position += 2
        else:
            position += 1
    raise ValueError("Unterminated JSON string")


def _skip_value(text: str, position: int) -> int:
    position = _skip_whitespace(text, position)
    if position >= len(text):
        raise ValueError("Expected a JSON value")
    if text[position] == '"':
        return _skip_string(text, position)
    if text[position] in "[{":
        opening = text[position]
        closing = "]" if opening == "[" else "}"
        stack = [closing]
        position += 1
        while position < len(text) and stack:
            character = text[position]
            if character == '"':
                position = _skip_string(text, position)
                continue
            if character == "[":
                stack.append("]")
            elif character == "{":
                stack.append("}")
            elif character in "]}":
                if character != stack[-1]:
                    raise ValueError("Mismatched JSON container")
                stack.pop()
            position += 1
        if stack:
            raise ValueError("Unterminated JSON container")
        return position
    end = position
    while end < len(text) and text[end] not in ",]}":
        end += 1
    value_end = end
    while value_end > position and text[value_end - 1] in " \t\r\n":
        value_end -= 1
    if value_end == position:
        raise ValueError("Expected a JSON scalar")
    return value_end


def _object_members(text: str, object_start: int, object_end: int) -> list[_JsonMember]:
    if text[object_start] != "{" or text[object_end - 1] != "}":
        raise ValueError("Expected a JSON object")
    members: list[_JsonMember] = []
    position = _skip_whitespace(text, object_start + 1)
    if position == object_end - 1:
        return members
    while position < object_end - 1:
        key_start = position
        key_end = _skip_string(text, key_start)
        key = json.loads(text[key_start:key_end])
        position = _skip_whitespace(text, key_end)
        if position >= object_end or text[position] != ":":
            raise ValueError("Expected a JSON member separator")
        value_start = _skip_whitespace(text, position + 1)
        value_end = _skip_value(text, value_start)
        members.append(
            _JsonMember(
                key=str(key),
                key_start=key_start,
                value_start=value_start,
                value_end=value_end,
            )
        )
        position = _skip_whitespace(text, value_end)
        if position < object_end - 1 and text[position] == ",":
            position = _skip_whitespace(text, position + 1)
            continue
        if position == object_end - 1:
            return members
        raise ValueError("Expected a JSON comma or object terminator")
    raise ValueError("Invalid JSON object")


def _only_member(members: list[_JsonMember], key: str) -> _JsonMember | None:
    matches = [member for member in members if member.key == key]
    if len(matches) > 1:
        raise ValueError(f"Duplicate JSON member: {key}")
    return matches[0] if matches else None


def _line_indent(text: str, position: int) -> str:
    line_start = max(text.rfind("\n", 0, position), text.rfind("\r", 0, position)) + 1
    indent = text[line_start:position]
    return indent if not indent.strip() else "  "


def _formatted_binding(binding: dict[str, Any], *, newline: str, indent: str) -> str:
    rendered = json.dumps(binding, ensure_ascii=False, indent=2)
    return rendered.replace("\n", newline + indent)


def _replace_binding_bytes(
    original: bytes, binding: dict[str, Any]
) -> tuple[bytes, str]:
    bom = original.startswith(codecs.BOM_UTF8)
    body = original[len(codecs.BOM_UTF8) :] if bom else original
    text = body.decode("utf-8")
    parsed = json.loads(text)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("sources"), dict):
        raise ValueError("Growth registry must contain a sources object")

    root_start = _skip_whitespace(text, 0)
    root_end = _skip_value(text, root_start)
    if _skip_whitespace(text, root_end) != len(text):
        raise ValueError("Unexpected bytes after the growth registry JSON object")
    root_members = _object_members(text, root_start, root_end)
    sources_member = _only_member(root_members, "sources")
    if sources_member is None or text[sources_member.value_start] != "{":
        raise ValueError("Growth registry must contain exactly one sources object")
    source_members = _object_members(
        text, sources_member.value_start, sources_member.value_end
    )
    target = _only_member(source_members, SOURCE_ID)
    newline = "\r\n" if text.count("\r\n") > text.count("\n") / 2 else "\n"

    if target is not None:
        current = json.loads(text[target.value_start : target.value_end])
        if current == binding:
            return original, "unchanged"
        indent = _line_indent(text, target.key_start)
        replacement = _formatted_binding(binding, newline=newline, indent=indent)
        updated_text = text[: target.value_start] + replacement + text[target.value_end :]
        action = "update"
    else:
        if not source_members:
            root_indent = _line_indent(text, sources_member.key_start)
            indent = root_indent + "  "
            insertion_position = sources_member.value_start + 1
            insertion = (
                newline
                + indent
                + json.dumps(SOURCE_ID)
                + ": "
                + _formatted_binding(binding, newline=newline, indent=indent)
            )
        else:
            last = source_members[-1]
            indent = _line_indent(text, last.key_start)
            insertion_position = last.value_end
            insertion = (
                ","
                + newline
                + indent
                + json.dumps(SOURCE_ID)
                + ": "
                + _formatted_binding(binding, newline=newline, indent=indent)
            )
        updated_text = text[:insertion_position] + insertion + text[insertion_position:]
        action = "insert"

    prefix = codecs.BOM_UTF8 if bom else b""
    return prefix + updated_text.encode("utf-8"), action


def _expected_binding(route_set_sha256: str) -> dict[str, Any]:
    return {
        "enabled": True,
        "kind": GrowthRegistry.PUBLIC_LAND_SOURCE_KIND,
        "fetch_mode": GrowthRegistry.PUBLIC_LAND_FETCH_MODE,
        "motor": "construction",
        "bucket": "property_development",
        "route_set_sha256": route_set_sha256,
    }


def _validated_registry(raw: bytes, expected_binding: dict[str, Any]) -> GrowthRegistry:
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GrowthRegistryError("Updated growth registry JSON is unreadable") from exc
    if not isinstance(value, dict):
        raise GrowthRegistryError("Updated growth registry is not an object")
    loaded = GrowthRegistry(value)
    if loaded.sources.get(SOURCE_ID) != expected_binding:
        raise GrowthRegistryError("Public land source binding exact readback failed")
    duplicates = [
        source_id
        for source_id, source in loaded.sources.items()
        if source_id != SOURCE_ID
        and isinstance(source, dict)
        and source.get("enabled") is True
        and source.get("fetch_mode") == GrowthRegistry.PUBLIC_LAND_FETCH_MODE
        and source.get("motor") == "construction"
        and source.get("bucket") == "property_development"
    ]
    if duplicates:
        raise GrowthRegistryError("Public land source binding is not unique")
    readiness = loaded.readiness()
    if (
        readiness.get("public_land_source_ready") is not True
        or readiness.get("public_land_route_set_sha256")
        != expected_binding["route_set_sha256"]
    ):
        raise GrowthRegistryError("Public land source readiness readback failed")
    return loaded


def _resolve_registry_path(explicit: str | Path | None) -> Path:
    return Path(explicit) if explicit else Path(growth_settings().registry_file)


def _resolve_portal_registry_path(explicit: str | Path | None) -> Path:
    if explicit:
        return Path(explicit)
    configured = os.getenv("LAND_ACQUISITION_PORTAL_REGISTRY_FILE", "").strip()
    if configured:
        return Path(configured)
    runtime = Path("/app/config/land-acquisition/portals.json")
    if runtime.is_file():
        return runtime
    return Path(__file__).resolve().parents[3] / "config/land-acquisition/portals.json"


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _write_exclusive(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    _fsync_directory(path.parent)


def _atomic_replace(
    target: Path,
    data: bytes,
    *,
    original_mode: int,
    original_owner: tuple[int, int] | None,
) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if original_owner is not None and hasattr(os, "chown"):
            try:
                os.chown(temporary, *original_owner)
            except OSError:
                pass
        os.replace(temporary, target)
        try:
            os.chmod(target, original_mode)
        except OSError:
            pass
        _fsync_directory(target.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _backup_path(target: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return target.with_name(f"{target.name}.backup-{stamp}-{uuid4().hex[:8]}")


def _readback(
    target: Path,
    *,
    proposed_sha256: str,
    expected_binding: dict[str, Any],
) -> str:
    current = target.read_bytes()
    current_sha256 = _sha256(current)
    if current_sha256 != proposed_sha256:
        raise GrowthRegistryError("Atomic registry byte hash readback failed")
    _validated_registry(current, expected_binding)
    return current_sha256


def ensure_public_land_registry_binding(
    *,
    registry_file: str | Path | None = None,
    portal_registry_file: str | Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    unresolved_target = _resolve_registry_path(registry_file).expanduser()
    if unresolved_target.is_symlink():
        raise GrowthRegistryError("Growth registry symlinks are not allowed")
    target = unresolved_target.resolve(strict=True)
    portal_path = _resolve_portal_registry_path(portal_registry_file).resolve(strict=True)
    if not target.is_file():
        raise FileNotFoundError("Growth registry must be an existing regular non-symlink file")
    if not portal_path.is_file():
        raise FileNotFoundError("Portal registry must be an existing regular file")

    original_stat = target.stat()
    original_mode = stat.S_IMODE(original_stat.st_mode)
    original_owner = (
        (original_stat.st_uid, original_stat.st_gid)
        if hasattr(original_stat, "st_uid") and hasattr(original_stat, "st_gid")
        else None
    )
    original = target.read_bytes()
    portal_bytes = portal_path.read_bytes()
    portal_registry = PortalRegistry.load(portal_path)
    route_digest = managed_public_land_route_set_sha256(portal_registry)
    if route_digest != GrowthRegistry.PUBLIC_LAND_ROUTE_SET_SHA256:
        raise GrowthRegistryError("Portal route digest conflicts with the runtime growth gate")
    expected_binding = _expected_binding(route_digest)
    proposed, plan_action = _replace_binding_bytes(original, expected_binding)
    _validated_registry(proposed, expected_binding)

    before_sha256 = _sha256(original)
    proposed_sha256 = _sha256(proposed)
    summary: dict[str, Any] = {
        "status": "dry_run" if not apply else "unchanged",
        "dry_run": not apply,
        "applied": False,
        "action": "unchanged" if plan_action == "unchanged" else f"would_{plan_action}",
        "registry_file": str(target),
        "portal_registry_file": str(portal_path),
        "source_id": SOURCE_ID,
        "route_set_sha256": route_digest,
        "portal_registry_sha256": _sha256(portal_bytes),
        "before_sha256": before_sha256,
        "proposed_sha256": proposed_sha256,
        "readback_sha256": before_sha256 if plan_action == "unchanged" else None,
        "backup_path": None,
        "backup_sha256": None,
        "rollback_performed": False,
    }
    if not apply or plan_action == "unchanged":
        return summary

    backup = _backup_path(target)
    _write_exclusive(backup, original)
    summary["backup_path"] = str(backup)
    try:
        backup_sha256 = _sha256(backup.read_bytes())
    except OSError as exc:
        summary.update(
            {
                "status": "error",
                "action": "backup_verification_failed",
                "error_code": "backup_readback_failed",
                "error_type": type(exc).__name__,
            }
        )
        raise RegistryBindingUpdateError(summary) from exc
    summary["backup_sha256"] = backup_sha256
    if backup_sha256 != before_sha256:
        summary.update(
            {
                "status": "error",
                "action": "backup_verification_failed",
                "error_code": "backup_hash_readback_failed",
            }
        )
        raise RegistryBindingUpdateError(summary)
    try:
        _atomic_replace(
            target,
            proposed,
            original_mode=original_mode,
            original_owner=original_owner,
        )
        summary["readback_sha256"] = _readback(
            target,
            proposed_sha256=proposed_sha256,
            expected_binding=expected_binding,
        )
    except Exception as exc:
        rollback_ok = False
        try:
            backup_bytes = backup.read_bytes()
            if _sha256(backup_bytes) != before_sha256:
                raise OSError("Backup hash mismatch")
            _atomic_replace(
                target,
                backup_bytes,
                original_mode=original_mode,
                original_owner=original_owner,
            )
            rollback_ok = _sha256(target.read_bytes()) == before_sha256
        except Exception:
            rollback_ok = False
        summary.update(
            {
                "status": "error",
                "action": f"{plan_action}_failed",
                "error_code": "post_replace_readback_failed",
                "error_type": type(exc).__name__,
                "rollback_performed": rollback_ok,
                "readback_sha256": _sha256(target.read_bytes()) if target.is_file() else None,
            }
        )
        raise RegistryBindingUpdateError(summary) from exc

    summary.update(
        {
            "status": "applied",
            "applied": True,
            "action": plan_action,
        }
    )
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or atomically enable the exact managed public-land source binding."
        )
    )
    parser.add_argument(
        "--registry-file",
        help=(
            "Active growth registry. Defaults to GROWTH_OPS_REGISTRY_FILE/the growth settings."
        ),
    )
    parser.add_argument(
        "--portal-registry-file",
        help=(
            "Portal registry used to compute the exact managed route digest. "
            "Defaults to LAND_ACQUISITION_PORTAL_REGISTRY_FILE."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create a sibling backup and atomically apply. Omit for a read-only dry run.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = ensure_public_land_registry_binding(
            registry_file=args.registry_file,
            portal_registry_file=args.portal_registry_file,
            apply=args.apply,
        )
    except RegistryBindingUpdateError as exc:
        result = exc.summary
        exit_code = 1
    except (GrowthRegistryError, LandRegistryError, OSError, ValueError) as exc:
        result = {
            "status": "error",
            "dry_run": not args.apply,
            "applied": False,
            "error_code": type(exc).__name__,
        }
        exit_code = 1
    except Exception as exc:  # pragma: no cover - last-resort secret-safe CLI boundary
        result = {
            "status": "error",
            "dry_run": not args.apply,
            "applied": False,
            "error_code": "unexpected_error",
            "error_type": type(exc).__name__,
        }
        exit_code = 1
    else:
        exit_code = 0
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
