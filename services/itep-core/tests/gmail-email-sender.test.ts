import { describe, expect, it } from "vitest";
import { GmailEmailSender, type GmailTransport } from "../src/notifications/gmail-email-sender.js";
import { renderTaskReminder } from "../src/notifications/templates.js";
import { makeTask } from "./fixtures.js";

class MemoryTransport implements GmailTransport {
  calls: Array<{ subject: string; text: string }> = [];

  async send(input: { from: string; to: string; cc: string[]; subject: string; text: string }) {
    this.calls.push({ subject: input.subject, text: input.text });
    return { id: "gmail-1" };
  }
}

describe("GmailEmailSender outbound copy gate", () => {
  it.each([
    "API-t", "backendet", "frontendet", "endpointot", "deploymentet",
    "sprintet", "ticketet", "taskot", "projektmenedzsmentet",
    "projektkontrollt", "scope-ot", "korai fejlesztési jeleket", "auditigényeket",
    "BOM-ot", "DfMA-t", "deduplikálást",
  ])("blocks IT and project-management jargon: %s", async (term) => {
    const transport = new MemoryTransport();
    const sender = new GmailEmailSender(
      transport,
      "imperial-holding",
      "info@imperialholding.hu",
    );

    await expect(sender.send({
      to: "partner@example.hu",
      cc: [],
      audience: "external",
      subject: "Rövid egyeztetés",
      text: `Keressük az együttműködés lehetőségét. A ${term} egyszerűbb munkát ad Önöknek. Kérjük, válaszoljanak. Imperial Holding`,
    })).rejects.toThrow(/jargon/);
    expect(transport.calls).toHaveLength(0);
  });

  it("sends a short, single-brand Hungarian message", async () => {
    const transport = new MemoryTransport();
    const sender = new GmailEmailSender(
      transport,
      "imperial-holding",
      "info@imperialholding.hu",
    );

    await sender.send({
      to: "kollega@imperialholding.hu",
      cc: [],
      audience: "internal",
      subject: "Mai feladat",
      text: "Azért írunk, mert a mai érdeklődőket át kell nézni. Ez segít Önnek a gyors válaszadásban. Kérjük, nézze át a mellékelt listát. Imperial Holding",
    });

    expect(transport.calls).toHaveLength(1);
  });

  it("does not trust an internal label for an external recipient", async () => {
    const transport = new MemoryTransport();
    const sender = new GmailEmailSender(
      transport,
      "imperial-holding",
      "info@imperialholding.hu",
    );

    await expect(sender.send({
      to: "external@example.hu",
      cc: [],
      audience: "internal",
      subject: "Mai feladat",
      text: "Kérjük, nézze át a mai érdeklődőket. Imperial Holding",
    })).rejects.toThrow(/recipient_audience_mismatch/);
    expect(transport.calls).toHaveLength(0);
  });

  it("requires purpose and recipient benefit in internal messages too", async () => {
    const transport = new MemoryTransport();
    const sender = new GmailEmailSender(
      transport,
      "imperial-holding",
      "info@imperialholding.hu",
    );

    await expect(sender.send({
      to: "employee@imperialholding.hu",
      cc: [],
      audience: "internal",
      subject: "Mai feladat",
      text: "Kérjük, nézze át a listát. Imperial Holding",
    })).rejects.toThrow(/purpose_not_clear.*recipient_benefit_not_clear/);
    expect(transport.calls).toHaveLength(0);
  });

  it("does not treat a recipient pronoun as a recipient benefit", async () => {
    const transport = new MemoryTransport();
    const sender = new GmailEmailSender(
      transport,
      "imperial-holding",
      "info@imperialholding.hu",
    );

    await expect(sender.send({
      to: "partner@example.hu",
      cc: [],
      audience: "external",
      subject: "Rövid bemutatkozás",
      text: "Szeretnénk bemutatni a cégünket. Önöknek küldjük ezt a levelet. Kérjük, válaszoljanak. Imperial Holding",
    })).rejects.toThrow(/recipient_benefit_not_clear/);
    expect(transport.calls).toHaveLength(0);
  });

  it("blocks the MAISZ jargon and cross-brand signature before transport", async () => {
    const transport = new MemoryTransport();
    const sender = new GmailEmailSender(
      transport,
      "imperial-holding",
      "info@imperialholding.hu",
    );

    await expect(sender.send({
      to: "info@maisz.hu",
      cc: [],
      audience: "external",
      subject: "Ingatlanfejlesztési és műszaki partnerhálózat",
      text: "Strukturált együttműködést keresünk. Bemutatjuk a projektjel-feldolgozási rendszert. Kérjük, válaszoljanak. Imperial Holding / Property360 / BauShield",
    })).rejects.toThrow(/OUTBOUND_COPY_BLOCKED/);
    expect(transport.calls).toHaveLength(0);
  });

  it("blocks a sender that does not belong to the selected brand", async () => {
    const transport = new MemoryTransport();
    const sender = new GmailEmailSender(
      transport,
      "imperial-holding",
      "info@baushield.hu",
    );

    await expect(sender.send({
      to: "kollega@example.hu",
      cc: [],
      audience: "internal",
      subject: "Mai feladat",
      text: "Kérjük, nézze át a mai érdeklődőket. Imperial Holding",
    })).rejects.toThrow(/sender_brand_mismatch/);
    expect(transport.calls).toHaveLength(0);
  });

  it("blocks an unknown product name in the sender display", async () => {
    const transport = new MemoryTransport();
    const sender = new GmailEmailSender(
      transport,
      "imperial-holding",
      "MyImperial <info@imperialholding.hu>",
    );

    await expect(sender.send({
      to: "employee@imperialholding.hu",
      cc: [],
      audience: "internal",
      subject: "Mai feladat",
      text: "Azért írunk, mert a mai listát át kell nézni. Ez segít Önnek a gyors válaszadásban. Kérjük, nézze át a listát. Imperial Holding",
    })).rejects.toThrow(/sender_brand_mismatch/);
    expect(transport.calls).toHaveLength(0);
  });

  it("blocks a mixed sender display even when it starts with the right brand", async () => {
    const transport = new MemoryTransport();
    const sender = new GmailEmailSender(
      transport,
      "imperial-holding",
      "Imperial Holding / MyImperial <info@imperialholding.hu>",
    );

    await expect(sender.send({
      to: "employee@imperialholding.hu",
      cc: [],
      audience: "internal",
      subject: "Mai feladat",
      text: "Azért írunk, mert a mai listát át kell nézni. Ez segít Önnek a gyors válaszadásban. Kérjük, nézze át a listát. Imperial Holding",
    })).rejects.toThrow(/sender_brand_mismatch/);
    expect(transport.calls).toHaveLength(0);
  });

  it("sends the real plain task-reminder template through the final gate", async () => {
    const transport = new MemoryTransport();
    const sender = new GmailEmailSender(
      transport,
      "imperial-holding",
      "Imperial Holding <info@imperialholding.hu>",
    );
    const rendered = renderTaskReminder(makeTask(), 1, "NONE");

    await sender.send({
      to: "employee@imperialholding.hu",
      cc: [],
      audience: rendered.audience,
      subject: rendered.subject,
      text: rendered.text,
      html: rendered.html,
    });

    expect(transport.calls).toHaveLength(1);
  });

  it("blocks empty content and reserved identity headers", async () => {
    const transport = new MemoryTransport();
    const sender = new GmailEmailSender(
      transport,
      "imperial-holding",
      "info@imperialholding.hu",
    );

    await expect(sender.send({
      to: "employee@example.hu",
      cc: [],
      audience: "internal",
      subject: "Imperial Holding",
      text: "",
    })).rejects.toThrow(/body_missing/);
    await expect(sender.send({
      to: "employee@example.hu",
      cc: [],
      audience: "internal",
      subject: "Mai feladat",
      text: "Kérjük, nézze át a mai feladatot. Imperial Holding",
      headers: { "Reply-To": "info@baushield.hu" },
    })).rejects.toThrow(/reserved_identity_header/);
    expect(transport.calls).toHaveLength(0);
  });
});
