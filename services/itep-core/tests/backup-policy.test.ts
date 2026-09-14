import { describe, expect, it } from "vitest";
import {
  defaultBackupPolicy,
  validateBackupPolicy,
} from "../src/operations/backup-policy.js";

describe("backup policy", () => {
  it("accepts the production default", () => {
    expect(() => validateBackupPolicy(defaultBackupPolicy)).not.toThrow();
  });

  it("rejects a single backup copy", () => {
    expect(() =>
      validateBackupPolicy({
        ...defaultBackupPolicy,
        minimumVerifiedCopies: 1,
      }),
    ).toThrow("two verified");
  });
});
