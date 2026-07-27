"use client";

import { FormEvent, useEffect, useState } from "react";
import { rememberCsrf } from "@/lib/browser-auth";
import styles from "./login.module.css";

type Step = "password" | "mfa" | "invitation" | "enroll" | "recovery";

export default function LoginPage() {
  const [step, setStep] = useState<Step>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [challengeToken, setChallengeToken] = useState("");
  const [enrollmentToken, setEnrollmentToken] = useState("");
  const [secret, setSecret] = useState("");
  const [otpAuthUri, setOtpAuthUri] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const [invitationToken, setInvitationToken] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams(window.location.search);
      const invite = params.get("invite") ?? "";
      if (invite) {
        setInvitationToken(invite);
        setStep("invitation");
        return;
      }
      fetch("/api/auth/me", { cache: "no-store" }).then((response) => {
        if (response.ok) window.location.replace(safeReturnPath(params.get("returnTo")));
      }).catch(() => undefined);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function submitPassword(event: FormEvent) {
    event.preventDefault();
    await execute(async () => {
      const payload = await jsonRequest<{ challengeToken: string }>(
        "/api/auth/login",
        { email, password },
      );
      setChallengeToken(payload.challengeToken);
      setCode("");
      setStep("mfa");
    });
  }

  async function submitMfa(event: FormEvent) {
    event.preventDefault();
    await execute(async () => {
      const credential = code.replace(/\s+/g, "");
      const payload = await jsonRequest<{ csrfToken: string }>(
        "/api/auth/mfa/verify",
        /^\d{6}$/.test(credential)
          ? { challengeToken, code: credential }
          : { challengeToken, recoveryCode: credential },
      );
      rememberCsrf(payload.csrfToken);
      window.location.replace(safeReturnPath(
        new URLSearchParams(window.location.search).get("returnTo"),
      ));
    });
  }

  async function acceptInvitation(event: FormEvent) {
    event.preventDefault();
    await execute(async () => {
      const payload = await jsonRequest<{
        enrollmentToken: string;
        secret: string;
        otpAuthUri: string;
      }>("/api/auth/invitations/accept", {
        invitationToken,
        password,
      });
      setEnrollmentToken(payload.enrollmentToken);
      setSecret(payload.secret);
      setOtpAuthUri(payload.otpAuthUri);
      setPassword("");
      setCode("");
      setStep("enroll");
    });
  }

  async function confirmEnrollment(event: FormEvent) {
    event.preventDefault();
    await execute(async () => {
      const payload = await jsonRequest<{
        csrfToken: string;
        recoveryCodes: string[];
      }>("/api/auth/mfa/enroll/confirm", {
        enrollmentToken,
        code: code.replace(/\s+/g, ""),
      });
      rememberCsrf(payload.csrfToken);
      setRecoveryCodes(payload.recoveryCodes);
      setStep("recovery");
    });
  }

  async function execute(action: () => Promise<void>) {
    setWorking(true);
    setError("");
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
      <section className={styles.card}>
        <div className={styles.brand}>
          <span><i /><b /></span>
          <div><strong>IMPERIAL</strong><small>INTELLIGENCE</small></div>
        </div>
        <div className={styles.security}>VÉDETT BELSŐ RENDSZER</div>

        {step === "password" && (
          <form onSubmit={submitPassword}>
            <h1>Belépés</h1>
            <p>A folytatáshoz add meg a céges fiókodat.</p>
            <label>E-mail-cím<input type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
            <label>Jelszó<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
            {error && <div className={styles.error}>{error}</div>}
            <button disabled={working}>{working ? "Ellenőrzés…" : "Tovább"}</button>
          </form>
        )}

        {step === "mfa" && (
          <form onSubmit={submitMfa}>
            <h1>Kétlépcsős ellenőrzés</h1>
            <p>Írd be a hitelesítő alkalmazás hatjegyű kódját. Elveszett telefon esetén egy helyreállító kódot is használhatsz.</p>
            <label>Hitelesítő vagy helyreállító kód<input inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(event) => setCode(event.target.value)} /></label>
            {error && <div className={styles.error}>{error}</div>}
            <button disabled={working}>{working ? "Belépés…" : "Belépés"}</button>
            <button className={styles.linkButton} type="button" onClick={() => setStep("password")}>Vissza</button>
          </form>
        )}

        {step === "invitation" && (
          <form onSubmit={acceptInvitation}>
            <h1>Fiók aktiválása</h1>
            <p>Állíts be legalább 14 karakteres, egyedi jelszót.</p>
            <label>Új jelszó<input type="password" autoComplete="new-password" minLength={14} maxLength={128} required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
            {error && <div className={styles.error}>{error}</div>}
            <button disabled={working}>{working ? "Mentés…" : "Hitelesítő alkalmazás beállítása"}</button>
          </form>
        )}

        {step === "enroll" && (
          <form onSubmit={confirmEnrollment}>
            <h1>Hitelesítő alkalmazás</h1>
            <p>Add hozzá ezt a kulcsot a Google Authenticator, Microsoft Authenticator, 1Password vagy más TOTP-alkalmazáshoz, majd írd be a kapott kódot.</p>
            <div className={styles.secret}><span>Beállítási kulcs</span><strong>{secret}</strong></div>
            <a className={styles.uri} href={otpAuthUri}>Megnyitás hitelesítő alkalmazásban</a>
            <label>Hatjegyű kód<input inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" required value={code} onChange={(event) => setCode(event.target.value)} /></label>
            {error && <div className={styles.error}>{error}</div>}
            <button disabled={working}>{working ? "Ellenőrzés…" : "Aktiválás"}</button>
          </form>
        )}

        {step === "recovery" && (
          <div>
            <h1>Fiók kész</h1>
            <p>Ezek a kódok csak egyszer láthatók. Mentsd őket jelszókezelőbe; elveszett telefonnál ezekkel lehet belépni.</p>
            <div className={styles.codes}>{recoveryCodes.map((item) => <code key={item}>{item}</code>)}</div>
            <button onClick={() => window.location.replace("/")}>Elmentettem, belépek</button>
          </div>
        )}
        <footer>A jelszavadat és a hitelesítő kulcsodat senkinek ne küldd el e-mailben.</footer>
      </section>
    </main>
  );
}

async function jsonRequest<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({})) as T & { error?: string; message?: string };
  if (!response.ok) throw new Error(payload.error || payload.message || "Az ellenőrzés nem sikerült.");
  return payload;
}

function safeReturnPath(value: string | null): string {
  return value?.startsWith("/") && !value.startsWith("//") ? value : "/";
}
