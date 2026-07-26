"use client";

import styles from "./intelligence.module.css";

export type IntelligenceWorkspace = {
  workspaceId: string;
  generatedAt: string;
  modules: {
    key: string;
    name: string;
    owner: string;
    state: "ready" | "testable" | "blocked";
    evidence: string;
    productionGate?: string;
  }[];
  projects: {
    imported: {
      id: number;
      title: string;
      location: string | null;
      projectType: string | null;
      status: string;
      customerMatchStatus: string;
      updatedAt: string;
    }[];
    portal: {
      id: string;
      title: string;
      customerName: string;
      status: string;
      phase: string;
      progress: number;
      targetCompletion: string;
      updatedAt: string;
    }[];
  };
  partners: {
    id: number;
    name: string;
    partnerType: string;
    location: string | null;
    specialties: string | null;
    status: string;
    matchConfidence: number;
    updatedAt: string;
  }[];
  reviews: {
    id: number;
    entityType: string;
    reasonCode: string;
    summary: string;
    status: string;
    sourceTitle: string;
    sourceUrl: string;
    createdAt: string;
  }[];
  sources: {
    id: number;
    title: string;
    recordType: string;
    sourceSystem: string;
    sourceUrl: string;
    reviewStatus: string;
    mimeType: string | null;
    byteSize: number | null;
    updatedAt: string;
  }[];
  calendar: {
    id: string;
    kind: string;
    title: string;
    context: string;
    when: string;
    priority: string;
    status: string;
  }[];
  agents: {
    key: string;
    name: string;
    owner: string;
    purpose: string;
    forbidden: string;
  }[];
  audit: {
    id: string;
    source: string;
    actor: string;
    action: string;
    entityType: string;
    entityId: string | number;
    detail: string;
    createdAt: string;
  }[];
  taskSummary: { total: number; open: number; aiSuggested: number };
};

