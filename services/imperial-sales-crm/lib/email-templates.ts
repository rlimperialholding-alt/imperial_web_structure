export type EmailTemplate = { subject: string; html: string; text: string };

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[character] || character);
}

function emailShell(title: string, intro: string, content: string, actionLabel: string, actionUrl: string) {
  const safeTitle = escapeHtml(title);
  const safeIntro = escapeHtml(intro);
  const safeUrl = escapeHtml(actionUrl);
  return `<!doctype html><html lang="hu"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head><body style="margin:0;background:#f2f5f7;font-family:Arial,sans-serif;color:#14253a"><table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td style="padding:28px 12px"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;margin:auto;background:#fff;border-radius:14px;overflow:hidden"><tr><td style="padding:26px 30px;background:#0b2944;color:#fff"><strong style="font-size:20px;letter-spacing:1px">MYIMPERIAL</strong><div style="margin-top:5px;font-size:11px;color:#b9c9d6;letter-spacing:1.4px">AZ OTTHONOD PROJEKTJE</div></td></tr><tr><td style="padding:30px"><div style="font-size:11px;font-weight:700;color:#90741f;letter-spacing:1px">BIZTONSÁGOS PROJEKTÉRTESÍTÉS</div><h1 style="font-size:24px;line-height:1.25;margin:12px 0 10px">${safeTitle}</h1><p style="font-size:15px;line-height:1.6;color:#5c6b79">${safeIntro}</p>${content}<p style="margin:26px 0"><a href="${safeUrl}" style="display:inline-block;padding:13px 18px;border-radius:8px;background:#edc94d;color:#17243a;text-decoration:none;font-size:14px;font-weight:700">${escapeHtml(actionLabel)}</a></p><p style="font-size:12px;line-height:1.5;color:#84909b">Biztonsági okból ne továbbítsd ezt az üzenetet. A projektet érintő döntéseket mindig a MyImperial felületén rögzítsd.</p></td></tr><tr><td style="padding:17px 30px;background:#f6f8f9;font-size:11px;color:#87939e">Imperial Holding · MyImperial ügyfélportál</td></tr></table></td></tr></table></body></html>`;
}

export function invitationEmail(input: {
  recipientName: string; projectTitle: string; portalCode: string; inviteUrl: string; expiresAt: string;
}): EmailTemplate {
  const expiry = new Intl.DateTimeFormat("hu-HU", { year: "numeric", month: "long", day: "numeric", timeZone: "Europe/Budapest" }).format(new Date(input.expiresAt));
  const subject = `Meghívás a MyImperial projektbe · ${input.portalCode}`;
  const content = `<div style="margin:22px 0;padding:16px;border-radius:9px;background:#f6f8f9"><strong>${escapeHtml(input.projectTitle)}</strong><div style="margin-top:6px;font-size:13px;color:#607080">Projektazonosító: ${escapeHtml(input.portalCode)} · Érvényes: ${escapeHtml(expiry)} nap végéig</div></div>`;
  return {
    subject,
    html: emailShell(`Kedves ${input.recipientName}!`, "Meghívást kaptál a projekt biztonságos MyImperial ügyfélterébe.", content, "Meghívás elfogadása", input.inviteUrl),
    text: `Kedves ${input.recipientName}!\n\nMeghívást kaptál a(z) ${input.projectTitle} (${input.portalCode}) MyImperial projektterébe.\n\nMeghívás elfogadása: ${input.inviteUrl}\n\nA link ${expiry} nap végéig érvényes. Ne továbbítsd ezt az üzenetet.`,
  };
}

export function projectEventEmail(input: {
  recipientName: string; projectTitle: string; portalCode: string; eventTitle: string; eventSummary: string; portalUrl: string;
}): EmailTemplate {
  const subject = `${input.eventTitle} · ${input.portalCode}`;
  const content = `<div style="margin:22px 0;padding:16px;border-left:4px solid #edc94d;background:#f6f8f9"><strong>${escapeHtml(input.projectTitle)}</strong><p style="margin:7px 0 0;font-size:14px;line-height:1.55;color:#607080">${escapeHtml(input.eventSummary)}</p></div>`;
  return {
    subject,
    html: emailShell(`Kedves ${input.recipientName}!`, input.eventTitle, content, "Projekt megnyitása", input.portalUrl),
    text: `Kedves ${input.recipientName}!\n\n${input.eventTitle}\n${input.projectTitle} (${input.portalCode})\n${input.eventSummary}\n\nProjekt megnyitása: ${input.portalUrl}`,
  };
}

export { escapeHtml };
