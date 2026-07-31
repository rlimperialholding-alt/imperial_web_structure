from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleDefinition:
    id: str
    label: str
    initials: str
    module_access: frozenset[str]


def _role(
    role_id: str,
    label: str,
    initials: str,
    modules: str,
) -> RoleDefinition:
    return RoleDefinition(
        id=role_id,
        label=label,
        initials=initials,
        module_access=frozenset(modules.split()),
    )


ROLE_DEFINITIONS = (
    _role("owner", "Tulajdonos", "TU", "workspace executive-dashboard control-center integration-control-room completion-audit financial-control finance-intelligence crm project-control digital-project-managers pm-cockpit operations-workspace"),
    _role("managing-director", "Ügyvezető", "ÜV", "workspace executive-dashboard control-center crm project-control digital-project-managers pm-cockpit operations-workspace smart-calendar financial-control finance-intelligence procurement document-evidence workflow-center"),
    _role("marketing", "Marketing", "MK", "workspace marketing-control campaign-factory content-factory claim-registry website-content-control lead-intelligence b2b-project-intake housematch housevision crm answer-center"),
    _role("technical-prep", "Műszaki előkészítő", "ME", "workspace house-catalog housebuild-agent housematch plotcheck buildconfig plancheck engineering-workspace document-evidence project-control"),
    _role("sales", "Értékesítő", "ÉR", "workspace crm sales housematch plotcheck buildconfig booking-engine reservation-engine contract-generator my-imperial"),
    _role("finance", "Pénzügy", "PÜ", "workspace financial-control finance-intelligence procurement import-center tendermail project-control change-control document-evidence executive-dashboard"),
    _role("project-manager", "Projektmenedzser", "PM", "workspace project-control digital-project-managers pm-cockpit operations-workspace smart-calendar procurement change-control my-imperial document-evidence partner-connect partner-field field-pwa imperial-care"),
    _role("designer", "Tervező partner", "TP", "workspace engineering-workspace plancheck plotcheck buildconfig my-imperial document-evidence"),
    _role("subcontractor", "Alvállalkozó", "AV", "workspace partner-connect partner-field field-pwa operations-workspace procurement document-evidence imperial-care"),
    _role("customer", "Ügyfél", "ÜF", "workspace my-imperial housematch plotcheck buildconfig booking-engine reservation-engine change-control imperial-care"),
    _role("legal", "Jogász", "JG", "workspace contract-generator change-control document-evidence my-imperial claim-registry"),
    _role("platform-admin", "Platform admin", "PA", "workspace executive-dashboard control-center integration-control-room completion-audit admin workflow-center crm sales contract-generator my-imperial booking-engine reservation-engine house-catalog housebuild-agent housematch plotcheck buildconfig plancheck engineering-workspace housevision project-control digital-project-managers pm-cockpit operations-workspace smart-calendar change-control document-center document-evidence import-center tendermail procurement partner-connect partner-control partner-field field-pwa financial-control finance-intelligence imperial-care marketing-control campaign-factory content-factory claim-registry website-content-control answer-center lead-intelligence b2b-project-intake"),
)

ROLES = {role.id: role for role in ROLE_DEFINITIONS}

PAGE_ACCESS = (
    ("/financial", ("financial-control", "finance-intelligence")),
    ("/executive", ("executive-dashboard",)),
    ("/tasks", ("workflow-center", "workspace")),
    ("/projects", ("project-control",)),
    ("/operations", ("operations-workspace", "pm-cockpit")),
    ("/field", ("field-pwa", "partner-field")),
    ("/procurement", ("procurement",)),
    ("/documents", ("document-center", "document-evidence")),
    ("/search", ("workspace",)),
    ("/imports", ("import-center",)),
    ("/experience", ("housematch", "buildconfig")),
    ("/tendermail", ("tendermail",)),
    ("/commercial", ("contract-generator", "change-control")),
    ("/exceptions", ("control-center", "executive-dashboard")),
    ("/modules", ("control-center", "admin")),
    ("/development-governance", ("admin",)),
    ("/releases", ("completion-audit", "admin")),
    ("/pilots", ("integration-control-room", "admin")),
    ("/", ("workspace",)),
)


def role_definition(role_id: str) -> RoleDefinition | None:
    return ROLES.get(role_id)


def can_access_role(role_id: str, *module_ids: str) -> bool:
    role = role_definition(role_id)
    return bool(role and any(module_id in role.module_access for module_id in module_ids))


def can_access(user: object | None, *module_ids: str) -> bool:
    role_id = getattr(user, "role", None)
    return bool(role_id and can_access_role(role_id, *module_ids))


def modules_for_path(path: str) -> tuple[str, ...]:
    for prefix, module_ids in PAGE_ACCESS:
        if prefix == "/" and path != "/":
            continue
        if path == prefix or path.startswith(f"{prefix}/"):
            return module_ids
    return ()


def public_role_payload(role_id: str) -> dict[str, object]:
    role = ROLES[role_id]
    return {
        "id": role.id,
        "label": role.label,
        "initials": role.initials,
        "moduleAccess": sorted(role.module_access),
    }
