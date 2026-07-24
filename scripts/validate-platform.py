#!/usr/bin/env python3
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "sites/_portal/data/platform.json"
SYSTEM_FILE = ROOT / "sites/_portal/data/system.json"
PORTAL_FILE = ROOT / "sites/_portal/index.html"
SCRIPT_FILE = ROOT / "sites/_shared/assets/platform.js"
STYLE_FILE = ROOT / "sites/_shared/assets/platform.css"

EXPECTED_MODULES = {
    "executive-dashboard",
    "my-imperial",
    "crm",
    "sales",
    "contract-generator",
    "project-control",
    "financial-control",
    "imperial-care",
    "partner-control",
    "marketing-control",
    "website-content-control",
    "document-center",
    "workflow-center",
    "admin",
    "workspace",
    "control-center",
    "integration-control-room",
    "completion-audit",
    "smart-calendar",
    "change-control",
    "document-evidence",
    "procurement",
    "partner-connect",
    "partner-field",
    "house-catalog",
    "housebuild-agent",
    "housematch",
    "plotcheck",
    "buildconfig",
    "plancheck",
    "engineering-workspace",
    "housevision",
    "booking-engine",
    "reservation-engine",
    "campaign-factory",
    "content-factory",
    "claim-registry",
    "answer-center",
    "lead-intelligence",
    "digital-project-managers",
}

MINIMUM_COUNTS = {
    "leads": 10,
    "customers": 5,
    "projects": 3,
    "partners": 5,
    "offers": 8,
    "contracts": 4,
    "financialItems": 20,
    "careTickets": 6,
    "milestones": 1,
    "documents": 1,
    "tasks": 1,
}

ENTITY_COLLECTIONS = {
    "lead": "leads",
    "customer": "customers",
    "offer": "offers",
    "contract": "contracts",
    "project": "projects",
    "partner": "partners",
    "financialItem": "financialItems",
    "careTicket": "careTickets",
    "milestone": "milestones",
    "document": "documents",
    "task": "tasks",
    "campaign": "campaigns",
    "workflow": "workflows",
    "user": "users",
    "auditEvent": "auditEvents",
}


def fail(message):
    raise SystemExit(f"Platform validation failed: {message}")


