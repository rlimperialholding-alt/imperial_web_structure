import { describe, expect, it } from "vitest";
import {
  defaultBackupPolicy,
  validateBackupPolicy,
} from "../src/operations/backup-policy.js";

describe("backup policy", () => {
  it("accepts the production default", () => {
    expect(() => validateBackupPolicy(defaultBackupPolicy)).not.toThrow();
  });

  it("rejects fewer than three backup copies", () => {
    expect(() =>
      validateBackupPolicy({
        ...defaultBackupPolicy,
        minimumVerifiedCopies: 2,
      }),
    ).toThrow("three verified");
  });
});
