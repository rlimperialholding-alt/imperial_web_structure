import { createHash } from "node:crypto";
import type {
  EvidenceSubmission,
  EvidenceType,
  Task,
} from "../domain/types.js";
import type { EvidenceVerifier } from "../application/ports.js";

export interface DriveFileMetadata {
  id: string;
  name: string;
  mimeType: string;
  sizeBytes?: number;
  modifiedAt: Date;
  owners: string[];
  webViewLink?: string;
  md5Checksum?: string;
  trashed: boolean;
}

export interface DriveEvidenceGateway {
  getFileMetadata(fileId: string): Promise<DriveFileMetadata | null>;
  canActorRead(fileId: string, actorId: string): Promise<boolean>;
  getRevisionFingerprint(fileId: string): Promise<string>;
}

export class GoogleDriveEvidenceVerifier implements EvidenceVerifier {
  constructor(private readonly drive: DriveEvidenceGateway) {}

  async verify(
    task: Task,
    evidence: EvidenceSubmission,
  ): Promise<{
    accepted: boolean;
    reason: string;
    verifiedBy: string;
  }> {
    if (!isDriveUri(evidence.uri)) {
      return {
        accepted: false,
        reason: "Evidence URI is not a supported Google Drive reference",
        verifiedBy: "digital-anne-drive-verifier",
      };
    }

    const fileId = parseDriveFileId(evidence.uri);
    const metadata = await this.drive.getFileMetadata(fileId);

    if (!metadata) {
      return {
        accepted: false,
        reason: "Drive file does not exist or is inaccessible",
        verifiedBy: "digital-anne-drive-verifier",
      };
    }

    if (metadata.trashed) {
      return {
        accepted: false,
        reason: "Drive file is in Trash",
        verifiedBy: "digital-anne-drive-verifier",
      };
    }

    const readable = await this.drive.canActorRead(
      fileId,
      evidence.submittedBy,
    );
    if (!readable) {
      return {
        accepted: false,
        reason: "Submitter cannot read the referenced Drive file",
        verifiedBy: "digital-anne-drive-verifier",
      };
    }

    const typeResult = validateMimeType(
      task.evidenceRequirement.type,
      metadata.mimeType,
    );
    if (!typeResult.accepted) {
      return {
        ...typeResult,
        verifiedBy: "digital-anne-drive-verifier",
      };
    }

    const fingerprint = await this.drive.getRevisionFingerprint(fileId);
    const expectedChecksum = evidence.checksum;
    if (expectedChecksum && expectedChecksum !== fingerprint) {
      return {
        accepted: false,
        reason: "Drive revision fingerprint does not match submitted checksum",
        verifiedBy: "digital-anne-drive-verifier",
      };
    }

    return {
      accepted: true,
      reason: `Verified Drive file: ${metadata.name}`,
      verifiedBy: "digital-anne-drive-verifier",
    };
  }
}

export function buildDriveEvidenceSubmission(input: {
  fileId: string;
  type: EvidenceType;
  submittedAt: Date;
  submittedBy: string;
  revisionFingerprint?: string;
}): EvidenceSubmission {
  return {
    id: createHash("sha256")
      .update(
        `${input.fileId}:${input.submittedBy}:${input.submittedAt.toISOString()}`,
      )
      .digest("hex")
      .slice(0, 32),
    type: input.type,
    uri: `gdrive://file/${input.fileId}`,
    submittedAt: input.submittedAt,
    submittedBy: input.submittedBy,
    ...(input.revisionFingerprint
      ? { checksum: input.revisionFingerprint }
      : {}),
  };
}

export function isDriveUri(uri: string): boolean {
  return uri.startsWith("gdrive://file/");
}

export function parseDriveFileId(uri: string): string {
  if (!isDriveUri(uri)) {
    throw new Error("Invalid gdrive URI");
  }
  const fileId = uri.slice("gdrive://file/".length).trim();
  if (!fileId) throw new Error("Missing Drive file ID");
  return fileId;
}

function validateMimeType(
  expected: EvidenceType,
  mimeType: string,
): { accepted: boolean; reason: string } {
  if (expected === "PHOTO" && !mimeType.startsWith("image/")) {
    return { accepted: false, reason: "Expected an image file" };
  }
  if (
    expected === "DOCUMENT" &&
    !(
      mimeType.startsWith("application/") ||
      mimeType.startsWith("text/") ||
      mimeType.startsWith("application/vnd.google-apps.")
    )
  ) {
    return { accepted: false, reason: "Expected a document file" };
  }
  if (expected === "FILE" || expected === "OTHER") {
    return { accepted: true, reason: "File type accepted" };
  }
  return { accepted: true, reason: "MIME type accepted" };
}
