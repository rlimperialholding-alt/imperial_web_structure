"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedFetch } from "@/lib/browser-auth";
import Link from "next/link";
import styles from "./myimperial.module.css";
import docStyles from "./documents.module.css";
import teamStyles from "./team.module.css";
import notificationStyles from "./notifications.module.css";

type Tab =
  | "overview"
  | "schedule"
  | "documents"
  | "finance"
  | "tasks"
  | "decisions"
  | "changes"
  | "care"
  | "notifications"
  | "team"
  | "photos";

type CustomerTask = {
  id: string;
  source: string;
  title: string;
  due: string;
  status: "waiting_customer" | "submitted" | "completed";
  action: string;
  severity: "high" | "normal";
};

type ProjectChange = {
  id: string;
  title: string;
  origin: string;
  scope: string;
  price: string;
  schedule: string;
  internalControl: string;
  status: "internal_review" | "customer_approval" | "approved" | "rejected";
  created: string;
  evidence: string;
};

type ProjectDecision = {
  id: number;
  title: string;
  area: string;
  due: string;
  impact: string;
  status: "open" | "approved" | "question";
};

type PortalProject = {
  id: string;
  portalCode: string;
  customerName: string;
  title: string;
  phase: string;
  progress: number;
  handoverDate: string | null;
};

type PortalDocument = {
  id: string;
  name: string;
  group: string;
  date: string;
  version: string;
  currentVersion: number;
  status: "draft" | "approval" | "verified";
  fileName: string;
  size: number;
  sha256: string;
  downloadUrl: string;
  reference: boolean;
};

type DocumentVersion = {
  version: number;
  fileName: string;
  contentType: string;
  size: number;
  sha256: string;
  uploadedByEmail: string;
  uploadedAt: string;
};

type MemberRole = "customer" | "contact" | "project_manager" | "technical" | "finance" | "warranty";
type ProjectMember = { email: string; displayName: string; role: MemberRole; createdAt: string };
type ProjectInvitation = { id: string; email: string; displayName: string; role: MemberRole; status: "pending" | "accepted" | "revoked" | "expired"; expiresAt: string; createdAt: string };
type NotificationPreferences = {
  taskNotifications: boolean; decisionNotifications: boolean; changeNotifications: boolean;
  documentNotifications: boolean; messageNotifications: boolean; careNotifications: boolean;
  digestFrequency: "immediate" | "daily" | "weekly" | "off";
};
type EmailNotification = {
  id: string; recipientEmail: string; recipientName: string;
  templateKey: "invitation" | "task" | "decision" | "change" | "document" | "message" | "care";
  subject: string; status: "draft" | "approved" | "sending" | "sent" | "failed" | "cancelled";
  attemptCount: number; lastError: string | null; createdAt: string; sentAt: string | null;
};
type EmailProvider = { configured: boolean; fromEmail: string; provider: "resend" };

const tabs: { id: Tab; label: string; icon: string }[] = [
  { id: "overview", label: "Áttekintés", icon: "home" },
  { id: "schedule", label: "Ütemterv", icon: "calendar" },
  { id: "documents", label: "Dokumentumok", icon: "file" },
  { id: "finance", label: "Pénzügyek", icon: "wallet" },
  { id: "tasks", label: "Teendőim", icon: "list" },
  { id: "decisions", label: "Döntéseim", icon: "check" },
  { id: "changes", label: "ChangeControl", icon: "change" },
  { id: "care", label: "Imperial Care", icon: "heart" },
  { id: "notifications", label: "Értesítések", icon: "bell" },
  { id: "team", label: "Projektcsapat", icon: "users" },
  { id: "photos", label: "Fotónapló", icon: "camera" },
];

const milestones = [
  {
    title: "Szerződés és projektindítás",
    date: "2026. március 18.",
    status: "done",
    note: "Szerződés, 35% induló befizetés",
  },
  {
    title: "Telek- és alapadatok lezárása",
    date: "2026. április 9.",
    status: "done",
    note: "Geodézia, helyszínrajz, talajmechanika",
  },
  {
    title: "Építészeti tervezés",
    date: "2026. május 4. – július 31.",
    status: "active",
    note: "Alaprajz és homlokzat véglegesítése",
  },
  {
    title: "Szakági tervek és tervütköztetés",
    date: "2026. augusztus",
    status: "next",
    note: "Statika, gépészet, elektromosság",
  },
  {
    title: "Végleges költségvetés és ütemterv",
    date: "2026. szeptember",
    status: "next",
    note: "Ügyfél- és vezetői jóváhagyás",
  },
  {
    title: "Kivitelezésindítás",
    date: "Engedély és G5 gate után",
    status: "locked",
    note: "Munkaterület-átadás és felvonulás",
  },
  {
    title: "Műszaki átadás",
    date: "Tervezett: 2027. május",
    status: "locked",
    note: "Átadási dokumentáció és hibajegyzék",
  },
];

const referenceDocuments: PortalDocument[] = [
  {
    id: "REF-001",
    name: "Kivitelezési szerződés",
    group: "Szerződések",
    date: "2026. március 18.",
    version: "Aláírt",
    status: "verified",
    currentVersion: 0, fileName: "", size: 0, sha256: "", downloadUrl: "", reference: true,
  },
  {
    id: "REF-002",
    name: "Tervezési program",
    group: "Tervezés",
    date: "2026. április 14.",
    version: "v2.1",
    status: "verified",
    currentVersion: 0, fileName: "", size: 0, sha256: "", downloadUrl: "", reference: true,
  },
  {
    id: "REF-003",
    name: "Geodéziai felmérés",
    group: "Telek",
    date: "2026. április 7.",
    version: "Végleges",
    status: "verified",
    currentVersion: 0, fileName: "", size: 0, sha256: "", downloadUrl: "", reference: true,
  },
  {
    id: "REF-004",
    name: "Építész alaprajz",
    group: "Tervezés",
    date: "2026. július 18.",
    version: "v4 – jóváhagyásra",
    status: "approval",
    currentVersion: 0, fileName: "", size: 0, sha256: "", downloadUrl: "", reference: true,
  },
  {
    id: "REF-005",
    name: "Előzetes pénzügyi-műszaki ütemterv",
    group: "Pénzügy",
    date: "2026. július 16.",
    version: "v1.3",
    status: "draft",
    currentVersion: 0, fileName: "", size: 0, sha256: "", downloadUrl: "", reference: true,
  },
];

const payments = [
  {
    title: "Projektindítás",
    percent: 35,
    amount: "24 290 000 Ft",
    due: "2026. március 18.",
    status: "paid",
  },
  {
    title: "Falazat / szerkezet",
    percent: 8,
    amount: "5 552 000 Ft",
    due: "G5 után",
    status: "upcoming",
  },
  {
    title: "Födém / födémszerkezet",
    percent: 6,
    amount: "4 164 000 Ft",
    due: "Készültség szerint",
    status: "locked",
  },
  {
    title: "Tetőszerkezet",
    percent: 9,
    amount: "6 246 000 Ft",
    due: "Készültség szerint",
    status: "locked",
  },
  {
    title: "Gépészeti alapszerelés",
    percent: 7,
    amount: "4 858 000 Ft",
    due: "Készültség szerint",
    status: "locked",
  },
  {
    title: "Tetőfedés",
    percent: 4,
    amount: "2 776 000 Ft",
    due: "Készültség szerint",
    status: "locked",
  },
  {
    title: "Műszaki átadás",
    percent: 5,
    amount: "3 470 000 Ft",
    due: "Átadáskor",
    status: "locked",
  },
];

const decisions: ProjectDecision[] = [
  {
    id: 1,
    title: "Építészeti alaprajz v4",
    area: "Tervezés",
    due: "Határidő: július 22.",
    impact: "A szakági tervezés csak jóváhagyás után indulhat.",
    status: "open",
  },
  {
    id: 2,
    title: "Külső nyílászárók színe",
    area: "Anyagválasztás",
    due: "Határidő: július 28.",
    impact: "Javaslat: RAL 7016 antracit, kívül-belül.",
    status: "open",
  },
  {
    id: 3,
    title: "Gépészeti koncepció",
    area: "Műszaki tartalom",
    due: "Jóváhagyva július 11.",
    impact: "Levegő–víz hőszivattyú, padlófűtés.",
    status: "approved",
  },
];

const customerTasks: CustomerTask[] = [
  {
    id: "TSK-PC-031",
    source: "PlanCheck",
    title: "Telek tulajdoni lap feltöltése",
    due: "július 22.",
    status: "waiting_customer",
    action: "Fájl feltöltése",
    severity: "high",
  },
  {
    id: "TSK-TEC-018",
    source: "Technical",
    title: "Konyhai gépek teljesítményigénye",
    due: "július 25.",
    status: "waiting_customer",
    action: "Adatok megadása",
    severity: "normal",
  },
  {
    id: "TSK-FIN-007",
    source: "Finance",
    title: "Finanszírozási konstrukció visszaigazolása",
    due: "július 29.",
    status: "waiting_customer",
    action: "Visszaigazolás",
    severity: "normal",
  },
  {
    id: "TSK-PC-024",
    source: "PlanCheck",
    title: "Geodéziai felmérés ellenőrzése",
    due: "Lezárva július 9.",
    status: "completed",
    action: "Megtekintés",
    severity: "normal",
  },
];

