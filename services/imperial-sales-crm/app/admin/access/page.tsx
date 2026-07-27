"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { authenticatedFetch } from "@/lib/browser-auth";
import styles from "./access.module.css";

type Organization = {
  id: string;
  displayName: string;
  taxNumber: string | null;
  active: boolean;
};
type Membership = {
  organizationId: string;
  jobRole: string;
  projectIds: string[];
  permissionGrants: string[];
  permissionDenials: string[];
};
type User = {
  id: string;
  email: string;
  displayName: string;
  status: string;
  isSystemAdmin: boolean;
  isExecutive: boolean;
  mfaEnabled: boolean;
  lockedUntil: string | null;
  lastLoginAt: string | null;
  memberships: Membership[];
};
type MembershipDraft = Membership & { enabled: boolean };

const ROLE_LABELS: Record<string, string> = {
  SYSTEM_ADMIN: "Rendszeradminisztrátor",
  EXECUTIVE: "Ügyvezető",
  FINANCE: "Pénzügy",
  HR: "HR",
  SALES: "Értékesítő",
  MARKETING: "Marketing",
  PROJECT_MANAGER: "Projektmenedzser",
  ENGINEERING: "Mérnök / tervező",
  LEGAL: "Jogi",
  PROCUREMENT: "Beszerzés",
  WAREHOUSE: "Raktár",
  SUBCONTRACTOR: "Alvállalkozó",
  CUSTOMER: "Ügyfél",
};

