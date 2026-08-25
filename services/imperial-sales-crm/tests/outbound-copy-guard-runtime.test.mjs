import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";

test("outbound gate blocks the remaining MAISZ jargon on its own", () => {
  const source = `
    import { validateOutboundEmail } from "./lib/outbound-copy-guard.ts";
    for (const phrase of [
      "korai fejlesztési jeleket",
      "auditigényeket",
      "BOM-ot",
      "DfMA-t",
      "deduplikálást",
    ]) {
      let blocked = false;
      try {
        validateOutboundEmail({
          fromEmail: "Imperial Holding <info@imperialholding.hu>",
          subject: "Rövid egyeztetés",
          text: \`Keressük az együttműködés lehetőségét. \${phrase} azonosítunk. Ezzel tudunk segíteni Önöknek. Kérjük, válaszoljanak. Imperial Holding\`,
          kind: "outreach",
        });
      } catch (error) {
        blocked = String(error).includes("jargon:");
      }
      if (!blocked) throw new Error(\`not blocked: \${phrase}\`);
    }
  `;
  const result = spawnSync(
    process.execPath,
    ["--experimental-strip-types", "--input-type=module", "--eval", source],
    { cwd: process.cwd(), encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr || result.stdout);
});

test("transactional templates also pass purpose, benefit and one-brand checks", () => {
  const source = `
    import { invitationEmail, projectEventEmail } from "./lib/email-templates.ts";
    import { validateOutboundEmail } from "./lib/outbound-copy-guard.ts";
    const templates = [
      invitationEmail({
        recipientName: "Kovács Anna",
        projectTitle: "Családi ház",
        portalCode: "IH-123",
        inviteUrl: "https://myimperial.hu/meghivas",
        expiresAt: "2026-09-01T00:00:00Z",
      }),
      projectEventEmail({
        recipientName: "Kovács Anna",
        projectTitle: "Családi ház",
        portalCode: "IH-123",
        eventTitle: "Elkészült az új terv",
        eventSummary: "A terv most már megtekinthető.",
        portalUrl: "https://myimperial.hu/ugy",
      }),
    ];
    for (const template of templates) {
      validateOutboundEmail({
        fromEmail: "Imperial Holding <info@imperialholding.hu>",
        subject: template.subject,
        text: template.text,
        html: template.html,
        kind: "transactional",
      });
    }
    let blocked = false;
    try {
      validateOutboundEmail({
        fromEmail: "info@imperialholding.hu",
        subject: "Mai feladat",
        text: "Kérjük, nézze át a listát. Imperial Holding",
        kind: "transactional",
      });
    } catch (error) {
      blocked = String(error).includes("purpose_not_clear")
        && String(error).includes("recipient_benefit_not_clear");
    }
    if (!blocked) throw new Error("transactional structure bypass");
    for (const fromEmail of [
      "MyImperial <info@imperialholding.hu>",
      "Imperial Holding / MyImperial <info@imperialholding.hu>",
      "Imperial Holding Értesítések <info@imperialholding.hu>",
    ]) {
      let displayBlocked = false;
      try {
        validateOutboundEmail({
          fromEmail,
          subject: templates[0].subject,
          text: templates[0].text,
          html: templates[0].html,
          kind: "transactional",
        });
      } catch (error) {
        displayBlocked = String(error).includes("sender_brand_mismatch");
      }
      if (!displayBlocked) throw new Error(\`display name bypass: \${fromEmail}\`);
    }
  `;
  const result = spawnSync(
    process.execPath,
    ["--experimental-strip-types", "--input-type=module", "--eval", source],
    { cwd: process.cwd(), encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr || result.stdout);
});
