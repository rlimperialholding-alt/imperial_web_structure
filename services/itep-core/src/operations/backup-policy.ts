export interface BackupPolicy {
  frequencyHours: number;
  retentionDays: number;
  minimumVerifiedCopies: number;
  restoreTestIntervalDays: number;
}

export const defaultBackupPolicy: BackupPolicy = {
  frequencyHours: 6,
  retentionDays: 35,
  minimumVerifiedCopies: 3,
  restoreTestIntervalDays: 30,
};

export function validateBackupPolicy(policy: BackupPolicy): void {
  if (policy.frequencyHours <= 0) {
    throw new Error("Backup frequency must be positive");
  }
  if (policy.retentionDays < 7) {
    throw new Error("Backup retention must be at least 7 days");
  }
  if (policy.minimumVerifiedCopies < 3) {
    throw new Error("At least three verified backup copies are required");
  }
  if (policy.restoreTestIntervalDays > 30) {
    throw new Error("Restore testing must happen at least monthly");
  }
}
