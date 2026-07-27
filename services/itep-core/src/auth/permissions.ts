import type { ActorContext } from "../application/ports.js";

export type AuthJobRole =
  | "SYSTEM_ADMIN"
  | "EXECUTIVE"
  | "FINANCE"
  | "HR"
  | "SALES"
  | "MARKETING"
  | "PROJECT_MANAGER"
  | "ENGINEERING"
  | "LEGAL"
  | "PROCUREMENT"
  | "WAREHOUSE"
  | "SUBCONTRACTOR"
  | "CUSTOMER";

const COMMON = ["task.create", "task.read.all"];

export const JOB_ROLE_PERMISSIONS: Record<AuthJobRole, readonly string[]> = {
  SYSTEM_ADMIN: ["*"],
  EXECUTIVE: ["*"],
  FINANCE: [
    ...COMMON,
    "task.transition.all",
    "task.accept.all",
    "task.sensitive.financial",
    "finance.read",
    "finance.write",
    "customer.read",
    "contract.read",
    "whatsapp.read",
  ],
  HR: [
    ...COMMON,
    "task.sensitive.hr",
    "hr.read",
    "hr.write",
    "audit.read.hr",
  ],
  SALES: [
    ...COMMON,
    "customer.read",
    "customer.write",
    "contract.read",
    "contract.write",
    "whatsapp.read",
    "whatsapp.send.request",
  ],
  MARKETING: [
    ...COMMON,
    "customer.read.marketing",
    "marketing.read",
    "marketing.write",
    "whatsapp.read",
    "whatsapp.send.request",
  ],
  PROJECT_MANAGER: [
    ...COMMON,
    "task.transition.all",
    "project.read",
    "project.write",
    "document.read",
    "document.write",
    "customer.read.project",
    "whatsapp.read.project",
    "whatsapp.send.request",
  ],
  ENGINEERING: [
    ...COMMON,
    "project.read",
    "engineering.read",
    "engineering.write",
    "document.read",
    "document.write",
  ],
  LEGAL: [
    ...COMMON,
    "task.sensitive.legal",
    "contract.read",
    "contract.write",
    "document.read.legal",
    "document.write.legal",
  ],
  PROCUREMENT: [
    ...COMMON,
    "project.read",
    "procurement.read",
    "procurement.write",
    "finance.read.commitments",
  ],
  WAREHOUSE: [
    ...COMMON,
    "project.read",
    "warehouse.read",
    "warehouse.write",
  ],
  SUBCONTRACTOR: [
    "task.create",
    "project.read.assigned",
    "document.read.assigned",
    "document.write.assigned",
  ],
  CUSTOMER: [
    "project.read.own",
    "document.read.own",
    "whatsapp.read.own",
    "whatsapp.send.request",
  ],
};

export function resolvePermissions(input: {
  jobRole: AuthJobRole;
  grants?: readonly string[];
  denials?: readonly string[];
  fullAccess?: boolean;
}): string[] {
  if (input.fullAccess) return ["*"];
  const permissions = new Set(JOB_ROLE_PERMISSIONS[input.jobRole]);
  for (const grant of input.grants ?? []) permissions.add(grant);
  for (const denial of input.denials ?? []) permissions.delete(denial);
  return [...permissions].sort();
}

export function hasPermission(
  actor: Pick<ActorContext, "permissions">,
  permission: string,
): boolean {
  return (
    actor.permissions.includes("*") ||
    actor.permissions.includes(permission)
  );
}

export function requirePermission(
  actor: Pick<ActorContext, "permissions">,
  permission: string,
): void {
  if (!hasPermission(actor, permission)) {
    throw new Error(`Permission required: ${permission}`);
  }
}
