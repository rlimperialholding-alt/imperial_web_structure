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
    _role("owner", "Tulajdonos", "TU", "workspace executive-dashboard control-center integration-control-room completion-audit admin financial-control finance-intelligence crm project-control digital-project-managers pm-cockpit operations-workspace smart-calendar procurement tendermail document-evidence housebuild-agent plotcheck buildconfig plancheck housevision imperial-care marketing-control campaign-factory content-factory claim-registry website-content-control lead-intelligence"),
    _role("managing-director", "Ügyvezető", "ÜV", "workspace executive-dashboard control-center crm project-control digital-project-managers pm-cockpit operations-workspace smart-calendar financial-control finance-intelligence procurement tendermail document-evidence workflow-center housebuild-agent plotcheck buildconfig plancheck housevision imperial-care marketing-control campaign-factory content-factory claim-registry website-content-control lead-intelligence"),
    _role("marketing", "Marketing", "MK", "workspace marketing-control campaign-factory content-factory claim-registry website-content-control lead-intelligence b2b-project-intake housematch housevision crm answer-center"),
    _role("copywriter", "Direct-response szövegíró", "SZ", "workspace marketing-control campaign-factory content-factory claim-registry website-content-control"),
    _role("language-editor", "Magyar nyelvi szerkesztő", "NY", "workspace marketing-control content-factory website-content-control"),
    _role("creative-director", "Kreatív igazgató", "KI", "workspace marketing-control content-factory website-content-control housevision"),
    _role("technical-prep", "Műszaki előkészítő", "ME", "workspace house-catalog housebuild-agent housematch plotcheck buildconfig plancheck housevision engineering-workspace document-evidence project-control procurement tendermail"),
    _role("sales", "Értékesítő", "ÉR", "workspace crm sales housematch plotcheck buildconfig booking-engine reservation-engine contract-generator my-imperial document-evidence lead-intelligence"),
    _role("finance", "Pénzügy", "PÜ", "workspace financial-control finance-intelligence procurement import-center tendermail project-control change-control document-evidence executive-dashboard buildconfig"),
    _role("project-manager", "Projektmenedzser", "PM", "workspace project-control digital-project-managers pm-cockpit operations-workspace smart-calendar procurement tendermail change-control my-imperial document-evidence partner-connect partner-field field-pwa imperial-care plotcheck plancheck financial-control finance-intelligence"),
    _role("designer", "Tervező partner", "TP", "workspace engineering-workspace project-control plancheck plotcheck buildconfig housevision my-imperial document-evidence"),
    _role("subcontractor", "Alvállalkozó", "AV", "workspace partner-connect partner-field field-pwa operations-workspace document-evidence imperial-care"),
    _role("customer", "Ügyfél", "ÜF", "workspace my-imperial housematch plotcheck buildconfig booking-engine reservation-engine imperial-care"),
    _role("legal", "Jogász", "JG", "workspace contract-generator change-control document-evidence my-imperial claim-registry housevision"),
    _role("platform-admin", "Platform admin", "PA", "workspace executive-dashboard control-center integration-control-room completion-audit admin workflow-center crm sales contract-generator my-imperial booking-engine reservation-engine house-catalog housebuild-agent housematch plotcheck buildconfig plancheck engineering-workspace housevision project-control digital-project-managers pm-cockpit operations-workspace smart-calendar change-control document-center document-evidence import-center tendermail procurement partner-connect partner-control partner-field field-pwa financial-control finance-intelligence imperial-care marketing-control campaign-factory content-factory claim-registry website-content-control answer-center lead-intelligence b2b-project-intake"),
)

ROLES = {role.id: role for role in ROLE_DEFINITIONS}

EXTRA_ROLE_ACCESS = {
    "owner": frozenset({"sales", "booking-engine", "reservation-engine", "contract-generator", "my-imperial", "house-catalog", "engineering-workspace", "partner-connect", "partner-control", "answer-center", "b2b-project-intake", "house-designer", "market-creative-intelligence"}),
    "managing-director": frozenset({"sales", "booking-engine", "reservation-engine", "contract-generator", "my-imperial", "house-catalog", "engineering-workspace", "partner-connect", "partner-control", "answer-center", "b2b-project-intake", "house-designer", "market-creative-intelligence"}),
    "finance": frozenset({"sales", "reservation-engine", "house-catalog", "engineering-workspace", "partner-connect", "partner-control", "answer-center", "b2b-project-intake"}),
    "legal": frozenset({"sales", "house-catalog", "partner-control", "answer-center"}),
    "technical-prep": frozenset({"sales", "partner-connect", "partner-control", "answer-center", "house-designer"}),
    "copywriter": frozenset({"answer-center"}),
    "language-editor": frozenset({"answer-center"}),
    "creative-director": frozenset({"answer-center"}),
    "designer": frozenset({"house-catalog", "house-designer"}),
    "sales": frozenset({"house-catalog", "answer-center", "b2b-project-intake", "house-designer"}),
    "project-manager": frozenset({"engineering-workspace", "partner-control", "answer-center", "b2b-project-intake", "house-designer"}),
    "customer": frozenset({"house-designer"}),
    "marketing": frozenset({"market-creative-intelligence"}),
    "platform-admin": frozenset({"house-designer", "market-creative-intelligence"}),
}

PAGE_ACCESS = (
    ("/financial", ("financial-control", "finance-intelligence")),
    ("/executive", ("executive-dashboard",)),
    ("/tasks", ("workflow-center", "workspace")),
    ("/smart-calendar", ("smart-calendar",)),
    ("/communications", ("workspace",)),
    ("/projects", ("project-control",)),
    ("/project-control", ("project-control",)),
    ("/digital-project-managers", ("digital-project-managers", "pm-cockpit")),
    ("/operations", ("operations-workspace", "pm-cockpit")),
    ("/field", ("field-pwa", "partner-field")),
    ("/procurement", ("procurement",)),
    ("/house-designer", ("house-designer",)),
    ("/market-intelligence", ("market-creative-intelligence",)),
    ("/housevision", ("housevision",)),
    ("/website-content-control", ("website-content-control",)),
    ("/answer-center", ("answer-center",)),
    ("/b2b-project-intake", ("b2b-project-intake",)),
    ("/documents", ("document-center", "document-evidence")),
    ("/search", ("workspace",)),
    ("/imports", ("import-center",)),
    ("/experience", ("housematch", "buildconfig")),
    ("/house-catalog", ("house-catalog",)),
    ("/engineering-workspace", ("engineering-workspace",)),
    ("/technical", ("housebuild-agent", "plotcheck", "buildconfig", "plancheck")),
    ("/marketing/automation", ("lead-intelligence", "campaign-factory")),
    ("/marketing", ("marketing-control", "campaign-factory", "content-factory")),
    ("/tendermail", ("tendermail",)),
    ("/tenders", ("tendermail",)),
    ("/partners", ("partner-control",)),
    ("/commercial", ("contract-generator", "change-control")),
    ("/my-imperial", ("my-imperial",)),
    ("/imperial-care", ("imperial-care",)),
    ("/sales-commercial", ("sales", "booking-engine", "reservation-engine")),
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
    granted = role.module_access | EXTRA_ROLE_ACCESS.get(role_id, frozenset()) if role else frozenset()
    return bool(role and any(module_id in granted for module_id in module_ids))


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