const initialChanges: ProjectChange[] = [
  {
    id: "CHG-2026-004",
    title: "Nappali teraszajtó szélesítése",
    origin: "Ügyféligény",
    scope:
      "A 240 cm-es nyílászáró 300 cm-re módosítása, statikai és áthidaló ellenőrzéssel.",
    price: "+1 180 000 Ft",
    schedule: "+4 munkanap",
    internalControl: "Belső kontroll teljesült",
    status: "customer_approval",
    created: "2026. július 17.",
    evidence: "Műszaki lap v2 · költségszámítás v1",
  },
  {
    id: "CHG-2026-003",
    title: "Gépészeti helyiség áthelyezése",
    origin: "Tervezői javaslat",
    scope:
      "A gépészeti tér átszervezése a csőhossz és karbantarthatóság javítására.",
    price: "0 Ft",
    schedule: "Nincs hatás",
    internalControl: "Belső kontroll teljesült",
    status: "approved",
    created: "2026. július 11.",
    evidence: "Alaprajz v4 · gépészeti állásfoglalás",
  },
  {
    id: "CHG-2026-002",
    title: "Plusz tetőablak",
    origin: "Ügyféligény",
    scope: "Egy további 78×118 cm-es tetőablak beépítése.",
    price: "+420 000 Ft",
    schedule: "+1 munkanap",
    internalControl: "Belső kontroll teljesült",
    status: "rejected",
    created: "2026. június 28.",
    evidence: "Árkalkuláció és tetőmetszet",
  },
];

function Icon({ name }: { name: string }) {
  const paths: Record<string, React.ReactNode> = {
    home: (
      <>
        <path d="M3 11 12 3l9 8" />
        <path d="M5 10v10h14V10M9 20v-6h6v6" />
      </>
    ),
    calendar: (
      <>
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M8 3v4M16 3v4M3 10h18" />
      </>
    ),
    file: (
      <>
        <path d="M6 2h8l4 4v16H6z" />
        <path d="M14 2v5h5M9 13h6M9 17h6" />
      </>
    ),
    wallet: (
      <>
        <path d="M3 6h16v14H3z" />
        <path d="M3 8V5h14M15 12h6v4h-6z" />
      </>
    ),
    check: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="m8 12 3 3 5-6" />
      </>
    ),
    camera: (
      <>
        <rect x="3" y="6" width="18" height="14" rx="2" />
        <path d="m8 6 2-3h4l2 3" />
        <circle cx="12" cy="13" r="4" />
      </>
    ),
    bell: <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />,
    arrow: <path d="m9 18 6-6-6-6" />,
    shield: (
      <>
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10" />
        <path d="m9 12 2 2 4-4" />
      </>
    ),
    message: <path d="M4 4h16v13H8l-4 4z" />,
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    download: (
      <>
        <path d="M12 3v12M7 10l5 5 5-5" />
        <path d="M5 21h14" />
      </>
    ),
    lock: (
      <>
        <rect x="5" y="10" width="14" height="11" rx="2" />
        <path d="M8 10V7a4 4 0 0 1 8 0v3" />
      </>
    ),
    list: <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />,
    change: (
      <>
        <path d="M4 7h11M12 4l3 3-3 3" />
        <path d="M20 17H9M12 14l-3 3 3 3" />
      </>
    ),
    heart: (
      <>
        <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z" />
        <path d="M8 12h2l1-3 2 6 1-3h2" />
      </>
    ),
    tool: (
      <>
        <path d="M14.7 6.3a4 4 0 0 0-5-5l2.1 2.1-2.8 2.8-2.1-2.1a4 4 0 0 0 5 5L20 17.2 17.2 20z" />
      </>
    ),
    users: (
      <>
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
      </>
    ),
    plus: <path d="M12 5v14M5 12h14" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
  };
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {paths[name]}
    </svg>
  );
}

async function portalRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData) && !headers.has("content-type")) headers.set("content-type", "application/json");
  const response = await authenticatedFetch(url, {
    ...init,
    headers,
  });
  const payload = (await response.json().catch(() => ({}))) as T & { error?: string };
  if (!response.ok) throw new Error(payload.error || "A művelet most nem hajtható végre.");
  return payload;
}

type DocumentRecord = {
  id: string; name: string; group: string; status: PortalDocument["status"];
  currentVersion: number; fileName: string; size: number; sha256: string;
  uploadedAt: string; downloadUrl: string;
};

