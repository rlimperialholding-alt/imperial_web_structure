"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { authenticatedFetch } from "@/lib/browser-auth";
import styles from "./whatsapp.module.css";

type Conversation = {
  id: string;
  displayName: string | null;
  phoneMasked: string;
  crmCustomerId: string | null;
  projectId: string | null;
  status: string;
  lastMessageAt: string;
};
type Message = {
  id: string;
  direction: "INBOUND" | "OUTBOUND";
  status: string;
  body: string | null;
  createdAt: string;
  requestedBy: string | null;
};

export default function WhatsAppPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const selected = conversations.find((item) => item.id === selectedId);

  async function loadConversations() {
    const rows = await request<Conversation[]>("/api/whatsapp/conversations?limit=100");
    setConversations(rows);
    const nextId = selectedId || rows[0]?.id || "";
    if (nextId) await selectConversation(nextId, rows);
  }

  async function selectConversation(id: string, rows = conversations) {
    setSelectedId(id);
    const conversation = rows.find((item) => item.id === id);
    setCustomerId(conversation?.crmCustomerId ?? "");
    setProjectId(conversation?.projectId ?? "");
    setMessages(await request<Message[]>(`/api/whatsapp/conversations/${id}/messages?limit=200`));
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      loadConversations().catch((caught) => setError(messageOf(caught)));
    }, 0);
    return () => window.clearTimeout(timer);
    // Initial mailbox load only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    if (!selectedId || !draft.trim()) return;
    await execute(async () => {
      await request(`/api/whatsapp/conversations/${selectedId}/messages`, {
        method: "POST",
        body: JSON.stringify({ body: draft }),
      });
      setDraft("");
      await selectConversation(selectedId);
    });
  }

  async function saveLink() {
    if (!selectedId) return;
    await execute(async () => {
      await request(`/api/whatsapp/conversations/${selectedId}`, {
        method: "PATCH",
        body: JSON.stringify({
          crmCustomerId: customerId.trim() || null,
          projectId: projectId.trim() || null,
        }),
      });
      await loadConversations();
    });
  }

  async function approve(messageId: string) {
    await execute(async () => {
      await request(`/api/whatsapp/messages/${messageId}/approve`, { method: "POST" });
      await selectConversation(selectedId);
    });
  }

  async function reject(messageId: string) {
    const reason = window.prompt("Miért nem küldhető el ez az üzenet?");
    if (!reason) return;
    await execute(async () => {
      await request(`/api/whatsapp/messages/${messageId}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      });
      await selectConversation(selectedId);
    });
  }

  async function execute(action: () => Promise<void>) {
    setWorking(true);
    setError("");
    try {
      await action();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setWorking(false);
    }
  }

  return (
    <main className={styles.page}>
      <header><div><small>IMPERIAL INTELLIGENCE</small><h1>WhatsApp ügyfélkommunikáció</h1></div><Link href="/">Vissza a rendszerbe</Link></header>
      <div className={styles.info}>A rendszer kizárólag a céges WhatsApp Business-számot kezeli. A munkatársak személyes száma nem kerül ide.</div>
      {error && <div className={styles.error}>{error}</div>}
      <section className={styles.shell}>
        <aside>
          <h2>Beszélgetések</h2>
          {conversations.length === 0 && <p>Még nincs beérkezett WhatsApp-üzenet.</p>}
          {conversations.map((item) => (
            <button key={item.id} className={selectedId === item.id ? styles.active : ""} onClick={() => selectConversation(item.id)}>
              <span><strong>{item.displayName || item.phoneMasked}</strong><small>{item.crmCustomerId || "Még nincs ügyfélhez kapcsolva"}</small></span>
              <time>{new Date(item.lastMessageAt).toLocaleDateString("hu-HU")}</time>
            </button>
          ))}
        </aside>
        <article>
          {selected ? (
            <>
              <div className={styles.chatHead}><div><h2>{selected.displayName || selected.phoneMasked}</h2><small>{selected.phoneMasked}</small></div><span>{selected.status}</span></div>
              <div className={styles.linker}>
                <label>CRM-ügyfél azonosító<input value={customerId} onChange={(event) => setCustomerId(event.target.value)} /></label>
                <label>Projektazonosító<input value={projectId} onChange={(event) => setProjectId(event.target.value)} /></label>
                <button disabled={working} onClick={saveLink}>Kapcsolás</button>
              </div>
              <div className={styles.messages}>
                {messages.map((item) => (
                  <div key={item.id} className={item.direction === "OUTBOUND" ? styles.outbound : styles.inbound}>
                    <p>{item.body || "Nem szöveges üzenet"}</p>
                    <small>{new Date(item.createdAt).toLocaleString("hu-HU")} · {item.status}</small>
                    {item.status === "PENDING_APPROVAL" && (
                      <div><button disabled={working} onClick={() => approve(item.id)}>Jóváhagyom</button><button disabled={working} onClick={() => reject(item.id)}>Elutasítom</button></div>
                    )}
                  </div>
                ))}
              </div>
              <form onSubmit={sendMessage}><textarea maxLength={4096} required placeholder="Írd ide a választ…" value={draft} onChange={(event) => setDraft(event.target.value)} /><button disabled={working || !draft.trim()}>Küldés / jóváhagyásra küldés</button></form>
            </>
          ) : <div className={styles.empty}>Válassz egy beszélgetést.</div>}
        </article>
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

function messageOf(value: unknown): string {
  return value instanceof Error ? value.message : "A művelet nem sikerült.";
}
