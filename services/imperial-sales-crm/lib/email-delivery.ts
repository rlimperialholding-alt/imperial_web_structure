import { getRuntimeValue } from "@/db";
import type { EmailTemplate } from "@/lib/email-templates";
import { validateOutboundEmail } from "@/lib/outbound-copy-guard";

export type EmailProviderStatus = { configured: boolean; fromEmail: string; provider: "resend" };

export async function getEmailProviderStatus(): Promise<EmailProviderStatus> {
  const [apiKey, fromEmail] = await Promise.all([
    getRuntimeValue("RESEND_API_KEY"),
    getRuntimeValue("MYIMPERIAL_FROM_EMAIL"),
  ]);
  return { configured: Boolean(apiKey && fromEmail), fromEmail: fromEmail || "", provider: "resend" };
}

export async function deliverEmail(input: {
  to: string; template: EmailTemplate; idempotencyKey: string;
}): Promise<{ ok: true; messageId: string } | { ok: false; error: string; configurationRequired?: boolean }> {
  const [apiKey, fromEmail, replyTo] = await Promise.all([
    getRuntimeValue("RESEND_API_KEY"),
    getRuntimeValue("MYIMPERIAL_FROM_EMAIL"),
    getRuntimeValue("MYIMPERIAL_REPLY_TO"),
  ]);
  if (!apiKey || !fromEmail) return { ok: false, error: "Az email-küldés még nincs konfigurálva.", configurationRequired: true };

  try {
    validateOutboundEmail({
      fromEmail,
      subject: input.template.subject,
      text: input.template.text,
      html: input.template.html,
      ...(replyTo ? { replyToEmail: replyTo } : {}),
      kind: "transactional",
    });
  } catch {
    return { ok: false, error: "A levél szövege nem felel meg a kötelező nyelvi vagy márkaszabálynak." };
  }

  try {
    const response = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        authorization: `Bearer ${apiKey}`,
        "content-type": "application/json",
        "idempotency-key": input.idempotencyKey,
      },
      body: JSON.stringify({
        from: fromEmail,
        to: [input.to],
        subject: input.template.subject,
        html: input.template.html,
        text: input.template.text,
        ...(replyTo ? { reply_to: replyTo } : {}),
        tags: [{ name: "system", value: "myimperial" }],
      }),
    });
    const payload = await response.json().catch(() => ({})) as { id?: string; message?: string; error?: { message?: string } };
    if (!response.ok || !payload.id) return { ok: false, error: payload.message || payload.error?.message || "Az email-szolgáltató elutasította a küldést." };
    return { ok: true, messageId: payload.id };
  } catch {
    return { ok: false, error: "Az email-szolgáltató most nem érhető el." };
  }
}