def load_text(path):
    if not path.is_file():
        fail(f"missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def ids(data, collection):
    return {item["id"] for item in data[collection]}


def require_reference(valid_ids, value, source):
    if value is not None and value not in valid_ids:
        fail(f"{source} references missing entity {value}")


def main():
    data = json.loads(load_text(DATA_FILE))
    system = json.loads(load_text(SYSTEM_FILE))
    portal = load_text(PORTAL_FILE)
    script = load_text(SCRIPT_FILE)
    style = load_text(STYLE_FILE)

    meta = data.get("meta", {})
    required_meta = {
        "environment": "local-prototype",
        "synthetic": True,
        "containsCustomerData": False,
        "usesExternalApis": False,
        "containsProductionSecrets": False,
    }
    for key, expected in required_meta.items():
        if meta.get(key) != expected:
            fail(f"meta.{key} must be {expected!r}")

    modules = data.get("modules", [])
    module_ids = {module.get("id") for module in modules}
    routes = [module.get("route") for module in modules]
    if module_ids != EXPECTED_MODULES:
        fail(f"module set mismatch: {sorted(module_ids ^ EXPECTED_MODULES)}")
    if len(modules) != len(EXPECTED_MODULES) or len(set(routes)) != len(routes):
        fail("module IDs and routes must be unique")
    for module in modules:
        expected_route = f"/{module['id']}/"
        if module.get("route") != expected_route:
            fail(f"{module['id']} must use stable route {expected_route}")
        if not (module.get("name") or module.get("label")) or not module.get("description"):
            fail(f"{module['id']} requires a label and description")

    system_meta = system.get("meta", {})
    required_system_meta = {
        "environment": "local-integration-prototype",
        "synthetic": True,
        "containsCustomerData": False,
        "usesExternalApis": False,
        "containsProductionSecrets": False,
    }
    for key, expected in required_system_meta.items():
        if system_meta.get(key) != expected:
            fail(f"system.meta.{key} must be {expected!r}")

    roles = system.get("roles", [])
    role_ids = [role.get("id") for role in roles]
    if len(roles) < 10 or None in role_ids or len(set(role_ids)) != len(role_ids):
        fail("system requires at least ten unique role workspaces")
    for role in roles:
        access = role.get("moduleAccess", [])
        if not access or set(access) - module_ids:
            fail(f"role {role['id']} has empty or invalid module access")
    admin_role = next((role for role in roles if role["id"] == "platform-admin"), None)
    if not admin_role or set(admin_role["moduleAccess"]) != module_ids:
        fail("platform-admin must have access to every registered module")

    event_contracts = system.get("eventContracts", [])
    event_keys = [contract.get("eventKey") for contract in event_contracts]
    if len(event_contracts) < 12 or None in event_keys or len(set(event_keys)) != len(event_keys):
        fail("system requires unique canonical event contracts")
    for contract in event_contracts:
        if contract.get("producer") not in module_ids:
            fail(f"event {contract['eventKey']} has an unknown producer")
        consumers = contract.get("consumers", [])
        if not consumers or set(consumers) - module_ids:
            fail(f"event {contract['eventKey']} has unknown consumers")
        if not contract.get("idempotency"):
            fail(f"event {contract['eventKey']} requires an idempotency key")

    house_build = system.get("houseBuild", {})
    sources = house_build.get("sources", [])
    source_ids = {source.get("id") for source in sources}
    approved_source_ids = {source["id"] for source in sources if source.get("status") == "approved"}
    if not approved_source_ids or not any(source.get("status") == "rights_blocked" for source in sources):
        fail("HouseBuild requires approved and rights-blocked source fixtures")
    for job in house_build.get("jobs", []):
        if job.get("sourceId") not in source_ids or not job.get("housePlanId"):
            fail(f"HouseBuild job {job.get('id')} has invalid source/projection IDs")
        if job.get("sourceId") not in approved_source_ids:
            fail(f"HouseBuild job {job.get('id')} must use an approved source")
        required_gates = {"source", "rights", "grossArea", "topology", "duplicates", "humanApproval"}
        if set(job.get("qa", {})) != required_gates:
            fail(f"HouseBuild job {job.get('id')} has an incomplete QA gate set")

    briefs = system.get("campaignFactory", {}).get("briefs", [])
    if not briefs or any(not brief.get("claimIds") or not brief.get("channels") for brief in briefs):
        fail("Campaign Factory requires claim-linked multi-channel briefs")
    if len(system.get("consistencyChecks", [])) < 4:
        fail("cross-module consistency checks are incomplete")

    for collection, minimum in MINIMUM_COUNTS.items():
        records = data.get(collection)
        if not isinstance(records, list) or len(records) < minimum:
            fail(f"{collection} requires at least {minimum} records")
        record_ids = [record.get("id") for record in records]
        if None in record_ids or len(set(record_ids)) != len(record_ids):
            fail(f"{collection} IDs must be present and unique")

    active_projects = [project for project in data["projects"] if project.get("active") is True]
    if len(active_projects) < 3:
        fail("at least three construction projects must be explicitly active")

    entity_ids = {
        entity_type: ids(data, collection)
        for entity_type, collection in ENTITY_COLLECTIONS.items()
    }
    journey = data.get("journey", {})
    steps = journey.get("steps", [])
    if len(steps) < 10 or not journey.get("customerId"):
        fail("the full lead-to-warranty journey is incomplete")
    journey_modules = set()
    for step in steps:
        module_id = step.get("moduleId")
        entity_type = step.get("entityType")
        entity_id = step.get("entityId")
        if module_id not in module_ids:
            fail(f"journey step uses missing module {module_id}")
        if entity_type not in entity_ids or entity_id not in entity_ids[entity_type]:
            fail(f"journey step uses missing entity {entity_type}:{entity_id}")
        journey_modules.add(module_id)
    for required in ("marketing-control", "crm", "sales", "contract-generator",
                     "project-control", "financial-control", "my-imperial", "imperial-care"):
        if required not in journey_modules:
            fail(f"journey must include {required}")

    lead_ids = entity_ids["lead"]
    customer_ids = entity_ids["customer"]
    offer_ids = entity_ids["offer"]
    contract_ids = entity_ids["contract"]
    project_ids = entity_ids["project"]
    partner_ids = entity_ids["partner"]
    finance_ids = entity_ids["financialItem"]
    care_ids = entity_ids["careTicket"]

    for customer in data["customers"]:
        require_reference(lead_ids, customer.get("leadId"), f"customer {customer['id']}")
        for key, valid in (
            ("offerIds", offer_ids),
            ("contractIds", contract_ids),
            ("projectIds", project_ids),
            ("financialItemIds", finance_ids),
            ("careTicketIds", care_ids),
        ):
            for value in customer.get(key, []):
                require_reference(valid, value, f"customer {customer['id']}.{key}")

    for offer in data["offers"]:
        require_reference(customer_ids, offer.get("customerId"), f"offer {offer['id']}")
        require_reference(lead_ids, offer.get("leadId"), f"offer {offer['id']}")
        require_reference(contract_ids, offer.get("contractId"), f"offer {offer['id']}")

    for contract in data["contracts"]:
        require_reference(customer_ids, contract.get("customerId"), f"contract {contract['id']}")
        require_reference(offer_ids, contract.get("offerId"), f"contract {contract['id']}")
        require_reference(project_ids, contract.get("projectId"), f"contract {contract['id']}")

    for project in data["projects"]:
        require_reference(customer_ids, project.get("customerId"), f"project {project['id']}")
        require_reference(contract_ids, project.get("contractId"), f"project {project['id']}")
        for partner_id in project.get("partnerIds", []):
            require_reference(partner_ids, partner_id, f"project {project['id']}.partnerIds")

    for collection in ("financialItems", "careTickets", "documents", "tasks"):
        for record in data[collection]:
            require_reference(customer_ids, record.get("customerId"), f"{collection} {record['id']}")
            require_reference(project_ids, record.get("projectId"), f"{collection} {record['id']}")

    demo = next((customer for customer in data["customers"]
                 if customer["id"] == journey["customerId"]), None)
    if not demo:
        fail("demo journey customer is missing")
    required_customer_links = {
        "offerIds": offer_ids,
        "contractIds": contract_ids,
        "projectIds": project_ids,
        "financialItemIds": finance_ids,
        "careTicketIds": care_ids,
    }
    for key, valid in required_customer_links.items():
        values = demo.get(key, [])
        if not values or values[0] not in valid:
            fail(f"demo customer requires a valid {key} cross-module link")
    if not demo.get("profileStatus"):
        fail("demo customer requires a MyImperial profile")

    emails = []
    for collection in ("leads", "users"):
        emails.extend(record.get("email") for record in data[collection] if record.get("email"))
    if not emails or any(not email.endswith("@example.test") for email in emails):
        fail("all synthetic emails must use the @example.test domain")

    for marker in (
        'href="/assets/platform.css"',
        'src="/assets/platform.js"',
    ):
        if marker not in portal:
            fail(f"portal bootstrap marker missing: {marker}")

    for module in modules:
        if f'"{module["route"].rstrip("/")}"' not in script:
            fail(f"route missing from client router: {module['route']}")
    for marker in (
        "history.pushState",
        'addEventListener("popstate"',
        'id="module-nav"',
        'id="global-search"',
        'id="module-view"',
        'id="detail-drawer"',
        "data-nav-module",
        "data-entity-type",
        "/data/platform.json",
        "/data/system.json",
        'id="role-switcher"',
        "runtimeStorageKey",
        "HOUSE_PLAN_DRAFTED",
        "HOUSE_PLAN_APPROVED",
        "CAMPAIGN_BRIEF_APPROVED",
    ):
        if marker not in script:
            fail(f"platform client marker missing: {marker}")

    for marker in ("@media (max-width: 1180px)", "@media (max-width: 900px)",
                   "@media (max-width: 640px)", "--ii-navy", "--ii-gold"):
        if marker not in style:
            fail(f"responsive/design marker missing: {marker}")

    combined = script + style + json.dumps(data) + json.dumps(system)
    if "https://" in combined or "http://" in combined:
        fail("platform runtime must not contain external HTTP dependencies")

    print(
        "Imperial Intelligence validation passed: "
        f"{len(modules)} modules, {len(roles)} role workspaces, "
        f"{len(event_contracts)} event contracts, {len(steps)} journey steps, "
        f"{sum(len(data[name]) for name in MINIMUM_COUNTS)} core fixture records."
    )


if __name__ == "__main__":
    try:
        main()
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        fail(str(error))