function mapDocument(document: DocumentRecord): PortalDocument {
  return {
    id: document.id,
    name: document.name,
    group: document.group,
    date: portalDate(document.uploadedAt),
    version: `v${document.currentVersion}`,
    currentVersion: document.currentVersion,
    status: document.status,
    fileName: document.fileName,
    size: document.size,
    sha256: document.sha256,
    downloadUrl: document.downloadUrl,
    reference: false,
  };
}

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function portalDate(value: string) {
  return new Intl.DateTimeFormat("hu-HU", {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(new Date(value));
}

export default function MyImperialPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [toast, setToast] = useState("");
  const [requestOpen, setRequestOpen] = useState(false);
  const [requestText, setRequestText] = useState("");
  const [requestTopic, setRequestTopic] = useState("Általános kérdés");
  const [tasks, setTasks] = useState<CustomerTask[]>(customerTasks);
  const [changes, setChanges] = useState<ProjectChange[]>(initialChanges);
  const [projectDecisions, setProjectDecisions] = useState<ProjectDecision[]>(decisions);
  const [projectDocuments, setProjectDocuments] = useState<PortalDocument[]>(referenceDocuments);
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [invitations, setInvitations] = useState<ProjectInvitation[]>([]);
  const [canManageMembers, setCanManageMembers] = useState(false);
  const [allowedInviteRoles, setAllowedInviteRoles] = useState<MemberRole[]>(["contact"]);
  const [notificationPreferences, setNotificationPreferences] = useState<NotificationPreferences>({
    taskNotifications: true, decisionNotifications: true, changeNotifications: true,
    documentNotifications: true, messageNotifications: true, careNotifications: true,
    digestFrequency: "immediate",
  });
  const [emailNotifications, setEmailNotifications] = useState<EmailNotification[]>([]);
  const [canApproveEmails, setCanApproveEmails] = useState(false);
  const [emailProvider, setEmailProvider] = useState<EmailProvider>({ configured: false, fromEmail: "", provider: "resend" });
  const [isCrmAdmin, setIsCrmAdmin] = useState(false);
  const [project, setProject] = useState<PortalProject>({
    id: "PRJ-2026-014", portalCode: "MI-2026-014", customerName: "Minta Péter",
    title: "Ürömi családi ház", phase: "Tervezési szakasz", progress: 42, handoverDate: null,
  });
  const [liveData, setLiveData] = useState<"loading" | "live" | "demo">("loading");
  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 3200);
  };
  const openDecisions = useMemo(
    () => projectDecisions.filter((decision) => decision.status === "open").length,
    [projectDecisions],
  );

  useEffect(() => {
    let active = true;
    portalRequest<{
      identity: { role: "admin" | "sales_manager" | "sales" };
      project: PortalProject;
      tasks: CustomerTask[];
      decisions: ProjectDecision[];
      changes: Array<{
        id: string; title: string; origin: string; scope: string;
        customerPriceImpact: string; scheduleImpact: string; internalControl: string;
        status: ProjectChange["status"]; createdAt: string; evidence: string;
      }>;
    }>("/api/myimperial")
      .then((snapshot) => {
        if (!active) return;
        setProject(snapshot.project);
        setIsCrmAdmin(snapshot.identity.role === "admin");
        setTasks(snapshot.tasks);
        setProjectDecisions(snapshot.decisions);
        setChanges(snapshot.changes.map((change) => ({
          id: change.id, title: change.title, origin: change.origin, scope: change.scope,
          price: change.customerPriceImpact, schedule: change.scheduleImpact,
          internalControl: change.internalControl, status: change.status,
          created: portalDate(change.createdAt), evidence: change.evidence,
        })));
        setLiveData("live");
      })
      .catch(() => active && setLiveData("demo"));
    portalRequest<{ documents: DocumentRecord[] }>("/api/myimperial/documents")
      .then(({ documents }) => {
        if (!active) return;
        const uploaded = documents.map(mapDocument);
        setProjectDocuments([...uploaded, ...referenceDocuments]);
      })
      .catch(() => undefined);
    portalRequest<{ members: ProjectMember[]; invitations: ProjectInvitation[]; canManage: boolean; allowedInviteRoles: MemberRole[] }>("/api/myimperial/members")
      .then((payload) => {
        if (!active) return;
        setMembers(payload.members);
        setInvitations(payload.invitations);
        setCanManageMembers(payload.canManage);
        setAllowedInviteRoles(payload.allowedInviteRoles);
      })
      .catch(() => undefined);
    portalRequest<{ preferences: NotificationPreferences; notifications: EmailNotification[]; canApprove: boolean; provider: EmailProvider }>("/api/myimperial/notifications")
      .then((payload) => {
        if (!active) return;
        setNotificationPreferences(payload.preferences);
        setEmailNotifications(payload.notifications);
        setCanApproveEmails(payload.canApprove);
        setEmailProvider(payload.provider);
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);

  const runAction = async (action: () => Promise<void>) => {
    try { await action(); return true; } catch (error) {
      notify(error instanceof Error ? error.message : "A művelet most nem hajtható végre.");
      return false;
    }
  };

  const updateTask = async (id: string, status: "submitted" | "completed") => runAction(async () => {
    const { task } = await portalRequest<{ task: CustomerTask }>(`/api/myimperial/tasks/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
    setTasks((current) => current.map((item) => item.id === id ? task : item));
    notify(`${id}: a teljesítést időbélyeggel rögzítettük és ellenőrzésre küldtük.`);
  });

  const updateDecision = async (id: number, status: "approved" | "question") => runAction(async () => {
    const { decision } = await portalRequest<{ decision: ProjectDecision }>(`/api/myimperial/decisions/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
    setProjectDecisions((current) => current.map((item) => item.id === id ? decision : item));
    notify(status === "approved" ? "A jóváhagyást időbélyeggel rögzítettük." : "A kérdésedet rögzítettük; a projektcsapat válaszolni fog.");
  });

  const createChange = async (title: string, description: string, category: string) => runAction(async () => {
    const { change } = await portalRequest<{ change: {
      id: string; title: string; origin: string; scope: string; customerPriceImpact: string;
      scheduleImpact: string; internalControl: string; status: ProjectChange["status"];
      createdAt: string; evidence: string;
    } }>("/api/myimperial/changes", { method: "POST", body: JSON.stringify({ title, description, category }) });
    setChanges((current) => [{
      id: change.id, title: change.title, origin: change.origin, scope: change.scope,
      price: change.customerPriceImpact, schedule: change.scheduleImpact,
      internalControl: change.internalControl, status: change.status,
      created: portalDate(change.createdAt), evidence: change.evidence,
    }, ...current]);
    notify(`${change.id}: a változtatási igényt rögzítettük, belső elemzés indult.`);
  });

  const updateChange = async (id: string, status: "approved" | "rejected") => runAction(async () => {
    await portalRequest(`/api/myimperial/changes/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
    setChanges((current) => current.map((item) => item.id === id ? { ...item, status } : item));
    notify(status === "approved" ? `${id}: az ügyféljóváhagyást időbélyeggel rögzítettük.` : `${id}: a változtatást elutasítottuk; munka nem indítható.`);
  });

  const sendMessage = async () => runAction(async () => {
    await portalRequest("/api/myimperial/messages", { method: "POST", body: JSON.stringify({ topic: requestTopic, body: requestText }) });
    setRequestOpen(false);
    setRequestText("");
    notify("Az üzenetet időbélyeggel rögzítettük a projekt naplójában.");
  });

  const uploadDocument = async (form: FormData) => runAction(async () => {
    const { document } = await portalRequest<{ document: DocumentRecord }>("/api/myimperial/documents", { method: "POST", body: form });
    const mapped = mapDocument(document);
    setProjectDocuments((current) => {
      const exists = current.some((item) => item.id === mapped.id);
      return exists ? current.map((item) => item.id === mapped.id ? mapped : item) : [mapped, ...current];
    });
    notify(`${mapped.id}: ${mapped.version} feltöltve és SHA-256 ellenőrzőösszeggel rögzítve.`);
  });

  const inviteMember = async (data: { email: string; displayName: string; role: MemberRole }) => {
    try {
      const payload = await portalRequest<{ invitation: ProjectInvitation; inviteUrl: string }>("/api/myimperial/members", { method: "POST", body: JSON.stringify(data) });
      setInvitations((current) => [payload.invitation, ...current]);
      notify(`${payload.invitation.id}: a projektmeghívás elkészült.`);
      return { inviteUrl: payload.inviteUrl, invitationId: payload.invitation.id };
    } catch (error) {
      notify(error instanceof Error ? error.message : "A meghívás most nem készíthető el.");
      return null;
    }
  };

  const sendInvitationEmail = async (invitationId: string, inviteUrl: string) => runAction(async () => {
    await portalRequest("/api/myimperial/notifications/invitation/send", {
      method: "POST", body: JSON.stringify({ invitationId, inviteUrl }),
    });
    notify("A meghívó emailt jóváhagytuk, elküldtük és a projekt naplójában rögzítettük.");
    const snapshot = await portalRequest<{ notifications: EmailNotification[] }>("/api/myimperial/notifications");
    setEmailNotifications(snapshot.notifications);
  });

  const saveNotificationPreferences = async (changes: Partial<NotificationPreferences>) => runAction(async () => {
    const { preferences } = await portalRequest<{ preferences: NotificationPreferences }>("/api/myimperial/notifications", {
      method: "PATCH", body: JSON.stringify(changes),
    });
    setNotificationPreferences(preferences);
    notify("Az email-értesítési beállításokat elmentettük.");
  });

  const approveNotification = async (id: string) => runAction(async () => {
    const { notification } = await portalRequest<{ notification: EmailNotification }>(`/api/myimperial/notifications/${id}/send`, { method: "POST" });
    setEmailNotifications((current) => current.map((item) => item.id === id ? { ...item, ...notification } : item));
    notify(`${id}: az emailt jóváhagytuk, elküldtük és naplóztuk.`);
  });

  const revokeInvitation = async (id: string) => runAction(async () => {
    await portalRequest(`/api/myimperial/members/invitations/${id}`, { method: "PATCH", body: JSON.stringify({ status: "revoked" }) });
    setInvitations((current) => current.map((item) => item.id === id ? { ...item, status: "revoked" } : item));
    notify(`${id}: a meghívást visszavontuk.`);
  });

  const initials = project.customerName.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();

  return (
    <main className={styles.portal}>
      <aside className={styles.sidebar}>
        <Link href="/myimperial" className={styles.logo}>
          <span className={styles.logoMark}>
            <i />
            <b />
          </span>
          <span>
            <strong>MYIMPERIAL</strong>
            <small>AZ OTTHONOD PROJEKTJE</small>
          </span>
        </Link>
        <div className={styles.projectMini}>
          <span>{project.portalCode}</span>
          <strong>{project.title}</strong>
          <small>{project.phase} · {project.progress}%</small>
          <div>
            <i style={{ width: `${project.progress}%` }} />
          </div>
        </div>
        <nav>
          {tabs.map((item) => (
            <button
              key={item.id}
              className={tab === item.id ? styles.active : ""}
              onClick={() => setTab(item.id)}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
              {item.id === "decisions" && openDecisions > 0 && (
                <em>{openDecisions}</em>
              )}
            </button>
          ))}
        </nav>
        <div className={styles.sidebarHelp}>
          <Icon name="message" />
          <strong>Segítségre van szükséged?</strong>
          <small>A projektcsapat egy munkanapon belül válaszol.</small>
          <button onClick={() => setRequestOpen(true)}>Üzenet küldése</button>
        </div>
        {isCrmAdmin && <Link className={styles.internalLink} href="/">
          <Icon name="lock" /> Belső rendszer
        </Link>}
      </aside>

      <section className={styles.main}>
        <header className={styles.topbar}>
          <div>
            <span>MYIMPERIAL ÜGYFÉLPORTÁL · {liveData === "live" ? "ÉLŐ PROJEKTADATOK" : liveData === "loading" ? "ADATKAPCSOLAT…" : "PILOT / BEMUTATÓ"}</span>
            <h1>{tabs.find((item) => item.id === tab)?.label}</h1>
          </div>
          <div className={styles.topActions}>
            <span className={styles.secure}>
              <Icon name="shield" /> BIZTONSÁGOS PROJEKTTÉR
            </span>
            <button
              className={styles.bell}
              onClick={() => setTab("notifications")}
            >
              <Icon name="bell" />
              {emailNotifications.some((item) => item.status === "draft" || item.status === "failed") && <i />}
            </button>
            <span className={styles.avatar}>{initials}</span>
            <span className={styles.user}>
              <strong>{project.customerName}</strong>
              <small>Megrendelő</small>
            </span>
          </div>
        </header>

        <div className={styles.content}>
          {tab === "overview" && (
            <Overview
              onTab={setTab}
              onRequest={() => setRequestOpen(true)}
              openDecisions={openDecisions}
            />
          )}
          {tab === "schedule" && <Schedule />}
          {tab === "documents" && <Documents documents={projectDocuments} onUpload={uploadDocument} notify={notify} />}
          {tab === "finance" && <Finance />}
          {tab === "tasks" && <CustomerTasks tasks={tasks} onAction={updateTask} notify={notify} projectCode={project.portalCode} />}
          {tab === "decisions" && (
            <Decisions
              decisions={projectDecisions}
              onDecide={updateDecision}
            />
          )}
          {tab === "changes" && <ChangeControl changes={changes} onCreate={createChange} onDecide={updateChange} />}
          {tab === "care" && <ImperialCare notify={notify} handoverDate={project.handoverDate} />}
          {tab === "notifications" && <NotificationCenter preferences={notificationPreferences} notifications={emailNotifications} provider={emailProvider} canApprove={canApproveEmails} onSave={saveNotificationPreferences} onApprove={approveNotification} />}
          {tab === "team" && <ProjectTeam members={members} invitations={invitations} canManage={canManageMembers} allowedRoles={allowedInviteRoles} providerConfigured={emailProvider.configured} onInvite={inviteMember} onSendInvitation={sendInvitationEmail} onRevoke={revokeInvitation} notify={notify} />}
          {tab === "photos" && <Photos />}
        </div>
      </section>

      {requestOpen && (
        <div className={styles.modalLayer}>
          <button
            className={styles.modalScrim}
            onClick={() => setRequestOpen(false)}
          />
          <section className={styles.modal}>
            <header>
              <div>
                <small>DOKUMENTÁLT KAPCSOLATFELVÉTEL</small>
                <h2>Üzenet a projektcsapatnak</h2>
                <p>Az üzenet bekerül a projekt eseménynaplójába.</p>
              </div>
              <button onClick={() => setRequestOpen(false)}>
                <Icon name="close" />
              </button>
            </header>
            <label>
              Téma
              <select value={requestTopic} onChange={(event) => setRequestTopic(event.target.value)}>
                <option>Általános kérdés</option>
                <option>Tervezési kérdés</option>
                <option>Pénzügy</option>
                <option>Változtatási igény</option>
                <option>Dokumentum</option>
              </select>
            </label>
            <label>
              Üzenet
              <textarea
                autoFocus
                rows={6}
                value={requestText}
                onChange={(event) => setRequestText(event.target.value)}
                placeholder="Írd le röviden, miben kérsz segítséget…"
              />
            </label>
            <footer>
              <button onClick={() => setRequestOpen(false)}>Mégse</button>
              <button
                disabled={!requestText.trim()}
                onClick={sendMessage}
              >
                Üzenet rögzítése
              </button>
            </footer>
          </section>
        </div>
      )}
      {toast && (
        <div className={styles.toast}>
          <Icon name="check" />
          {toast}
        </div>
      )}
    </main>
  );
}

function Overview({
  onTab,
  onRequest,
  openDecisions,
}: {
  onTab: (tab: Tab) => void;
  onRequest: () => void;
  openDecisions: number;
}) {
  return (
    <>
      <section className={styles.welcome}>
        <div>
          <p className={styles.eyebrow}>ÜDVÖZLÜNK A PROJEKTEDBEN</p>
          <h2>Jó reggelt, Péter!</h2>
          <p>
            A tervezés a jóváhagyott ütem szerint halad. A következő lépéshez{" "}
            <strong>{openDecisions} döntésedre</strong> van szükség.
          </p>
        </div>
        <button onClick={() => onTab("decisions")}>
          Döntéseim megnyitása <Icon name="arrow" />
        </button>
      </section>
      <section className={styles.summaryCards}>
        <article>
          <span>Projekt állapota</span>
          <strong>Tervezés · 42%</strong>
          <small>Az építészeti terv v4 jóváhagyásra vár</small>
          <div>
            <i style={{ width: "42%" }} />
          </div>
        </article>
        <article>
          <span>Következő mérföldkő</span>
          <strong>Alaprajz lezárása</strong>
          <small>Határidő: 2026. július 22.</small>
          <Icon name="calendar" />
        </article>
        <article>
          <span>Pénzügyi állapot</span>
          <strong>Rendezett</strong>
          <small>35% projektindítási összeg beérkezett</small>
          <Icon name="shield" />
        </article>
        <article className={openDecisions ? styles.attention : ""}>
          <span>Jóváhagyásra vár</span>
          <strong>{openDecisions} döntés</strong>
          <small>Nélkülük a következő gate nem nyitható</small>
          <button onClick={() => onTab("decisions")}>Áttekintés</button>
        </article>
      </section>
      <div className={styles.overviewGrid}>
        <section className={styles.panel}>
          <header>
            <div>
              <p className={styles.eyebrow}>PROJEKTÚT</p>
              <h3>Hol tart most az otthonod?</h3>
            </div>
            <button onClick={() => onTab("schedule")}>Teljes ütemterv</button>
          </header>
          <div className={styles.miniTimeline}>
            {milestones.slice(0, 5).map((item) => (
              <article key={item.title} className={styles[item.status]}>
                <i>
                  <Icon
                    name={
                      item.status === "done"
                        ? "check"
                        : item.status === "active"
                          ? "clock"
                          : "lock"
                    }
                  />
                </i>
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.note}</small>
                </span>
                <time>{item.date}</time>
              </article>
            ))}
          </div>
        </section>
        <aside className={styles.sideStack}>
          <section className={styles.panel}>
            <header>
              <div>
                <p className={styles.eyebrow}>KÖVETKEZŐ DÖNTÉSEK</p>
                <h3>Rád vár</h3>
              </div>
            </header>
            <div className={styles.nextDecisions}>
              {decisions
                .filter((item) => item.status === "open")
                .map((item) => (
                  <button key={item.id} onClick={() => onTab("decisions")}>
                    <i />
                    <span>
                      <strong>{item.title}</strong>
                      <small>{item.due}</small>
                    </span>
                    <Icon name="arrow" />
                  </button>
                ))}
            </div>
          </section>
          <section className={styles.managerCard}>
            <span className={styles.managerAvatar}>KA</span>
            <div>
              <small>PROJEKTMENEDZSERED</small>
              <strong>Kiss Andrea</strong>
              <p>Hétfő–péntek · 8:00–17:00</p>
            </div>
            <button onClick={onRequest}>
              <Icon name="message" />
            </button>
          </section>
        </aside>
      </div>
      <section className={styles.panel}>
        <header>
          <div>
            <p className={styles.eyebrow}>LEGUTÓBBI FRISSÍTÉSEK</p>
            <h3>Projektaktivitás</h3>
          </div>
          <button onClick={() => onTab("photos")}>Fotónapló</button>
        </header>
        <div className={styles.activityGrid}>
          <article>
            <span className={`${styles.photo} ${styles.photoOne}`}>
              <Icon name="camera" />
            </span>
            <div>
              <small>JÚLIUS 18. · TERVEZÉS</small>
              <strong>Építészeti alaprajz v4 feltöltve</strong>
              <p>A terv jóváhagyásra került az ügyfélportálra.</p>
            </div>
          </article>
          <article>
            <span className={`${styles.photo} ${styles.photoTwo}`}>
              <Icon name="file" />
            </span>
            <div>
              <small>JÚLIUS 16. · DOKUMENTUM</small>
              <strong>Előzetes ütemterv frissítve</strong>
              <p>A következő tervezési mérföldkövek pontosítva.</p>
            </div>
          </article>
          <article>
            <span className={`${styles.photo} ${styles.photoThree}`}>
              <Icon name="check" />
            </span>
            <div>
              <small>JÚLIUS 11. · JÓVÁHAGYÁS</small>
              <strong>Gépészeti koncepció elfogadva</strong>
              <p>A döntés bekerült a projekt változástörténetébe.</p>
            </div>
          </article>
        </div>
      </section>
      <section className={styles.serviceHub}>
        <div>
          <p className={styles.eyebrow}>MYIMPERIAL SZOLGÁLTATÁSOK</p>
          <h3>A teljes ügyfélút egy felületen</h3>
        </div>
        <button onClick={() => onTab("tasks")}>
          <i>
            <Icon name="list" />
          </i>
          <span>
            <strong>Teendőim</strong>
            <small>PlanCheck, pénzügy és műszaki hiánypótlások</small>
          </span>
          <b>3</b>
          <Icon name="arrow" />
        </button>
        <button onClick={() => onTab("changes")}>
          <i>
            <Icon name="change" />
          </i>
          <span>
            <strong>ChangeControl</strong>
            <small>Pótmunkák és változtatások dokumentált kezelése</small>
          </span>
          <b>1</b>
          <Icon name="arrow" />
        </button>
        <button onClick={() => onTab("care")}>
          <i>
            <Icon name="heart" />
          </i>
          <span>
            <strong>Imperial Care</strong>
            <small>Átadás, garancia, hibajegyek és visszaigazolás</small>
          </span>
          <em>ELŐKÉSZÍTVE</em>
          <Icon name="arrow" />
        </button>
      </section>
    </>
  );
}

function Schedule() {
  return (
    <>
      <PageIntro
        eyebrow="ÁTTEKINTHETŐ ÉS ELLENŐRIZHETŐ"
        title="Projektütemterv"
        text="A teljes folyamat a szerződéstől a műszaki átadásig. Zárt gate csak a kötelező dokumentumok és jóváhagyások után nyitható."
      />
      <section className={`${styles.panel} ${styles.fullTimeline}`}>
        {milestones.map((item, index) => (
          <article key={item.title} className={styles[item.status]}>
            <span className={styles.step}>{index + 1}</span>
            <i />
            <div>
              <small>
                {item.status === "done"
                  ? "TELJESÍTVE"
                  : item.status === "active"
                    ? "FOLYAMATBAN"
                    : item.status === "next"
                      ? "KÖVETKEZIK"
                      : "ZÁROLT GATE"}
              </small>
              <strong>{item.title}</strong>
              <p>{item.note}</p>
            </div>
            <time>{item.date}</time>
            {item.status === "locked" && <Icon name="lock" />}
          </article>
        ))}
      </section>
    </>
  );
}

function Documents({ documents, onUpload, notify }: {
  documents: PortalDocument[];
  onUpload: (form: FormData) => Promise<boolean>;
  notify: (message: string) => void;
}) {
  const [uploadOpen, setUploadOpen] = useState(false);
  const [target, setTarget] = useState<PortalDocument | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [group, setGroup] = useState("Tervezés");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<{ document: PortalDocument; versions: DocumentVersion[] } | null>(null);

  const openUpload = (document?: PortalDocument) => {
    setTarget(document || null);
    setName(document?.name || "");
    setGroup(document?.group || "Tervezés");
    setFile(null);
    setUploadOpen(true);
  };

  const showHistory = async (document: PortalDocument) => {
    try {
      const payload = await portalRequest<{ versions: DocumentVersion[] }>(`/api/myimperial/documents/${document.id}`);
      setHistory({ document, versions: payload.versions });
    } catch (error) {
      notify(error instanceof Error ? error.message : "A verziótörténet nem tölthető be.");
    }
  };

  const submit = async () => {
    if (!file) return;
    const form = new FormData();
    form.set("file", file);
    form.set("name", name);
    form.set("group", group);
    if (target) form.set("documentId", target.id);
    setBusy(true);
    const saved = await onUpload(form);
    setBusy(false);
    if (saved) setUploadOpen(false);
  };

  return (
    <>
      <PageIntro
        eyebrow="EGY HELYEN, VERZIÓKÖVETVE"
        title="Projektdokumentumok"
        text="Biztonságos projektfájlok verziószámmal, feltöltővel, időbélyeggel és SHA-256 ellenőrzőösszeggel."
      />
      <section className={docStyles.documentUploadBar}>
        <span>
          <Icon name="shield" />
          <i>
            <strong>Védett objektumtár</strong>
            <small>Projektjogosultság · 15 MB · PDF, kép, DOCX, XLSX</small>
          </i>
        </span>
        <span>
          <strong>{documents.filter((document) => !document.reference).length}</strong>
          <small>valódi projektfájl</small>
        </span>
        <button onClick={() => openUpload()}><Icon name="plus" /> Dokumentum feltöltése</button>
      </section>
      <section className={styles.panel}>
        <div className={`${styles.documentHead} ${docStyles.documentHead}`}>
          <span>Dokumentum</span>
          <span>Csoport</span>
          <span>Verzió</span>
          <span>Állapot</span>
          <span />
        </div>
        {documents.map((doc) => (
          <article className={`${styles.documentRow} ${docStyles.documentRow}`} key={doc.id}>
            <i>
              <Icon name="file" />
            </i>
            <span>
              <strong>{doc.name}</strong>
              <small>{doc.reference ? `${doc.date} · pilot referencia` : `${doc.date} · ${formatBytes(doc.size)} · SHA ${doc.sha256.slice(0, 8)}…`}</small>
            </span>
            <span>{doc.group}</span>
            <span>{doc.version}</span>
            <b className={styles[doc.status]}>
              {doc.status === "verified"
                ? "ELLENŐRZÖTT"
                : doc.status === "approval"
                  ? "JÓVÁHAGYÁSRA VÁR"
                  : "TERVEZET"}
            </b>
            <div className={docStyles.documentActions}>
              {doc.reference ? (
                <button onClick={() => notify("Ez a sor pilot referencia; tölts fel valódi fájlt a projekt objektumtárába.")} title="Pilot referencia">
                  <Icon name="lock" />
                </button>
              ) : (
                <>
                  <button onClick={() => showHistory(doc)} title="Verziótörténet"><Icon name="list" /></button>
                  <button onClick={() => openUpload(doc)} title="Új verzió"><Icon name="plus" /></button>
                  <a href={doc.downloadUrl} title="Letöltés"><Icon name="download" /></a>
                </>
              )}
            </div>
          </article>
        ))}
      </section>
      {uploadOpen && (
        <div className={styles.modalLayer}>
          <button className={styles.modalScrim} onClick={() => setUploadOpen(false)} />
          <section className={styles.modal}>
            <header>
              <div>
                <small>{target ? `${target.id} · ÚJ VERZIÓ` : "ÚJ PROJEKTDOKUMENTUM"}</small>
                <h2>{target ? target.name : "Dokumentum feltöltése"}</h2>
                <p>A fájl csak a projekt jogosult tagjai számára lesz elérhető.</p>
              </div>
              <button onClick={() => setUploadOpen(false)}><Icon name="close" /></button>
            </header>
            {!target && <label>
              Dokumentum neve
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder="pl. Építész alaprajz" />
            </label>}
            <label>
              Dokumentumcsoport
              <select value={group} disabled={Boolean(target)} onChange={(event) => setGroup(event.target.value)}>
                {['Szerződések', 'Tervezés', 'Telek', 'Pénzügy', 'Jegyzőkönyvek', 'Egyéb'].map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
            <label className={docStyles.filePicker}>
              Fájl kiválasztása
              <input
                type="file"
                accept=".pdf,.jpg,.jpeg,.png,.webp,.docx,.xlsx"
                onChange={(event) => {
                  const selected = event.target.files?.[0] || null;
                  setFile(selected);
                  if (selected && !target && !name) setName(selected.name.replace(/\.[^.]+$/, ""));
                }}
              />
              <span><Icon name="file" /><strong>{file?.name || "Kattints a fájl kiválasztásához"}</strong><small>{file ? formatBytes(file.size) : "Legfeljebb 15 MB"}</small></span>
            </label>
            <div className={styles.changeNotice}><Icon name="shield" /> Feltöltéskor fájltípus- és tartalomszignatúra-ellenőrzés, SHA-256 képzés, verziózás és auditnapló készül.</div>
            <footer>
              <button onClick={() => setUploadOpen(false)}>Mégse</button>
              <button disabled={busy || !file || (!target && !name.trim())} onClick={submit}>{busy ? "Biztonságos feltöltés…" : target ? `v${target.currentVersion + 1} feltöltése` : "Feltöltés"}</button>
            </footer>
          </section>
        </div>
      )}
      {history && (
        <div className={styles.modalLayer}>
          <button className={styles.modalScrim} onClick={() => setHistory(null)} />
          <section className={styles.modal}>
            <header>
              <div><small>{history.document.id}</small><h2>Verziótörténet</h2><p>{history.document.name}</p></div>
              <button onClick={() => setHistory(null)}><Icon name="close" /></button>
            </header>
            <div className={docStyles.versionList}>
              {history.versions.map((version) => (
                <article key={version.version}>
                  <i>v{version.version}</i>
                  <span><strong>{version.fileName}</strong><small>{portalDate(version.uploadedAt)} · {formatBytes(version.size)} · SHA-256 {version.sha256.slice(0, 12)}…</small></span>
                  <a href={`${history.document.downloadUrl}?version=${version.version}`}><Icon name="download" /></a>
                </article>
              ))}
            </div>
            <footer><button onClick={() => setHistory(null)}>Bezárás</button></footer>
          </section>
        </div>
      )}
    </>
  );
}

function Finance() {
  const paid = payments
    .filter((item) => item.status === "paid")
    .reduce((sum, item) => sum + item.percent, 0);
  return (
    <>
      <PageIntro
        eyebrow="PÉNZÜGYI-MŰSZAKI ÜTEMEZÉS"
        title="Fizetések és mérföldkövek"
        text="Fizetési pont csak dokumentált műszaki teljesítés és jóváhagyás után válik esedékessé."
      />
      <section className={styles.financeSummary}>
        <article>
          <span>Szerződéses alapösszeg</span>
          <strong>69 400 000 Ft</strong>
          <small>Pilot projektadat · 5% ÁFA szerint</small>
        </article>
        <article>
          <span>Teljesítve és befizetve</span>
          <strong>{paid}%</strong>
          <small>24 290 000 Ft</small>
        </article>
        <article>
          <span>Következő fizetési pont</span>
          <strong>Falazat · 8%</strong>
          <small>Csak G5 kapu és teljesítésigazolás után</small>
        </article>
      </section>
      <section className={styles.panel}>
        <div className={styles.paymentProgress}>
          <span>
            <strong>Projekt pénzügyi készültsége</strong>
            <small>{paid}% rendezve</small>
          </span>
          <div>
            <i style={{ width: `${paid}%` }} />
          </div>
        </div>
        <div className={styles.payments}>
          {payments.map((payment) => (
            <article key={payment.title} className={styles[payment.status]}>
              <i>
                {payment.status === "paid" ? (
                  <Icon name="check" />
                ) : (
                  <Icon name="lock" />
                )}
              </i>
              <span>
                <strong>{payment.title}</strong>
                <small>{payment.due}</small>
              </span>
              <b>{payment.percent}%</b>
              <em>{payment.amount}</em>
              <strong>
                {payment.status === "paid"
                  ? "RENDEZVE"
                  : payment.status === "upcoming"
                    ? "KÖVETKEZŐ"
                    : "MÉG NEM ESEDÉKES"}
              </strong>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}

function CustomerTasks({ tasks, onAction, notify, projectCode }: {
  tasks: CustomerTask[];
  onAction: (id: string, status: "submitted" | "completed") => Promise<boolean>;
  notify: (message: string) => void;
  projectCode: string;
}) {
  const [busy, setBusy] = useState("");
  return (
    <>
      <PageIntro
        eyebrow="KÖZÖS ÜGYFÉL-MUNKASOR"
        title="Teendőim és hiánypótlások"
        text="A PlanCheck, a műszaki csapat, a pénzügy és a ChangeControl minden ügyfélközreműködést igénylő feladata közös TaskID-val jelenik meg."
      />
      <section className={styles.taskSummary}>
        <article>
          <span>Nyitott ügyfélteendő</span>
          <strong>
            {
              tasks.filter((task) => task.status === "waiting_customer").length
            }
          </strong>
          <small>waiting_customer státusz</small>
        </article>
        <article>
          <span>Kritikus határidő</span>
          <strong>{tasks.filter((task) => task.severity === "high" && task.status === "waiting_customer").length}</strong>
          <small>PlanCheck hiánypótlás</small>
        </article>
        <article>
          <span>Lezárt ebben a hónapban</span>
          <strong>{tasks.filter((task) => task.status === "completed").length}</strong>
          <small>Időbélyeggel és bizonyítékkal</small>
        </article>
      </section>
      <section className={`${styles.panel} ${styles.customerTasks}`}>
        <header>
          <div>
            <p className={styles.eyebrow}>CUSTOMER ACTION REQUIRED</p>
            <h3>Rád váró feladatok</h3>
          </div>
          <span>ProjectID: {projectCode}</span>
        </header>
        {tasks.map((task) => {
          const isDone = task.status === "completed";
          const isSubmitted = task.status === "submitted";
          return (
            <article key={task.id} className={isDone || isSubmitted ? styles.taskDone : ""}>
              <i className={styles[task.severity]}>
                {isDone || isSubmitted ? <Icon name="check" /> : <Icon name="clock" />}
              </i>
              <span>
                <small>
                  {task.source} · {task.id}
                </small>
                <strong>{task.title}</strong>
                <em>{isDone ? "TELJESÍTVE" : isSubmitted ? "ELLENŐRZÉSRE BEKÜLDVE" : `Határidő: ${task.due}`}</em>
              </span>
              <b>
                {task.status === "waiting_customer" ? "ÜGYFÉLRE VÁR" : isSubmitted ? "ELLENŐRZÉS ALATT" : "LEZÁRVA"}
              </b>
              <button
                disabled={busy === task.id}
                onClick={async () => {
                  if (task.status === "waiting_customer") {
                    setBusy(task.id);
                    await onAction(task.id, "submitted");
                    setBusy("");
                  } else notify(`${task.id}: a feladat bizonyítékai megnyithatók.`);
                }}
              >
                {busy === task.id ? "Rögzítés…" : isDone || isSubmitted ? "Megtekintés" : task.action}
                <Icon name="arrow" />
              </button>
            </article>
          );
        })}
      </section>
      <section className={styles.planCheckInfo}>
        <Icon name="shield" />
        <div>
          <small>PLANCHECK KAPCSOLAT</small>
          <strong>
            A feltöltött dokumentum csak műszaki ellenőrzés után zárja le a
            hiánypótlást.
          </strong>
          <p>
            A rendszer nem jelöl automatikusan megfelelőnek egy fájlt pusztán a
            feltöltés miatt.
          </p>
        </div>
      </section>
    </>
  );
}

function ChangeControl({ changes, onCreate, onDecide }: {
  changes: ProjectChange[];
  onCreate: (title: string, description: string, category: string) => Promise<boolean>;
  onDecide: (id: string, status: "approved" | "rejected") => Promise<boolean>;
}) {
  const [showNew, setShowNew] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("Alaprajzi módosítás");
  const [busy, setBusy] = useState("");
  const [filter, setFilter] = useState<"active" | "all">("active");
  const visible = changes.filter(
    (change) =>
      filter === "all" ||
      ["customer_approval", "internal_review"].includes(change.status),
  );
  const decide = async (id: string, status: "approved" | "rejected") => {
    setBusy(id);
    await onDecide(id, status);
    setBusy("");
  };
  return (
    <>
      <section className={styles.changeHero}>
        <div>
          <p className={styles.eyebrow}>SCOPE · ÁR · HATÁRIDŐ · JÓVÁHAGYÁS</p>
          <h2>ChangeControl</h2>
          <p>
            Minden eltérés és pótmunka külön ChangeID-val, teljes
            hatáselemzéssel és dokumentált döntéssel.
          </p>
        </div>
        <button onClick={() => setShowNew(true)}>
          <Icon name="plus" /> Változtatási igény
        </button>
      </section>
      <section className={styles.changeRules}>
        <article>
          <Icon name="lock" />
          <span>
            <strong>Jóváhagyás nélkül nincs végrehajtás</strong>
            <small>
              A munka csak a szükséges műszaki, pénzügyi és ügyfélkapuk után
              indítható.
            </small>
          </span>
        </article>
        <article>
          <Icon name="wallet" />
          <span>
            <strong>Belső ár- és fedezetkontroll</strong>
            <small>
              A belső fedezetvizsgálatot az Imperial végzi; itt csak a
              jóváhagyásra kész árhatás jelenik meg.
            </small>
          </span>
        </article>
        <article>
          <Icon name="calendar" />
          <span>
            <strong>Ütemterv automatikus hatásvizsgálata</strong>
            <small>
              Az elfogadott határidőhatás a projekt baseline új verzióját
              képezi.
            </small>
          </span>
        </article>
      </section>
      <div className={styles.changeToolbar}>
        <div>
          <button
            className={filter === "active" ? styles.selected : ""}
            onClick={() => setFilter("active")}
          >
            Aktív
          </button>
          <button
            className={filter === "all" ? styles.selected : ""}
            onClick={() => setFilter("all")}
          >
            Összes
          </button>
        </div>
        <span>{visible.length} változtatás</span>
      </div>
      <div className={styles.changeList}>
        {visible.map((change) => (
          <article key={change.id}>
            <header>
              <span>
                <small>
                  {change.id} · {change.origin}
                </small>
                <strong>{change.title}</strong>
              </span>
              <b className={styles[change.status]}>
                {change.status === "customer_approval"
                  ? "ÜGYFÉLJÓVÁHAGYÁSRA VÁR"
                  : change.status === "approved"
                    ? "JÓVÁHAGYVA"
                    : change.status === "rejected"
                      ? "ELUTASÍTVA"
                      : "BELSŐ ELEMZÉS"}
              </b>
            </header>
            <p>{change.scope}</p>
            <div className={styles.changeImpact}>
              <span>
                <small>ÁRHATÁS</small>
                <strong>{change.price}</strong>
              </span>
              <span>
                <small>HATÁRIDŐHATÁS</small>
                <strong>{change.schedule}</strong>
              </span>
              <span>
                <small>BELSŐ KONTROLL</small>
                <strong>{change.internalControl}</strong>
              </span>
              <span>
                <small>BIZONYÍTÉK</small>
                <strong>{change.evidence}</strong>
              </span>
            </div>
            <footer>
              <small>Létrehozva: {change.created}</small>
              {change.status === "customer_approval" ? (
                <div>
                  <button disabled={busy === change.id} onClick={() => decide(change.id, "rejected")}>
                    {busy === change.id ? "Rögzítés…" : "Elutasítom"}
                  </button>
                  <button disabled={busy === change.id} onClick={() => decide(change.id, "approved")}>
                    <Icon name="check" /> Elfogadom a hatásokat
                  </button>
                </div>
              ) : (
                <span>
                  <Icon
                    name={change.status === "approved" ? "check" : "lock"}
                  />
                  {change.status === "approved"
                    ? "Végrehajtható a jóváhagyott tartalom szerint"
                    : change.status === "rejected"
                      ? "Nem hajtható végre"
                      : "Belső jóváhagyásokra vár"}
                </span>
              )}
            </footer>
          </article>
        ))}
      </div>
      {showNew && (
        <div className={styles.modalLayer}>
          <button
            className={styles.modalScrim}
            onClick={() => setShowNew(false)}
          />
          <section className={styles.modal}>
            <header>
              <div>
                <small>ÚJ CHANGEID INDÍTÁSA</small>
                <h2>Változtatási igény</h2>
                <p>Az igény még nem jelent megrendelést vagy jóváhagyást.</p>
              </div>
              <button onClick={() => setShowNew(false)}>
                <Icon name="close" />
              </button>
            </header>
            <label>
              Kategória
              <select value={category} onChange={(event) => setCategory(event.target.value)}>
                <option>Alaprajzi módosítás</option>
                <option>Műszaki tartalom</option>
                <option>Anyagválasztás</option>
                <option>Határidő</option>
                <option>Egyéb</option>
              </select>
            </label>
            <label>
              Igény rövid megnevezése
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="pl. Nappali nyílászáró módosítása"
              />
            </label>
            <label>
              Részletes leírás
              <textarea
                rows={5}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Mit szeretnél módosítani és miért?"
              />
            </label>
            <div className={styles.changeNotice}>
              <Icon name="clock" /> A projektcsapat műszaki, ár- és
              határidőhatást készít, valamint elvégzi a belső kontrollt. Csak
              ezután kérhető ügyféljóváhagyás.
            </div>
            <footer>
              <button onClick={() => setShowNew(false)}>Mégse</button>
              <button
                disabled={!title.trim() || !description.trim()}
                onClick={async () => {
                  setBusy("new");
                  const saved = await onCreate(title, description, category);
                  if (saved) {
                    setTitle("");
                    setDescription("");
                    setShowNew(false);
                  }
                  setBusy("");
                }}
              >
                {busy === "new" ? "Rögzítés…" : "Igény rögzítése"}
              </button>
            </footer>
          </section>
        </div>
      )}
    </>
  );
}

function ImperialCare({ notify, handoverDate }: { notify: (message: string) => void; handoverDate: string | null }) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const careActive = Boolean(handoverDate);
  return (
    <>
      <section className={styles.careHero}>
        <div className={styles.careSymbol}>
          <Icon name="heart" />
        </div>
        <div>
          <p className={styles.eyebrow}>ÁTADÁS UTÁNI BIZTONSÁG</p>
          <h2>Imperial Care</h2>
          <p>
            A garanciális időszak, hibabejelentések, javítási bizonyítékok és
            ügyfél-visszaigazolások ellenőrzött felülete.
          </p>
        </div>
        <b>
          <Icon name={careActive ? "check" : "lock"} /> {careActive ? "AKTÍV" : "ÁTADÁSKOR AKTIVÁLÓDIK"}
        </b>
      </section>
      <section className={styles.careStatus}>
        <article>
          <span>Jelenlegi projektfázis</span>
          <strong>Tervezés</strong>
          <small>{careActive ? "Imperial Care aktív" : "Imperial Care még nem aktív"}</small>
        </article>
        <article>
          <span>Tervezett átadás</span>
          <strong>2027. május</strong>
          <small>A garanciális időszak kezdete</small>
        </article>
        <article>
          <span>Care-felelős</span>
          <strong>Átadáskor kijelölve</strong>
          <small>Külön garanciális koordinátor</small>
        </article>
      </section>
      <div className={styles.careGrid}>
        <section className={styles.panel}>
          <header>
            <div>
              <p className={styles.eyebrow}>IMPERIAL CARE FOLYAMAT</p>
              <h3>Így kezeljük a garanciális ügyet</h3>
            </div>
          </header>
          <div className={styles.careSteps}>
            <article>
              <i>1</i>
              <span>
                <strong>CaseID és bejelentés</strong>
                <small>
                  Helyiség, hibajelenség, súlyosság, fotók és elérhetőség.
                </small>
              </span>
            </article>
            <article>
              <i>2</i>
              <span>
                <strong>Garanciális vizsgálat</strong>
                <small>
                  A koordinátor határidőt, felelőst és szükséges helyszíni
                  vizsgálatot rendel.
                </small>
              </span>
            </article>
            <article>
              <i>3</i>
              <span>
                <strong>Javítás és bizonyíték</strong>
                <small>
                  A javítás fotóval, munkalappal és dátummal dokumentált.
                </small>
              </span>
            </article>
            <article>
              <i>4</i>
              <span>
                <strong>Ügyfél-visszaigazolás</strong>
                <small>
                  Az ügy csak a dokumentált javítás és az ügyfél visszaigazolása
                  után zárható.
                </small>
              </span>
            </article>
          </div>
        </section>
        <aside className={styles.sideStack}>
          <section className={styles.careCard}>
            <Icon name="shield" />
            <span>
              <small>GARANCIÁLIS DOKUMENTUMCSOMAG</small>
              <strong>Automatikusan létrejön átadáskor</strong>
              <p>
                Jegyzőkönyv, használati útmutatók, jótállási dokumentumok és
                kapcsolattartók.
              </p>
            </span>
          </section>
          <section className={styles.panel}>
            <header>
              <div>
                <p className={styles.eyebrow}>AKTÍV HIBAJEGY</p>
                <h3>Nincs nyitott ügy</h3>
              </div>
            </header>
            <div className={styles.emptyCare}>
              <Icon name="check" />
              <strong>A projekt még nem került átadásra</strong>
              <small>
                Átadás előtti műszaki észrevételt a projektcsapatnak kell
                elküldeni, nem garanciális ügyként.
              </small>
              <button
                onClick={() =>
                  notify("Az üzenetküldőben a „Műszaki kérdés” témát válaszd.")
                }
              >
                Műszaki észrevétel
              </button>
            </div>
          </section>
        </aside>
      </div>
      <section className={styles.carePreview}>
        <div>
          <p className={styles.eyebrow}>HIBAJEGY FELÜLET ELŐNÉZETE</p>
          <h3>A Care-modul már elő van készítve</h3>
          <p>
            Az aktív bejelentés minden kötelező adatot és bizonyítékot egy
            helyen kezel majd.
          </p>
        </div>
        <button onClick={() => setPreviewOpen(!previewOpen)}>
          {previewOpen ? "Előnézet bezárása" : "Hibajegykártya megtekintése"}
        </button>
      </section>
      {previewOpen && (
        <article className={styles.warrantyPreview}>
          <header>
            <span>
              <small>CASE-2027-001 · FOLYAMATMINTA</small>
              <strong>Nappali nyílászáró beállítása</strong>
            </span>
            <b>VIZSGÁLAT ÜTEMEZVE</b>
          </header>
          <div>
            <span>
              <small>SÚLYOSSÁG</small>
              <strong>Normál</strong>
            </span>
            <span>
              <small>FELELŐS</small>
              <strong>Garanciális koordinátor</strong>
            </span>
            <span>
              <small>KÖVETKEZŐ HATÁRIDŐ</small>
              <strong>2 munkanap</strong>
            </span>
            <span>
              <small>BIZONYÍTÉK</small>
              <strong>3 fotó · bejelentés</strong>
            </span>
          </div>
          <footer>
            <Icon name="lock" /> Folyamatminta – nem valós garanciális ügy
          </footer>
        </article>
      )}
    </>
  );
}

function Decisions({
  decisions,
  onDecide,
}: {
  decisions: ProjectDecision[];
  onDecide: (id: number, status: "approved" | "question") => Promise<boolean>;
}) {
  const [busy, setBusy] = useState(0);
  const decide = async (id: number, status: "approved" | "question") => {
    setBusy(id);
    await onDecide(id, status);
    setBusy(0);
  };
  return (
    <>
      <PageIntro
        eyebrow="DOKUMENTÁLT ÜGYFÉLDÖNTÉSEK"
        title="Jóváhagyások és választások"
        text="A döntéseid időbélyeggel bekerülnek a projekt változástörténetébe. Műszaki vagy pénzügyi változtatás külön ChangeControl folyamatot indít."
      />
      <div className={styles.decisionList}>
        {decisions.map((decision) => {
          const status = decision.status;
          return (
            <article
              key={decision.id}
              className={status === "approved" ? styles.approvedCard : ""}
            >
              <header>
                <span>{decision.area}</span>
                <b>
                  {status === "approved"
                    ? "JÓVÁHAGYVA"
                    : status === "question"
                      ? "KÉRDÉS ELKÜLDVE"
                      : decision.due}
                </b>
              </header>
              <h3>{decision.title}</h3>
              <p>{decision.impact}</p>
              {status === "open" ? (
                <footer>
                  <button
                    disabled={busy === decision.id}
                    onClick={() => decide(decision.id, "question")}
                  >
                    {busy === decision.id ? "Rögzítés…" : "Kérdésem van"}
                  </button>
                  <button
                    disabled={busy === decision.id}
                    onClick={() => decide(decision.id, "approved")}
                  >
                    <Icon name="check" /> Jóváhagyom
                  </button>
                </footer>
              ) : (
                <footer>
                  <span>
                    <Icon name={status === "approved" ? "check" : "message"} />
                    {status === "approved"
                      ? "Döntés dokumentálva"
                      : "Projektcsapat válaszára vár"}
                  </span>
                </footer>
              )}
            </article>
          );
        })}
      </div>
    </>
  );
}

const memberRoleLabels: Record<MemberRole, string> = {
  customer: "Elsődleges megrendelő",
  contact: "Ügyfél-kapcsolattartó",
  project_manager: "Projektmenedzser",
  technical: "Műszaki szakértő",
  finance: "Pénzügyi kapcsolattartó",
  warranty: "Garanciális koordinátor",
};

const notificationLabels: Record<EmailNotification["templateKey"], string> = {
  invitation: "Projektmeghívó",
  task: "Teendő",
  decision: "Döntés",
  change: "ChangeControl",
  document: "Dokumentum",
  message: "Projektüzenet",
  care: "Imperial Care",
};

const notificationStatusLabels: Record<EmailNotification["status"], string> = {
  draft: "JÓVÁHAGYÁSRA VÁR",
  approved: "JÓVÁHAGYVA",
  sending: "KÜLDÉS ALATT",
  sent: "ELKÜLDVE",
  failed: "SIKERTELEN",
  cancelled: "TÖRÖLVE",
};

function NotificationCenter({ preferences, notifications, provider, canApprove, onSave, onApprove }: {
  preferences: NotificationPreferences;
  notifications: EmailNotification[];
  provider: EmailProvider;
  canApprove: boolean;
  onSave: (changes: Partial<NotificationPreferences>) => Promise<boolean>;
  onApprove: (id: string) => Promise<boolean>;
}) {
  const [busyId, setBusyId] = useState("");
  const preferenceRows: Array<{ key: keyof NotificationPreferences; title: string; text: string }> = [
    { key: "taskNotifications", title: "Teendők", text: "Beküldés, ellenőrzés és lezárás" },
    { key: "decisionNotifications", title: "Döntések", text: "Jóváhagyás vagy új kérdés" },
    { key: "changeNotifications", title: "ChangeControl", text: "Új ChangeID és ügyféldöntés" },
    { key: "documentNotifications", title: "Dokumentumok", text: "Új fájl vagy verzió" },
    { key: "messageNotifications", title: "Projektüzenetek", text: "Dokumentált kapcsolattartás" },
    { key: "careNotifications", title: "Imperial Care", text: "Garanciális és karbantartási események" },
  ];
  const pendingCount = notifications.filter((item) => item.status === "draft" || item.status === "failed").length;

  const approve = async (id: string) => {
    setBusyId(id);
    await onApprove(id);
    setBusyId("");
  };

  return (
    <>
      <section className={notificationStyles.hero}>
        <div>
          <p className={styles.eyebrow}>EMAIL · EMBERI JÓVÁHAGYÁS · AUDIT</p>
          <h2>Értesítési központ</h2>
          <p>A projekt eseményeiből áttekinthető piszkozat készül. Külső email csak jogosult személy jóváhagyása után indul.</p>
        </div>
        <span className={provider.configured ? notificationStyles.ready : notificationStyles.setup}>
          <Icon name={provider.configured ? "check" : "tool"} />
          <strong>{provider.configured ? "Küldésre kész" : "Beállítás szükséges"}</strong>
          <small>{provider.configured ? provider.fromEmail : "Email-szolgáltató nincs összekötve"}</small>
        </span>
      </section>
      <section className={notificationStyles.metrics}>
        <article><span>Jóváhagyásra vár</span><strong>{pendingCount}</strong><small>ellenőrizhető piszkozat</small></article>
        <article><span>Elküldött email</span><strong>{notifications.filter((item) => item.status === "sent").length}</strong><small>naplózott kézbesítési kérés</small></article>
        <article><span>Biztonsági mód</span><strong>Emberi kontroll</strong><small>nincs automatikus vállalás</small></article>
      </section>
      {!provider.configured && <section className={notificationStyles.notice}><Icon name="shield" /><span><strong>A funkció elő van készítve, de még nem küld valódi emailt.</strong><small>A Resend API-kulcs és egy hitelesített feladói email megadása után kapcsolható be. A meghívási link addig kézzel is másolható.</small></span></section>}
      <div className={notificationStyles.grid}>
        <section className={styles.panel}>
          <header><div><p className={styles.eyebrow}>SAJÁT BEÁLLÍTÁSOK</p><h3>Miről kérsz emailt?</h3></div></header>
          <div className={notificationStyles.preferences}>
            {preferenceRows.map((row) => (
              <label key={row.key}>
                <span><strong>{row.title}</strong><small>{row.text}</small></span>
                <input type="checkbox" checked={Boolean(preferences[row.key])} onChange={(event) => onSave({ [row.key]: event.target.checked })} />
                <i />
              </label>
            ))}
            <label className={notificationStyles.frequency}>
              <span><strong>Értesítési mód</strong><small>Azonnali piszkozat vagy kikapcsolás</small></span>
              <select value={preferences.digestFrequency} onChange={(event) => onSave({ digestFrequency: event.target.value as NotificationPreferences["digestFrequency"] })}>
                <option value="immediate">Azonnali piszkozat</option>
                <option value="off">Kikapcsolva</option>
              </select>
            </label>
          </div>
        </section>
        <section className={styles.panel}>
          <header><div><p className={styles.eyebrow}>KÜLDÉSI NAPLÓ</p><h3>Email-piszkozatok</h3></div></header>
          <div className={notificationStyles.outbox}>
            {notifications.length === 0 && <div className={notificationStyles.empty}><Icon name="bell" /><strong>Még nincs email-piszkozat</strong><small>A következő releváns projektesemény automatikusan megjelenik itt.</small></div>}
            {notifications.map((item) => (
              <article key={item.id}>
                <div className={notificationStyles.outboxIcon}><Icon name={item.templateKey === "document" ? "file" : item.templateKey === "change" ? "change" : item.templateKey === "invitation" ? "users" : "bell"} /></div>
                <span><small>{notificationLabels[item.templateKey]} · {portalDate(item.createdAt)}</small><strong>{item.subject}</strong><em>{item.recipientName} · {item.recipientEmail}</em>{item.lastError && <b>{item.lastError}</b>}</span>
                <div className={notificationStyles.outboxAction}>
                  <i className={notificationStyles[item.status]}>{notificationStatusLabels[item.status]}</i>
                  {canApprove && (item.status === "draft" || item.status === "failed") && <button disabled={busyId === item.id || !provider.configured} onClick={() => approve(item.id)}>{busyId === item.id ? "Küldés…" : "Jóváhagyás és küldés"}</button>}
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}

function ProjectTeam({ members, invitations, canManage, allowedRoles, providerConfigured, onInvite, onSendInvitation, onRevoke, notify }: {
  members: ProjectMember[];
  invitations: ProjectInvitation[];
  canManage: boolean;
  allowedRoles: MemberRole[];
  providerConfigured: boolean;
  onInvite: (data: { email: string; displayName: string; role: MemberRole }) => Promise<{ inviteUrl: string; invitationId: string } | null>;
  onSendInvitation: (invitationId: string, inviteUrl: string) => Promise<boolean>;
  onRevoke: (id: string) => Promise<boolean>;
  notify: (message: string) => void;
}) {
  const [modalOpen, setModalOpen] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<MemberRole>(allowedRoles[0] || "contact");
  const [busy, setBusy] = useState(false);
  const [inviteUrl, setInviteUrl] = useState("");
  const [invitationId, setInvitationId] = useState("");
  const [emailSent, setEmailSent] = useState(false);

  const createInvite = async () => {
    setBusy(true);
    const result = await onInvite({ displayName, email, role });
    setBusy(false);
    if (result) {
      setInviteUrl(result.inviteUrl);
      setInvitationId(result.invitationId);
    }
  };

  const sendInvitation = async () => {
    setBusy(true);
    const sent = await onSendInvitation(invitationId, inviteUrl);
    setBusy(false);
    if (sent) setEmailSent(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    setInviteUrl("");
    setInvitationId("");
    setEmailSent(false);
    setDisplayName("");
    setEmail("");
  };

  return (
    <>
      <section className={teamStyles.hero}>
        <div>
          <p className={styles.eyebrow}>SZEREPKÖR · LEGKISEBB JOGOSULTSÁG · AUDIT</p>
          <h2>Projektcsapat és hozzáférések</h2>
          <p>Minden résztvevő csak a saját projektjét és szerepköréhez tartozó ügyféladatokat érheti el.</p>
        </div>
        {canManage && <button onClick={() => setModalOpen(true)}><Icon name="plus" /> Kapcsolattartó meghívása</button>}
      </section>
      <section className={teamStyles.accessNotice}>
        <Icon name="lock" />
        <span>
          <strong>Tulajdonosi pilot hozzáférés</strong>
          <small>A meghívási folyamat működik, de az új személy csak külön Sites-adminisztrátori engedély után jut át a belépési kapun.</small>
        </span>
      </section>
      <section className={teamStyles.metrics}>
        <article><span>Aktív projekttag</span><strong>{members.length}</strong><small>azonosított hozzáférés</small></article>
        <article><span>Függő meghívás</span><strong>{invitations.filter((item) => item.status === "pending").length}</strong><small>7 napos érvényesség</small></article>
        <article><span>Hozzáférési modell</span><strong>Projektalapú</strong><small>más projekt nem látható</small></article>
      </section>
      <div className={teamStyles.grid}>
        <section className={styles.panel}>
          <header><div><p className={styles.eyebrow}>AKTÍV HOZZÁFÉRÉSEK</p><h3>Projekt tagjai</h3></div></header>
          <div className={teamStyles.memberList}>
            {members.map((member) => (
              <article key={member.email}>
                <i>{member.displayName.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase()}</i>
                <span><strong>{member.displayName}</strong><small>{member.email}</small></span>
                <b>{memberRoleLabels[member.role]}</b>
                <em><Icon name="shield" /> AKTÍV</em>
              </article>
            ))}
          </div>
        </section>
        <section className={styles.panel}>
          <header><div><p className={styles.eyebrow}>MEGHÍVÁSI NAPLÓ</p><h3>Kapcsolattartói meghívások</h3></div></header>
          <div className={teamStyles.inviteList}>
            {invitations.length === 0 && <div className={teamStyles.empty}><Icon name="users" /><strong>Még nincs további meghívás</strong><small>Új kapcsolattartót a fenti gombbal adhatsz a projekthez.</small></div>}
            {invitations.map((invitation) => (
              <article key={invitation.id}>
                <span><small>{invitation.id}</small><strong>{invitation.displayName}</strong><em>{invitation.email} · {memberRoleLabels[invitation.role]}</em></span>
                <b className={teamStyles[invitation.status]}>{invitation.status === "pending" ? "FÜGGŐBEN" : invitation.status === "accepted" ? "ELFOGADVA" : invitation.status === "revoked" ? "VISSZAVONVA" : "LEJÁRT"}</b>
                {invitation.status === "pending" && canManage && <button onClick={() => onRevoke(invitation.id)}>Visszavonás</button>}
              </article>
            ))}
          </div>
        </section>
      </div>
      {modalOpen && (
        <div className={styles.modalLayer}>
          <button className={styles.modalScrim} onClick={closeModal} />
          <section className={styles.modal}>
            <header>
              <div><small>PROJEKTJOGOSULTSÁG</small><h2>{inviteUrl ? "Meghívás elkészült" : "Kapcsolattartó meghívása"}</h2><p>{inviteUrl ? "A link egyszer jelenik meg; másold ki biztonságosan." : "A hozzáférés személyhez, emailhez és szerepkörhöz kötött."}</p></div>
              <button onClick={closeModal}><Icon name="close" /></button>
            </header>
            {inviteUrl ? (
              <div className={teamStyles.inviteReady}>
                <Icon name="check" />
                <strong>7 napig érvényes meghívó</strong>
                <p>A link csak a megadott email-címmel használható. A címzett belépéséhez külön Sites-adminisztrátori engedély is szükséges.</p>
                <input readOnly value={inviteUrl} onFocus={(event) => event.currentTarget.select()} />
                <button onClick={() => navigator.clipboard.writeText(inviteUrl).then(() => notify("A meghívási linket a vágólapra másoltuk.")).catch(() => notify("Jelöld ki és másold ki kézzel a linket."))}>Hivatkozás másolása</button>
                <button className={teamStyles.emailButton} disabled={busy || emailSent || !providerConfigured} onClick={sendInvitation}>{emailSent ? "Email elküldve" : busy ? "Küldés…" : "Email jóváhagyása és küldése"}</button>
                {!providerConfigured && <small className={teamStyles.emailHint}>Az email-küldés beállításáig használd a másolható hivatkozást.</small>}
              </div>
            ) : (
              <>
                <label>Név<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="pl. Minta Anna" /></label>
                <label>Email-cím<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="anna@pelda.hu" /></label>
                <label>Szerepkör<select value={role} onChange={(event) => setRole(event.target.value as MemberRole)}>{allowedRoles.map((item) => <option key={item} value={item}>{memberRoleLabels[item]}</option>)}</select></label>
                <div className={styles.changeNotice}><Icon name="shield" /> Ügyfélként csak további kapcsolattartó hívható meg. Belső szakmai szerepkört kizárólag CRM-admin adhat.</div>
              </>
            )}
            <footer>
              <button onClick={closeModal}>{inviteUrl ? "Bezárás" : "Mégse"}</button>
              {!inviteUrl && <button disabled={busy || !displayName.trim() || !email.trim()} onClick={createInvite}>{busy ? "Meghívás készítése…" : "Meghívó létrehozása"}</button>}
            </footer>
          </section>
        </div>
      )}
    </>
  );
}

function Photos() {
  const items = [
    "Telek geodéziai felmérése",
    "Talajmechanikai mintavétel",
    "Helyszíni tervezői bejárás",
    "Kitűzési alappontok",
    "Utcai csatlakozások",
    "Telek állapota projektindításkor",
  ];
  return (
    <>
      <PageIntro
        eyebrow="FOTÓDOKUMENTÁCIÓ ÉS BIZONYÍTÁS"
        title="Projektfotók"
        text="Minden lényeges mérföldkő és takarás előtti állapot dátummal, készítővel és kapcsolódó munkafázissal."
      />
      <div className={styles.photoGrid}>
        {items.map((item, index) => (
          <article key={item}>
            <div className={styles[`gallery${index + 1}`]}>
              <Icon name="camera" />
              <span>{index + 1}/6</span>
            </div>
            <footer>
              <small>2026. ÁPRILIS {4 + index}.</small>
              <strong>{item}</strong>
              <p>Kiss Andrea · Projektmenedzser</p>
            </footer>
          </article>
        ))}
      </div>
    </>
  );
}

function PageIntro({
  eyebrow,
  title,
  text,
}: {
  eyebrow: string;
  title: string;
  text: string;
}) {
  return (
    <section className={styles.pageIntro}>
      <p className={styles.eyebrow}>{eyebrow}</p>
      <h2>{title}</h2>
      <p>{text}</p>
    </section>
  );
}
