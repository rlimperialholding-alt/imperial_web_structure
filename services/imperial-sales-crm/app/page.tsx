"use client";

import { useEffect, useMemo, useState } from "react";
import accessStyles from "./access.module.css";
import { authenticatedFetch, clearBrowserSession } from "@/lib/browser-auth";
import {
  AgentsWorkspace,
  AuditWorkspace,
  CalendarWorkspace,
  KnowledgeWorkspace,
  ModulesWorkspace,
  ProjectsWorkspace,
  type IntelligenceWorkspace,
} from "./intelligence-workspace";

type View =
  | "today"
  | "pipeline"
  | "records"
  | "customers"
  | "reports"
  | "finance"
  | "control"
  | "executive"
  | "modules"
  | "projects"
  | "calendar"
  | "knowledge"
  | "agents"
  | "audit";
type Stage =
  | "new"
  | "contact"
  | "consultation"
  | "offer"
  | "negotiation"
  | "contract";
type Lead = {
  id: number;
  name: string;
  title: string;
  brand: string;
  brandCode: string;
  location: string;
  email: string;
  phone: string;
  source: string;
  owner: string;
  ownerInitials: string;
  stage: Stage;
  value: number;
  probability: number;
  score: number;
  quality: number;
  temperature: "hot" | "warm" | "cold";
  health: "green" | "yellow" | "red";
  nextAction: string;
  nextDate: string;
  projectType: string;
  technology: string;
  plot: boolean;
  financing: boolean;
  notes: string;
};
type Task = {
  id: number;
  title: string;
  leadId: number;
  leadName: string;
  type: string;
  due: string;
  priority: "critical" | "high" | "normal";
  done: boolean;
  ai?: boolean;
};
type NewTask = Pick<Task, "title" | "type" | "due" | "priority">;
type Customer = {
  id: string;
  customerType: "person" | "company";
  name: string;
  email: string;
  phone: string;
  billingAddress: string;
  taxNumber: string | null;
  sourceLeadId: number | null;
  status: "prospect" | "active" | "archived";
};
type Contract = {
  id: string;
  contractNumber: string;
  customerId: string;
  leadId: number | null;
  projectId: string | null;
  title: string;
  contractType: "construction" | "design" | "consulting" | "other";
  netAmount: number;
  vatRate: number;
  grossAmount: number;
  currency: string;
  status: "draft" | "review" | "approved" | "signed" | "cancelled";
  effectiveDate: string;
  signedAt: string | null;
};
type BusinessProject = {
  id: string;
  portalCode: string;
  customerId: string | null;
  contractId: string | null;
  title: string;
  status: "planning" | "construction" | "handover" | "care";
  phase: string;
  progress: number;
  targetCompletion: string;
};
type Identity = {
  email: string;
  name: string;
  role: "admin" | "sales_manager" | "sales";
};
type Invoice = {
  id: number;
  invoiceNumber: string;
  invoiceType: "invoice" | "storno";
  buyerName: string;
  issueDate: string;
  dueDate: string;
  paymentMethod: string;
  currency: string;
  netAmount: number;
  taxAmount: number;
  grossAmount: number;
  description: string;
  referencedInvoiceNumber: string | null;
  sourceUrl: string;
  sourceFileName: string;
  customerMatchStatus: "matched" | "review" | "unmatched";
  projectMatchStatus: "matched" | "review" | "unmatched";
  matchConfidence: number;
  crmCustomerName: string | null;
  projectTitle: string | null;
};
type CashflowEntry = {
  id: string;
  sourceType: "imported_invoice" | "manual" | "contract_schedule" | "bank";
  direction: "inflow" | "outflow";
  category: string;
  counterparty: string;
  description: string;
  projectId: string | null;
  amount: number;
  currency: string;
  status: "planned" | "due" | "paid" | "cancelled";
  dueDate: string;
  paidAt: string | null;
};
type CashflowWorkspace = {
  period: { from: string; to: string };
  summaries: Array<{
    currency: string;
    actualInflow: number;
    actualOutflow: number;
    forecastInflow: number;
    forecastOutflow: number;
    overdueOutflow: number;
    actualBalance: number;
    forecastBalance: number;
  }>;
  monthly: Array<{
    month: string;
    currency: string;
    actualInflow: number;
    actualOutflow: number;
    forecastInflow: number;
    forecastOutflow: number;
  }>;
  entries: CashflowEntry[];
};
type ImportStatus = {
  workspaceId: string;
  recordCounts: {
    recordType: string;
    reviewStatus: string;
    count: number;
  }[];
  partnerCounts: {
    partnerType: string;
    recordStatus: string;
    count: number;
  }[];
  projectCounts: {
    projectStatus: string;
    customerMatchStatus: string;
    count: number;
  }[];
  openReviews: { entityType: string; count: number }[];
  recentRecords: {
    externalId: string;
    recordType: string;
    title: string;
    sourceUrl: string;
    reviewStatus: string;
    updatedAt: string;
  }[];
};
type DataState = "connecting" | "live" | "forbidden" | "unavailable";

const stages: { id: Stage; label: string; color: string }[] = [
  { id: "new", label: "Új lead", color: "#6f7f92" },
  { id: "contact", label: "Kapcsolatfelvétel", color: "#3f75a7" },
  { id: "consultation", label: "Konzultáció", color: "#765ea7" },
  { id: "offer", label: "Konfiguráció / ajánlat", color: "#c18a29" },
  { id: "negotiation", label: "Tárgyalás", color: "#c6653a" },
  { id: "contract", label: "Szerződés", color: "#2c8a68" },
];

// Retained as a visual fixture for component development; never used as an
// authorization or runtime fallback.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const initialLeads: Lead[] = [
  {
    id: 1,
    name: "Minta Anna",
    title: "120 m²-es Danish Fabrik családi ház",
    brand: "Danish Fabrik",
    brandCode: "DF",
    location: "Üröm",
    email: "anna@example.hu",
    phone: "+36 30 111 2233",
    source: "Google Ads",
    owner: "Kiss Andrea",
    ownerInitials: "KA",
    stage: "offer",
    value: 118000000,
    probability: 55,
    score: 91,
    quality: 94,
    temperature: "hot",
    health: "green",
    nextAction: "Helyszíni felmérés egyeztetése",
    nextDate: "Ma, 14:30",
    projectType: "Családi ház",
    technology: "Danish Fabrik",
    plot: true,
    financing: true,
    notes:
      "Otthon Start finanszírozásban gondolkodik. A telek rendelkezésre áll.",
  },
  {
    id: 2,
    name: "Nagy Péter",
    title: "Váci kétlakásos Prefab projekt",
    brand: "Prefab",
    brandCode: "PF",
    location: "Vác",
    email: "peter@nagyprojekt.hu",
    phone: "+36 20 222 3344",
    source: "Ajánlás",
    owner: "Kiss Andrea",
    ownerInitials: "KA",
    stage: "negotiation",
    value: 180000000,
    probability: 72,
    score: 94,
    quality: 98,
    temperature: "hot",
    health: "yellow",
    nextAction: "Döntési akadályok átbeszélése",
    nextDate: "Ma, 11:00",
    projectType: "Kétlakásos ház",
    technology: "Prefab / Leier",
    plot: true,
    financing: true,
    notes:
      "Ajánlat kiküldve. A döntéshez a műszaki tartalom véglegesítése szükséges.",
  },
  {
    id: 3,
    name: "Kovács Dóra",
    title: "Gödi 90 m²-es családi ház",
    brand: "BauFreund",
    brandCode: "BF",
    location: "Göd",
    email: "dora@example.hu",
    phone: "—",
    source: "Facebook",
    owner: "Farkas Bence",
    ownerInitials: "FB",
    stage: "new",
    value: 72000000,
    probability: 18,
    score: 62,
    quality: 54,
    temperature: "cold",
    health: "red",
    nextAction: "Első visszahívás",
    nextDate: "3 órája lejárt",
    projectType: "Családi ház",
    technology: "Tégla",
    plot: false,
    financing: false,
    notes: "A telekválasztás még folyamatban van. Költségkeret pontosítandó.",
  },
  {
    id: 4,
    name: "Szabó Márton",
    title: "Passzát típusház Érden",
    brand: "Imperial",
    brandCode: "IH",
    location: "Érd",
    email: "marton@example.hu",
    phone: "+36 70 444 5566",
    source: "Weboldal",
    owner: "Kiss Andrea",
    ownerInitials: "KA",
    stage: "consultation",
    value: 96000000,
    probability: 42,
    score: 83,
    quality: 86,
    temperature: "warm",
    health: "green",
    nextAction: "Konzultáció összefoglaló küldése",
    nextDate: "Holnap, 09:00",
    projectType: "Családi ház",
    technology: "Tégla",
    plot: true,
    financing: true,
    notes: "Passzát típusház, kisebb alaprajzi módosításokkal.",
  },
  {
    id: 5,
    name: "Tóth Katalin",
    title: "Telek és 3 hálós Eco Basic",
    brand: "Danish Fabrik",
    brandCode: "DF",
    location: "Dunakeszi",
    email: "katalin@example.hu",
    phone: "+36 30 555 6677",
    source: "Kiállítás",
    owner: "Farkas Bence",
    ownerInitials: "FB",
    stage: "contact",
    value: 83000000,
    probability: 28,
    score: 71,
    quality: 78,
    temperature: "warm",
    health: "yellow",
    nextAction: "Finanszírozási igény egyeztetése",
    nextDate: "július 21.",
    projectType: "Családi ház",
    technology: "Danish Fabrik",
    plot: true,
    financing: false,
    notes: "Három hálószoba, gyors beköltözés elsődleges.",
  },
  {
    id: 6,
    name: "Varga Építő Kft.",
    title: "12 lakásos szerkezetépítési csomag",
    brand: "Bautica",
    brandCode: "BA",
    location: "Budapest XI.",
    email: "projekt@vargaepito.hu",
    phone: "+36 1 555 0199",
    source: "Baudata",
    owner: "Kiss Andrea",
    ownerInitials: "KA",
    stage: "offer",
    value: 265000000,
    probability: 48,
    score: 86,
    quality: 91,
    temperature: "hot",
    health: "green",
    nextAction: "Műszaki ajánlat jóváhagyása",
    nextDate: "július 22.",
    projectType: "B2B kivitelezés",
    technology: "Vasbeton",
    plot: true,
    financing: true,
    notes: "B2B opportunity. Minimum árrés ellenőrzés kötelező.",
  },
  {
    id: 7,
    name: "Horváth Gábor",
    title: "110 m²-es Imperial típusház",
    brand: "Imperial",
    brandCode: "IH",
    location: "Győr",
    email: "gabor@example.hu",
    phone: "+36 30 772 1144",
    source: "Google organikus",
    owner: "Farkas Bence",
    ownerInitials: "FB",
    stage: "contract",
    value: 103000000,
    probability: 92,
    score: 96,
    quality: 97,
    temperature: "hot",
    health: "green",
    nextAction: "Szerződéstervezet jóváhagyása",
    nextDate: "július 20.",
    projectType: "Családi ház",
    technology: "Tégla",
    plot: true,
    financing: true,
    notes: "Szerződés előkészítés alatt. Kiküldés emberi jóváhagyáshoz kötött.",
  },
  {
    id: 8,
    name: "Molnár Eszter",
    title: "Pajtaház a Velencei-tónál",
    brand: "Prefab",
    brandCode: "PF",
    location: "Pákozd",
    email: "eszter@example.hu",
    phone: "+36 20 883 4466",
    source: "Instagram",
    owner: "Kiss Andrea",
    ownerInitials: "KA",
    stage: "contact",
    value: 126000000,
    probability: 32,
    score: 76,
    quality: 68,
    temperature: "warm",
    health: "yellow",
    nextAction: "Telekadatok bekérése",
    nextDate: "július 23.",
    projectType: "Pajtaház",
    technology: "Liapor",
    plot: true,
    financing: false,
    notes: "Modern pajtaház, nagy üvegfelületekkel.",
  },
];
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const initialTasks: Task[] = [
  {
    id: 1,
    title: "Kovács Dóra első visszahívása",
    leadId: 3,
    leadName: "Kovács Dóra",
    type: "Hívás",
    due: "3 órája lejárt",
    priority: "critical",
    done: false,
    ai: true,
  },
  {
    id: 2,
    title: "Nagy Péter ajánlat utánkövetése",
    leadId: 2,
    leadName: "Nagy Péter",
    type: "Follow-up",
    due: "Ma, 11:00",
    priority: "high",
    done: false,
    ai: true,
  },
  {
    id: 3,
    title: "Minta Anna helyszíni felmérés egyeztetése",
    leadId: 1,
    leadName: "Minta Anna",
    type: "Találkozó",
    due: "Ma, 14:30",
    priority: "normal",
    done: false,
  },
  {
    id: 4,
    title: "Varga Építő műszaki ajánlat belső kontrollja",
    leadId: 6,
    leadName: "Varga Építő Kft.",
    type: "Jóváhagyás",
    due: "Ma, 16:00",
    priority: "high",
    done: false,
    ai: true,
  },
];
const money = (value: number) =>
  new Intl.NumberFormat("hu-HU", { maximumFractionDigits: 0 }).format(
    Math.round(value / 1000000),
  ) + " M Ft";

