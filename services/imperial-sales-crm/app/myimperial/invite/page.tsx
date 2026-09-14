"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import styles from "./invite.module.css";

export default function MyImperialInvitePage() {
  const [token, setToken] = useState("");
  const [state, setState] = useState<"ready" | "working" | "accepted" | "error">("ready");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setToken(new URLSearchParams(window.location.search).get("token") || "");
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const accept = async () => {
    setState("working");
    const response = await fetch("/api/myimperial/invitations/accept", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token }),
    });
    const payload = await response.json().catch(() => ({})) as { error?: string };
    if (!response.ok) {
      setMessage(payload.error || "A meghívás most nem fogadható el.");
      setState("error");
      return;
    }
    setState("accepted");
  };

  return (
    <main className={styles.page}>
      <section className={styles.card}>
        <div className={styles.mark}><i /><b /></div>
        <small>MYIMPERIAL · BIZTONSÁGOS PROJEKTTÉR</small>
        {state === "accepted" ? (
          <>
            <span className={styles.success}>✓</span>
            <h1>Hozzáférés elfogadva</h1>
            <p>A projekt bekerült a fiókodba. A döntéseket, dokumentumokat és teendőket mostantól a saját azonosítóddal éred el.</p>
            <Link href="/myimperial">Belépés a projektbe</Link>
          </>
        ) : (
          <>
            <h1>Projektmeghívás</h1>
            <p>A meghívás elfogadásával kizárólag a hozzád rendelt projekt adataihoz kapsz hozzáférést. Minden művelet auditálva lesz.</p>
            {message && <div className={styles.error}>{message}</div>}
            <button disabled={!token || state === "working"} onClick={accept}>
              {state === "working" ? "Ellenőrzés…" : token ? "Meghívás elfogadása" : "Érvénytelen hivatkozás"}
            </button>
            <em>Csak azzal az email-címmel fogadható el, amelyre a meghívás készült.</em>
          </>
        )}
      </section>
    </main>
  );
}