function Intro({ eyebrow, title, children }: {
  eyebrow: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <header className={styles.intro}>
      <p>{eyebrow}</p>
      <h2>{title}</h2>
      <div>{children}</div>
    </header>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className={styles.empty}>{children}</div>;
}

function State({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  const tone = ["ready", "verified", "active", "matched", "completed", "construction"].includes(normalized)
    ? styles.good
    : ["blocked", "error", "excluded", "unmatched"].includes(normalized)
      ? styles.bad
      : styles.warn;
  const labels: Record<string, string> = {
    ready: "MŰKÖDIK",
    testable: "TESZTELHETŐ",
    blocked: "KAPU HIÁNYZIK",
    review: "ELLENŐRIZENDŐ",
    open: "NYITOTT",
    verified: "ELLENŐRZÖTT",
    matched: "PÁROSÍTVA",
    unmatched: "NINCS PÁR",
    prospect: "JELÖLT",
  };
  return <span className={`${styles.state} ${tone}`}>{labels[normalized] ?? value.toUpperCase()}</span>;
}

export function ModulesWorkspace({ data }: { data: IntelligenceWorkspace }) {
  const ready = data.modules.filter((module) => module.state === "ready").length;
  const testable = data.modules.filter((module) => module.state === "testable").length;
  const blocked = data.modules.filter((module) => module.state === "blocked").length;
  return (
    <>
      <Intro eyebrow="TELJES RENDSZERLELTÁR" title="Imperial Intelligence modulok">
        A kézikönyv szerinti teljes célrendszer, külön jelölve a működő, ellenőrizhető és
        még külső adat- vagy jóváhagyási kapura váró részeket.
      </Intro>
      <section className={styles.summary}>
        <article><strong>{ready}</strong><span>Működő modul</span></article>
        <article><strong>{testable}</strong><span>Tesztelhető modul</span></article>
        <article><strong>{blocked}</strong><span>Hiányzó production kapu</span></article>
        <article><strong>{data.modules.length}</strong><span>Nyilvántartott rendszerterület</span></article>
      </section>
      <section className={styles.moduleGrid}>
        {data.modules.map((module) => (
          <article key={module.key} className={styles.moduleCard}>
            <div><State value={module.state} /><small>{module.owner}</small></div>
            <h3>{module.name}</h3>
            <p>{module.evidence}</p>
            {module.productionGate && <footer><b>Élesítési kapu</b>{module.productionGate}</footer>}
          </article>
        ))}
      </section>
    </>
  );
}

export function ProjectsWorkspace({ data }: { data: IntelligenceWorkspace }) {
  return (
    <>
      <Intro eyebrow="PROJECT 360°" title="Projektek és partnerkapacitás">
        Az importált projektforrások, a MyImperial aktív projektek és a partneradatbázis
        egy közös, olvasható munkaképen.
      </Intro>
      <section className={styles.summary}>
        <article><strong>{data.projects.imported.length}</strong><span>Importált projekt</span></article>
        <article><strong>{data.projects.portal.length}</strong><span>MyImperial projekt</span></article>
        <article><strong>{data.partners.length}</strong><span>Listázott partner</span></article>
        <article><strong>{data.reviews.filter((row) => row.entityType === "project").length}</strong><span>Projektellenőrzés</span></article>
      </section>
      <section className={styles.twoColumns}>
        <div className={styles.panel}>
          <header><h3>Projektforrások</h3><span>{data.projects.imported.length} tétel</span></header>
          <div className={styles.rows}>
            {data.projects.imported.length ? data.projects.imported.map((project) => (
              <article key={project.id}>
                <div><strong>{project.title}</strong><small>{project.location || "Helyszín nincs megadva"} · {project.projectType || "Típus ellenőrzendő"}</small></div>
                <State value={project.status} />
              </article>
            )) : <Empty>Nincs importált projekt ebben a munkatérben.</Empty>}
          </div>
        </div>
        <div className={styles.panel}>
          <header><h3>MyImperial projektek</h3><span>{data.projects.portal.length} tétel</span></header>
          <div className={styles.rows}>
            {data.projects.portal.length ? data.projects.portal.map((project) => (
              <article key={project.id}>
                <div><strong>{project.title}</strong><small>{project.customerName} · {project.phase} · cél: {project.targetCompletion}</small><i><b style={{ width: `${project.progress}%` }} /></i></div>
                <span className={styles.progress}>{project.progress}%</span>
              </article>
            )) : <Empty>A MyImperial projektlista még üres.</Empty>}
          </div>
        </div>
      </section>
      <section className={styles.panel}>
        <header><h3>Alvállalkozók, tervezők és beszállítók</h3><span>első {data.partners.length} rekord</span></header>
        <div className={styles.table}>
          <div className={styles.tableHead}><span>Név</span><span>Típus</span><span>Hely / szakág</span><span>Állapot</span></div>
          {data.partners.map((partner) => (
            <div key={partner.id}>
              <strong>{partner.name}</strong>
              <span>{partner.partnerType}</span>
              <span>{partner.location || partner.specialties || "–"}</span>
              <State value={partner.status} />
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

export function CalendarWorkspace({ data }: { data: IntelligenceWorkspace }) {
  const critical = data.calendar.filter((item) => item.priority === "critical" || item.priority === "high");
  return (
    <>
      <Intro eyebrow="OKOSNAPTÁR" title="Feladatok és projektmérföldkövek">
        Egy időrendben jelennek meg az értékesítési teendők és a projektcélok. Az
        éles Google Naptár-szinkron külön hitelesítési kapu marad.
      </Intro>
      <section className={styles.summary}>
        <article><strong>{data.calendar.length}</strong><span>Ütemezett tétel</span></article>
        <article><strong>{critical.length}</strong><span>Kiemelt prioritás</span></article>
        <article><strong>{data.taskSummary.open}</strong><span>Nyitott teendő</span></article>
        <article><strong>{data.projects.portal.length}</strong><span>Projektmérföldkő</span></article>
      </section>
      <section className={styles.timeline}>
        {data.calendar.length ? data.calendar.map((item) => (
          <article key={item.id}>
            <time>{item.when}</time>
            <i className={item.priority === "critical" ? styles.dangerDot : ""} />
            <div><strong>{item.title}</strong><span>{item.context} · {item.kind === "task" ? "teendő" : "mérföldkő"}</span></div>
            <State value={item.status} />
          </article>
        )) : <Empty>Nincs megjeleníthető naptári tétel.</Empty>}
      </section>
    </>
  );
}

export function KnowledgeWorkspace({
  data,
  onReview,
}: {
  data: IntelligenceWorkspace;
  onReview: (id: number, status: "resolved" | "dismissed") => Promise<void>;
}) {
  return (
    <>
      <Intro eyebrow="KERESŐ ÉS DOKUMENTUMTÁR" title="Források és adatminőségi ellenőrzés">
        A nagy fájlokat nem duplikáljuk: az eredeti Drive- vagy Gmail-forrást
        hivatkozással, verzióval és ellenőrzési állapottal tartjuk nyilván.
      </Intro>
      <section className={styles.summary}>
        <article><strong>{data.sources.length}</strong><span>Legutóbbi forrás</span></article>
        <article><strong>{data.reviews.length}</strong><span>Nyitott ellenőrzés</span></article>
        <article><strong>{data.sources.filter((row) => row.reviewStatus === "verified").length}</strong><span>Ellenőrzött forrás</span></article>
        <article><strong>{new Set(data.sources.map((row) => row.sourceSystem)).size}</strong><span>Forrásrendszer</span></article>
      </section>
      <section className={styles.twoColumns}>
        <div className={styles.panel}>
          <header><h3>Nyitott adatminőségi tételek</h3><span>{data.reviews.length}</span></header>
          <div className={styles.reviewRows}>
            {data.reviews.length ? data.reviews.map((review) => (
              <article key={review.id}>
                <div>
                  <strong>{review.summary}</strong>
                  <a href={review.sourceUrl} target="_blank" rel="noreferrer">{review.sourceTitle}</a>
                  <small>{review.entityType} · {review.reasonCode}</small>
                </div>
                <aside>
                  <button onClick={() => onReview(review.id, "resolved")}>Ellenőrizve</button>
                  <button onClick={() => onReview(review.id, "dismissed")}>Kizárás</button>
                </aside>
              </article>
            )) : <Empty>Nincs nyitott adatminőségi tétel.</Empty>}
          </div>
        </div>
        <div className={styles.panel}>
          <header><h3>Legutóbbi források</h3><span>{data.sources.length}</span></header>
          <div className={styles.rows}>
            {data.sources.map((source) => (
              <article key={source.id}>
                <div><a href={source.sourceUrl} target="_blank" rel="noreferrer"><strong>{source.title}</strong></a><small>{source.sourceSystem} · {source.recordType}</small></div>
                <State value={source.reviewStatus} />
              </article>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}

export function AgentsWorkspace({ data }: { data: IntelligenceWorkspace }) {
  return (
    <>
      <Intro eyebrow="EMBERI DÖNTÉSI KAPUK" title="AI-ügynökök vezérlőközpontja">
        Az ügynökök csak értelmeznek és javasolnak. Árat, szerződést, műszaki
        lezárást, számlafizetést vagy vezetői döntést nem hagyhatnak jóvá.
      </Intro>
      <section className={styles.summary}>
        <article><strong>{data.agents.length}</strong><span>Definiált ügynök</span></article>
        <article><strong>{data.taskSummary.aiSuggested}</strong><span>Nyitott AI-javaslat</span></article>
        <article><strong>{data.reviews.length}</strong><span>Emberi review-sor</span></article>
        <article><strong>0</strong><span>Önálló pénzügyi/jogi döntés</span></article>
      </section>
      <section className={styles.agentGrid}>
        {data.agents.map((agent) => (
          <article key={agent.key}>
            <header><span>AI</span><small>{agent.owner}</small></header>
            <h3>{agent.name}</h3>
            <p>{agent.purpose}</p>
            <footer><b>Tiltott önálló művelet</b>{agent.forbidden}</footer>
          </article>
        ))}
      </section>
    </>
  );
}

export function AuditWorkspace({ data }: { data: IntelligenceWorkspace }) {
  return (
    <>
      <Intro eyebrow="VISSZAKERESHETŐ MŰKÖDÉS" title="Audit- és eseménynapló">
        A CRM és a MyImperial felhasználói változásai egy közös, időrendi
        nézetben. A forrásadatok tartalmát ez a lista nem másolja.
      </Intro>
      <section className={styles.summary}>
        <article><strong>{data.audit.length}</strong><span>Legutóbbi esemény</span></article>
        <article><strong>{new Set(data.audit.map((row) => row.actor)).size}</strong><span>Eseménygazda</span></article>
        <article><strong>{new Set(data.audit.map((row) => row.entityType)).size}</strong><span>Entitástípus</span></article>
        <article><strong>2</strong><span>Naplózott alrendszer</span></article>
      </section>
      <section className={styles.audit}>
        {data.audit.length ? data.audit.map((event) => (
          <article key={event.id}>
            <time>{new Date(event.createdAt).toLocaleString("hu-HU")}</time>
            <div><strong>{event.action}</strong><span>{event.detail}</span></div>
            <small>{event.source} · {event.entityType} #{event.entityId} · {event.actor}</small>
          </article>
        )) : <Empty>Még nincs naplózott felhasználói változás.</Empty>}
      </section>
    </>
  );
}