function Icon({ name }: { name: string }) {
  const p: Record<string, React.ReactNode> = {
    check: <path d="m5 12 4 4L19 6" />,
    sales: <path d="M4 19V9M10 19V5M16 19v-7M22 19H2" />,
    project: (
      <>
        <rect x="3" y="6" width="18" height="15" rx="2" />
        <path d="M8 6V3h8v3M3 11h18" />
      </>
    ),
    calendar: (
      <>
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M16 3v4M8 3v4M3 10h18" />
      </>
    ),
    grid: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </>
    ),
    finance: <path d="M4 19V9M10 19V5M16 19v-7M2 19h20" />,
    search: (
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-4-4" />
      </>
    ),
    bot: (
      <>
        <rect x="4" y="7" width="16" height="13" rx="3" />
        <path d="M12 3v4M8 12h.01M16 12h.01M8 16h8" />
      </>
    ),
    audit: <path d="M6 3h12v18H6zM9 8h6M9 12h6M9 16h4" />,
    bell: <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />,
    plus: <path d="M12 5v14M5 12h14" />,
    menu: <path d="M4 7h16M4 12h16M4 17h16" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    arrow: <path d="m9 18 6-6-6-6" />,
    mail: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <path d="m3 7 9 6 9-6" />
      </>
    ),
    phone: (
      <path d="M6 3h4l2 5-3 2a14 14 0 0 0 5 5l2-3 5 2v4c0 2-2 3-4 3C9 20 4 15 3 7c0-2 1-4 3-4Z" />
    ),
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    user: (
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21a8 8 0 0 1 16 0" />
      </>
    ),
    list: <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />,
    filter: <path d="M4 5h16M7 12h10M10 19h4" />,
    shield: (
      <>
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10" />
        <path d="m9 12 2 2 4-4" />
      </>
    ),
  };
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {p[name]}
    </svg>
  );
}
function Logo() {
  return (
    <div className="brand">
      <span className="brand-symbol">
        <i />
        <b />
      </span>
      <span>
        <strong>IMPERIAL</strong>
        <small>INTELLIGENCE CRM</small>
      </span>
    </div>
  );
}
function viewTitle(view: View) {
  return {
    today: "Mai napom",
    pipeline: "Értékesítési pipeline",
    records: "Értékesítési adatlapok",
    customers: "Ügyfelek",
    reports: "Értékesítési riportok",
    finance: "Pénzügy",
    control: "Sales Control Center",
    executive: "Executive Dashboard",
    modules: "Teljes rendszerleltár",
    projects: "Projekt 360°",
    calendar: "Okosnaptár",
    knowledge: "Tudásbázis és dokumentumtár",
    agents: "AI-ügynökök",
    audit: "Auditnapló",
  }[view];
}

