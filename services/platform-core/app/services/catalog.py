from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EventDefinition:
    code: str
    default_severity: str
    create_task: bool
    executive_relevance: bool
    task_title: str
    default_route_to: tuple[str, ...] = ()


EVENT_CATALOG: dict[str, EventDefinition] = {
    "CONTRACT_PACKAGE_GENERATED": EventDefinition("CONTRACT_PACKAGE_GENERATED", "info", True, False, "Szerződéscsomag jóváhagyása és aláírási előkészítése", ("crm", "myimperial")),
    "CONTRACT_SIGNED": EventDefinition("CONTRACT_SIGNED", "info", True, False, "Projektindítás előkészítése", ("project_control", "finance", "myimperial")),
    "PROJECT_CREATED": EventDefinition("PROJECT_CREATED", "info", False, False, "", ("calendar", "finance")),
    "SCHEDULE_APPROVED": EventDefinition("SCHEDULE_APPROVED", "info", True, False, "Ütemterv szinkronjának ellenőrzése", ("calendar", "finance", "procurement")),
    "CALENDAR_ENTRY_CREATED": EventDefinition("CALENDAR_ENTRY_CREATED", "info", False, False, "", ("project-control", "workflow-center")),
    "CALENDAR_ENTRY_RESCHEDULED": EventDefinition("CALENDAR_ENTRY_RESCHEDULED", "info", False, False, "", ("project-control", "workflow-center")),
    "CALENDAR_ENTRY_STATUS_CHANGED": EventDefinition("CALENDAR_ENTRY_STATUS_CHANGED", "info", False, False, "", ("project-control", "workflow-center")),
    "CALENDAR_ENTRY_COMPLETED": EventDefinition("CALENDAR_ENTRY_COMPLETED", "info", False, False, "", ("project-control", "workflow-center")),
    "BOOKING_FORM_COMPLETED": EventDefinition("BOOKING_FORM_COMPLETED", "info", True, False, "Külső naptár-visszaigazolás ellenőrzése", ("crm", "smart-calendar")),
    "BOOKING_CONFIRMED": EventDefinition("BOOKING_CONFIRMED", "info", True, False, "Konzultáció előkészítése", ("crm", "smart-calendar", "my-imperial")),
    "BOOKING_CALENDAR_SYNC_FAILED": EventDefinition("BOOKING_CALENDAR_SYNC_FAILED", "high", True, True, "Naptáradapter javítása és újraszinkronizálás", ("crm", "smart-calendar")),
    "BOOKING_CANCELLED": EventDefinition("BOOKING_CANCELLED", "info", False, False, "", ("crm", "smart-calendar", "my-imperial")),
    "BOOKING_RESCHEDULED": EventDefinition("BOOKING_RESCHEDULED", "info", True, False, "Átfoglalt időpont külső megerősítése", ("crm", "smart-calendar", "my-imperial")),
    "PAYMENT_STARTED": EventDefinition("PAYMENT_STARTED", "info", True, False, "Fizetési eredmény és ReservationID egyezésének ellenőrzése", ("crm", "financial-control")),
    "PAYMENT_FAILED": EventDefinition("PAYMENT_FAILED", "high", True, False, "Sikertelen lekötési fizetés kezelése", ("crm", "financial-control")),
    "RESERVATION_ACTIVATED": EventDefinition("RESERVATION_ACTIVATED", "info", True, True, "Telek-, finanszírozási és szerződéses ügyfélút indítása", ("crm", "financial-control", "contract-generator", "my-imperial", "plotcheck", "buildconfig")),
    "RESERVATION_CONVERTED": EventDefinition("RESERVATION_CONVERTED", "info", True, True, "MyImperial projektaktiválás és projektmenedzseri átadás", ("crm", "contract-generator", "my-imperial", "project-control")),
    "MILESTONE_DELAYED": EventDefinition("MILESTONE_DELAYED", "high", True, True, "Késés-helyreállítási terv készítése", ("finance", "myimperial")),
    "CUSTOMER_DECISION_OVERDUE": EventDefinition("CUSTOMER_DECISION_OVERDUE", "high", True, True, "Ügyféldöntés sürgős megszerzése", ("myimperial", "project_control")),
    "CHANGE_APPROVED": EventDefinition("CHANGE_APPROVED", "info", True, False, "Pótmunka átvezetése az ütemtervbe és pénzügybe", ("finance", "calendar", "procurement")),
    "CHANGE_CUSTOMER_ACCEPTED": EventDefinition("CHANGE_CUSTOMER_ACCEPTED", "info", True, False, "Munkakezdési engedély feltételeinek ellenőrzése", ("project_control", "finance", "calendar")),
    "CHANGE_WORK_AUTHORIZED": EventDefinition("CHANGE_WORK_AUTHORIZED", "info", True, False, "Jóváhagyott változtatás végrehajtásának ütemezése", ("project_control", "finance", "calendar", "procurement")),
    "CHANGE_COMPLETED": EventDefinition("CHANGE_COMPLETED", "info", True, False, "Pótmunka teljesítésének és számlázásának lezárása", ("finance", "myimperial")),
    "CHANGE_REJECTED": EventDefinition("CHANGE_REJECTED", "high", True, True, "Elutasított változtatás scope- és ütemtervi hatásának lezárása", ("project_control", "finance")),
    "CHANGE_STATUS_UPDATED": EventDefinition("CHANGE_STATUS_UPDATED", "info", False, False, "", ()),
    "PROCUREMENT_ORDERED": EventDefinition("PROCUREMENT_ORDERED", "info", False, False, "", ("finance", "calendar")),
    "DELIVERY_NOTE_MISSING": EventDefinition("DELIVERY_NOTE_MISSING", "critical", True, True, "Hiányzó szállítólevél pótlása és fizetési blokk fenntartása", ("finance",)),
    "QUANTITY_VARIANCE_DETECTED": EventDefinition("QUANTITY_VARIANCE_DETECTED", "high", True, True, "Tervmennyiségi eltérés kivizsgálása", ("project_control", "finance", "change_control")),
    "QUALITY_VARIANCE_DETECTED": EventDefinition("QUALITY_VARIANCE_DETECTED", "critical", True, True, "Minőségi eltérés műszaki kivizsgálása", ("project_control", "finance")),
    "PERFORMANCE_DECLARATION_MISSING": EventDefinition("PERFORMANCE_DECLARATION_MISSING", "critical", True, True, "Teljesítménynyilatkozat és e-napló bizonyíték pótlása", ("project_control", "finance")),
    "MATERIAL_OVERUSE_DETECTED": EventDefinition("MATERIAL_OVERUSE_DETECTED", "high", True, True, "Anyagtúlhasználat és levonási jogalap vizsgálata", ("finance", "project_control")),
    "INVOICE_READY": EventDefinition("INVOICE_READY", "info", False, False, "", ("finance",)),
    "PAYMENT_BLOCKED": EventDefinition("PAYMENT_BLOCKED", "high", True, True, "Fizetési blokk okának rendezése", ("finance", "project_control")),
    "PROJECT_MARGIN_AT_RISK": EventDefinition("PROJECT_MARGIN_AT_RISK", "critical", True, True, "Projektfedezet-helyreállítási döntés", ("finance", "project_control")),
    "WARRANTY_CASE_OPENED": EventDefinition("WARRANTY_CASE_OPENED", "high", True, True, "Garanciális ügy kivizsgálása és felelős kijelölése", ("imperial_care", "project_control")),
    "MODULE_HEALTH_FAILED": EventDefinition("MODULE_HEALTH_FAILED", "critical", True, True, "Modulhiba elhárítása", ()),
    "CONSISTENCY_ISSUE_DETECTED": EventDefinition("CONSISTENCY_ISSUE_DETECTED", "high", True, True, "Adatkonzisztencia-eltérés feloldása", ()),
    "RELEASE_READY_FOR_PRODUCTION": EventDefinition("RELEASE_READY_FOR_PRODUCTION", "info", True, True, "Production kiadási döntés", ()),
    "HOUSE_DESIGN_ORDER_REQUESTED": EventDefinition("HOUSE_DESIGN_ORDER_REQUESTED", "info", True, False, "House Designer megrendelési igény értékesítési ellenőrzése", ("crm", "sales", "smart-calendar")),
    "HOUSE_DESIGN_SUBMISSION_STATUS_CHANGED": EventDefinition("HOUSE_DESIGN_SUBMISSION_STATUS_CHANGED", "info", False, False, "", ("crm", "sales", "my-imperial")),
    "HOUSE_DESIGN_CHANGES_REQUESTED": EventDefinition("HOUSE_DESIGN_CHANGES_REQUESTED", "high", True, False, "House Designer tervcsomag hiányainak javítása", ("crm", "sales", "my-imperial")),
}


def get_event_definition(event_type: str) -> EventDefinition:
    return EVENT_CATALOG.get(
        event_type,
        EventDefinition(event_type, "info", False, False, "", ()),
    )
