import { describe, expect, it } from "vitest";
import {
  assertStrongPassword,
  hashPassword,
  normalizeEmail,
  verifyPassword,
} from "../src/security/password.js";
import {
  decryptSecret,
  encryptSecret,
  generateRecoveryCodes,
  generateTotpSecret,
  totpCode,
  verifyTotp,
} from "../src/security/totp.js";
import {
  hasPermission,
  resolvePermissions,
} from "../src/auth/permissions.js";

describe("internal identity security", () => {
  it("normalizes email and hashes passwords with a unique salt", async () => {
    expect(normalizeEmail("  Admin@ImperialHolding.hu ")).toBe(
      "admin@imperialholding.hu",
    );
    const password = "Hosszú és egyedi mondat 2026!";
    const first = await hashPassword(password);
    const second = await hashPassword(password);
    expect(first).not.toBe(second);
    expect(await verifyPassword(password, first)).toBe(true);
    expect(await verifyPassword("helytelen jelszó", first)).toBe(false);
  });

  it("rejects weak or identity-derived passwords", () => {
    expect(() => assertStrongPassword("rövid")).toThrow();
    expect(() =>
      assertStrongPassword(
        "admin@imperialholding.hu-2026",
        "admin@imperialholding.hu",
      )
    ).toThrow();
  });

  it("verifies TOTP with a small clock window and encrypts the seed", () => {
    const secret = generateTotpSecret();
    const now = new Date("2026-07-27T20:00:00.000Z");
    const code = totpCode(secret, now);
    expect(verifyTotp(secret, code, now)).toBe(true);
    expect(
      verifyTotp(secret, code, new Date(now.getTime() + 31_000)),
    ).toBe(true);
    expect(
      verifyTotp(secret, code, new Date(now.getTime() + 91_000)),
    ).toBe(false);

    const ciphertext = encryptSecret(
      secret,
      "test-encryption-key-material-at-least-32",
    );
    expect(ciphertext).not.toContain(secret);
    expect(
      decryptSecret(
        ciphertext,
        "test-encryption-key-material-at-least-32",
      ),
    ).toBe(secret);
  });

  it("creates distinct one-time recovery codes", () => {
    const codes = generateRecoveryCodes();
    expect(codes).toHaveLength(10);
    expect(new Set(codes).size).toBe(10);
    expect(codes.every((code) => /^[A-Z0-9_-]{6}-[A-Z0-9_-]{6}$/.test(code)))
      .toBe(true);
  });

  it("provides job defaults while preserving explicit denial", () => {
    const finance = resolvePermissions({
      jobRole: "FINANCE",
      grants: ["whatsapp.send.request"],
      denials: ["finance.write"],
    });
    expect(finance).toContain("finance.read");
    expect(finance).toContain("whatsapp.send.request");
    expect(finance).not.toContain("finance.write");
    expect(hasPermission({ permissions: ["*"] }, "anything")).toBe(true);
  });
});