export default function Home() {
  const [view, setView] = useState<View>("today"),
    [leads, setLeads] = useState<Lead[]>([]),
    [tasks, setTasksRaw] = useState<Task[]>([]),
    [customers, setCustomers] = useState<Customer[]>([]),
    [contracts, setContracts] = useState<Contract[]>([]),
    [businessProjects, setBusinessProjects] = useState<BusinessProject[]>([]),
    [cashflow, setCashflow] = useState<CashflowWorkspace | null>(null),
    [invoices, setInvoices] = useState<Invoice[]>([]),
    [importStatus, setImportStatus] = useState<ImportStatus | null>(null),
    [intelligence, setIntelligence] = useState<IntelligenceWorkspace | null>(null);
  const [query, setQuery] = useState(""),
    [brand, setBrand] = useState("Mind"),
    [owner, setOwner] = useState("Mind");
  const [mode, setMode] = useState<"kanban" | "list">("kanban"),
    [selected, setSelected] = useState<Lead | null>(null),
    [newOpen, setNewOpen] = useState(false),
    [newCustomerOpen, setNewCustomerOpen] = useState(false),
    [newContractOpen, setNewContractOpen] = useState(false),
    [newCashflowOpen, setNewCashflowOpen] = useState(false),
    [mobileOpen, setMobileOpen] = useState(false),
    [toast, setToast] = useState("");
  const [identity, setIdentity] = useState<Identity>({
      email: "",
      name: "Bodó Csaba",
      role: "sales",
    }),
    [dataState, setDataState] = useState<DataState>("connecting");
  useEffect(() => {
    let active = true;
    authenticatedFetch("/api/crm", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) {
          setDataState(
            response.status === 401 || response.status === 403
              ? "forbidden"
              : "unavailable",
          );
          throw new Error(String(response.status));
        }
        return response.json() as Promise<{
          identity: Identity;
          leads: Lead[];
          tasks: Task[];
          customers: Customer[];
          contracts: Contract[];
          projects: BusinessProject[];
          invoices: Invoice[];
          importStatus: ImportStatus;
        }>;
      })
      .then((data) => {
        if (!active) return;
        setIdentity(data.identity);
        setLeads(data.leads);
        setTasksRaw(data.tasks);
        setCustomers(data.customers);
        setContracts(data.contracts);
        setBusinessProjects(data.projects);
        setInvoices(data.invoices);
        setImportStatus(data.importStatus);
        setDataState("live");
      })
      .catch((error) => {
        if (!active) return;
        const status = error instanceof Error ? error.message : "";
        setDataState(
          status === "401" || status === "403" ? "forbidden" : "unavailable",
        );
      });
    return () => {
      active = false;
    };
  }, []);
  const refreshIntelligence = async () => {
    const response = await authenticatedFetch("/api/intelligence", { cache: "no-store" });
    if (!response.ok) throw new Error(String(response.status));
    setIntelligence(await response.json() as IntelligenceWorkspace);
  };
  useEffect(() => {
    let active = true;
    authenticatedFetch("/api/intelligence", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json() as Promise<IntelligenceWorkspace>;
      })
      .then((data) => {
        if (active) setIntelligence(data);
      })
      .catch(() => {
        if (active) setIntelligence(null);
      });
    return () => {
      active = false;
    };
  }, []);
  const refreshCashflow = async () => {
    const response = await authenticatedFetch("/api/crm/finance/cashflow", { cache: "no-store" });
    if (!response.ok) throw new Error(String(response.status));
    const workspace = await response.json() as CashflowWorkspace;
    setCashflow(workspace);
    return workspace;
  };
  useEffect(() => {
    let active = true;
    authenticatedFetch("/api/crm/finance/cashflow", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json() as Promise<CashflowWorkspace>;
      })
      .then((workspace) => { if (active) setCashflow(workspace); })
      .catch(() => { if (active) setCashflow(null); });
    return () => { active = false; };
  }, []);
  const filtered = useMemo(
    () =>
      leads.filter(
        (l) =>
          `${l.name} ${l.title} ${l.location} ${l.email}`
            .toLowerCase()
            .includes(query.toLowerCase()) &&
          (brand === "Mind" || l.brand === brand) &&
          (owner === "Mind" || l.owner === owner),
      ),
    [leads, query, brand, owner],
  );
  const notify = (m: string) => {
      setToast(m);
      window.setTimeout(() => setToast(""), 3200);
    },
    changeView = (v: View) => {
      setView(v);
      setMobileOpen(false);
    };
  const logout = async () => {
    try {
      await authenticatedFetch("/api/auth/logout", { method: "POST" });
    } finally {
      clearBrowserSession();
      window.location.assign("/login");
    }
  };
  const resolveImportReview = async (
    id: number,
    status: "resolved" | "dismissed",
  ) => {
    try {
      const response = await authenticatedFetch(`/api/intelligence/reviews/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (!response.ok) throw new Error();
      await refreshIntelligence();
      notify(status === "resolved" ? "Az ellenőrzést lezártuk." : "A forrást kizártuk ebből a feldolgozásból.");
    } catch {
      notify("Az ellenőrzési tétel mentése nem sikerült.");
    }
  };
  const setTasks = (update: React.SetStateAction<Task[]>) =>
    setTasksRaw((current) => {
      const next = typeof update === "function" ? update(current) : update;
      const completed = next.find(
        (task) => task.done && !current.find((old) => old.id === task.id)?.done,
      );
      if (completed && dataState !== "live") {
        return current;
      }
      if (completed)
        authenticatedFetch(`/api/crm/tasks/${completed.id}`, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ done: true }),
        })
          .then((response) => {
            if (!response.ok) throw new Error();
          })
          .catch(() => {
            setTasksRaw((rows) =>
              rows.map((task) =>
                task.id === completed.id ? { ...task, done: false } : task,
              ),
            );
            notify("A teendő mentése nem sikerült. Próbáld újra.");
          });
      return next;
    });
  const moveLead = async (id: number, stage: Stage) => {
    if (dataState !== "live") {
      notify("Nincs élő adatkapcsolat; a státusz nem módosítható.");
      return;
    }
    const previous = leads.find((l) => l.id === id)?.stage;
    setLeads((c) => c.map((l) => (l.id === id ? { ...l, stage } : l)));
    try {
      const response = await authenticatedFetch(`/api/crm/leads/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ stage }),
      });
      if (!response.ok) throw new Error();
      notify(
        `Az adatlap átkerült: ${stages.find((s) => s.id === stage)?.label}.`,
      );
    } catch {
      if (previous)
        setLeads((c) =>
          c.map((l) => (l.id === id ? { ...l, stage: previous } : l)),
        );
      notify("A státusz mentése nem sikerült. Próbáld újra.");
    }
  };
  const addLead = async (lead: Omit<Lead, "id">) => {
    if (dataState !== "live") {
      notify("Nincs élő adatkapcsolat; az adatlap nem hozható létre.");
      return;
    }
    try {
      const response = await authenticatedFetch("/api/crm/leads", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(lead),
      });
      if (!response.ok) throw new Error();
      const data = (await response.json()) as { lead: Lead };
      setLeads((c) => [data.lead, ...c]);
      setNewOpen(false);
      setView("records");
      notify("Az új értékesítési adatlap létrejött és elmentettük.");
    } catch {
      notify("Az adatlap mentése nem sikerült. Ellenőrizd az adatokat.");
    }
  };
  const saveLead = async (id: number, changes: Partial<Lead>) => {
    if (dataState !== "live") {
      notify("Nincs élő adatkapcsolat; az adatlap nem módosítható.");
      return false;
    }
    const previous = leads.find((lead) => lead.id === id);
    if (!previous) return false;
    const optimistic = { ...previous, ...changes };
    setLeads((rows) => rows.map((lead) => (lead.id === id ? optimistic : lead)));
    setSelected(optimistic);
    try {
      const response = await authenticatedFetch(`/api/crm/leads/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(changes),
      });
      if (!response.ok) throw new Error();
      const data = (await response.json()) as { lead: Lead };
      setLeads((rows) => rows.map((lead) => (lead.id === id ? data.lead : lead)));
      setSelected(data.lead);
      notify("Az adatlap módosításait elmentettük.");
      return true;
    } catch {
      setLeads((rows) => rows.map((lead) => (lead.id === id ? previous : lead)));
      setSelected(previous);
      notify("Az adatlap mentése nem sikerült. Próbáld újra.");
      return false;
    }
  };
  const addTask = async (leadId: number, task: NewTask) => {
    if (dataState !== "live") {
      notify("Nincs élő adatkapcsolat; a teendő nem hozható létre.");
      return false;
    }
    try {
      const response = await authenticatedFetch("/api/crm/tasks", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...task, leadId }),
      });
      if (!response.ok) throw new Error();
      const data = (await response.json()) as { task: Task };
      setTasksRaw((rows) => [...rows, data.task]);
      notify("Az új teendőt rögzítettük.");
      return true;
    } catch {
      notify("A teendő mentése nem sikerült. Próbáld újra.");
      return false;
    }
  };
  const addCustomer = async (customer: {
    customerType: "person" | "company";
    name: string;
    email: string;
    phone: string;
    billingAddress: string;
    taxNumber?: string;
  }) => {
    try {
      const response = await authenticatedFetch("/api/crm/customers", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(customer),
      });
      const payload = await response.json() as { customer?: Customer; error?: string };
      if (!response.ok || !payload.customer) throw new Error(payload.error);
      setCustomers((rows) => [payload.customer!, ...rows]);
      setNewCustomerOpen(false);
      notify("Az ügyfél bekerült az élő ügyféltörzsbe.");
      return true;
    } catch (error) {
      notify(error instanceof Error && error.message ? error.message : "Az ügyfél mentése nem sikerült.");
      return false;
    }
  };
  const addContract = async (data: {
    customerId: string;
    title: string;
    contractType: Contract["contractType"];
    netAmount: number;
    vatRate: number;
    effectiveDate: string;
  }) => {
    try {
      const response = await authenticatedFetch("/api/crm/contracts", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(data),
      });
      const payload = await response.json() as { contract?: Contract; error?: string };
      if (!response.ok || !payload.contract) throw new Error(payload.error);
      setContracts((rows) => [payload.contract!, ...rows]);
      setNewContractOpen(false);
      notify("A szerződéstervezet létrejött és auditnaplóba került.");
      return true;
    } catch (error) {
      notify(error instanceof Error && error.message ? error.message : "A szerződés mentése nem sikerült.");
      return false;
    }
  };
  const advanceContract = async (
    contract: Contract,
    status: "review" | "approved" | "signed" | "cancelled",
    targetCompletion?: string,
  ) => {
    try {
      const response = await authenticatedFetch(`/api/crm/contracts/${contract.id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ status, targetCompletion, projectTitle: contract.title }),
      });
      const payload = await response.json() as {
        contract?: Contract;
        project?: BusinessProject;
        error?: string;
      };
      if (!response.ok || !payload.contract) throw new Error(payload.error);
      setContracts((rows) => rows.map((item) => item.id === contract.id ? payload.contract! : item));
      if (payload.project) setBusinessProjects((rows) => [payload.project!, ...rows]);
      notify(status === "signed" ? "A szerződésből létrejött a projekt és a MyImperial hozzáférés." : "A szerződés állapota frissült.");
      return true;
    } catch (error) {
      notify(error instanceof Error && error.message ? error.message : "Az állapotváltás nem sikerült.");
      return false;
    }
  };
  const addCashflowEntry = async (entry: {
    direction: "inflow" | "outflow";
    category: string;
    counterparty: string;
    description: string;
    projectId: string;
    amount: number;
    dueDate: string;
    status: "planned" | "due";
  }) => {
    try {
      const response = await authenticatedFetch("/api/crm/finance/cashflow", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(entry),
      });
      const payload = await response.json() as { entry?: CashflowEntry; error?: string };
      if (!response.ok || !payload.entry) throw new Error(payload.error);
      await refreshCashflow();
      setNewCashflowOpen(false);
      notify("A cashflow-tételt auditáltan rögzítettük.");
      return true;
    } catch (error) {
      notify(error instanceof Error && error.message ? error.message : "A cashflow-tétel mentése nem sikerült.");
      return false;
    }
  };
  const markCashflowPaid = async (entry: CashflowEntry) => {
    try {
      const response = await authenticatedFetch(`/api/crm/finance/cashflow/${entry.id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ status: "paid" }),
      });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error);
      await refreshCashflow();
      notify("A pénzmozgást teljesítettként rögzítettük.");
    } catch (error) {
      notify(error instanceof Error && error.message ? error.message : "A teljesítés mentése nem sikerült.");
    }
  };
  const initials = identity.name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const roleLabel =
    identity.role === "admin"
      ? "Tulajdonos"
      : identity.role === "sales_manager"
        ? "Értékesítési vezető"
        : "Értékesítő";
  const crmViews = ["pipeline", "records", "customers", "reports", "control"];
  if (dataState === "forbidden") return (
    <main className={accessStyles.page}>
      <section>
        <Logo />
        <span><Icon name="lock" /></span>
        <small>BELSŐ IMPERIAL RENDSZER</small>
        <h1>Ehhez a felülethez nincs hozzáférésed</h1>
        <p>Az ügyfél- és kapcsolattartói fiókok kizárólag a saját MyImperial projektterüket érhetik el. A CRM értékesítési és vezetői adatai belső használatúak.</p>
        <a href="/myimperial">Vissza a MyImperial projekthez</a>
      </section>
    </main>
  );
  if (dataState === "unavailable") return (
    <main className={accessStyles.page}>
      <section>
        <Logo />
        <span><Icon name="alert" /></span>
        <small>BELSŐ IMPERIAL RENDSZER</small>
        <h1>Az élő CRM-adatkapcsolat most nem érhető el</h1>
        <p>Biztonsági okból a rendszer nem jelenít meg mintaadatokat, és nem enged helyi mentést. Próbáld újra később, vagy jelezd a rendszerüzemeltetőnek.</p>
        <button onClick={() => window.location.reload()}>Újrapróbálás</button>
      </section>
    </main>
  );
  return (
    <main className="app-shell">
      <aside className={`sidebar ${mobileOpen ? "open" : ""}`}>
        <div className="mobile-brand-row">
          <Logo />
          <button onClick={() => setMobileOpen(false)}>
            <Icon name="close" />
          </button>
        </div>
        <div className="desktop-brand">
          <Logo />
        </div>
        <nav className="side-nav">
          <span className="nav-label">MUNKA</span>
          <button
            className={view === "today" ? "active" : ""}
            onClick={() => changeView("today")}
          >
            <Icon name="check" />
            <span>Mai napom</span>
            <em>{tasks.filter((t) => !t.done).length}</em>
          </button>
          <button
            className={crmViews.includes(view) ? "active" : ""}
            onClick={() => changeView("pipeline")}
          >
            <Icon name="sales" />
            <span>Értékesítés</span>
          </button>
          <button
            className={view === "projects" ? "active" : ""}
            onClick={() => changeView("projects")}
          >
            <Icon name="project" />
            <span>Projektek</span>
          </button>
          <button
            className={view === "calendar" ? "active" : ""}
            onClick={() => changeView("calendar")}
          >
            <Icon name="calendar" />
            <span>Okosnaptár</span>
          </button>
          <button onClick={() => (window.location.href = "/myimperial")}>
            <Icon name="user" />
            <span>MyImperial</span>
          </button>
          <span className="nav-label intelligence-label">INTELLIGENCE</span>
          <button
            className={view === "modules" ? "active" : ""}
            onClick={() => changeView("modules")}
          >
            <Icon name="grid" />
            <span>Rendszerleltár</span>
          </button>
          <button
            className={view === "executive" ? "active" : ""}
            onClick={() => changeView("executive")}
          >
            <Icon name="grid" />
            <span>Vezetői központ</span>
          </button>
          <button
            className={view === "finance" ? "active" : ""}
            onClick={() => changeView("finance")}
          >
            <Icon name="finance" />
            <span>Pénzügy</span>
          </button>
          <button
            className={view === "knowledge" ? "active" : ""}
            onClick={() => changeView("knowledge")}
          >
            <Icon name="search" />
            <span>Tudásbázis</span>
          </button>
          <button
            className={view === "agents" ? "active" : ""}
            onClick={() => changeView("agents")}
          >
            <Icon name="bot" />
            <span>AI ügynökök</span>
          </button>
          <button
            className={view === "audit" ? "active" : ""}
            onClick={() => changeView("audit")}
          >
            <Icon name="audit" />
            <span>Audit</span>
          </button>
        </nav>
        <button
          className="secondary"
          onClick={() => window.location.assign("/communications/whatsapp")}
        >
          WhatsApp
        </button>
        <div className="sidebar-footer">
          <span>Imperial Sales CRM</span>
          <small>Executive UI · v1.5</small>
        </div>
      </aside>
      {mobileOpen && (
        <button className="scrim" onClick={() => setMobileOpen(false)} />
      )}
      <section className="main-area">
        <header className="topbar">
          <button className="menu-button" onClick={() => setMobileOpen(true)}>
            <Icon name="menu" />
          </button>
          <div className="page-heading">
            <span>IMPERIAL HOLDING GROUP</span>
            <h1>{viewTitle(view)}</h1>
          </div>
          <div className="top-actions">
            <span className={`data-pill ${dataState}`}>
              <i />
              {dataState === "live" ? "ÉLŐ ADATOK" : "KAPCSOLÓDÁS"}
            </span>
            <span className="private-pill">
              <Icon name="shield" /> BELSŐ RENDSZER
            </span>
            <button
              className="bell"
              onClick={() =>
                notify("2 értékesítési figyelmeztetés vár ellenőrzésre.")
              }
            >
              <Icon name="bell" />
              <i />
            </button>
            <button className="quick-add" onClick={() => setNewOpen(true)}>
              <Icon name="plus" /> Új adatlap
            </button>
            {identity.role === "admin" && (
              <button
                className="bell"
                title="Felhasználók és jogosultságok"
                onClick={() => window.location.assign("/admin/access")}
              >
                <Icon name="shield" />
              </button>
            )}
            <span className="avatar">{initials || "CRM"}</span>
            <span className="user-name">
              <strong>{identity.name}</strong>
              <small>{roleLabel}</small>
            </span>
            <button className="bell" title="Kilépés" onClick={logout}>
              <Icon name="close" />
            </button>
          </div>
        </header>
        {crmViews.includes(view) && (
          <nav className="product-tabs">
            <button onClick={() => changeView("today")}>Mai napom</button>
            <button
              className={view === "pipeline" ? "active" : ""}
              onClick={() => changeView("pipeline")}
            >
              Pipeline
            </button>
            <button
              className={view === "records" ? "active" : ""}
              onClick={() => changeView("records")}
            >
              Adatlapok
            </button>
            <button
              className={view === "customers" ? "active" : ""}
              onClick={() => changeView("customers")}
            >
              Ügyfelek
            </button>
            <button
              className={view === "reports" ? "active" : ""}
              onClick={() => changeView("reports")}
            >
              Riportok
            </button>
            <button
              className={view === "control" ? "active" : ""}
              onClick={() => changeView("control")}
            >
              Sales Control
            </button>
          </nav>
        )}
        <div className="page-content">
          {view === "today" ? (
            <Today
              leads={leads}
              tasks={tasks.filter((t) => !t.done)}
              onComplete={(id) => {
                setTasks((c) =>
                  c.map((t) => (t.id === id ? { ...t, done: true } : t)),
                );
                notify("A teendő elkészült.");
              }}
              onLead={setSelected}
              onPipeline={() => setView("pipeline")}
            />
          ) : view === "pipeline" ? (
            <Pipeline
              leads={filtered}
              query={query}
              setQuery={setQuery}
              brand={brand}
              setBrand={setBrand}
              owner={owner}
              setOwner={setOwner}
              mode={mode}
              setMode={setMode}
              onMove={moveLead}
              onLead={setSelected}
              onNew={() => setNewOpen(true)}
            />
          ) : view === "records" ? (
            <Records
              leads={filtered}
              query={query}
              setQuery={setQuery}
              brand={brand}
              setBrand={setBrand}
              owner={owner}
              setOwner={setOwner}
              onLead={setSelected}
              onNew={() => setNewOpen(true)}
            />
          ) : view === "customers" ? (
            <Customers
              customers={customers}
              contracts={contracts}
              projects={businessProjects}
              identity={identity}
              onNewCustomer={() => setNewCustomerOpen(true)}
              onNewContract={() => setNewContractOpen(true)}
              onAdvanceContract={advanceContract}
            />
          ) : view === "reports" ? (
            <Reports leads={leads} />
          ) : view === "finance" ? (
            <Finance
              invoices={invoices}
              importStatus={importStatus}
              cashflow={cashflow}
              onNew={() => setNewCashflowOpen(true)}
              onPaid={markCashflowPaid}
            />
          ) : view === "executive" ? (
            <ExecutiveDashboard
              leads={leads}
              tasks={tasks.filter((task) => !task.done)}
              onLead={setSelected}
              onNavigate={changeView}
              notify={notify}
            />
          ) : view === "modules" ? (
            intelligence
              ? <ModulesWorkspace data={intelligence} />
              : <IntelligenceLoading />
          ) : view === "projects" ? (
            intelligence
              ? <ProjectsWorkspace data={intelligence} />
              : <IntelligenceLoading />
          ) : view === "calendar" ? (
            intelligence
              ? <CalendarWorkspace data={intelligence} />
              : <IntelligenceLoading />
          ) : view === "knowledge" ? (
            intelligence
              ? <KnowledgeWorkspace data={intelligence} onReview={resolveImportReview} />
              : <IntelligenceLoading />
          ) : view === "agents" ? (
            intelligence
              ? <AgentsWorkspace data={intelligence} />
              : <IntelligenceLoading />
          ) : view === "audit" ? (
            intelligence
              ? <AuditWorkspace data={intelligence} />
              : <IntelligenceLoading />
          ) : (
            <Control leads={leads} onLead={setSelected} />
          )}
        </div>
      </section>
      {selected && (
        <LeadDrawer
          lead={selected}
          onClose={() => setSelected(null)}
          onStage={(stage) => {
            moveLead(selected.id, stage);
            setSelected({ ...selected, stage });
          }}
          tasks={tasks.filter((task) => task.leadId === selected.id && !task.done)}
          onSave={(changes) => saveLead(selected.id, changes)}
          onAddTask={(task) => addTask(selected.id, task)}
          onCompleteTask={(id) => {
            setTasks((rows) =>
              rows.map((task) => (task.id === id ? { ...task, done: true } : task)),
            );
            notify("A teendő elkészült.");
          }}
          notify={notify}
        />
      )}{" "}
      {newOpen && (
        <NewLeadModal onClose={() => setNewOpen(false)} onSave={addLead} />
      )}{" "}
      {newCustomerOpen && (
        <NewCustomerModal onClose={() => setNewCustomerOpen(false)} onSave={addCustomer} />
      )}{" "}
      {newContractOpen && (
        <NewContractModal customers={customers} onClose={() => setNewContractOpen(false)} onSave={addContract} />
      )}{" "}
      {newCashflowOpen && (
        <NewCashflowModal projects={businessProjects} onClose={() => setNewCashflowOpen(false)} onSave={addCashflowEntry} />
      )}{" "}
      {toast && (
        <div className="toast">
          <Icon name="check" />
          {toast}
        </div>
      )}
    </main>
  );
}

function IntelligenceLoading() {
  return (
    <section className="empty">
      <h2>A közös rendszeradatok betöltése folyamatban van</h2>
      <p>Ha ez tartósan így marad, ellenőrizni kell a helyi adatbázis-kapcsolatot.</p>
    </section>
  );
}

function Today({
  leads,
  tasks,
  onComplete,
  onLead,
  onPipeline,
}: {
  leads: Lead[];
  tasks: Task[];
  onComplete: (id: number) => void;
  onLead: (l: Lead) => void;
  onPipeline: () => void;
}) {
  const urgent = leads.filter((l) => l.health !== "green").slice(0, 4);
  return (
    <>
      <section className="welcome">
        <div>
          <p className="eyebrow">VASÁRNAP, 2026. JÚLIUS 19.</p>
          <h2>Jó reggelt, Csaba!</h2>
          <p>
            A mai fókusz: <strong>4 teendő</strong>, ebből <b>1 lejárt</b>. A
            pipeline-ban 3 kiemelt lehetőség vár döntésre.
          </p>
        </div>
        <button className="primary" onClick={onPipeline}>
          Pipeline megnyitása <Icon name="arrow" />
        </button>
      </section>
      <section className="kpis">
        <article className="danger">
          <span>Lejárt teendő</span>
          <strong>1</strong>
          <small>Azonnali figyelmet igényel</small>
        </article>
        <article>
          <span>Mai teendő</span>
          <strong>{tasks.length}</strong>
          <small>Saját és csapatfeladatok</small>
        </article>
        <article>
          <span>Nyitott adatlap</span>
          <strong>{leads.length}</strong>
          <small>{money(leads.reduce((s, l) => s + l.value, 0))} érték</small>
        </article>
        <article className="warning">
          <span>Érintést igényel</span>
          <strong>{urgent.length}</strong>
          <small>SLA vagy adatminőség miatt</small>
        </article>
      </section>
      <div className="today-grid">
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">TEENDŐK</p>
              <h3>A mai munkasor</h3>
            </div>
            <span className="count">{tasks.length}</span>
          </div>
          <div className="task-list">
            {tasks.map((t) => (
              <article className={`task ${t.priority}`} key={t.id}>
                <button className="task-check" onClick={() => onComplete(t.id)}>
                  <Icon name="check" />
                </button>
                <div className="task-body">
                  <p>
                    <span>{t.type}</span>
                    <i className={`priority ${t.priority}`} />
                    {t.due}
                    {t.ai && <em>AI</em>}
                  </p>
                  <strong>{t.title}</strong>
                  <button
                    onClick={() => {
                      const l = leads.find((x) => x.id === t.leadId);
                      if (l) onLead(l);
                    }}
                  >
                    {t.leadName} <Icon name="arrow" />
                  </button>
                </div>
                <span className="mini-avatar">KA</span>
              </article>
            ))}
          </div>
        </section>
        <aside className="side-stack">
          <section className="panel">
            <div className="panel-head">
              <div>
                <p className="eyebrow">SALES COPILOT</p>
                <h3>Következő érintések</h3>
              </div>
              <button onClick={onPipeline}>Mind</button>
            </div>
            {urgent.map((l) => (
              <button
                className="touch-row"
                key={l.id}
                onClick={() => onLead(l)}
              >
                <i className={`temperature ${l.temperature}`} />
                <span>
                  <strong>{l.name}</strong>
                  <small>{l.nextAction}</small>
                </span>
                <b>{l.score}</b>
              </button>
            ))}
          </section>
          <section className="ai-brief">
            <div>
              <Icon name="bot" />
            </div>
            <span>
              <p>AI NAPI ÖSSZEFOGLALÓ</p>
              <strong>
                A Váci Prefab projekt a legnagyobb mai bevételi esély.
              </strong>
              <small>Javaslat: döntési akadály feltárása 11:00 előtt.</small>
            </span>
          </section>
        </aside>
      </div>
    </>
  );
}

function FilterBar({
  query,
  setQuery,
  brand,
  setBrand,
  owner,
  setOwner,
  children,
}: {
  query: string;
  setQuery: (v: string) => void;
  brand: string;
  setBrand: (v: string) => void;
  owner: string;
  setOwner: (v: string) => void;
  children?: React.ReactNode;
}) {
  return (
    <div className="filterbar">
      <label className="search">
        <Icon name="search" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Név, projekt, település vagy e-mail…"
        />
      </label>
      <select value={owner} onChange={(e) => setOwner(e.target.value)}>
        <option>Mind</option>
        <option>Kiss Andrea</option>
        <option>Farkas Bence</option>
      </select>
      <select value={brand} onChange={(e) => setBrand(e.target.value)}>
        <option>Mind</option>
        <option>Imperial</option>
        <option>Prefab</option>
        <option>Danish Fabrik</option>
        <option>BauFreund</option>
        <option>Bautica</option>
      </select>
      {children}
    </div>
  );
}

function Pipeline({
  leads,
  query,
  setQuery,
  brand,
  setBrand,
  owner,
  setOwner,
  mode,
  setMode,
  onMove,
  onLead,
  onNew,
}: {
  leads: Lead[];
  query: string;
  setQuery: (v: string) => void;
  brand: string;
  setBrand: (v: string) => void;
  owner: string;
  setOwner: (v: string) => void;
  mode: "kanban" | "list";
  setMode: (v: "kanban" | "list") => void;
  onMove: (id: number, s: Stage) => void;
  onLead: (l: Lead) => void;
  onNew: () => void;
}) {
  const total = leads.reduce((s, l) => s + l.value, 0),
    weighted = leads.reduce((s, l) => s + (l.value * l.probability) / 100, 0);
  return (
    <>
      <section className="pipeline-summary">
        <div>
          <small>Nyitott adatlap</small>
          <strong>{leads.length}</strong>
        </div>
        <div>
          <small>Pipeline érték</small>
          <strong>{money(total)}</strong>
        </div>
        <div>
          <small>Súlyozott várható érték</small>
          <strong>{money(weighted)}</strong>
        </div>
        <div>
          <small>Várható konverzió</small>
          <strong>31,4%</strong>
          <span>+4,2% előző hónaphoz</span>
        </div>
      </section>
      <FilterBar {...{ query, setQuery, brand, setBrand, owner, setOwner }}>
        <div className="mode-switch">
          <button
            className={mode === "kanban" ? "active" : ""}
            onClick={() => setMode("kanban")}
          >
            <Icon name="grid" />
          </button>
          <button
            className={mode === "list" ? "active" : ""}
            onClick={() => setMode("list")}
          >
            <Icon name="list" />
          </button>
        </div>
        <button className="primary compact" onClick={onNew}>
          <Icon name="plus" /> Új adatlap
        </button>
      </FilterBar>
      {mode === "kanban" ? (
        <div className="kanban">
          {stages.map((s) => {
            const group = leads.filter((l) => l.stage === s.id);
            return (
              <section
                className="kanban-column"
                key={s.id}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) =>
                  onMove(Number(e.dataTransfer.getData("lead-id")), s.id)
                }
              >
                <header
                  style={{ "--stage-color": s.color } as React.CSSProperties}
                >
                  <div>
                    <strong>{s.label}</strong>
                    <span>{group.length}</span>
                  </div>
                  <small>{money(group.reduce((a, l) => a + l.value, 0))}</small>
                </header>
                <div className="kanban-cards">
                  {group.map((l) => (
                    <LeadCard key={l.id} lead={l} onOpen={() => onLead(l)} />
                  ))}
                  <button className="column-add" onClick={onNew}>
                    <Icon name="plus" /> Új adatlap
                  </button>
                </div>
              </section>
            );
          })}
        </div>
      ) : (
        <LeadTable leads={leads} onLead={onLead} />
      )}
    </>
  );
}
function LeadCard({ lead, onOpen }: { lead: Lead; onOpen: () => void }) {
  return (
    <article
      className="lead-card"
      draggable
      onDragStart={(e) => e.dataTransfer.setData("lead-id", String(lead.id))}
    >
      <div className="lead-card-top">
        <span className="brand-code">{lead.brandCode}</span>
        <i className={`health ${lead.health}`} />
        <i className={`temperature ${lead.temperature}`} />
      </div>
      <button className="lead-link" onClick={onOpen}>
        <strong>{lead.name}</strong>
        <p>{lead.title}</p>
      </button>
      <div className="lead-value">
        <strong>{money(lead.value)}</strong>
        <span>{lead.probability}%</span>
      </div>
      <div className={`next-action ${lead.health === "red" ? "late" : ""}`}>
        <Icon name="clock" />
        <span>
          {lead.nextAction}
          <small>{lead.nextDate}</small>
        </span>
      </div>
      <footer>
        <b>{lead.score}</b>
        <span>{lead.quality}% adat</span>
        <i className="mini-avatar">{lead.ownerInitials}</i>
      </footer>
    </article>
  );
}
function LeadTable({
  leads,
  onLead,
}: {
  leads: Lead[];
  onLead: (l: Lead) => void;
}) {
  return (
    <section className="table-panel">
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Adatlap</th>
              <th>Státusz</th>
              <th>Felelős</th>
              <th>Érték</th>
              <th>Score</th>
              <th>Következő lépés</th>
            </tr>
          </thead>
          <tbody>
            {leads.map((l) => (
              <tr key={l.id} onClick={() => onLead(l)}>
                <td>
                  <strong>{l.name}</strong>
                  <small>{l.title}</small>
                </td>
                <td>
                  <span className="status-chip">
                    {stages.find((s) => s.id === l.stage)?.label}
                  </span>
                </td>
                <td>
                  <span className="mini-avatar">{l.ownerInitials}</span>
                  {l.owner}
                </td>
                <td>
                  <strong>{money(l.value)}</strong>
                  <small>{l.probability}% várható</small>
                </td>
                <td>
                  <i className={`temperature ${l.temperature}`} />
                  <b>{l.score}</b>
                </td>
                <td className={l.health === "red" ? "late-cell" : ""}>
                  {l.nextAction}
                  <small>{l.nextDate}</small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
function Records({
  leads,
  query,
  setQuery,
  brand,
  setBrand,
  owner,
  setOwner,
  onLead,
  onNew,
}: {
  leads: Lead[];
  query: string;
  setQuery: (v: string) => void;
  brand: string;
  setBrand: (v: string) => void;
  owner: string;
  setOwner: (v: string) => void;
  onLead: (l: Lead) => void;
  onNew: () => void;
}) {
  return (
    <div className="records-layout">
      <aside className="status-tree panel">
        <div>
          <strong>Státuszfa</strong>
          <span>{leads.length}</span>
        </div>
        <button className="active">
          Összes adatlap <b>{leads.length}</b>
        </button>
        {stages.map((s) => (
          <button key={s.id}>
            <i style={{ background: s.color }} />
            {s.label}
            <b>{leads.filter((l) => l.stage === s.id).length}</b>
          </button>
        ))}
        <hr />
        <button>
          <Icon name="filter" /> Mentett szűrők
        </button>
      </aside>
      <section className="records-main">
        <FilterBar {...{ query, setQuery, brand, setBrand, owner, setOwner }}>
          <button className="primary compact" onClick={onNew}>
            <Icon name="plus" /> Új adatlap
          </button>
        </FilterBar>
        <LeadTable leads={leads} onLead={onLead} />
      </section>
    </div>
  );
}

function Customers({
  customers,
  contracts,
  projects,
  identity,
  onNewCustomer,
  onNewContract,
  onAdvanceContract,
}: {
  customers: Customer[];
  contracts: Contract[];
  projects: BusinessProject[];
  identity: Identity;
  onNewCustomer: () => void;
  onNewContract: () => void;
  onAdvanceContract: (
    contract: Contract,
    status: "review" | "approved" | "signed" | "cancelled",
    targetCompletion?: string,
  ) => Promise<boolean>;
}) {
  const [targetCompletion, setTargetCompletion] = useState<Record<string, string>>({});
  const contractStatus: Record<Contract["status"], string> = {
    draft: "Tervezet",
    review: "Ellenőrzés alatt",
    approved: "Jóváhagyva",
    signed: "Aláírva",
    cancelled: "Megszüntetve",
  };
  return (
    <>
      <section className="section-title">
        <div>
          <p className="eyebrow">KAPCSOLATOK ÉS CÉGEK</p>
          <h2>Ügyfélközpont</h2>
          <p>
            Élő ügyféltörzs, szerződés-jóváhagyás és projektindítás egy helyen.
          </p>
        </div>
        <button className="secondary" onClick={onNewCustomer}>
          <Icon name="plus" /> Új ügyfél
        </button>
      </section>
      <div className="customer-grid">
        {customers.map((customer) => (
          <article className="customer-card" key={customer.id}>
            <span className="customer-avatar">
              {customer.name
                .split(" ")
                .map((x) => x[0])
                .slice(0, 2)
                .join("")}
            </span>
            <div>
              <strong>{customer.name}</strong>
              <p>{customer.customerType === "company" ? "Vállalati ügyfél" : "Magánszemély"} · {customer.billingAddress}</p>
              <span>{customer.email} · {customer.phone}</span>
            </div>
            <i className={`health ${customer.status === "active" ? "green" : customer.status === "prospect" ? "yellow" : "red"}`} />
            <footer>
              <span>{customer.status === "active" ? "Aktív" : customer.status === "prospect" ? "Érdeklődő" : "Archivált"}</span>
              <b>{contracts.filter((item) => item.customerId === customer.id).length} szerződés</b>
            </footer>
          </article>
        ))}
      </div>
      {customers.length === 0 && (
        <section className="empty"><h2>Még nincs ügyfél az élő törzsben</h2><p>Az „Új ügyfél” gombbal rögzíthető az első ügyfél.</p></section>
      )}

      <section className="section-title">
        <div><p className="eyebrow">SZERZŐDÉS ÉS PROJEKTINDÍTÁS</p><h2>Szerződések</h2><p>Vezetői jóváhagyás után az aláírás automatikusan létrehozza a projektet és a MyImperial tagságot.</p></div>
        <button className="secondary" onClick={onNewContract} disabled={customers.length === 0}><Icon name="plus" /> Új szerződés</button>
      </section>
      <section className="panel">
        <div className="record-table">
          {contracts.map((contract) => (
            <article key={contract.id}>
              <div><small>{contract.contractNumber}</small><strong>{contract.title}</strong><span>{customers.find((item) => item.id === contract.customerId)?.name ?? contract.customerId}</span></div>
              <div><small>Bruttó érték</small><strong>{money(contract.grossAmount)}</strong><span>{contract.effectiveDate}</span></div>
              <div><small>Állapot</small><strong>{contractStatus[contract.status]}</strong><span>{contract.projectId ? `Projekt: ${contract.projectId}` : "Projekt még nincs"}</span></div>
              <div className="row-actions">
                {contract.status === "draft" && <button onClick={() => onAdvanceContract(contract, "review")}>Ellenőrzésre</button>}
                {contract.status === "review" && identity.role !== "sales" && <button onClick={() => onAdvanceContract(contract, "approved")}>Jóváhagyás</button>}
                {contract.status === "approved" && identity.role !== "sales" && (
                  <><input type="date" aria-label={`${contract.contractNumber} tervezett befejezés`} value={targetCompletion[contract.id] ?? ""} onChange={(event) => setTargetCompletion((current) => ({ ...current, [contract.id]: event.target.value }))} /><button disabled={!targetCompletion[contract.id]} onClick={() => onAdvanceContract(contract, "signed", targetCompletion[contract.id])}>Aláírás és projektindítás</button></>
                )}
              </div>
            </article>
          ))}
        </div>
        {contracts.length === 0 && <div className="empty"><h2>Még nincs szerződés</h2></div>}
      </section>

      <section className="section-title"><div><p className="eyebrow">MYIMPERIAL</p><h2>Elindított projektek</h2></div></section>
      <div className="customer-grid">
        {projects.map((project) => (
          <article className="customer-card" key={project.id}>
            <span className="customer-avatar">{project.progress}%</span>
            <div><strong>{project.title}</strong><p>{project.portalCode} · {project.phase}</p><span>Tervezett befejezés: {project.targetCompletion}</span></div>
            <i className="health green" />
          </article>
        ))}
      </div>
    </>
  );
}
function Reports({ leads }: { leads: Lead[] }) {
  const sources = [
    "Google Ads",
    "Weboldal",
    "Ajánlás",
    "Facebook",
    "Baudata",
    "Kiállítás",
  ]
    .map((source) => ({
      source,
      count: leads.filter((l) => l.source === source).length,
      value: leads
        .filter((l) => l.source === source)
        .reduce((s, l) => s + l.value, 0),
    }))
    .filter((x) => x.count);
  return (
    <>
      <section className="section-title">
        <div>
          <p className="eyebrow">ÉRTÉKESÍTÉSI TELJESÍTMÉNY</p>
          <h2>Júliusi vezetői kép</h2>
          <p>A pipeline állapota és a bevételhez vezető kritikus pontok.</p>
        </div>
        <select>
          <option>2026. július</option>
        </select>
      </section>
      <section className="kpis">
        <article>
          <span>Új lead</span>
          <strong>28</strong>
          <small>+16% előző hónaphoz</small>
        </article>
        <article>
          <span>Kiküldött ajánlat</span>
          <strong>11</strong>
          <small>39% lead → ajánlat</small>
        </article>
        <article>
          <span>Szerződés</span>
          <strong>4</strong>
          <small>372 M Ft érték</small>
        </article>
        <article>
          <span>Átlagos ciklus</span>
          <strong>34 nap</strong>
          <small>–6 nap javulás</small>
        </article>
      </section>
      <div className="reports-grid">
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">FORRÁSHATÉKONYSÁG</p>
              <h3>Leadek forrás szerint</h3>
            </div>
          </div>
          <div className="bar-list">
            {sources.map((x) => (
              <div key={x.source}>
                <span>{x.source}</span>
                <div>
                  <i style={{ width: `${Math.max(18, x.count * 30)}%` }} />
                </div>
                <b>{x.count}</b>
                <small>{money(x.value)}</small>
              </div>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">KONVERZIÓS TÖLCSÉR</p>
              <h3>Folyamatlépések</h3>
            </div>
          </div>
          <div className="funnel">
            <div style={{ width: "100%" }}>
              Új lead <b>28</b>
            </div>
            <div style={{ width: "84%" }}>
              Kapcsolat <b>23</b>
            </div>
            <div style={{ width: "66%" }}>
              Konzultáció <b>18</b>
            </div>
            <div style={{ width: "45%" }}>
              Ajánlat <b>11</b>
            </div>
            <div style={{ width: "28%" }}>
              Szerződés <b>4</b>
            </div>
          </div>
        </section>
      </div>
    </>
  );
}
function Finance({
  invoices,
  importStatus,
  cashflow,
  onNew,
  onPaid,
}: {
  invoices: Invoice[];
  importStatus: ImportStatus | null;
  cashflow: CashflowWorkspace | null;
  onNew: () => void;
  onPaid: (entry: CashflowEntry) => void;
}) {
  const signedGross = invoices.reduce(
    (total, invoice) => total + invoice.grossAmount,
    0,
  );
  const matchedCustomers = new Set(
    invoices
      .filter((invoice) => invoice.customerMatchStatus === "matched")
      .map((invoice) => invoice.crmCustomerName),
  ).size;
  const projectReview = invoices.filter(
    (invoice) => invoice.projectMatchStatus !== "matched",
  ).length;
  const sourceCount = importStatus?.recordCounts.reduce(
    (total, row) => total + row.count,
    0,
  ) ?? 0;
  const partnerCount = importStatus?.partnerCounts.reduce(
    (total, row) => total + row.count,
    0,
  ) ?? 0;
  const projectCount = importStatus?.projectCounts.reduce(
    (total, row) => total + row.count,
    0,
  ) ?? 0;
  const openReviewCount = importStatus?.openReviews.reduce(
    (total, row) => total + row.count,
    0,
  ) ?? 0;
  const huf = new Intl.NumberFormat("hu-HU", {
    style: "currency",
    currency: "HUF",
    maximumFractionDigits: 0,
  });
  const hufSummary = cashflow?.summaries.find((item) => item.currency === "HUF");
  return (
    <>
      <section className="section-title">
        <div>
          <p className="eyebrow">PÉNZÜGYI TÉNY ÉS ELŐREJELZÉS</p>
          <h2>Cashflow</h2>
          <p>A tervezett, esedékes és tényleges pénzmozgások elkülönítve; a számlaimport nem minősül automatikusan kifizetésnek.</p>
        </div>
        {cashflow && <button className="secondary" onClick={onNew}><Icon name="plus" /> Új cashflow-tétel</button>}
      </section>
      {cashflow ? (
        <>
          <section className="kpis finance-kpis">
            <article><span>Tényleges egyenleg</span><strong>{huf.format(hufSummary?.actualBalance ?? 0)}</strong><small>Csak teljesített HUF pénzmozgás</small></article>
            <article><span>Várható egyenleg</span><strong>{huf.format(hufSummary?.forecastBalance ?? 0)}</strong><small>Tervezett és esedékes HUF tételek</small></article>
            <article><span>Várható bevétel</span><strong>{huf.format(hufSummary?.forecastInflow ?? 0)}</strong><small>A kiválasztott időszakban</small></article>
            <article className={(hufSummary?.overdueOutflow ?? 0) > 0 ? "warning" : ""}><span>Lejárt esedékes kiadás</span><strong>{huf.format(hufSummary?.overdueOutflow ?? 0)}</strong><small>Kifizetettnek még nem jelölt tételek</small></article>
          </section>
          <section className="table-panel finance-panel">
            <div className="panel-head"><div><p className="eyebrow">CASHFLOW-NAPLÓ</p><h3>Pénzmozgások</h3></div><span className="count">{cashflow.entries.length}</span></div>
            <div className="invoice-table">
              <div className="invoice-row invoice-head"><span>Határidő</span><span>Partner és tétel</span><span>Irány</span><span>Összeg</span><span>Állapot</span></div>
              {cashflow.entries.slice(0, 100).map((entry) => (
                <article className="invoice-row" key={entry.id}>
                  <span><strong>{entry.dueDate}</strong><small>{entry.category}</small></span>
                  <span><strong>{entry.counterparty}</strong><small>{entry.description}</small></span>
                  <span><strong>{entry.direction === "inflow" ? "Bevétel" : "Kiadás"}</strong><small>{entry.sourceType === "imported_invoice" ? "Számlaimport" : "Kézi tétel"}</small></span>
                  <span className={entry.direction === "outflow" ? "negative" : ""}><strong>{entry.currency === "HUF" ? huf.format(entry.amount) : `${entry.amount.toLocaleString("hu-HU")} ${entry.currency}`}</strong></span>
                  <span className="invoice-links"><b className={entry.status === "paid" ? "matched" : "review"}>{entry.status === "planned" ? "Tervezett" : entry.status === "due" ? "Esedékes" : entry.status === "paid" ? "Teljesített" : "Törölt"}</b>{entry.status !== "paid" && entry.status !== "cancelled" && <button onClick={() => onPaid(entry)}>Teljesítve</button>}</span>
                </article>
              ))}
            </div>
          </section>
        </>
      ) : (
        <section className="empty"><h2>A cashflow-hoz pénzügyi jogosultság szükséges</h2><p>A számlajegyzék ettől függetlenül csak olvasható forrásadatként látható.</p></section>
      )}
      <section className="section-title">
        <div>
          <p className="eyebrow">FORRÁSADATOK · BEJÖVŐ SZÁMLÁK</p>
          <h2>Számlapilot</h2>
          <p>
            Drive-forrással igazolt, duplikációvédett számlaadatok és
            CRM-kapcsolatok.
          </p>
        </div>
      </section>
      <section className="kpis finance-kpis">
        <article>
          <span>Importált bizonylat</span>
          <strong>{invoices.length}</strong>
          <small>A sztornók külön bizonylatként szerepelnek</small>
        </article>
        <article>
          <span>Előjeles bruttó érték</span>
          <strong>{huf.format(signedGross)}</strong>
          <small>Az eredeti és sztornó összegek együtt</small>
        </article>
        <article>
          <span>Biztos ügyfélkapcsolat</span>
          <strong>{matchedCustomers}</strong>
          <small>Forrásazonosító és névegyezés alapján</small>
        </article>
        <article className={projectReview ? "warning" : ""}>
          <span>Projektkapcsolat ellenőrzendő</span>
          <strong>{projectReview}</strong>
          <small>Projekt csak valódi adatlaphoz kapcsolható</small>
        </article>
      </section>
      <section className="section-title datahub-title">
        <div>
          <p className="eyebrow">ÉLŐ FORRÁSREGISZTER</p>
          <h2>Importált üzleti adatok</h2>
          <p>
            Ügyfél-, projekt-, szerződés- és partnerforrások. A nagy Drive-fájlok
            hivatkozásként szerepelnek, így nem foglalnak kétszer tárhelyet.
          </p>
        </div>
      </section>
      <section className="kpis datahub-kpis">
        <article>
          <span>Nyilvántartott forrás</span>
          <strong>{sourceCount}</strong>
          <small>Drive-, Gmail- és táblázatrekord</small>
        </article>
        <article>
          <span>Üzleti partner</span>
          <strong>{partnerCount}</strong>
          <small>Alvállalkozó, tervező, beszállító és B2B partner</small>
        </article>
        <article>
          <span>Projekt</span>
          <strong>{projectCount}</strong>
          <small>Forrásmappához kapcsolt projektadat</small>
        </article>
        <article className={openReviewCount ? "warning" : ""}>
          <span>Emberi ellenőrzésre vár</span>
          <strong>{openReviewCount}</strong>
          <small>Bizonytalan kapcsolat vagy hiányos forrásadat</small>
        </article>
      </section>
      {importStatus?.recentRecords.length ? (
        <section className="table-panel source-panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">FORRÁSHIVATKOZÁSOK</p>
              <h3>Legutóbb nyilvántartott dokumentumok</h3>
            </div>
            <span className="count">{importStatus.recentRecords.length}</span>
          </div>
          <div className="source-list">
            {importStatus.recentRecords.slice(0, 25).map((record) => (
              <a
                href={record.sourceUrl}
                key={`${record.recordType}:${record.externalId}`}
                target="_blank"
                rel="noreferrer"
              >
                <span>
                  <strong>{record.title}</strong>
                  <small>{record.recordType.replaceAll("_", " ")}</small>
                </span>
                <b className={record.reviewStatus}>{record.reviewStatus}</b>
                <Icon name="arrow" />
              </a>
            ))}
          </div>
        </section>
      ) : null}
      <section className="table-panel finance-panel">
        <div className="panel-head">
          <div>
            <p className="eyebrow">SZÁMLAJEGYZÉK</p>
            <h3>Importált pénzügyi tételek</h3>
          </div>
          <span className="count">{invoices.length}</span>
        </div>
        {invoices.length ? (
          <div className="invoice-table">
            <div className="invoice-row invoice-head">
              <span>Számla</span>
              <span>Ügyfél és tétel</span>
              <span>Dátum</span>
              <span>Bruttó</span>
              <span>Kapcsolatok</span>
            </div>
            {invoices.map((invoice) => (
              <article className="invoice-row" key={invoice.id}>
                <span>
                  <strong>{invoice.invoiceNumber}</strong>
                  <small>
                    {invoice.invoiceType === "storno"
                      ? `Sztornó · ${invoice.referencedInvoiceNumber}`
                      : invoice.paymentMethod}
                  </small>
                </span>
                <span>
                  <strong>{invoice.buyerName}</strong>
                  <small>{invoice.description}</small>
                </span>
                <span>
                  <strong>{invoice.issueDate}</strong>
                  <small>Határidő: {invoice.dueDate}</small>
                </span>
                <span className={invoice.grossAmount < 0 ? "negative" : ""}>
                  <strong>{huf.format(invoice.grossAmount)}</strong>
                  <small>Nettó: {huf.format(invoice.netAmount)}</small>
                </span>
                <span className="invoice-links">
                  <b className="matched">Ügyfél kapcsolva</b>
                  <b className={
                    invoice.projectMatchStatus === "matched"
                      ? "matched"
                      : "review"
                  }>
                    {invoice.projectMatchStatus === "matched"
                      ? invoice.projectTitle
                      : "Projekt ellenőrzendő"}
                  </b>
                </span>
              </article>
            ))}
          </div>
        ) : (
          <div className="finance-empty">
            Még nincs importált számlaadat ebben a környezetben.
          </div>
        )}
      </section>
    </>
  );
}
function Control({
  leads,
  onLead,
}: {
  leads: Lead[];
  onLead: (l: Lead) => void;
}) {
  const risks = leads.filter((l) => l.health !== "green");
  return (
    <>
      <section className="control-banner">
        <div>
          <Icon name="shield" />
        </div>
        <span>
          <p className="eyebrow">SALES SLA GUARDIAN</p>
          <h2>Értékesítési kontrollközpont</h2>
          <p>
            A bevételt veszélyeztető elakadások, hiányzó adatok és lejárt
            vállalások.
          </p>
        </span>
        <b>{risks.length} aktív jelzés</b>
      </section>
      <div className="control-grid">
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">KRITIKUS ADATLAPOK</p>
              <h3>Beavatkozást igényel</h3>
            </div>
          </div>
          {risks.map((l) => (
            <button className="risk-row" key={l.id} onClick={() => onLead(l)}>
              <i className={`health ${l.health}`} />
              <span>
                <strong>{l.name}</strong>
                <small>
                  {l.health === "red"
                    ? "Lejárt következő lépés"
                    : "Adatminőség vagy SLA figyelmeztetés"}
                </small>
              </span>
              <b>{money(l.value)}</b>
              <Icon name="arrow" />
            </button>
          ))}
        </section>
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">CSAPATTERHELÉS</p>
              <h3>Nyitott feladatok</h3>
            </div>
          </div>
          <div className="team-load">
            <div>
              <span className="avatar">KA</span>
              <p>
                <strong>Kiss Andrea</strong>
                <small>5 adatlap · 3 teendő</small>
              </p>
              <i>
                <b style={{ width: "78%" }} />
              </i>
              <em>78%</em>
            </div>
            <div>
              <span className="avatar alt">FB</span>
              <p>
                <strong>Farkas Bence</strong>
                <small>3 adatlap · 2 teendő</small>
              </p>
              <i>
                <b style={{ width: "46%" }} />
              </i>
              <em>46%</em>
            </div>
          </div>
        </section>
      </div>
    </>
  );
}

function ExecutiveDashboard({
  leads,
  tasks,
  onLead,
  onNavigate,
  notify,
}: {
  leads: Lead[];
  tasks: Task[];
  onLead: (lead: Lead) => void;
  onNavigate: (view: View) => void;
  notify: (message: string) => void;
}) {
  const [period, setPeriod] = useState("30");
  const [scenarioLift, setScenarioLift] = useState(5);
  const total = leads.reduce((sum, lead) => sum + lead.value, 0);
  const weighted = leads.reduce(
    (sum, lead) => sum + (lead.value * lead.probability) / 100,
    0,
  );
  const targetMargin = weighted * 0.35;
  const scenarioValue = weighted * (1 + scenarioLift / 100);
  const risks = leads.filter((lead) => lead.health !== "green");
  const criticalTasks = tasks.filter(
    (task) => task.priority === "critical" || task.priority === "high",
  );
  const topOpportunities = [...leads]
    .sort(
      (a, b) => b.value * b.probability - a.value * a.probability,
    )
    .slice(0, 3);
  const urgentLead =
    leads.find((lead) => lead.health === "red") ?? topOpportunities[0];
  const contractReady = leads.filter(
    (lead) => lead.stage === "negotiation" || lead.stage === "contract",
  );
  const stageMaximum = Math.max(
    1,
    ...stages.map(
      (stage) => leads.filter((lead) => lead.stage === stage.id).length,
    ),
  );
  const dateLabel = new Intl.DateTimeFormat("hu-HU", {
    month: "long",
    day: "numeric",
    weekday: "long",
  })
    .format(new Date())
    .toUpperCase();

  return (
    <div className="executive-shell">
      <section className="executive-hero">
        <div className="executive-hero-copy">
          <p className="eyebrow">DIGITAL BOARD MEMBER · {dateLabel}</p>
          <h2>Jó reggelt, Csaba. Ez igényel ma tulajdonosi figyelmet.</h2>
          <p>
            A rendszer a realizálható profitot, a bevételi esélyeket és a
            beavatkozást igénylő kockázatokat rangsorolja.
          </p>
        </div>
        <div className="executive-controls">
          <span className="objective-badge">
            <i /> AKTÍV CÉLFÜGGVÉNY
          </span>
          <select value={period} onChange={(event) => setPeriod(event.target.value)}>
            <option value="7">Következő 7 nap</option>
            <option value="30">Következő 30 nap</option>
            <option value="90">Következő 90 nap</option>
          </select>
        </div>
      </section>

      <section className="executive-kpis">
        <article>
          <span>Súlyozott szerződésállomány</span>
          <strong>{money(weighted)}</strong>
          <small>{money(total)} teljes nyitott pipeline</small>
          <i className="kpi-accent green" />
        </article>
        <article>
          <span>Várható árréstömeg</span>
          <strong>{money(targetMargin)}</strong>
          <small>35% vállalati célfedezettel számolva</small>
          <i className="kpi-accent gold" />
        </article>
        <article className={risks.length ? "attention" : ""}>
          <span>Beavatkozást igényel</span>
          <strong>{risks.length}</strong>
          <small>értékesítési kockázat vagy SLA-jelzés</small>
          <button onClick={() => onNavigate("control")}>Megnyitás</button>
        </article>
        <article className={criticalTasks.length ? "attention" : ""}>
          <span>Kritikus munkasor</span>
          <strong>{criticalTasks.length}</strong>
          <small>magas vagy kritikus prioritású teendő</small>
          <button onClick={() => onNavigate("today")}>Mai napom</button>
        </article>
      </section>

      <div className="executive-main-grid">
        <section className="executive-panel decision-brief">
          <header>
            <div>
              <p className="eyebrow">NAPI VEZETŐI BRIEFING</p>
              <h3>A három legfontosabb ügy</h3>
            </div>
            <span>AI rangsorolás</span>
          </header>
          <div className="brief-list">
            <button onClick={() => urgentLead && onLead(urgentLead)}>
              <b className="brief-rank critical">1</b>
              <span>
                <em>AZONNALI BEAVATKOZÁS</em>
                <strong>
                  {urgentLead?.name ?? "Nincs kritikus értékesítési ügy"}
                </strong>
                <small>
                  {urgentLead?.nextAction ?? "A munkasor jelenleg rendezett."}
                </small>
              </span>
              <i>{urgentLead ? money(urgentLead.value) : "—"}</i>
              <Icon name="arrow" />
            </button>
            <button
              onClick={() => topOpportunities[0] && onLead(topOpportunities[0])}
            >
              <b className="brief-rank opportunity">2</b>
              <span>
                <em>LEGERŐSEBB BEVÉTELI ESÉLY</em>
                <strong>{topOpportunities[0]?.name ?? "Nincs nyitott ügy"}</strong>
                <small>
                  {topOpportunities[0]
                    ? `${topOpportunities[0].probability}% valószínűség · ${topOpportunities[0].nextAction}`
                    : "Nincs értékelhető pipeline-adat."}
                </small>
              </span>
              <i>{topOpportunities[0] ? money(topOpportunities[0].value) : "—"}</i>
              <Icon name="arrow" />
            </button>
            <button onClick={() => onNavigate("pipeline")}>
              <b className="brief-rank decision">3</b>
              <span>
                <em>DÖNTÉSRE KÖZELI ÜGYEK</em>
                <strong>{contractReady.length} adatlap tárgyalási szakaszban</strong>
                <small>
                  {money(contractReady.reduce((sum, lead) => sum + lead.value, 0))}
                  {" "}lehetséges szerződésérték.
                </small>
              </span>
              <i>{period} nap</i>
              <Icon name="arrow" />
            </button>
          </div>
        </section>

        <aside className="executive-panel company-pulse">
          <header>
            <div>
              <p className="eyebrow">VÁLLALATI PULZUS</p>
              <h3>Modulok állapota</h3>
            </div>
          </header>
          <div className="pulse-list">
            <button onClick={() => onNavigate("pipeline")}>
              <span className="pulse-icon live"><Icon name="sales" /></span>
              <span><strong>CRM Sales</strong><small>{leads.length} nyitott adatlap</small></span>
              <b className="module-status live">ÉLŐ</b>
            </button>
            <button onClick={() => notify("A Finance Intelligence adatkapcsolata a következő fejlesztési ütemben aktiválható.")}>
              <span className="pulse-icon"><Icon name="finance" /></span>
              <span><strong>Pénzügy</strong><small>Cash-flow és tényadatok</small></span>
              <b className="module-status waiting">BEKÖTÉSRE VÁR</b>
            </button>
            <button onClick={() => notify("A PM Cockpit projektadatait a következő ütemben kapcsolom a dashboardhoz.")}>
              <span className="pulse-icon"><Icon name="project" /></span>
              <span><strong>Projektek</strong><small>Határidő, fedezet, kapacitás</small></span>
              <b className="module-status waiting">BEKÖTÉSRE VÁR</b>
            </button>
            <button onClick={() => notify("A Marketing Intelligence kampányadatai még nem érkeznek élő adatforrásból.")}>
              <span className="pulse-icon"><Icon name="grid" /></span>
              <span><strong>Marketing</strong><small>Lead, CAC, ROAS, konverzió</small></span>
              <b className="module-status waiting">BEKÖTÉSRE VÁR</b>
            </button>
          </div>
        </aside>
      </div>

      <div className="executive-lower-grid">
        <section className="executive-panel value-flow">
          <header>
            <div>
              <p className="eyebrow">ÉRTÉKTEREMTÉSI FOLYAMAT</p>
              <h3>Hol áll jelenleg a bevétel?</h3>
            </div>
            <button onClick={() => onNavigate("pipeline")}>Pipeline megnyitása</button>
          </header>
          <div className="executive-stage-list">
            {stages.map((stage) => {
              const stageLeads = leads.filter((lead) => lead.stage === stage.id);
              const stageValue = stageLeads.reduce((sum, lead) => sum + lead.value, 0);
              return (
                <div key={stage.id}>
                  <span><i style={{ background: stage.color }} />{stage.label}</span>
                  <div><b style={{ width: `${(stageLeads.length / stageMaximum) * 100}%`, background: stage.color }} /></div>
                  <strong>{stageLeads.length}</strong>
                  <small>{money(stageValue)}</small>
                </div>
              );
            })}
          </div>
        </section>

        <section className="executive-panel scenario-panel">
          <header>
            <div>
              <p className="eyebrow">MI LENNE, HA…?</p>
              <h3>Gyors forgatókönyv</h3>
            </div>
            <Icon name="bot" />
          </header>
          <p>Ha a súlyozott konverzió javulna:</p>
          <div className="scenario-switch">
            {[0, 5, 10, 15].map((lift) => (
              <button key={lift} className={scenarioLift === lift ? "active" : ""} onClick={() => setScenarioLift(lift)}>
                {lift === 0 ? "Alap" : `+${lift}%`}
              </button>
            ))}
          </div>
          <div className="scenario-result">
            <span><small>Várható szerződésállomány</small><strong>{money(scenarioValue)}</strong></span>
            <span><small>35% célfedezet</small><strong>{money(scenarioValue * 0.35)}</strong></span>
          </div>
          <small className="scenario-note">
            Szimuláció a jelenlegi CRM pipeline alapján; nem pénzügyi előrejelzés.
          </small>
        </section>
      </div>

      <section className="executive-panel board-decisions">
        <header>
          <div>
            <p className="eyebrow">DÖNTÉSI KÖZPONT</p>
            <h3>Előkészített vezetői döntések</h3>
          </div>
          <span>Az AI javasol, a vezető dönt</span>
        </header>
        <div className="decision-cards">
          {topOpportunities.map((lead, index) => (
            <article key={lead.id}>
              <div><span>{index + 1}</span><i className={`health ${lead.health}`} /></div>
              <small>{lead.brand} · {stages.find((stage) => stage.id === lead.stage)?.label}</small>
              <strong>{lead.name}</strong>
              <p>{lead.nextAction}</p>
              <footer><b>{money(lead.value)}</b><button onClick={() => onLead(lead)}>Áttekintem <Icon name="arrow" /></button></footer>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function LeadDrawer({
  lead,
  onClose,
  onStage,
  tasks,
  onSave,
  onAddTask,
  onCompleteTask,
  notify,
}: {
  lead: Lead;
  onClose: () => void;
  onStage: (s: Stage) => void;
  tasks: Task[];
  onSave: (changes: Partial<Lead>) => Promise<boolean>;
  onAddTask: (task: NewTask) => Promise<boolean>;
  onCompleteTask: (id: number) => void;
  notify: (m: string) => void;
}) {
  const [tab, setTab] = useState<"overview" | "activity" | "tasks">("overview");
  const [editing, setEditing] = useState(false);
  const [taskOpen, setTaskOpen] = useState(false);
  return (
    <div className="drawer-layer">
      <button className="drawer-scrim" onClick={onClose} />
      <aside className="lead-drawer">
        <header>
          <div>
            <span className="brand-code">{lead.brandCode}</span>
            <p>{lead.brand}</p>
            <h2>{lead.name}</h2>
            <small>{lead.title}</small>
          </div>
          <button onClick={onClose}>
            <Icon name="close" />
          </button>
        </header>
        <div className="drawer-score">
          <div>
            <span>Lead score</span>
            <strong>{lead.score}</strong>
          </div>
          <div>
            <span>Adatminőség</span>
            <strong>{lead.quality}%</strong>
          </div>
          <div>
            <span>Várható érték</span>
            <strong>{money(lead.value)}</strong>
          </div>
        </div>
        <nav>
          <button
            className={tab === "overview" ? "active" : ""}
            onClick={() => setTab("overview")}
          >
            Áttekintés
          </button>
          <button
            className={tab === "activity" ? "active" : ""}
            onClick={() => setTab("activity")}
          >
            Kommunikáció
          </button>
          <button
            className={tab === "tasks" ? "active" : ""}
            onClick={() => setTab("tasks")}
          >
            Teendők
          </button>
        </nav>
        <div className="drawer-content">
          {tab === "overview" ? (
            <>
              <div className="drawer-actions">
                <div>
                  <strong>Adatlap részletei</strong>
                  <small>Minden lényeges értékesítési adat egy helyen.</small>
                </div>
                <button className="secondary" onClick={() => setEditing(!editing)}>
                  {editing ? "Szerkesztés bezárása" : "Adatok szerkesztése"}
                </button>
              </div>
              {editing && (
                <LeadEditForm
                  lead={lead}
                  onCancel={() => setEditing(false)}
                  onSave={async (changes) => {
                    const saved = await onSave(changes);
                    if (saved) setEditing(false);
                  }}
                />
              )}
              <section className="drawer-section stage-section">
                <label>
                  Értékesítési státusz
                  <select
                    value={lead.stage}
                    onChange={(e) => onStage(e.target.value as Stage)}
                  >
                    {stages.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="next-box">
                  <Icon name="clock" />
                  <span>
                    <small>KÖVETKEZŐ LÉPÉS</small>
                    <strong>{lead.nextAction}</strong>
                    <p>{lead.nextDate}</p>
                  </span>
                </div>
              </section>
              <section className="drawer-section">
                <h3>Kapcsolattartás</h3>
                <div className="contact-grid">
                  <button onClick={() => notify("Hívásfeladat létrehozva.")}>
                    <Icon name="phone" />
                    <span>{lead.phone}</span>
                  </button>
                  <button
                    onClick={() =>
                      notify(
                        "E-mail piszkozat előkészítve; kiküldéshez jóváhagyás kell.",
                      )
                    }
                  >
                    <Icon name="mail" />
                    <span>{lead.email}</span>
                  </button>
                </div>
              </section>
              <section className="drawer-section">
                <h3>Projektadatok</h3>
                <dl>
                  <div>
                    <dt>Helyszín</dt>
                    <dd>{lead.location}</dd>
                  </div>
                  <div>
                    <dt>Projekt típusa</dt>
                    <dd>{lead.projectType}</dd>
                  </div>
                  <div>
                    <dt>Technológia</dt>
                    <dd>{lead.technology}</dd>
                  </div>
                  <div>
                    <dt>Forrás</dt>
                    <dd>{lead.source}</dd>
                  </div>
                  <div>
                    <dt>Telek</dt>
                    <dd>{lead.plot ? "Rendelkezésre áll" : "Ellenőrzendő"}</dd>
                  </div>
                  <div>
                    <dt>Finanszírozás</dt>
                    <dd>{lead.financing ? "Rendezett" : "Egyeztetendő"}</dd>
                  </div>
                </dl>
              </section>
              <section className="drawer-section">
                <h3>Belső megjegyzés</h3>
                <p className="notes">{lead.notes}</p>
              </section>
              <section className="copilot-box">
                <Icon name="bot" />
                <div>
                  <small>SALES COPILOT JAVASLATA</small>
                  <strong>
                    {lead.health === "red"
                      ? "Vedd fel ma a kapcsolatot, és pontosítsd a telek- valamint finanszírozási helyzetet."
                      : "Erősítsd meg a következő döntési pontot és rögzíts konkrét határidőt."}
                  </strong>
                  <p>Külső kommunikáció csak emberi jóváhagyással.</p>
                </div>
              </section>
            </>
          ) : tab === "activity" ? (
            <div className="timeline">
              <div>
                <i>
                  <Icon name="mail" />
                </i>
                <span>
                  <strong>Ajánlati összefoglaló elküldve</strong>
                  <p>Az ügyfél megnyitotta az e-mailt.</p>
                  <small>Tegnap, 16:42 · Kiss Andrea</small>
                </span>
              </div>
              <div>
                <i>
                  <Icon name="phone" />
                </i>
                <span>
                  <strong>Telefonos konzultáció</strong>
                  <p>Költségkeret és döntési horizont pontosítva.</p>
                  <small>július 17., 10:15 · 24 perc</small>
                </span>
              </div>
            </div>
          ) : (
            <div className="drawer-tasks">
              {tasks.length ? tasks.map((task) => (
                <article key={task.id}>
                  <i className={`priority ${task.priority}`} />
                  <span>
                    <strong>{task.title}</strong>
                    <small>{task.due} · {task.type}</small>
                  </span>
                  <button onClick={() => onCompleteTask(task.id)} aria-label="Teendő készre jelölése">
                    <Icon name="check" />
                  </button>
                </article>
              )) : <div className="empty-tasks"><Icon name="check"/><strong>Nincs nyitott teendő</strong><small>Az adatlap munkasora rendezett.</small></div>}
              {taskOpen ? (
                <NewTaskForm
                  onCancel={() => setTaskOpen(false)}
                  onSave={async (task) => {
                    const saved = await onAddTask(task);
                    if (saved) setTaskOpen(false);
                  }}
                />
              ) : (
                <button className="secondary" onClick={() => setTaskOpen(true)}>
                  <Icon name="plus" /> Új teendő
                </button>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function LeadEditForm({
  lead,
  onCancel,
  onSave,
}: {
  lead: Lead;
  onCancel: () => void;
  onSave: (changes: Partial<Lead>) => void;
}) {
  const [draft, setDraft] = useState(lead);
  const set = <K extends keyof Lead>(key: K, value: Lead[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const brandCodes: Record<string, string> = {
    Imperial: "IH",
    Prefab: "PF",
    "Danish Fabrik": "DF",
    BauFreund: "BF",
    Bautica: "BA",
  };
  return (
    <section className="drawer-section edit-card">
      <div className="edit-grid">
        <label className="wide">Név<input value={draft.name} onChange={(e) => set("name", e.target.value)} /></label>
        <label className="wide">Projekt / ügy megnevezése<input value={draft.title} onChange={(e) => set("title", e.target.value)} /></label>
        <label>E-mail<input type="email" value={draft.email} onChange={(e) => set("email", e.target.value)} /></label>
        <label>Telefon<input value={draft.phone} onChange={(e) => set("phone", e.target.value)} /></label>
        <label>Helyszín<input value={draft.location} onChange={(e) => set("location", e.target.value)} /></label>
        <label>Forrás<input value={draft.source} onChange={(e) => set("source", e.target.value)} /></label>
        <label>Márka<select value={draft.brand} onChange={(e) => { set("brand", e.target.value); set("brandCode", brandCodes[e.target.value] ?? "CRM"); }}><option>Imperial</option><option>Prefab</option><option>Danish Fabrik</option><option>BauFreund</option><option>Bautica</option></select></label>
        <label>Felelős<input value={draft.owner} onChange={(e) => set("owner", e.target.value)} /></label>
        <label>Projekt típusa<input value={draft.projectType} onChange={(e) => set("projectType", e.target.value)} /></label>
        <label>Technológia<input value={draft.technology} onChange={(e) => set("technology", e.target.value)} /></label>
        <label>Várható érték (Ft)<input type="number" min="0" value={draft.value} onChange={(e) => set("value", Number(e.target.value))} /></label>
        <label>Valószínűség (%)<input type="number" min="0" max="100" value={draft.probability} onChange={(e) => set("probability", Math.min(100, Number(e.target.value)))} /></label>
        <label className="wide">Következő lépés<input value={draft.nextAction} onChange={(e) => set("nextAction", e.target.value)} /></label>
        <label>Következő határidő<input value={draft.nextDate} onChange={(e) => set("nextDate", e.target.value)} /></label>
        <label>Ügyfélhőmérséklet<select value={draft.temperature} onChange={(e) => set("temperature", e.target.value as Lead["temperature"])}><option value="hot">Forró</option><option value="warm">Meleg</option><option value="cold">Hideg</option></select></label>
        <label className="wide">Belső megjegyzés<textarea value={draft.notes} onChange={(e) => set("notes", e.target.value)} rows={4} /></label>
      </div>
      <div className="check-row">
        <label><input type="checkbox" checked={draft.plot} onChange={(e) => set("plot", e.target.checked)} /> Telek rendelkezésre áll</label>
        <label><input type="checkbox" checked={draft.financing} onChange={(e) => set("financing", e.target.checked)} /> Finanszírozás rendezett</label>
      </div>
      <footer className="edit-footer">
        <button className="ghost" onClick={onCancel}>Mégse</button>
        <button className="primary" disabled={!draft.name.trim()} onClick={() => onSave(draft)}>Módosítások mentése</button>
      </footer>
    </section>
  );
}

function NewTaskForm({
  onCancel,
  onSave,
}: {
  onCancel: () => void;
  onSave: (task: NewTask) => void;
}) {
  const [title, setTitle] = useState("");
  const [type, setType] = useState("Hívás");
  const [due, setDue] = useState("Ma");
  const [priority, setPriority] = useState<NewTask["priority"]>("normal");
  return (
    <section className="inline-task-form">
      <h3>Új teendő</h3>
      <label>Feladat<input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Mit kell elvégezni?" /></label>
      <div>
        <label>Típus<select value={type} onChange={(e) => setType(e.target.value)}><option>Hívás</option><option>Follow-up</option><option>Találkozó</option><option>Jóváhagyás</option><option>E-mail</option></select></label>
        <label>Határidő<input value={due} onChange={(e) => setDue(e.target.value)} placeholder="pl. Holnap, 10:00" /></label>
      </div>
      <label>Prioritás<select value={priority} onChange={(e) => setPriority(e.target.value as NewTask["priority"])}><option value="normal">Normál</option><option value="high">Magas</option><option value="critical">Kritikus</option></select></label>
      <footer><button className="ghost" onClick={onCancel}>Mégse</button><button className="primary" disabled={!title.trim()} onClick={() => onSave({ title, type, due, priority })}>Teendő mentése</button></footer>
    </section>
  );
}

function NewLeadModal({
  onClose,
  onSave,
}: {
  onClose: () => void;
  onSave: (l: Omit<Lead, "id">) => void;
}) {
  const [name, setName] = useState(""),
    [title, setTitle] = useState(""),
    [email, setEmail] = useState(""),
    [phone, setPhone] = useState(""),
    [brand, setBrand] = useState("Imperial"),
    [location, setLocation] = useState("");
  const save = () => {
    if (!name.trim()) return;
    const codes: Record<string, string> = {
      Imperial: "IH",
      Prefab: "PF",
      "Danish Fabrik": "DF",
      BauFreund: "BF",
      Bautica: "BA",
    };
    onSave({
      name,
      title: title || "Új építési érdeklődés",
      brand,
      brandCode: codes[brand],
      location: location || "Nincs megadva",
      email: email || "—",
      phone: phone || "—",
      source: "Kézi rögzítés",
      owner: "Kiss Andrea",
      ownerInitials: "KA",
      stage: "new",
      value: 0,
      probability: 10,
      score: 45,
      quality: 38,
      temperature: "cold",
      health: "yellow",
      nextAction: "Első kapcsolatfelvétel",
      nextDate: "Ma",
      projectType: "Családi ház",
      technology: "Egyeztetendő",
      plot: false,
      financing: false,
      notes: "Újonnan rögzített adatlap; minősítés szükséges.",
    });
  };
  return (
    <div className="modal-layer">
      <button className="modal-scrim" onClick={onClose} />
      <section className="modal">
        <header>
          <div>
            <p className="eyebrow">ÚJ ÉRTÉKESÍTÉSI ADATLAP</p>
            <h2>Érdeklődő rögzítése</h2>
            <span>
              Csak a legfontosabb adatok; a többit később is kitöltheted.
            </span>
          </div>
          <button onClick={onClose}>
            <Icon name="close" />
          </button>
        </header>
        <div className="modal-form">
          <label>
            Név *
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              placeholder="Kapcsolattartó vagy cég neve"
            />
          </label>
          <label>
            Ügy / projekt címe
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="pl. 110 m²-es családi ház"
            />
          </label>
          <div>
            <label>
              E-mail
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label>
              Telefon
              <input
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+36…"
              />
            </label>
          </div>
          <div>
            <label>
              Márka
              <select value={brand} onChange={(e) => setBrand(e.target.value)}>
                <option>Imperial</option>
                <option>Prefab</option>
                <option>Danish Fabrik</option>
                <option>BauFreund</option>
                <option>Bautica</option>
              </select>
            </label>
            <label>
              Helyszín
              <input
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="Település"
              />
            </label>
          </div>
        </div>
        <footer>
          <button className="ghost" onClick={onClose}>
            Mégse
          </button>
          <button className="primary" onClick={save} disabled={!name.trim()}>
            Adatlap létrehozása <Icon name="arrow" />
          </button>
        </footer>
      </section>
    </div>
  );
}

function NewCustomerModal({
  onClose,
  onSave,
}: {
  onClose: () => void;
  onSave: (customer: {
    customerType: "person" | "company";
    name: string;
    email: string;
    phone: string;
    billingAddress: string;
    taxNumber?: string;
  }) => Promise<boolean>;
}) {
  const [customerType, setCustomerType] = useState<"person" | "company">("person");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [billingAddress, setBillingAddress] = useState("");
  const [taxNumber, setTaxNumber] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = Boolean(name.trim() && email.includes("@") && phone.trim() && billingAddress.trim());
  return (
    <div className="modal-layer">
      <button className="modal-scrim" onClick={onClose} />
      <section className="modal">
        <header><div><p className="eyebrow">ÉLŐ ÜGYFÉLTÖRZS</p><h2>Új ügyfél</h2><span>A kötelező kapcsolati és számlázási adatokkal.</span></div><button onClick={onClose}><Icon name="close" /></button></header>
        <div className="modal-form">
          <label>Ügyféltípus<select value={customerType} onChange={(event) => setCustomerType(event.target.value as "person" | "company")}><option value="person">Magánszemély</option><option value="company">Vállalkozás</option></select></label>
          <label>Név *<input autoFocus value={name} onChange={(event) => setName(event.target.value)} /></label>
          <div><label>E-mail *<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label><label>Telefon *<input value={phone} onChange={(event) => setPhone(event.target.value)} /></label></div>
          <label>Számlázási cím *<input value={billingAddress} onChange={(event) => setBillingAddress(event.target.value)} /></label>
          {customerType === "company" && <label>Adószám<input value={taxNumber} onChange={(event) => setTaxNumber(event.target.value)} /></label>}
        </div>
        <footer><button className="ghost" onClick={onClose}>Mégse</button><button className="primary" disabled={!valid || busy} onClick={async () => { setBusy(true); const saved = await onSave({ customerType, name, email, phone, billingAddress, taxNumber }); if (!saved) setBusy(false); }}>{busy ? "Mentés…" : "Ügyfél létrehozása"}</button></footer>
      </section>
    </div>
  );
}

function NewContractModal({
  customers,
  onClose,
  onSave,
}: {
  customers: Customer[];
  onClose: () => void;
  onSave: (contract: {
    customerId: string;
    title: string;
    contractType: Contract["contractType"];
    netAmount: number;
    vatRate: number;
    effectiveDate: string;
  }) => Promise<boolean>;
}) {
  const [customerId, setCustomerId] = useState(customers[0]?.id ?? "");
  const [title, setTitle] = useState("");
  const [contractType, setContractType] = useState<Contract["contractType"]>("construction");
  const [netAmount, setNetAmount] = useState("");
  const [vatRate, setVatRate] = useState("27");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = Boolean(customerId && title.trim() && netAmount !== "" && Number(netAmount) >= 0 && effectiveDate);
  return (
    <div className="modal-layer">
      <button className="modal-scrim" onClick={onClose} />
      <section className="modal">
        <header><div><p className="eyebrow">SZERZŐDÉSES FOLYAMAT</p><h2>Új szerződéstervezet</h2><span>A tervezet csak vezetői jóváhagyás után jelölhető aláírtnak.</span></div><button onClick={onClose}><Icon name="close" /></button></header>
        <div className="modal-form">
          <label>Ügyfél *<select value={customerId} onChange={(event) => setCustomerId(event.target.value)}>{customers.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select></label>
          <label>Szerződés tárgya *<input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} /></label>
          <div><label>Típus<select value={contractType} onChange={(event) => setContractType(event.target.value as Contract["contractType"])}><option value="construction">Kivitelezés</option><option value="design">Tervezés</option><option value="consulting">Tanácsadás</option><option value="other">Egyéb</option></select></label><label>Hatály kezdete *<input type="date" value={effectiveDate} onChange={(event) => setEffectiveDate(event.target.value)} /></label></div>
          <div><label>Nettó összeg (Ft) *<input type="number" min="0" step="1" value={netAmount} onChange={(event) => setNetAmount(event.target.value)} /></label><label>ÁFA (%)<input type="number" min="0" max="100" value={vatRate} onChange={(event) => setVatRate(event.target.value)} /></label></div>
        </div>
        <footer><button className="ghost" onClick={onClose}>Mégse</button><button className="primary" disabled={!valid || busy} onClick={async () => { setBusy(true); const saved = await onSave({ customerId, title, contractType, netAmount: Number(netAmount), vatRate: Number(vatRate), effectiveDate }); if (!saved) setBusy(false); }}>{busy ? "Mentés…" : "Tervezet létrehozása"}</button></footer>
      </section>
    </div>
  );
}

function NewCashflowModal({
  projects,
  onClose,
  onSave,
}: {
  projects: BusinessProject[];
  onClose: () => void;
  onSave: (entry: {
    direction: "inflow" | "outflow";
    category: string;
    counterparty: string;
    description: string;
    projectId: string;
    amount: number;
    dueDate: string;
    status: "planned" | "due";
  }) => Promise<boolean>;
}) {
  const [direction, setDirection] = useState<"inflow" | "outflow">("outflow");
  const [category, setCategory] = useState("");
  const [counterparty, setCounterparty] = useState("");
  const [description, setDescription] = useState("");
  const [projectId, setProjectId] = useState("");
  const [amount, setAmount] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [status, setStatus] = useState<"planned" | "due">("planned");
  const [busy, setBusy] = useState(false);
  const valid = Boolean(category.trim() && counterparty.trim() && description.trim() && Number(amount) > 0 && dueDate);
  return (
    <div className="modal-layer">
      <button className="modal-scrim" onClick={onClose} />
      <section className="modal">
        <header><div><p className="eyebrow">CASHFLOW</p><h2>Új pénzmozgás</h2><span>A teljesített állapot külön, utólagos művelettel rögzíthető.</span></div><button onClick={onClose}><Icon name="close" /></button></header>
        <div className="modal-form">
          <div><label>Irány<select value={direction} onChange={(event) => setDirection(event.target.value as "inflow" | "outflow")}><option value="inflow">Bevétel</option><option value="outflow">Kiadás</option></select></label><label>Állapot<select value={status} onChange={(event) => setStatus(event.target.value as "planned" | "due")}><option value="planned">Tervezett</option><option value="due">Esedékes</option></select></label></div>
          <div><label>Kategória *<input value={category} onChange={(event) => setCategory(event.target.value)} placeholder="pl. kivitelezési részszámla" /></label><label>Partner *<input value={counterparty} onChange={(event) => setCounterparty(event.target.value)} /></label></div>
          <label>Leírás *<input value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          <div><label>Összeg (HUF) *<input type="number" min="1" step="1" value={amount} onChange={(event) => setAmount(event.target.value)} /></label><label>Esedékesség *<input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></label></div>
          <label>Projekt<select value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">Nincs projekthez kapcsolva</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.portalCode} · {project.title}</option>)}</select></label>
        </div>
        <footer><button className="ghost" onClick={onClose}>Mégse</button><button className="primary" disabled={!valid || busy} onClick={async () => { setBusy(true); const saved = await onSave({ direction, category, counterparty, description, projectId, amount: Number(amount), dueDate, status }); if (!saved) setBusy(false); }}>{busy ? "Mentés…" : "Cashflow-tétel rögzítése"}</button></footer>
      </section>
    </div>
  );
}