export default function AccessAdminPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [templates, setTemplates] = useState<Record<string, string[]>>({});
  const [selectedId, setSelectedId] = useState("");
  const [drafts, setDrafts] = useState<Record<string, MembershipDraft>>({});
  const [executive, setExecutive] = useState(false);
  const [invite, setInvite] = useState({ email: "", displayName: "", organizationId: "", jobRole: "SALES" });
  const [newCompany, setNewCompany] = useState({ id: "", displayName: "", taxNumber: "" });
  const [oneTimeLink, setOneTimeLink] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);

  const selected = useMemo(
    () => users.find((user) => user.id === selectedId),
    [selectedId, users],
  );

  async function load() {
    const [userRows, companyRows, roleRows] = await Promise.all([
      request<User[]>("/api/auth/admin/users"),
      request<Organization[]>("/api/auth/admin/organizations"),
      request<Record<string, string[]>>("/api/auth/admin/job-role-templates"),
    ]);
    setUsers(userRows);
    setOrganizations(companyRows);
    setTemplates(roleRows);
    setInvite((current) => ({
      ...current,
      organizationId: current.organizationId || companyRows[0]?.id || "",
    }));
    if (!selectedId && userRows[0]) selectUser(userRows[0], companyRows);
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      load().catch((caught) => {
        if (caught instanceof Error) setError(caught.message);
      });
    }, 0);
    return () => window.clearTimeout(timer);
    // The initial administrative snapshot is intentionally loaded once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function selectUser(user: User, companies = organizations) {
    setSelectedId(user.id);
    setExecutive(user.isExecutive);
    setDrafts(Object.fromEntries(companies.map((organization) => {
      const existing = user.memberships.find(
        (membership) => membership.organizationId === organization.id,
      );
      return [organization.id, {
        enabled: Boolean(existing),
        organizationId: organization.id,
        jobRole: existing?.jobRole ?? "SALES",
        projectIds: existing?.projectIds ?? [],
        permissionGrants: existing?.permissionGrants ?? [],
        permissionDenials: existing?.permissionDenials ?? [],
      }];
    })));
    setMessage("");
    setError("");
    setOneTimeLink("");
  }

  async function submitInvitation(event: FormEvent) {
    event.preventDefault();
    await execute(async () => {
      const result = await request<{ invitationToken: string }>(
        "/api/auth/admin/users/invite",
        {
          method: "POST",
          body: JSON.stringify({
            email: invite.email,
            displayName: invite.displayName,
            isExecutive: invite.jobRole === "EXECUTIVE",
            memberships: [{
              organizationId: invite.organizationId,
              jobRole: invite.jobRole === "EXECUTIVE" ? "EXECUTIVE" : invite.jobRole,
              projectIds: [],
              permissionGrants: [],
              permissionDenials: [],
            }],
          }),
        },
      );
      setOneTimeLink(`${window.location.origin}/login?invite=${encodeURIComponent(result.invitationToken)}`);
      setInvite((current) => ({ ...current, email: "", displayName: "" }));
      setMessage("A meghívó elkészült. A hivatkozást biztonságos csatornán add át.");
      await load();
    });
  }

  async function saveAccess() {
    if (!selected) return;
    await execute(async () => {
      await request(`/api/auth/admin/users/${selected.id}/access`, {
        method: "PATCH",
        body: JSON.stringify({
          isExecutive: executive,
          memberships: Object.values(drafts)
            .filter((item) => item.enabled)
            .map((item) => ({
              organizationId: item.organizationId,
              jobRole: item.jobRole,
              projectIds: item.projectIds,
              permissionGrants: item.permissionGrants,
              permissionDenials: item.permissionDenials,
            })),
        }),
      });
      setMessage("A jogosultságokat elmentettük. A felhasználó aktív munkameneteit biztonsági okból lezártuk.");
      await load();
    });
  }

  async function recoverAccess() {
    if (!selected) return;
    await execute(async () => {
      const result = await request<{ invitationToken: string }>(
        `/api/auth/admin/users/${selected.id}/recovery`,
        { method: "POST" },
      );
      setOneTimeLink(`${window.location.origin}/login?invite=${encodeURIComponent(result.invitationToken)}`);
      setMessage("A régi munkamenetek lezárultak. Az egyszer használható helyreállító hivatkozás elkészült.");
      await load();
    });
  }

  async function createCompany(event: FormEvent) {
    event.preventDefault();
    await execute(async () => {
      await request("/api/auth/admin/organizations", {
        method: "POST",
        body: JSON.stringify(newCompany),
      });
      setNewCompany({ id: "", displayName: "", taxNumber: "" });
      setMessage("A cég elkészült.");
      await load();
    });
  }

  async function execute(action: () => Promise<void>) {
    setWorking(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "A művelet nem sikerült.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <main className={styles.page}>
      <header>
        <div><small>IMPERIAL INTELLIGENCE</small><h1>Felhasználók és jogosultságok</h1></div>
        <Link href="/">Vissza a rendszerbe</Link>
      </header>
      <div className={styles.notice}>
        A munkakör kiválasztásakor a rendszer javasolt jogosultságcsomagot ad. Az egyedi engedélyekkel ezt lehet finomítani.
      </div>
      {message && <div className={styles.success}>{message}</div>}
      {error && <div className={styles.error}>{error}</div>}
      {oneTimeLink && <div className={styles.link}><strong>Egyszer használható hivatkozás</strong><input readOnly value={oneTimeLink} onFocus={(event) => event.currentTarget.select()} /></div>}

      <section className={styles.grid}>
        <article>
          <h2>Felhasználók</h2>
          <div className={styles.userList}>
            {users.map((user) => (
              <button className={selectedId === user.id ? styles.active : ""} key={user.id} onClick={() => selectUser(user)}>
                <span><strong>{user.displayName}</strong><small>{user.email}</small></span>
                <em>{user.isSystemAdmin ? "ADMIN" : user.isExecutive ? "ÜGYVEZETŐ" : user.status}</em>
              </button>
            ))}
          </div>
        </article>

        <article className={styles.access}>
          <h2>{selected ? `${selected.displayName} hozzáférése` : "Hozzáférés"}</h2>
          {selected && (
            <>
              <label className={styles.check}><input type="checkbox" checked={executive} disabled={selected.isSystemAdmin} onChange={(event) => setExecutive(event.target.checked)} /> Teljes ügyvezetői jogosultság</label>
              <div className={styles.companies}>
                {organizations.map((organization) => {
                  const draft = drafts[organization.id];
                  if (!draft) return null;
                  return (
                    <div key={organization.id}>
                      <label className={styles.check}><input type="checkbox" checked={draft.enabled} onChange={(event) => setDrafts((current) => ({ ...current, [organization.id]: { ...draft, enabled: event.target.checked } }))} /> {organization.displayName}</label>
                      {draft.enabled && (
                        <div className={styles.companyFields}>
                          <label>Munkakör<select value={draft.jobRole} onChange={(event) => setDrafts((current) => ({ ...current, [organization.id]: { ...draft, jobRole: event.target.value } }))}>{Object.keys(templates).map((role) => <option key={role} value={role}>{ROLE_LABELS[role] ?? role}</option>)}</select></label>
                          <label>Projektazonosítók, vesszővel<input value={draft.projectIds.join(", ")} onChange={(event) => setDrafts((current) => ({ ...current, [organization.id]: { ...draft, projectIds: csv(event.target.value) } }))} /></label>
                          <label>Plusz engedélyek, vesszővel<input value={draft.permissionGrants.join(", ")} onChange={(event) => setDrafts((current) => ({ ...current, [organization.id]: { ...draft, permissionGrants: csv(event.target.value) } }))} /></label>
                          <label>Tiltott engedélyek, vesszővel<input value={draft.permissionDenials.join(", ")} onChange={(event) => setDrafts((current) => ({ ...current, [organization.id]: { ...draft, permissionDenials: csv(event.target.value) } }))} /></label>
                          <small>Javaslat: {(templates[draft.jobRole] ?? []).join(", ") || "nincs alapértelmezett"}</small>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              <div className={styles.actions}><button disabled={working} onClick={saveAccess}>Jogosultságok mentése</button><button className={styles.secondary} disabled={working} onClick={recoverAccess}>Telefon/jelszó helyreállítása</button></div>
            </>
          )}
        </article>
      </section>

      <section className={styles.forms}>
        <form onSubmit={submitInvitation}>
          <h2>Új felhasználó meghívása</h2>
          <label>Név<input required value={invite.displayName} onChange={(event) => setInvite({ ...invite, displayName: event.target.value })} /></label>
          <label>E-mail<input required type="email" value={invite.email} onChange={(event) => setInvite({ ...invite, email: event.target.value })} /></label>
          <label>Cég<select required value={invite.organizationId} onChange={(event) => setInvite({ ...invite, organizationId: event.target.value })}>{organizations.map((item) => <option key={item.id} value={item.id}>{item.displayName}</option>)}</select></label>
          <label>Munkakör<select value={invite.jobRole} onChange={(event) => setInvite({ ...invite, jobRole: event.target.value })}>{Object.keys(templates).map((role) => <option key={role} value={role}>{ROLE_LABELS[role] ?? role}</option>)}</select></label>
          <button disabled={working}>Meghívó készítése</button>
        </form>
        <form onSubmit={createCompany}>
          <h2>Új cég felvétele</h2>
          <label>Technikai azonosító<input pattern="[a-z0-9][a-z0-9-]{1,99}" placeholder="pelda-kft" required value={newCompany.id} onChange={(event) => setNewCompany({ ...newCompany, id: event.target.value.toLowerCase() })} /></label>
          <label>Cégnév<input required value={newCompany.displayName} onChange={(event) => setNewCompany({ ...newCompany, displayName: event.target.value })} /></label>
          <label>Adószám<input value={newCompany.taxNumber} onChange={(event) => setNewCompany({ ...newCompany, taxNumber: event.target.value })} /></label>
          <button disabled={working}>Cég létrehozása</button>
        </form>
      </section>
    </main>
  );
}

async function request<T = unknown>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("content-type", "application/json");
  const response = await authenticatedFetch(url, { ...init, headers, cache: "no-store" });
  const payload = await response.json().catch(() => ({})) as T & { error?: string; message?: string };
  if (!response.ok) throw new Error(payload.error || payload.message || "A művelet nem sikerült.");
  return payload;
}

function csv(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}
