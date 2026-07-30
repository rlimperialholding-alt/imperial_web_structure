(() => {
  const routeMap = {
    "/executive-dashboard": "executive-dashboard",
    "/my-imperial": "my-imperial",
    "/crm": "crm",
    "/sales": "sales",
    "/contract-generator": "contract-generator",
    "/project-control": "project-control",
    "/financial-control": "financial-control",
    "/imperial-care": "imperial-care",
    "/partner-control": "partner-control",
    "/marketing-control": "marketing-control",
    "/website-content-control": "website-content-control",
    "/document-center": "document-center",
    "/workflow-center": "workflow-center",
    "/admin": "admin",
    "/workspace": "workspace",
    "/control-center": "control-center",
    "/integration-control-room": "integration-control-room",
    "/completion-audit": "completion-audit",
    "/smart-calendar": "smart-calendar",
    "/change-control": "change-control",
    "/document-evidence": "document-evidence",
    "/procurement": "procurement",
    "/partner-connect": "partner-connect",
    "/partner-field": "partner-field",
    "/house-catalog": "house-catalog",
    "/housebuild-agent": "housebuild-agent",
    "/housematch": "housematch",
    "/plotcheck": "plotcheck",
    "/buildconfig": "buildconfig",
    "/plancheck": "plancheck",
    "/engineering-workspace": "engineering-workspace",
    "/housevision": "housevision",
    "/booking-engine": "booking-engine",
    "/reservation-engine": "reservation-engine",
    "/campaign-factory": "campaign-factory",
    "/content-factory": "content-factory",
    "/claim-registry": "claim-registry",
    "/answer-center": "answer-center",
    "/lead-intelligence": "lead-intelligence",
    "/digital-project-managers": "digital-project-managers",
    "/pm-cockpit": "pm-cockpit",
    "/operations-workspace": "operations-workspace",
    "/field-pwa": "field-pwa",
    "/finance-intelligence": "finance-intelligence",
    "/import-center": "import-center",
    "/tendermail": "tendermail",
    "/b2b-project-intake": "b2b-project-intake"
  };

  const normalizedPath = location.pathname.replace(/\/+$/, "") || "/";
  if (!routeMap[normalizedPath]) {
    return;
  }

  const state = {
    data: null,
    system: null,
    brands: [],
    moduleId: routeMap[normalizedPath],
    query: "",
    status: "all",
    selectedSite: "imperial",
    previewDevice: "desktop",
    drawerReturnFocus: null,
    currentRoleId: null,
    identity: null,
    runtime: null,
    backend: null,
    backendStatus: "connecting"
  };

  const runtimeStorageKey = "imperial-intelligence-runtime-v2";

  const typeConfig = {
    lead: { collection: "leads", moduleId: "crm", label: "Lead", title: "name" },
    customer: { collection: "customers", moduleId: "crm", label: "Ügyfél", title: "name" },
    offer: { collection: "offers", moduleId: "sales", label: "Ajánlat", title: "title" },
    contract: { collection: "contracts", moduleId: "contract-generator", label: "Szerződés", title: "template" },
    project: { collection: "projects", moduleId: "project-control", label: "Projekt", title: "name" },
    partner: { collection: "partners", moduleId: "partner-control", label: "Partner", title: "name" },
    financialItem: { collection: "financialItems", moduleId: "financial-control", label: "Pénzügyi tétel", title: "label" },
    careTicket: { collection: "careTickets", moduleId: "imperial-care", label: "Care ügy", title: "title" },
    milestone: { collection: "milestones", moduleId: "project-control", label: "Mérföldkő", title: "label" },
    document: { collection: "documents", moduleId: "document-center", label: "Dokumentum", title: "title" },
    task: { collection: "tasks", moduleId: "workflow-center", label: "Feladat", title: "title" },
    campaign: { collection: "campaigns", moduleId: "marketing-control", label: "Kampány", title: "name" },
    workflow: { collection: "workflows", moduleId: "workflow-center", label: "Workflow", title: "name" },
    user: { collection: "users", moduleId: "admin", label: "Felhasználó", title: "name" },
    auditEvent: { collection: "auditEvents", moduleId: "admin", label: "Audit esemény", title: "action" }
  };

  const moduleSources = {
    "executive-dashboard": ["project"],
    "my-imperial": ["customer"],
    crm: ["customer", "lead"],
    sales: ["offer"],
    "contract-generator": ["contract"],
    "project-control": ["project", "milestone"],
    "financial-control": ["financialItem"],
    "imperial-care": ["careTicket"],
    "partner-control": ["partner"],
    "marketing-control": ["campaign"],
    "document-center": ["document"],
    "workflow-center": ["workflow", "task"],
    admin: ["user", "auditEvent"]
  };

  const icons = {
    "executive-dashboard": "ED",
    "my-imperial": "MI",
    crm: "CR",
    sales: "SA",
    "contract-generator": "CG",
    "project-control": "PC",
    "financial-control": "FC",
    "imperial-care": "IC",
    "partner-control": "PA",
    "marketing-control": "MC",
    "website-content-control": "WC",
    "document-center": "DC",
    "workflow-center": "WF",
    admin: "AD",
    workspace: "WS",
    "control-center": "CC",
    "integration-control-room": "IR",
    "completion-audit": "CA",
    "smart-calendar": "SC",
    "change-control": "CH",
    "document-evidence": "DE",
    procurement: "PR",
    "partner-connect": "PN",
    "partner-field": "PF",
    "house-catalog": "HC",
    "housebuild-agent": "HB",
    housematch: "HM",
    plotcheck: "PK",
    buildconfig: "BC",
    plancheck: "PL",
    "engineering-workspace": "EW",
    housevision: "HV",
    "booking-engine": "BK",
    "reservation-engine": "RS",
    "campaign-factory": "CF",
    "content-factory": "CT",
    "claim-registry": "CL",
    "answer-center": "AC",
    "lead-intelligence": "LI",
    "digital-project-managers": "DP"
  };

  const moduleGroups = [
    { id: "overview", label: "Áttekintés", modules: ["workspace", "executive-dashboard", "control-center", "integration-control-room"] },
    { id: "commercial", label: "Ügyfél és értékesítés", modules: ["crm", "sales", "contract-generator", "booking-engine", "reservation-engine", "my-imperial"] },
    { id: "house", label: "Típusház és műszaki", modules: ["house-catalog", "housebuild-agent", "housematch", "plotcheck", "buildconfig", "plancheck", "engineering-workspace", "housevision"] },
    { id: "delivery", label: "Projekt és teljesítés", modules: ["project-control", "digital-project-managers", "pm-cockpit", "operations-workspace", "smart-calendar", "change-control", "document-center", "document-evidence", "import-center", "tendermail", "procurement", "partner-connect", "partner-control", "partner-field", "field-pwa", "financial-control", "finance-intelligence", "imperial-care"] },
    { id: "marketing", label: "Marketing és web", modules: ["marketing-control", "campaign-factory", "content-factory", "claim-registry", "website-content-control", "answer-center", "lead-intelligence", "b2b-project-intake"] },
    { id: "governance", label: "Irányítás", modules: ["workflow-center", "completion-audit", "admin"] }
  ];

  const statusLabels = {
    active: "Aktív",
    qualified: "Minősített",
    new: "Új",
    contacted: "Kapcsolatban",
    nurturing: "Gondozás",
    won: "Megnyert",
    lost: "Elvesztett",
    draft: "Vázlat",
    sent: "Kiküldve",
    accepted: "Elfogadva",
    expired: "Lejárt",
    review: "Ellenőrzés",
    construction: "Kivitelezés",
    handover: "Átadás",
    warranty: "Garancia",
    completed: "Lezárt",
    planned: "Tervezett",
    open: "Nyitott",
    pending: "Függőben",
    paid: "Fizetve",
    overdue: "Lejárt",
    approved: "Jóváhagyva",
    invited: "Meghívva",
    negotiation: "Tárgyalás",
    archived: "Archivált",
    suspended: "Felfüggesztve",
    low: "Alacsony",
    medium: "Közepes",
    high: "Magas",
    urgent: "Sürgős",
    integration_pending: "Integrációra vár",
    artifact_verified: "Artifact igazolt",
    prototype: "Prototípus",
    simulated: "Szimulált",
    auth_required: "Hitelesítés kell",
    sandbox: "Sandbox",
    verification_required: "Ellenőrizendő",
    verified: "Igazolt",
    scheduled: "Ütemezett",
    delayed: "Késésben",
    customer_approval: "Ügyfél-jóváhagyás",
    technical_review: "Műszaki review",
    financial_review: "Pénzügyi review",
    evidence_submitted: "Bizonyíték beküldve",
    evaluation: "Értékelés",
    clarification: "Hiánypótlás",
    shortlisted: "Shortlist",
    engineer_review: "Mérnöki review",
    stop: "STOP",
    human_approval: "Emberi jóváhagyás",
    ready_for_review: "Review-ra kész",
    blocked: "Blokkolt",
    qa_review: "QA review",
    rights_blocked: "Jog miatt blokkolt",
    confirmed: "Visszaigazolva",
    slot_reserved: "Idősáv foglalva",
    terms_review: "Feltételek ellenőrzése",
    intent_recorded: "Szándék rögzítve",
    source_review: "Forrásellenőrzés",
    editorial_review: "Szerkesztői review",
    source_ready: "Forrás kész",
    deduplication: "Deduplikáció",
    plancheck_review: "PlanCheck review",
    ready: "Kész",
    brief_quality_gate: "Brief minőségi kapu",
    approved_for_production: "Gyártásra jóváhagyva",
    export_ready: "Export kész",
    warning: "Figyelmeztetés",
    pass: "PASS",
    attention: "Figyelmet kér",
    queued: "Sorban áll",
    retry: "Újrapróbálás",
    not_relevant: "Nem releváns"
  };

  const tableColumns = {
    lead: [
      ["id", "Azonosító"], ["name", "Lead"], ["source", "Forrás"], ["interest", "Érdeklődés"],
      ["location", "Helyszín"], ["value", "Érték"], ["status", "Státusz"], ["owner", "Felelős"]
    ],
    offer: [
      ["id", "Ajánlat"], ["title", "Megnevezés"], ["customerId", "Ügyfél"], ["version", "Verzió"],
      ["amount", "Összeg"], ["validUntil", "Érvényes"], ["status", "Státusz"], ["owner", "Felelős"]
    ],
    contract: [
      ["id", "Szerződés"], ["template", "Sablon"], ["customerId", "Ügyfél"], ["projectId", "Projekt"],
      ["amount", "Összeg"], ["signedAt", "Aláírás"], ["status", "Státusz"], ["nextAction", "Következő lépés"]
    ],
    financialItem: [
      ["id", "Tétel"], ["type", "Típus"], ["label", "Megnevezés"], ["projectId", "Projekt"],
      ["amount", "Összeg"], ["dueDate", "Határidő"], ["status", "Státusz"]
    ],
    careTicket: [
      ["id", "Hibajegy"], ["title", "Tárgy"], ["projectId", "Projekt"], ["category", "Kategória"],
      ["priority", "Prioritás"], ["sla", "SLA"], ["status", "Státusz"], ["owner", "Felelős"]
    ],
    document: [
      ["id", "Dokumentum"], ["title", "Megnevezés"], ["category", "Kategória"], ["projectId", "Projekt"],
      ["version", "Verzió"], ["updatedAt", "Frissítve"], ["status", "Státusz"]
    ],
    task: [
      ["id", "Feladat"], ["title", "Megnevezés"], ["moduleId", "Modul"], ["assignee", "Felelős"],
      ["dueDate", "Határidő"], ["priority", "Prioritás"], ["status", "Státusz"]
    ],
    auditEvent: [
      ["id", "Esemény"], ["actor", "Szereplő"], ["action", "Művelet"], ["target", "Cél"], ["time", "Időpont"]
    ],
    milestone: [
      ["id", "Mérföldkő"], ["label", "Megnevezés"], ["projectId", "Projekt"], ["date", "Dátum"], ["status", "Státusz"]
    ],
    campaign: [
      ["id", "Kampány"], ["name", "Megnevezés"], ["channel", "Csatorna"], ["budget", "Keret"],
      ["leads", "Lead"], ["qualified", "Minősített"], ["status", "Státusz"], ["owner", "Felelős"]
    ]
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatMoney(value) {
    return new Intl.NumberFormat("hu-HU", {
      style: "currency",
      currency: "HUF",
      maximumFractionDigits: 0
    }).format(Number(value || 0));
  }

  function displayValue(key, value) {
    if (value === null || value === undefined || value === "") return "—";
    if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
    if (typeof value === "boolean") return value ? "Igen" : "Nem";
    if (["amount", "budget", "spent", "value"].includes(key)) return formatMoney(value);
    if (["status", "priority", "risk"].includes(key)) return statusLabels[value] || value;
    return String(value);
  }

  function toneFor(value) {
    if (["active", "qualified", "won", "accepted", "construction", "paid", "approved", "completed", "low",
      "verified", "artifact_verified", "simulated", "sandbox", "pass", "ready", "confirmed",
      "approved_for_production", "export_ready", "intent_recorded", "source_ready"].includes(value)) return "green";
    if (["lost", "expired", "overdue", "suspended", "urgent", "high", "stop", "blocked",
      "rights_blocked", "auth_required"].includes(value)) return "red";
    return "amber";
  }

  function badge(value) {
    return `<span class="ii-badge" data-tone="${toneFor(value)}">${escapeHtml(statusLabels[value] || value || "—")}</span>`;
  }

  function loadRuntime() {
    const defaults = {
      events: [
        { id: "EVT-LOCAL-001", eventKey: "CONTRACT_SIGNED", producer: "contract-generator", status: "delivered", correlationId: "CORR-DEMO-001", at: "2026-07-24T07:30:00Z" },
        { id: "EVT-LOCAL-002", eventKey: "CONNECTOR_DEGRADED", producer: "integration-control-room", status: "attention", correlationId: "CORR-DEMO-002", at: "2026-07-24T08:00:00Z" }
      ],
      outbox: [
        { id: "OUT-001", eventKey: "PLOTCHECK_COMPLETED", status: "queued", attempts: 0, target: "engineering-workspace" },
        { id: "OUT-002", eventKey: "CLAIM_EXPIRING", status: "retry", attempts: 2, target: "content-factory" }
      ],
      houseBuildJobs: [],
      campaignBriefs: []
    };
    try {
      const stored = JSON.parse(localStorage.getItem(runtimeStorageKey) || "null");
      return stored && typeof stored === "object" ? { ...defaults, ...stored } : defaults;
    } catch {
      return defaults;
    }
  }

  function saveRuntime() {
    localStorage.setItem(runtimeStorageKey, JSON.stringify(state.runtime));
  }

  function currentRole() {
    return state.system.roles.find((role) => role.id === state.currentRoleId) || state.system.roles.at(-1);
  }

  function emitLocalEvent(eventKey, producer, target, payload = {}) {
    const stamp = new Date().toISOString();
    const serial = String(state.runtime.events.length + 1).padStart(3, "0");
    const event = {
      id: `EVT-LOCAL-${serial}`,
      eventKey,
      producer,
      status: "delivered",
      correlationId: `CORR-LOCAL-${Date.now()}`,
      target,
      payload,
      at: stamp
    };
    state.runtime.events.unshift(event);
    state.runtime.outbox.unshift({
      id: `OUT-LOCAL-${serial}`,
      eventKey,
      status: "delivered",
      attempts: 1,
      target
    });
    saveRuntime();
    return event;
  }

  function moduleById(id) {
    return state.data.modules.find((module) => module.id === id);
  }

  function moduleTitle(module) {
    return module?.name || module?.label || module?.id || "Modul";
  }

  function entityById(type, id) {
    const config = typeConfig[type];
    return config ? state.data[config.collection].find((item) => item.id === id) : null;
  }

  function customerName(id) {
    return state.data.customers.find((customer) => customer.id === id)?.name || id || "—";
  }

  function projectName(id) {
    return state.data.projects.find((project) => project.id === id)?.name || id || "—";
  }

  function recordLabel(type, record) {
    const config = typeConfig[type];
    return record?.[config.title] || record?.id || config.label;
  }

  function recordsForModule(moduleId) {
    if (moduleId === "website-content-control") {
      return state.brands.map((brand) => ({ ...brand, __type: "brand" }));
    }
    if (state.system?.moduleRecords?.[moduleId]) {
      return state.system.moduleRecords[moduleId].map((record) => ({ ...record, __type: "systemRecord", __moduleId: moduleId }));
    }
    if (moduleId === "housebuild-agent") {
      return [...new Map([...state.system.houseBuild.jobs, ...state.runtime.houseBuildJobs].map((record) => [record.id, record])).values()]
        .map((record) => ({ ...record, __type: "systemRecord", __moduleId: moduleId }));
    }
    if (moduleId === "campaign-factory") {
      return [...new Map([...state.system.campaignFactory.briefs, ...state.runtime.campaignBriefs].map((record) => [record.id, record])).values()]
        .map((record) => ({ ...record, __type: "systemRecord", __moduleId: moduleId }));
    }
    if (moduleId === "workspace") {
      return state.data.tasks.map((record) => ({ ...record, __type: "task" }));
    }
    return (moduleSources[moduleId] || []).flatMap((type) =>
      state.data[typeConfig[type].collection].map((record) => ({ ...record, __type: type }))
    );
  }

  function recordStatus(record) {
    return record.status || record.profileStatus || record.priority || "n/a";
  }

  function filteredRecords(moduleId) {
    const query = state.query.trim().toLocaleLowerCase("hu-HU");
    return recordsForModule(moduleId).filter((record) => {
      const statusMatch = state.status === "all" || recordStatus(record) === state.status;
      const textMatch = !query || JSON.stringify(record).toLocaleLowerCase("hu-HU").includes(query);
      return statusMatch && textMatch;
    });
  }

  function countForModule(moduleId) {
    if (moduleId === "executive-dashboard") return state.data.projects.length;
    if (moduleId === "website-content-control") return state.brands.length;
    if (moduleId === "integration-control-room") {
      return recordsForModule(moduleId).length + state.runtime.outbox.length;
    }
    return recordsForModule(moduleId).length;
  }

  function platformMarkup() {
    return `
      <a class="ii-skip-link" href="#module-view">Ugrás a modul tartalmához</a>
      <div class="ii-app">
        <aside class="ii-sidebar" id="platform-sidebar" aria-label="Imperial Intelligence modulok">
          <a class="ii-brand" href="/workspace/" data-nav-module="workspace">
            <span class="ii-brand-mark" aria-hidden="true">II</span>
            <span><strong>Imperial</strong><small>Intelligence</small></span>
          </a>
          <p class="ii-nav-label">Tesztplatform</p>
          <nav class="ii-nav" id="module-nav"></nav>
          <section class="ii-env-card">
            <strong>Lokális staging</strong>
            <small>Szintetikus adatok · nincs külső API · nincs production secret</small>
          </section>
        </aside>
        <button class="ii-sidebar-overlay" id="sidebar-overlay" aria-label="Navigáció bezárása"></button>
        <main class="ii-main">
          <header class="ii-topbar">
            <button class="ii-menu-button" id="menu-button" type="button" aria-label="Navigáció megnyitása">☰</button>
            <div class="ii-breadcrumb">Imperial Intelligence<strong id="breadcrumb-module"></strong></div>
            <label class="ii-search">
              <span class="ii-skip-link">Keresés az aktuális modulban</span>
              <input id="global-search" type="search" placeholder="Keresés az aktuális modulban…" autocomplete="off">
            </label>
            <div class="ii-user">
              <span><strong>${escapeHtml(state.identity.user.name)}</strong><small>${escapeHtml(currentRole().label)}</small></span>
              <span class="ii-user-avatar" id="role-avatar" aria-hidden="true">${escapeHtml(currentRole().initials)}</span>
              <form method="post" action="/logout"><button class="ii-button is-secondary is-small" type="submit">Kilépés</button></form>
            </div>
          </header>
          <div class="ii-content">
            <header class="ii-hero">
              <div>
                <p class="ii-kicker" id="module-id-label"></p>
                <h1 id="module-heading"></h1>
                <p id="module-description"></p>
              </div>
              <button class="ii-button is-secondary" id="journey-button" type="button">Teljes ügyfélút</button>
            </header>
            <section class="ii-panel ii-journey" id="journey-panel" aria-labelledby="journey-heading">
              <div class="ii-journey-head">
                <div><h2 id="journey-heading"></h2><p id="journey-description"></p></div>
                <span class="ii-badge" data-tone="green">Végigkövethető</span>
              </div>
              <div class="ii-journey-track" id="journey-track"></div>
            </section>
            <section class="ii-toolbar" id="module-controls" aria-label="Modul szűrők">
              <input id="module-search" type="search" placeholder="Keresés név, azonosító vagy tartalom alapján…">
              <select id="module-filter" aria-label="Státusz szerinti szűrés"></select>
              <button class="ii-button is-secondary" id="clear-filters" type="button">Szűrők törlése</button>
            </section>
            <section id="module-view" data-module-id="${escapeHtml(state.moduleId)}" aria-live="polite"></section>
          </div>
        </main>
      </div>
      <button class="ii-detail-overlay" id="detail-overlay" aria-label="Részletek bezárása"></button>
      <aside class="ii-detail-drawer" id="detail-drawer" aria-labelledby="detail-title" aria-hidden="true">
        <div id="detail-content"></div>
      </aside>
      <div class="ii-toast" id="platform-toast" role="status"></div>
    `;
  }

  function renderNav() {
    const nav = document.querySelector("#module-nav");
    const access = new Set(currentRole().moduleAccess);
    nav.innerHTML = moduleGroups.map((group) => {
      const modules = group.modules
        .map(moduleById)
        .filter(Boolean)
        .filter((module) => access.has(module.id));
      if (!modules.length) return "";
      return `
        <section class="ii-nav-group" aria-labelledby="nav-group-${escapeHtml(group.id)}">
          <p class="ii-nav-group-label" id="nav-group-${escapeHtml(group.id)}">${escapeHtml(group.label)}</p>
          ${modules.map((module) => `
            <a class="ii-nav-link ${module.id === state.moduleId ? "is-active" : ""}"
               href="${escapeHtml(module.route)}"
               data-nav-module="${escapeHtml(module.id)}"
               ${module.id === state.moduleId ? 'aria-current="page"' : ""}>
              <span class="ii-nav-icon" aria-hidden="true">${icons[module.id] || "II"}</span>
              <span>${escapeHtml(moduleTitle(module))}</span>
              <span class="ii-nav-count">${countForModule(module.id)}</span>
            </a>
          `).join("")}
        </section>
      `;
    }).join("");
  }

  function renderJourney() {
    document.querySelector("#journey-heading").textContent = state.data.journey.title;
    document.querySelector("#journey-description").textContent = state.data.journey.description;
    document.querySelector("#journey-track").innerHTML = state.data.journey.steps.map((step, index) => `
      <button class="ii-journey-step" type="button"
              data-nav-module="${escapeHtml(step.moduleId)}"
              data-focus-type="${escapeHtml(step.entityType)}"
              data-focus-id="${escapeHtml(step.entityId)}">
        <small>${String(index + 1).padStart(2, "0")} · ${escapeHtml(step.entityId)}</small>
        <strong>${escapeHtml(step.label)}</strong>
      </button>
    `).join("");
  }

  function renderFilterOptions() {
    const statuses = [...new Set(recordsForModule(state.moduleId).map(recordStatus))].filter(Boolean).sort();
    const select = document.querySelector("#module-filter");
    select.innerHTML = `<option value="all">Minden státusz</option>${statuses.map((status) =>
      `<option value="${escapeHtml(status)}">${escapeHtml(statusLabels[status] || status)}</option>`
    ).join("")}`;
    select.value = statuses.includes(state.status) ? state.status : "all";
    state.status = select.value;
  }

  function renderTable(records, type, columns = tableColumns[type]) {
    if (!records.length) return `<div class="ii-panel ii-empty">Nincs a szűrésnek megfelelő tesztadat.</div>`;
    return `
      <div class="ii-panel ii-table-wrap">
        <table class="ii-table">
          <thead><tr>${columns.map(([, label]) => `<th scope="col">${escapeHtml(label)}</th>`).join("")}</tr></thead>
          <tbody>${records.map((record) => `
            <tr tabindex="0" data-entity-type="${type}" data-entity-id="${escapeHtml(record.id)}">
              ${columns.map(([key]) => {
                let value = record[key];
                if (key === "customerId") value = customerName(value);
                if (key === "projectId") value = projectName(value);
                if (["status", "priority", "risk"].includes(key)) return `<td>${badge(value)}</td>`;
                return `<td>${escapeHtml(displayValue(key, value))}</td>`;
              }).join("")}
            </tr>
          `).join("")}</tbody>
        </table>
      </div>
    `;
  }

  function entityButton(type, id, label = "Részletek") {
    return `<button class="ii-button is-secondary is-small" type="button"
      data-entity-type="${escapeHtml(type)}" data-entity-id="${escapeHtml(id)}">${escapeHtml(label)}</button>`;
  }

  function renderCustomerCards(customers) {
    if (!customers.length) return `<div class="ii-panel ii-empty">Nincs a szűrésnek megfelelő ügyfél.</div>`;
    return `<div class="ii-grid">${customers.map((customer) => `
      <article class="ii-panel ii-record-card">
        <header><span class="ii-id">${escapeHtml(customer.id)}</span>${badge(customer.status)}</header>
        <h3>${escapeHtml(customer.name)}</h3>
        <p>${escapeHtml(customer.segment)} · MyImperial: ${escapeHtml(customer.profileStatus)}</p>
        <p>${customer.offerIds.length} ajánlat · ${customer.projectIds.length} projekt · ${customer.careTicketIds.length} Care ügy</p>
        <footer>
          ${entityButton("customer", customer.id, "Ügyfélkép")}
          <a class="ii-button is-small" href="/my-imperial/?focus=customer:${encodeURIComponent(customer.id)}"
             data-nav-module="my-imperial" data-focus-type="customer" data-focus-id="${escapeHtml(customer.id)}">MyImperial</a>
        </footer>
      </article>
    `).join("")}</div>`;
  }

  function renderProjectCards(projects) {
    if (!projects.length) return `<div class="ii-panel ii-empty">Nincs a szűrésnek megfelelő projekt.</div>`;
    return `<div class="ii-grid">${projects.map((project) => `
      <article class="ii-panel ii-record-card">
        <header><span class="ii-id">${escapeHtml(project.id)}</span>${badge(project.status)}</header>
        <h3>${escapeHtml(project.name)}</h3>
        <p>${escapeHtml(project.location)} · ${escapeHtml(project.technology)}</p>
        <div class="ii-progress" aria-label="${project.progress}% készültség"><span style="width:${Number(project.progress)}%"></span></div>
        <p>${project.progress}% · következő: ${escapeHtml(project.nextMilestone)}</p>
        <footer><span>${formatMoney(project.spent)} / ${formatMoney(project.budget)}</span>${entityButton("project", project.id)}</footer>
      </article>
    `).join("")}</div>`;
  }

  function renderPartnerCards(partners) {
    if (!partners.length) return `<div class="ii-panel ii-empty">Nincs a szűrésnek megfelelő partner.</div>`;
    return `<div class="ii-grid">${partners.map((partner) => `
      <article class="ii-panel ii-record-card">
        <header><span class="ii-id">${escapeHtml(partner.id)}</span>${badge(partner.status)}</header>
        <h3>${escapeHtml(partner.name)}</h3>
        <p>${escapeHtml(partner.category)} · értékelés: ${escapeHtml(partner.rating)}/5</p>
        <p>Kapacitás: ${escapeHtml(partner.capacity)} · ${partner.projectIds.length} kapcsolt projekt</p>
        <footer>${entityButton("partner", partner.id)}</footer>
      </article>
    `).join("")}</div>`;
  }

  function renderWorkflowCards(workflows) {
    if (!workflows.length) return "";
    return `<div class="ii-grid is-two">${workflows.map((workflow) => `
      <article class="ii-panel ii-record-card">
        <header><span class="ii-id">${escapeHtml(workflow.id)}</span>${badge(workflow.status)}</header>
        <h3>${escapeHtml(workflow.name)}</h3>
        <p>${escapeHtml(workflow.moduleIds.map((id) => moduleTitle(moduleById(id))).join(" → "))}</p>
        <p>${workflow.instances} futó példány · SLA: ${escapeHtml(workflow.sla)}</p>
        <footer>${entityButton("workflow", workflow.id)}</footer>
      </article>
    `).join("")}</div>`;
  }

  function renderUserCards(users) {
    if (!users.length) return "";
    return `<div class="ii-grid">${users.map((user) => `
      <article class="ii-panel ii-record-card">
        <header><span class="ii-id">${escapeHtml(user.id)}</span>${badge(user.status)}</header>
        <h3>${escapeHtml(user.name)}</h3>
        <p>${escapeHtml(user.role)} · ${user.moduleAccess.length} moduljogosultság</p>
        <p>${escapeHtml(user.email)}</p>
        <footer>${entityButton("user", user.id, "Jogosultságok")}</footer>
      </article>
    `).join("")}</div>`;
  }

  function renderDashboard(projects) {
    const revenue = state.data.financialItems
      .filter((item) => item.amount > 0 && item.status === "paid")
      .reduce((sum, item) => sum + item.amount, 0);
    const openCare = state.data.careTickets.filter((ticket) => !["completed", "closed"].includes(ticket.status)).length;
    const activeTasks = state.data.tasks.filter((task) => ["active", "planned", "review"].includes(task.status)).length;
    return `
      <div class="ii-kpi-grid">
        <article class="ii-panel ii-kpi"><span>Aktív projektek</span><strong>${projects.filter((p) => p.active).length}</strong><small>a szűrésnek megfelelő projekt</small></article>
        <article class="ii-panel ii-kpi"><span>Megnyert érték</span><strong>${formatMoney(revenue)}</strong><small>fizetett teszttételek alapján</small></article>
        <article class="ii-panel ii-kpi"><span>Nyitott Care ügy</span><strong>${openCare}</strong><small>6 összes hibajegyből</small></article>
        <article class="ii-panel ii-kpi"><span>Aktív feladat</span><strong>${activeTasks}</strong><small>modulokon átívelő teendő</small></article>
      </div>
      <div class="ii-section-head"><h2>Projektportfólió</h2><a class="ii-button is-secondary is-small" href="/project-control/" data-nav-module="project-control">Projekt Control</a></div>
      ${renderProjectCards(projects)}
    `;
  }

  function renderCrm(records) {
    const customers = records.filter((record) => record.__type === "customer");
    const leads = records.filter((record) => record.__type === "lead");
    return `
      <div class="ii-section-head"><h2>Ügyfélkapcsolatok</h2><span class="ii-badge">${customers.length} ügyfél</span></div>
      ${renderCustomerCards(customers)}
      <div class="ii-section-head" style="margin-top:1.2rem"><h2>Lead pipeline</h2><span class="ii-badge">${leads.length} lead</span></div>
      ${renderTable(leads, "lead")}
    `;
  }

  function renderWebsiteModule() {
    const query = state.query.trim().toLocaleLowerCase("hu-HU");
    const brands = state.brands.filter((brand) => {
      const statusMatch = state.status === "all" || brand.status === state.status;
      const textMatch = !query || JSON.stringify(brand).toLocaleLowerCase("hu-HU").includes(query);
      return statusMatch && textMatch;
    });
    if (!brands.some((brand) => brand.id === state.selectedSite)) state.selectedSite = brands[0]?.id || "imperial";
    const selected = state.brands.find((brand) => brand.id === state.selectedSite) || state.brands[0];
    if (!selected) return `<div class="ii-panel ii-empty">A márkakatalógus nem tölthető be.</div>`;
    const widths = { desktop: "100%", tablet: "834px", mobile: "390px" };
    return `
      <div class="ii-panel ii-website-preview">
        <div class="ii-site-list" aria-label="Imperial weboldalak">
          ${brands.map((brand) => `<button class="ii-site-button ${brand.id === selected.id ? "is-active" : ""}" type="button" data-site="${escapeHtml(brand.id)}">
            <span><strong>${escapeHtml(brand.shortName || brand.name)}</strong><small style="display:block;color:var(--ii-muted)">${escapeHtml(brand.statusLabel)}</small></span>
            <span class="ii-id">${escapeHtml(brand.initials)}</span>
          </button>`).join("")}
        </div>
        <div class="ii-preview-area">
          <div class="ii-preview-toolbar">
            <div><strong>${escapeHtml(selected.name)}</strong><small style="display:block;color:var(--ii-muted)">Same-origin staging előnézet</small></div>
            <div>
              ${["desktop", "tablet", "mobile"].map((device) => `<button class="ii-button is-small ${device === state.previewDevice ? "" : "is-secondary"}" type="button" data-preview-device="${device}">${device}</button>`).join("")}
            </div>
          </div>
          <div style="overflow:auto;text-align:center">
            <iframe class="ii-preview-frame" title="${escapeHtml(selected.name)} előnézet" src="/site-preview/${encodeURIComponent(selected.id)}/" style="max-width:${widths[state.previewDevice]}"></iframe>
          </div>
        </div>
      </div>
    `;
  }

  function recordTitle(record) {
    return record.name || record.title || record.label || record.eventKey || record.id;
  }

  function renderRecordFields(record, excluded = []) {
    const hidden = new Set(["id", "name", "title", "label", "status", "__type", "__moduleId", ...excluded]);
    return Object.entries(record)
      .filter(([key]) => !hidden.has(key))
      .map(([key, value]) => {
        const rendered = typeof value === "object" && value !== null
          ? Object.entries(value).map(([childKey, childValue]) => `${childKey}: ${displayValue(childKey, childValue)}`).join(" · ")
          : displayValue(key, value);
        return `<div class="ii-record-field"><span>${escapeHtml(key)}</span><strong>${escapeHtml(rendered)}</strong></div>`;
      }).join("");
  }

  function renderSystemRecords(records, title = "Tesztadatok") {
    if (!records.length) return `<div class="ii-panel ii-empty">Nincs a szűrésnek megfelelő tesztadat.</div>`;
    return `
      <div class="ii-section-head"><h2>${escapeHtml(title)}</h2><span class="ii-badge">${records.length} rekord</span></div>
      <div class="ii-grid is-two">${records.map((record) => `
        <article class="ii-panel ii-record-card">
          <header><span class="ii-id">${escapeHtml(record.id)}</span>${badge(recordStatus(record))}</header>
          <h3>${escapeHtml(recordTitle(record))}</h3>
          <div class="ii-record-fields">${renderRecordFields(record)}</div>
        </article>
      `).join("")}</div>
    `;
  }

  function backendModule(moduleId) {
    return state.backend?.modules?.find((module) => module.id === moduleId) || null;
  }

  function renderBackendModule(moduleId) {
    if (!state.backend) {
      return `
        <section class="ii-panel ii-live-module is-degraded">
          <header><div><p class="ii-kicker">Közös platform runtime</p><h2>A backend kapcsolat nem érhető el</h2></div>${badge("attention")}</header>
          <p>A statikus mintaadatok böngészhetők, de a modulműveletekhez indítsd el a teljes Docker Compose stacket.</p>
        </section>
      `;
    }
    const live = backendModule(moduleId);
    if (!live) {
      return `
        <section class="ii-panel ii-live-module is-degraded">
          <header><div><p class="ii-kicker">Közös platform runtime</p><h2>Nincs backend-regisztráció</h2></div>${badge("blocked")}</header>
          <p>A modul a portálon szerepel, de a közös demo runtime-ban még nincs regisztrálva.</p>
        </section>
      `;
    }
    const events = (state.backend.events || [])
      .filter((event) => event.producer === moduleId || event.consumers?.includes(moduleId))
      .slice(0, 4);
    return `
      <section class="ii-panel ii-live-module" data-live-module="${escapeHtml(moduleId)}">
        <header>
          <div>
            <p class="ii-kicker">Működő moduladapter · ${escapeHtml(live.sourceRelease)}</p>
            <h2>Interaktív sandbox teszt</h2>
          </div>
          ${badge(live.status)}
        </header>
        <div class="ii-live-meta">
          <span><strong>Felhasználó</strong> ${escapeHtml(state.identity.user.email)}</span>
          <span><strong>Adat</strong> kizárólag szintetikus</span>
          <span><strong>Külső írás</strong> tiltva</span>
        </div>
        ${renderSystemRecords((live.records || []).map((record) => ({ ...record, __type: "systemRecord" })), "Backend demo rekord")}
        <form class="ii-live-actions ii-panel" data-module-operation-form="${escapeHtml(moduleId)}">
          <label>ProjectID
            <input name="project_id" value="PRJ-DEMO-001" minlength="3" maxlength="80" required>
          </label>
          <label>Megjegyzés / ellenőrzési cél
            <textarea name="notes" rows="2" maxlength="1000" placeholder="A folyamat indításának oka vagy az ellenőrzés szempontja"></textarea>
          </label>
          <div>
          ${(live.actions || []).map((action) => `
            <button class="ii-button is-small" type="button"
              data-backend-action="${escapeHtml(action.id)}"
              data-backend-module="${escapeHtml(moduleId)}">
              ${escapeHtml(action.label)}
            </button>
          `).join("")}
          </div>
        </form>
        <div class="ii-section-head"><h3>Legutóbbi producer–consumer események</h3><span class="ii-badge">${events.length}</span></div>
        <div class="ii-runtime-list">
          ${events.map((event) => `
            <div class="ii-runtime-row">
              <span class="ii-id">${escapeHtml(event.id)}</span>
              <strong>${escapeHtml(event.eventKey)}</strong>
              <span>${escapeHtml(event.producer)} → ${escapeHtml(event.consumers.join(", "))}</span>
              ${badge(event.status)}
            </div>
          `).join("") || `<p class="ii-empty">Még nincs esemény. Futtasd a fenti műveletet vagy egy teljes tesztutat.</p>`}
        </div>
      </section>
    `;
  }

  function renderBackendJourneys() {
    if (!state.backend?.journeys?.length) return "";
    const canReset = state.currentRoleId === "platform-admin";
    return `
      <div class="ii-section-head"><h2>Keresztmodul E2E tesztutak</h2>${canReset ? '<button class="ii-button is-secondary is-small" type="button" data-backend-reset>Demo visszaállítása</button>' : ""}</div>
      <div class="ii-grid is-two">
        ${state.backend.journeys.map((journey) => {
          const completed = journey.steps.filter((step) => step.status === "completed").length;
          return `
            <article class="ii-panel ii-journey-test">
              <header><span class="ii-id">${escapeHtml(journey.id)}</span>${badge(journey.status)}</header>
              <h3>${escapeHtml(journey.name)}</h3>
              <p>${completed}/${journey.steps.length} lépés · ${escapeHtml(journey.projectId)}</p>
              <ol>${journey.steps.map((step) => `<li data-state="${escapeHtml(step.status)}"><span>${escapeHtml(step.moduleId)}</span><strong>${escapeHtml(step.label)}</strong></li>`).join("")}</ol>
              <button class="ii-button" type="button" data-backend-journey="${escapeHtml(journey.id)}">Teljes tesztút futtatása</button>
            </article>
          `;
        }).join("")}
      </div>
    `;
  }

  function renderWorkspace() {
    const role = currentRole();
    const access = role.moduleAccess.map(moduleById).filter(Boolean);
    const tasks = filteredRecords("workspace");
    return `
      <div class="ii-kpi-grid">
        <article class="ii-panel ii-kpi"><span>Aktív szerepkör</span><strong>${escapeHtml(role.label)}</strong><small>szerveroldalon érvényesített moduljogosultság</small></article>
        <article class="ii-panel ii-kpi"><span>Elérhető modul</span><strong>${access.length}</strong><small>a szerepkör munkaterületén</small></article>
        <article class="ii-panel ii-kpi"><span>Helyi esemény</span><strong>${state.runtime.events.length}</strong><small>event contract naplóban</small></article>
        <article class="ii-panel ii-kpi"><span>Outbox tétel</span><strong>${state.runtime.outbox.length}</strong><small>szimulált integrációs kézbesítés</small></article>
      </div>
      <div class="ii-section-head"><h2>Saját modulok</h2><span class="ii-badge" data-tone="green">${escapeHtml(role.label)}</span></div>
      <div class="ii-module-links">${access.map((module) => `
        <a class="ii-panel ii-module-link" href="${escapeHtml(module.route)}" data-nav-module="${escapeHtml(module.id)}">
          <span class="ii-nav-icon" aria-hidden="true">${icons[module.id] || "II"}</span>
          <span><strong>${escapeHtml(moduleTitle(module))}</strong><small>${escapeHtml(module.description)}</small></span>
        </a>
      `).join("")}</div>
      <div class="ii-section-head"><h2>Közös feladatlista</h2><span class="ii-badge">${tasks.length} feladat</span></div>
      ${renderTable(tasks, "task")}
    `;
  }

  function renderControlCenter(records) {
    const checks = state.system.consistencyChecks;
    return `
      <div class="ii-kpi-grid">
        <article class="ii-panel ii-kpi"><span>Regisztrált modul</span><strong>${state.data.modules.length}</strong><small>stabil modulazonosítóval</small></article>
        <article class="ii-panel ii-kpi"><span>Eseményszerződés</span><strong>${state.system.eventContracts.length}</strong><small>producer–consumer térkép</small></article>
        <article class="ii-panel ii-kpi"><span>Konzisztencia PASS</span><strong>${checks.filter((item) => item.status === "pass").length}</strong><small>${checks.length} automatikus ellenőrzésből</small></article>
        <article class="ii-panel ii-kpi"><span>Nyitott blokk</span><strong>${checks.filter((item) => ["blocked", "warning"].includes(item.status)).length}</strong><small>emberi vagy integrációs döntést kér</small></article>
      </div>
      ${renderSystemRecords(records, "Modulportfólió és döntési kapuk")}
      ${renderSystemRecords(checks.map((item) => ({ ...item, __type: "systemRecord" })), "Keresztmodul-konzisztencia")}
    `;
  }

  function renderIntegrationControlRoom(records) {
    const eventRows = state.runtime.events.slice(0, 10);
    return `
      ${renderSystemRecords(records, "Sandbox adapterek")}
      <div class="ii-section-head"><h2>Helyi outbox</h2><button class="ii-button is-secondary is-small" type="button" data-runtime-action="reset">Tesztfutás visszaállítása</button></div>
      <div class="ii-panel ii-runtime-list">
        ${state.runtime.outbox.map((item) => `
          <div class="ii-runtime-row">
            <span class="ii-id">${escapeHtml(item.id)}</span>
            <strong>${escapeHtml(item.eventKey)}</strong>
            <span>${escapeHtml(item.target || "—")}</span>
            ${badge(item.status)}
            <button class="ii-button is-secondary is-small" type="button" data-runtime-action="retry" data-runtime-id="${escapeHtml(item.id)}">Újraküldés</button>
          </div>
        `).join("") || `<p class="ii-empty">Az outbox üres.</p>`}
      </div>
      <div class="ii-section-head"><h2>Legutóbbi event contract események</h2><span class="ii-badge">${state.runtime.events.length} esemény</span></div>
      <div class="ii-panel ii-runtime-list">
        ${eventRows.map((event) => `
          <div class="ii-runtime-row">
            <span class="ii-id">${escapeHtml(event.id)}</span>
            <strong>${escapeHtml(event.eventKey)}</strong>
            <span>${escapeHtml(event.producer)} → ${escapeHtml(event.target || "szerződés szerinti fogyasztók")}</span>
            ${badge(event.status)}
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderHouseBuild() {
    const approvedSources = state.system.houseBuild.sources.filter((source) => source.status === "approved");
    const jobs = filteredRecords("housebuild-agent");
    return `
      <section class="ii-agent-grid">
        <form class="ii-panel ii-agent-form" id="housebuild-form">
          <p class="ii-kicker">Különálló generáló ügynök · helyi szimuláció</p>
          <h2>Új típusház-jelölt</h2>
          <p>A HouseBuild kizárólag jogtisztaság-ellenőrzött forrásból készít verziózott HousePlan-jelöltet. Nem publikál közvetlenül.</p>
          <label>Adatforrás
            <select name="sourceId" required>${approvedSources.map((source) => `<option value="${escapeHtml(source.id)}">${escapeHtml(source.label)}</option>`).join("")}</select>
          </label>
          <label>Ház neve<input name="name" required value="Dunakanyar tesztház"></label>
          <div class="ii-form-row">
            <label>Bruttó m²<input name="grossArea" required type="number" min="45" max="450" value="126"></label>
            <label>Hálószoba<input name="bedrooms" required type="number" min="1" max="10" value="4"></label>
          </div>
          <div class="ii-form-row">
            <label>Szintek<input name="storeys" required type="number" min="1" max="3" value="1"></label>
            <label>Technológia<select name="technology"><option>Liapor</option><option>Prefab</option><option>Hibrid</option></select></label>
          </div>
          <label>Építészeti karakter<select name="style"><option>kortárs</option><option>klasszikus</option><option>mediterrán</option></select></label>
          <button class="ii-button" type="submit">Jelölt generálása</button>
          <small>Generálás → deduplikáció → PlanCheck → emberi jóváhagyás → BuildConfig → HouseVision → HouseMatch.</small>
        </form>
        <div>
          <div class="ii-section-head"><h2>Forrásregiszter</h2><span class="ii-badge">${state.system.houseBuild.sources.length} forrás</span></div>
          <div class="ii-source-stack">${state.system.houseBuild.sources.map((source) => `
            <article class="ii-panel ii-source-card">
              <header><span class="ii-id">${escapeHtml(source.id)}</span>${badge(source.status)}</header>
              <strong>${escapeHtml(source.label)}</strong>
              <small>${escapeHtml(source.rights)} · ${escapeHtml(source.sourceType)} · ${escapeHtml(source.contentHash)}</small>
            </article>
          `).join("")}</div>
        </div>
      </section>
      <div class="ii-section-head"><h2>HousePlan munkasor</h2><span class="ii-badge">${jobs.length} job</span></div>
      <div class="ii-grid is-two">${jobs.map((job) => `
        <article class="ii-panel ii-record-card">
          <header><span class="ii-id">${escapeHtml(job.id)} · ${escapeHtml(job.housePlanId)}</span>${badge(job.status)}</header>
          <h3>${escapeHtml(job.name)}</h3>
          <p>${escapeHtml(job.grossArea)} m² · ${escapeHtml(job.bedrooms)} háló · ${escapeHtml(job.storeys)} szint · ${escapeHtml(job.technology)}</p>
          <div class="ii-stepper">
            ${["source", "rights", "grossArea", "topology", "duplicates", "humanApproval"].map((gate) => `<span data-tone="${toneFor(job.qa?.[gate])}">${escapeHtml(gate)}: ${escapeHtml(job.qa?.[gate] || "pending")}</span>`).join("")}
          </div>
          <footer>
            <span>Forrás: ${escapeHtml(job.sourceId)} · v${escapeHtml(job.version)}</span>
            ${job.status !== "approved" ? `<button class="ii-button is-small" type="button" data-housebuild-action="approve" data-job-id="${escapeHtml(job.id)}">PlanCheck jóváhagyás</button>` : `<a class="ii-button is-small" href="/buildconfig/" data-nav-module="buildconfig">BuildConfig megnyitása</a>`}
          </footer>
        </article>
      `).join("")}</div>
    `;
  }

  function renderCampaignFactory() {
    const briefs = filteredRecords("campaign-factory");
    return `
      <section class="ii-agent-grid">
        <form class="ii-panel ii-agent-form" id="campaign-form">
          <p class="ii-kicker">Marketing automatizmus · helyi szimuláció</p>
          <h2>Kampánybrief létrehozása</h2>
          <label>Kampány neve<input name="name" required value="Típusház-választó tesztkampány"></label>
          <label>Cél<textarea name="objective" required>Minősített HouseMatch konzultációk indítása.</textarea></label>
          <label>Célcsoport<input name="audience" required value="Építkezést tervező családok"></label>
          <label>Márka<select name="brandKey">${state.brands.map((brand) => `<option value="${escapeHtml(brand.id)}">${escapeHtml(brand.name)}</option>`).join("")}</select></label>
          <fieldset><legend>Csatornák</legend><label><input type="checkbox" name="channels" value="landing" checked> Landing</label><label><input type="checkbox" name="channels" value="email" checked> Email</label><label><input type="checkbox" name="channels" value="meta"> Meta</label></fieldset>
          <button class="ii-button" type="submit">Brief létrehozása</button>
          <small>A prototípus nem publikál és nem kapcsolódik hirdetési fiókhoz.</small>
        </form>
        <article class="ii-panel ii-agent-form">
          <p class="ii-kicker">Kötelező minőségi kapuk</p>
          <h2>Biztonságos publikációs lánc</h2>
          <ol class="ii-process-list">
            <li>Brief és célközönség ellenőrzése</li>
            <li>Claim Registry állítás- és forráskapu</li>
            <li>Marketing / jogi / pénzügyi / műszaki jóváhagyás</li>
            <li>Content Factory csatornaváltozatok</li>
            <li>Sandbox export és auditnapló</li>
          </ol>
        </article>
      </section>
      <div class="ii-section-head"><h2>Kampány munkasor</h2><span class="ii-badge">${briefs.length} brief</span></div>
      <div class="ii-grid is-two">${briefs.map((brief) => `
        <article class="ii-panel ii-record-card">
          <header><span class="ii-id">${escapeHtml(brief.id)}</span>${badge(brief.status)}</header>
          <h3>${escapeHtml(brief.name)}</h3>
          <p>${escapeHtml(brief.objective)}</p>
          <p>${escapeHtml(brief.audience)} · ${escapeHtml(brief.channels?.join(", "))}</p>
          <div class="ii-stepper">${Object.entries(brief.gates || {}).map(([gate, value]) => `<span data-tone="${toneFor(value)}">${escapeHtml(gate)}: ${escapeHtml(value)}</span>`).join("")}</div>
          <footer>
            <span>${escapeHtml(brief.brandKey)} · ${escapeHtml(brief.family)}</span>
            ${brief.status === "export_ready"
              ? `<span class="ii-badge" data-tone="green">Sandbox csomag elkészült</span>`
              : brief.status === "approved_for_production"
                ? `<button class="ii-button is-small" type="button" data-campaign-action="export" data-campaign-id="${escapeHtml(brief.id)}">Sandbox export</button>`
                : `<button class="ii-button is-small" type="button" data-campaign-action="gates" data-campaign-id="${escapeHtml(brief.id)}">Kapuk jóváhagyása</button>`}
          </footer>
        </article>
      `).join("")}</div>
    `;
  }

  function renderModule() {
    const module = moduleById(state.moduleId);
    document.body.dataset.moduleId = state.moduleId;
    document.title = `${moduleTitle(module)} · Imperial Intelligence`;
    document.querySelector("#breadcrumb-module").textContent = moduleTitle(module);
    document.querySelector("#module-id-label").textContent = `Modulazonosító · ${module.id}`;
    document.querySelector("#module-heading").textContent = moduleTitle(module);
    document.querySelector("#module-description").textContent = module.description;
    document.querySelector("#module-view").dataset.moduleId = module.id;
    document.querySelector("#global-search").value = state.query;
    document.querySelector("#module-search").value = state.query;
    renderNav();
    renderFilterOptions();

    const controls = document.querySelector("#module-controls");
    controls.hidden = false;
    const records = filteredRecords(module.id);
    let html = "";

    if (module.id === "workspace") html = renderWorkspace();
    else if (module.id === "control-center") html = renderControlCenter(records);
    else if (module.id === "integration-control-room") html = renderIntegrationControlRoom(records);
    else if (module.id === "housebuild-agent") html = renderHouseBuild();
    else if (module.id === "campaign-factory") html = renderCampaignFactory();
    else if (module.id === "executive-dashboard") html = renderDashboard(records.filter((r) => r.__type === "project"));
    else if (module.id === "my-imperial") html = renderCustomerCards(records.filter((r) => r.__type === "customer"));
    else if (module.id === "crm") html = renderCrm(records);
    else if (module.id === "project-control") {
      html = `${renderProjectCards(records.filter((r) => r.__type === "project"))}
        <div class="ii-section-head" style="margin-top:1.2rem"><h2>Projektmérföldkövek</h2></div>
        ${renderTable(records.filter((r) => r.__type === "milestone"), "milestone")}`;
    }
    else if (module.id === "partner-control") html = renderPartnerCards(records.filter((r) => r.__type === "partner"));
    else if (module.id === "website-content-control") html = renderWebsiteModule();
    else if (module.id === "workflow-center") {
      html = `${renderWorkflowCards(records.filter((r) => r.__type === "workflow"))}
        <div class="ii-section-head" style="margin-top:1.2rem"><h2>Feladatok</h2></div>
        ${renderTable(records.filter((r) => r.__type === "task"), "task")}`;
    } else if (module.id === "admin") {
      html = `${renderUserCards(records.filter((r) => r.__type === "user"))}
        <div class="ii-section-head" style="margin-top:1.2rem"><h2>Audit események</h2></div>
        ${renderTable(records.filter((r) => r.__type === "auditEvent"), "auditEvent")}`;
    } else if (moduleSources[module.id]) {
      const type = moduleSources[module.id][0];
      html = renderTable(records.filter((r) => r.__type === type), type);
    } else html = renderSystemRecords(records, `${moduleTitle(module)} tesztfolyamat`);

    if (module.id === "workspace") html += renderBackendJourneys();
    html += renderBackendModule(module.id);
    document.querySelector("#module-view").innerHTML = html;
  }

  function addLink(links, moduleId, type, id, label) {
    if (id && moduleById(moduleId)) links.push({ moduleId, type, id, label });
  }

  function relatedLinks(type, record) {
    const links = [];
    if (type === "customer") {
      addLink(links, "my-imperial", "customer", record.id, "MyImperial profil");
      addLink(links, "crm", "lead", record.leadId, "Eredeti lead");
      addLink(links, "sales", "offer", record.offerIds?.[0], "Ajánlat");
      addLink(links, "contract-generator", "contract", record.contractIds?.[0], "Szerződés");
      addLink(links, "project-control", "project", record.projectIds?.[0], "Projekt");
      addLink(links, "financial-control", "financialItem", record.financialItemIds?.[0], "Pénzügyi státusz");
      addLink(links, "imperial-care", "careTicket", record.careTicketIds?.[0], "Care ügy");
    }
    if (type === "lead") {
      addLink(links, "crm", "customer", record.customerId, "Ügyfél");
      addLink(links, "sales", "offer", record.offerId, "Ajánlat");
      addLink(links, "marketing-control", "campaign", record.campaignId, "Kampány");
    }
    if (type === "offer") {
      addLink(links, "crm", "customer", record.customerId, "Ügyfél");
      addLink(links, "crm", "lead", record.leadId, "Lead");
      addLink(links, "contract-generator", "contract", record.contractId, "Szerződés");
    }
    if (type === "contract") {
      addLink(links, "crm", "customer", record.customerId, "Ügyfél");
      addLink(links, "sales", "offer", record.offerId, "Ajánlat");
      addLink(links, "project-control", "project", record.projectId, "Projekt");
    }
    if (type === "project") {
      addLink(links, "crm", "customer", record.customerId, "Ügyfél");
      addLink(links, "contract-generator", "contract", record.contractId, "Szerződés");
      record.partnerIds?.forEach((id) => addLink(links, "partner-control", "partner", id, `Partner ${id}`));
      const finance = state.data.financialItems.find((item) => item.projectId === record.id);
      const ticket = state.data.careTickets.find((item) => item.projectId === record.id);
      const document = state.data.documents.find((item) => item.projectId === record.id);
      addLink(links, "financial-control", "financialItem", finance?.id, "Pénzügy");
      addLink(links, "imperial-care", "careTicket", ticket?.id, "Care");
      addLink(links, "document-center", "document", document?.id, "Dokumentum");
    }
    if (["financialItem", "careTicket", "document"].includes(type)) {
      addLink(links, "crm", "customer", record.customerId, "Ügyfél");
      addLink(links, "project-control", "project", record.projectId, "Projekt");
    }
    if (type === "partner") {
      record.projectIds?.forEach((id) => addLink(links, "project-control", "project", id, `Projekt ${id}`));
    }
    if (type === "task") {
      addLink(links, record.moduleId, "task", record.id, moduleTitle(moduleById(record.moduleId)));
      addLink(links, "crm", "customer", record.customerId, "Ügyfél");
      addLink(links, "project-control", "project", record.projectId, "Projekt");
    }
    return links;
  }

  function openDetail(type, id, trigger = document.activeElement) {
    const record = entityById(type, id);
    if (!record) {
      showToast(`Nem található tesztadat: ${id}`);
      return;
    }
    state.drawerReturnFocus = trigger;
    const config = typeConfig[type];
    const fields = Object.entries(record).filter(([key]) => key !== "__type");
    const links = relatedLinks(type, record);
    document.querySelector("#detail-content").innerHTML = `
      <header class="ii-detail-header">
        <div><span class="ii-id">${escapeHtml(config.label)} · ${escapeHtml(record.id)}</span><h2 id="detail-title">${escapeHtml(recordLabel(type, record))}</h2></div>
        <button class="ii-icon-button" id="close-detail" type="button" aria-label="Részletek bezárása">×</button>
      </header>
      <dl class="ii-detail-list">${fields.map(([key, value]) => `
        <div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(displayValue(key, value))}</dd></div>
      `).join("")}</dl>
      ${links.length ? `<section class="ii-related"><h3>Kapcsolt modulok</h3><div class="ii-related-links">
        ${links.map((link) => {
          const module = moduleById(link.moduleId);
          return `<a class="ii-button is-secondary is-small" href="${escapeHtml(module.route)}?focus=${encodeURIComponent(`${link.type}:${link.id}`)}"
            data-nav-module="${escapeHtml(link.moduleId)}" data-focus-type="${escapeHtml(link.type)}" data-focus-id="${escapeHtml(link.id)}">${escapeHtml(link.label)}</a>`;
        }).join("")}
      </div></section>` : ""}
    `;
    document.querySelector("#detail-drawer").classList.add("is-open");
    document.querySelector("#detail-drawer").setAttribute("aria-hidden", "false");
    document.querySelector("#detail-overlay").classList.add("is-open");
    document.querySelector("#close-detail").focus();
  }

  function closeDetail() {
    document.querySelector("#detail-drawer").classList.remove("is-open");
    document.querySelector("#detail-drawer").setAttribute("aria-hidden", "true");
    document.querySelector("#detail-overlay").classList.remove("is-open");
    if (state.drawerReturnFocus instanceof HTMLElement) state.drawerReturnFocus.focus();
  }

  function showToast(message) {
    const toast = document.querySelector("#platform-toast");
    toast.textContent = message;
    toast.classList.add("is-visible");
    window.setTimeout(() => toast.classList.remove("is-visible"), 2400);
  }

  function navigate(moduleId, focusType, focusId, push = true) {
    const module = moduleById(moduleId);
    if (!module) return;
    closeDetail();
    state.moduleId = moduleId;
    state.query = "";
    state.status = "all";
    const focus = focusType && focusId ? `?focus=${encodeURIComponent(`${focusType}:${focusId}`)}` : "";
    if (push) history.pushState({ moduleId }, "", `${module.route}${focus}`);
    renderModule();
    closeSidebar();
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (focusType && focusId) window.setTimeout(() => openDetail(focusType, focusId), 0);
  }

  function applyLocation() {
    const path = location.pathname.replace(/\/+$/, "") || "/";
    const moduleId = routeMap[path] || "executive-dashboard";
    const focus = new URLSearchParams(location.search).get("focus") || "";
    const separator = focus.indexOf(":");
    const focusType = separator > 0 ? focus.slice(0, separator) : "";
    const focusId = separator > 0 ? focus.slice(separator + 1) : "";
    navigate(moduleId, focusType, focusId, false);
  }

  function openSidebar() {
    document.querySelector("#platform-sidebar").classList.add("is-open");
    document.querySelector("#sidebar-overlay").classList.add("is-open");
  }

  function closeSidebar() {
    document.querySelector("#platform-sidebar").classList.remove("is-open");
    document.querySelector("#sidebar-overlay").classList.remove("is-open");
  }

  function upsertRuntime(collection, record) {
    const index = state.runtime[collection].findIndex((item) => item.id === record.id);
    if (index >= 0) state.runtime[collection][index] = record;
    else state.runtime[collection].unshift(record);
    saveRuntime();
  }

  function createHouseBuildJob(form) {
    const values = new FormData(form);
    const source = state.system.houseBuild.sources.find((item) => item.id === values.get("sourceId"));
    if (!source || source.status !== "approved") {
      showToast("A kiválasztott forrás jogtisztasági kapuja nem PASS.");
      return;
    }
    const serial = String(recordsForModule("housebuild-agent").length + 1).padStart(3, "0");
    const job = {
      id: `HBJ-LOCAL-${serial}`,
      sourceId: source.id,
      housePlanId: `HP-LOCAL-${Date.now().toString().slice(-6)}`,
      name: values.get("name"),
      status: "plancheck_review",
      brandKey: source.brandKey,
      grossArea: Number(values.get("grossArea")),
      bedrooms: Number(values.get("bedrooms")),
      storeys: Number(values.get("storeys")),
      technology: values.get("technology"),
      style: values.get("style"),
      version: 1,
      geometrySignature: `geo-local-${Date.now().toString(36)}`,
      qa: { source: "pass", rights: "pass", grossArea: "pass", topology: "pass", duplicates: "pass", humanApproval: "pending" }
    };
    upsertRuntime("houseBuildJobs", job);
    emitLocalEvent("HOUSE_PLAN_DRAFTED", "housebuild-agent", "plancheck", { jobId: job.id, housePlanId: job.housePlanId, sourceId: job.sourceId });
    showToast(`${job.housePlanId} elkészült, PlanCheck review szükséges.`);
    renderModule();
  }

  function approveHouseBuildJob(jobId) {
    const job = recordsForModule("housebuild-agent").find((item) => item.id === jobId);
    if (!job) return;
    const approved = {
      ...job,
      status: "approved",
      approvedAt: new Date().toISOString(),
      qa: { ...job.qa, humanApproval: "pass" }
    };
    delete approved.__type;
    delete approved.__moduleId;
    upsertRuntime("houseBuildJobs", approved);
    emitLocalEvent("HOUSE_PLAN_APPROVED", "plancheck", "buildconfig", { jobId: approved.id, housePlanId: approved.housePlanId, version: approved.version });
    showToast(`${approved.housePlanId} jóváhagyva; továbbadva a BuildConfig felé.`);
    renderModule();
  }

  function createCampaignBrief(form) {
    const values = new FormData(form);
    const serial = String(recordsForModule("campaign-factory").length + 1).padStart(3, "0");
    const brief = {
      id: `CMP-LOCAL-${serial}`,
      name: values.get("name"),
      status: "brief_quality_gate",
      brandKey: values.get("brandKey"),
      family: "lead-generation",
      objective: values.get("objective"),
      audience: values.get("audience"),
      claimIds: ["CLM-001"],
      channels: values.getAll("channels"),
      gates: { marketing: "pending", legal: "pending", finance: "not_relevant", technical: "pending" }
    };
    upsertRuntime("campaignBriefs", brief);
    emitLocalEvent("CAMPAIGN_BRIEF_DRAFTED", "campaign-factory", "claim-registry", { campaignId: brief.id, brandKey: brief.brandKey });
    showToast(`${brief.id} brief elkészült; jóváhagyási kapuk várnak.`);
    renderModule();
  }

  function updateCampaign(campaignId, action) {
    const brief = recordsForModule("campaign-factory").find((item) => item.id === campaignId);
    if (!brief) return;
    const next = { ...brief };
    delete next.__type;
    delete next.__moduleId;
    if (action === "gates") {
      next.status = "approved_for_production";
      next.gates = { marketing: "pass", legal: "pass", finance: "not_relevant", technical: "pass" };
      emitLocalEvent("CAMPAIGN_BRIEF_APPROVED", "campaign-factory", "content-factory", { campaignId: next.id, briefVersion: 1 });
      showToast(`${next.id} átment a kapukon; Content Factory feladat létrejött.`);
    } else {
      next.status = "export_ready";
      next.export = { mode: "sandbox", packageId: `PKG-${Date.now().toString().slice(-6)}`, externalDelivery: false };
      emitLocalEvent("CAMPAIGN_SANDBOX_PACKAGE_READY", "content-factory", "marketing-control", { campaignId: next.id, packageId: next.export.packageId });
      showToast(`${next.id} sandbox exportcsomag elkészült.`);
    }
    upsertRuntime("campaignBriefs", next);
    renderModule();
  }

  async function backendRequest(path, options = {}) {
    const response = await fetch(`/core/api/demo${path}`, {
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options
    });
    if (response.status === 401) {
      location.assign(`/login?return_to=${encodeURIComponent(location.pathname)}`);
      throw new Error("A munkamenet lejárt; új bejelentkezés szükséges.");
    }
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `Backend hiba (${response.status})`);
    }
    return response.json();
  }

  async function refreshBackend() {
    state.backend = await backendRequest("/state");
    state.backendStatus = "connected";
  }

  function bindEvents() {
    document.addEventListener("submit", (event) => {
      if (event.target.matches("#housebuild-form")) {
        event.preventDefault();
        createHouseBuildJob(event.target);
      }
      if (event.target.matches("#campaign-form")) {
        event.preventDefault();
        createCampaignBrief(event.target);
      }
    });

    document.addEventListener("click", async (event) => {
      const backendAction = event.target.closest("[data-backend-action]");
      if (backendAction) {
        backendAction.disabled = true;
        try {
          const operationForm = backendAction.closest("[data-module-operation-form]");
          const operationData = new FormData(operationForm);
          const result = await backendRequest("/actions", {
            method: "POST",
            body: JSON.stringify({
              module_id: backendAction.dataset.backendModule,
              action_id: backendAction.dataset.backendAction,
              project_id: operationData.get("project_id"),
              payload: {
                notes: operationData.get("notes") || "",
                initiatedFrom: location.pathname
              }
            })
          });
          await refreshBackend();
          showToast(`${result.event.eventKey} kézbesítve · ${result.event.correlationId}`);
          renderModule();
        } catch (error) {
          backendAction.disabled = false;
          showToast(error.message);
        }
        return;
      }
      const backendJourney = event.target.closest("[data-backend-journey]");
      if (backendJourney) {
        backendJourney.disabled = true;
        try {
          const result = await backendRequest(`/journeys/${encodeURIComponent(backendJourney.dataset.backendJourney)}/run`, {
            method: "POST",
            body: JSON.stringify({})
          });
          await refreshBackend();
          showToast(`${result.journey.name}: ${result.events.length} esemény sikeresen kézbesítve.`);
          renderModule();
        } catch (error) {
          backendJourney.disabled = false;
          showToast(error.message);
        }
        return;
      }
      const backendReset = event.target.closest("[data-backend-reset]");
      if (backendReset) {
        backendReset.disabled = true;
        try {
          await backendRequest("/reset", { method: "POST", body: "{}" });
          await refreshBackend();
          showToast("A teljes backend demoállapot visszaállt.");
          renderModule();
        } catch (error) {
          backendReset.disabled = false;
          showToast(error.message);
        }
        return;
      }
      const houseBuildAction = event.target.closest("[data-housebuild-action]");
      if (houseBuildAction) {
        approveHouseBuildJob(houseBuildAction.dataset.jobId);
        return;
      }
      const campaignAction = event.target.closest("[data-campaign-action]");
      if (campaignAction) {
        updateCampaign(campaignAction.dataset.campaignId, campaignAction.dataset.campaignAction);
        return;
      }
      const runtimeAction = event.target.closest("[data-runtime-action]");
      if (runtimeAction) {
        if (runtimeAction.dataset.runtimeAction === "reset") {
          localStorage.removeItem(runtimeStorageKey);
          state.runtime = loadRuntime();
          showToast("A helyi integrációs tesztfutás visszaállt.");
        } else {
          const item = state.runtime.outbox.find((entry) => entry.id === runtimeAction.dataset.runtimeId);
          if (item) {
            item.status = "delivered";
            item.attempts += 1;
            saveRuntime();
            showToast(`${item.id} szimulált újraküldése sikeres.`);
          }
        }
        renderModule();
        return;
      }
      const nav = event.target.closest("[data-nav-module]");
      if (nav) {
        event.preventDefault();
        navigate(nav.dataset.navModule, nav.dataset.focusType, nav.dataset.focusId);
        return;
      }
      const entity = event.target.closest("[data-entity-type]");
      if (entity) {
        openDetail(entity.dataset.entityType, entity.dataset.entityId, entity);
        return;
      }
      const site = event.target.closest("[data-site]");
      if (site) {
        state.selectedSite = site.dataset.site;
        renderModule();
        return;
      }
      const device = event.target.closest("[data-preview-device]");
      if (device) {
        state.previewDevice = device.dataset.previewDevice;
        renderModule();
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeDetail();
        closeSidebar();
      }
      const row = event.target.closest?.("tr[data-entity-type]");
      if (row && ["Enter", " "].includes(event.key)) {
        event.preventDefault();
        openDetail(row.dataset.entityType, row.dataset.entityId, row);
      }
    });

    document.querySelector("#global-search").addEventListener("input", (event) => {
      state.query = event.target.value;
      document.querySelector("#module-search").value = state.query;
      renderModule();
    });
    document.querySelector("#module-search").addEventListener("input", (event) => {
      state.query = event.target.value;
      document.querySelector("#global-search").value = state.query;
      renderModule();
    });
    document.querySelector("#module-filter").addEventListener("change", (event) => {
      state.status = event.target.value;
      renderModule();
    });
    document.querySelector("#clear-filters").addEventListener("click", () => {
      state.query = "";
      state.status = "all";
      renderModule();
      document.querySelector("#module-search").focus();
    });
    document.querySelector("#journey-button").addEventListener("click", () => {
      document.querySelector("#journey-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    document.querySelector("#menu-button").addEventListener("click", openSidebar);
    document.querySelector("#sidebar-overlay").addEventListener("click", closeSidebar);
    document.querySelector("#detail-overlay").addEventListener("click", closeDetail);
    document.querySelector("#detail-drawer").addEventListener("click", (event) => {
      if (event.target.closest("#close-detail")) closeDetail();
    });
    window.addEventListener("popstate", applyLocation);
  }

  async function initialize() {
    document.body.className = "platform-shell";
    document.body.dataset.moduleId = state.moduleId;
    document.body.innerHTML = `<main class="ii-empty">Imperial Intelligence betöltése…</main>`;
    try {
      const [platformResponse, brandResponse, systemResponse, identityResponse, backendResponse] = await Promise.all([
        fetch("/data/platform.json", { cache: "no-store" }),
        fetch("/data/brands.json", { cache: "no-store" }),
        fetch("/data/system.json", { cache: "no-store" }),
        fetch("/core/api/auth/session", { cache: "no-store" }),
        fetch("/core/api/demo/state", { cache: "no-store" }).catch(() => null)
      ]);
      if (!platformResponse.ok || !brandResponse.ok || !systemResponse.ok) throw new Error("A lokális tesztadat nem érhető el.");
      if (identityResponse.status === 401) {
        location.assign(`/login?return_to=${encodeURIComponent(location.pathname)}`);
        return;
      }
      if (!identityResponse.ok) throw new Error("A felhasználói jogosultság nem ellenőrizhető.");
      state.data = await platformResponse.json();
      const brandData = await brandResponse.json();
      state.brands = brandData.brands || [];
      state.system = await systemResponse.json();
      state.identity = await identityResponse.json();
      state.currentRoleId = state.identity.role.id;
      const configuredRole = state.system.roles.find((role) => role.id === state.currentRoleId);
      if (!configuredRole) throw new Error("A bejelentkezett szerepkör nincs a platformon regisztrálva.");
      configuredRole.moduleAccess = state.identity.role.moduleAccess;
      configuredRole.label = state.identity.role.label;
      configuredRole.initials = state.identity.role.initials;
      if (!configuredRole.moduleAccess.includes(state.moduleId)) {
        throw new Error(`A(z) ${configuredRole.label} szerepkör nem jogosult erre a modulra.`);
      }
      if (backendResponse?.ok) {
        state.backend = await backendResponse.json();
        state.backendStatus = "connected";
      } else {
        state.backend = null;
        state.backendStatus = "degraded";
      }
      state.runtime = loadRuntime();
      document.body.innerHTML = platformMarkup();
      bindEvents();
      renderJourney();
      applyLocation();
    } catch (error) {
      document.body.innerHTML = `<main class="ii-error"><h1>Az Imperial Intelligence nem indítható</h1><p>${escapeHtml(error.message)}</p></main>`;
    }
  }

  initialize();
})();
