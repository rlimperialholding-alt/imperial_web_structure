import { describe, expect, it } from "vitest";
import {
  GoogleDriveEvidenceVerifier,
  buildDriveEvidenceSubmission,
} from "../src/evidence/drive-evidence.js";
import { makeTask } from "./fixtures.js";

describe("GoogleDriveEvidenceVerifier", () => {
  it("accepts an accessible matching document", async () => {
    const verifier = new GoogleDriveEvidenceVerifier({
      async getFileMetadata() {
        return {
          id: "file-1",
          name: "approved.pdf",
          mimeType: "application/pdf",
          modifiedAt: new Date(),
          owners: ["director@example.com"],
          trashed: false,
        };
      },
      async canActorRead() { return true; },
      async getRevisionFingerprint() { return "rev-1"; },
    });

    const evidence = buildDriveEvidenceSubmission({
      fileId: "file-1",
      type: "DOCUMENT",
      submittedAt: new Date("2026-07-24T08:00:00Z"),
      submittedBy: "employee-1",
      revisionFingerprint: "rev-1",
    });

    const result = await verifier.verify(makeTask(), evidence);
    expect(result.accepted).toBe(true);
  });

  it("rejects a trashed file", async () => {
    const verifier = new GoogleDriveEvidenceVerifier({
      async getFileMetadata() {
        return {
          id: "file-1",
          name: "photo.jpg",
          mimeType: "image/jpeg",
          modifiedAt: new Date(),
          owners: [],
          trashed: true,
        };
      },
      async canActorRead() { return true; },
      async getRevisionFingerprint() { return "rev-1"; },
    });

    const evidence = buildDriveEvidenceSubmission({
      fileId: "file-1",
      type: "PHOTO",
      submittedAt: new Date(),
      submittedBy: "employee-1",
    });

    const result = await verifier.verify(
      makeTask({
        evidenceRequirement: {
          type: "PHOTO",
          description: "Helyszíni fotó",
          machineVerifiable: false,
        },
      }),
      evidence,
    );

    expect(result.accepted).toBe(false);
    expect(result.reason).toContain("Trash");
  });
});
