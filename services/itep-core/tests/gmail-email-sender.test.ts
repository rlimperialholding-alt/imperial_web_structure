import { describe, expect, it } from "vitest";

import {
  GmailEmailSender,
  publicationDigestIdempotencyKey,
  type GmailTransport,
} from "../src/notifications/gmail-email-sender.js";

describe("GmailEmailSender publication digest idempotency", () => {
  it("ignores changing caller keys and derives one recipient-date-type key", async () => {
    const calls: Parameters<GmailTransport["send"]>[0][] = [];
    const transport: GmailTransport = {
      async send(input) {
        calls.push(input);
        return { id: `gmail-${calls.length}` };
      },
    };
    const sender = new GmailEmailSender(transport);
    const subject = "Napi automatikus publikációs összesítő – 2026-08-27";

    await sender.send({
      to: " Molnar.Andrea@ImperialHolding.hu ",
      cc: [],
      subject,
      text: "Első ciklus",
      headers: { "X-Imperial-Idempotency-Key": "caller-random-one" },
    });
    await sender.send({
      to: "molnar.andrea@imperialholding.hu",
      cc: [],
      subject,
      text: "Második ciklus",
      headers: { "X-Imperial-Idempotency-Key": "caller-random-two" },
    });

    const expected = publicationDigestIdempotencyKey({
      messageType: "daily_publication_digest",
      recipient: "molnar.andrea@imperialholding.hu",
      localReportDate: "2026-08-27",
    });
    expect(calls).toHaveLength(2);
    expect(calls[0]?.headers?.["X-Imperial-Idempotency-Key"]).toBe(expected);
    expect(calls[1]?.headers?.["X-Imperial-Idempotency-Key"]).toBe(expected);
  });
});
