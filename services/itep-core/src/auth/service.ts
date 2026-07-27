import {
  createHmac,
  randomBytes,
  timingSafeEqual,
} from "node:crypto";
import type { Prisma, PrismaClient } from "@prisma/client";
import type { ActorContext } from "../application/ports.js";
import type { AppConfig } from "../config/env.js";
import {
  assertStrongPassword,
  hashPassword,
  normalizeEmail,
  verifyPassword,
} from "../security/password.js";
import {
  buildOtpAuthUri,
  decryptSecret,
  encryptSecret,
  generateRecoveryCodes,
  generateTotpSecret,
  verifyTotp,
} from "../security/totp.js";
import {
  JOB_ROLE_PERMISSIONS,
  resolvePermissions,
  type AuthJobRole,
} from "./permissions.js";

const DUMMY_PASSWORD_HASH =
  "scrypt$32768$8$1$MDAwMDAwMDAwMDAwMDAwMA$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";

export interface RequestSecurityContext {
  ip?: string;
  userAgent?: string;
  requestId?: string;
}

export interface MembershipInput {
  organizationId: string;
  jobRole: AuthJobRole;
  projectIds?: string[];
  permissionGrants?: string[];
  permissionDenials?: string[];
}

export class AuthService {
  private readonly tokenPepper: string;
  private readonly encryptionKey: string;

  constructor(
    private readonly prisma: PrismaClient,
    private readonly config: AppConfig,
    private readonly now: () => Date = () => new Date(),
  ) {
    if (
      config.NODE_ENV === "production" &&
      (!config.AUTH_TOKEN_PEPPER || !config.AUTH_DATA_ENCRYPTION_KEY)
    ) {
      throw new Error(
        "AUTH_TOKEN_PEPPER and AUTH_DATA_ENCRYPTION_KEY are required in production",
      );
    }
    this.tokenPepper =
      config.AUTH_TOKEN_PEPPER ?? config.IDENTITY_SHARED_SECRET;
    this.encryptionKey =
      config.AUTH_DATA_ENCRYPTION_KEY ?? config.IDENTITY_SHARED_SECRET;
  }

  jobRoleTemplates(): Record<string, readonly string[]> {
    return JOB_ROLE_PERMISSIONS;
  }

  async currentUser(actor: ActorContext) {
    const user = await this.prisma.authUser.findUniqueOrThrow({
      where: { id: actor.actorId },
      select: {
        id: true,
        email: true,
        displayName: true,
        isSystemAdmin: true,
        isExecutive: true,
        mfaEnabled: true,
        memberships: {
          select: {
            organizationId: true,
            jobRole: true,
            projectIds: true,
            permissionGrants: true,
            permissionDenials: true,
          },
        },
      },
    });
    return {
      ...user,
      activeOrganizationId: actor.organizationId,
      activeRoles: actor.roles,
      activePermissions: actor.permissions,
      activeProjectIds: actor.projectIds ?? [],
    };
  }

  async bootstrap(input: {
    bootstrapToken: string;
    email: string;
    displayName: string;
    password: string;
    organizationId?: string;
    organizationName?: string;
  }): Promise<EnrollmentResult> {
    const expected = this.config.AUTH_BOOTSTRAP_TOKEN;
    if (!expected || !safeEqual(input.bootstrapToken, expected)) {
      throw new Error("Invalid bootstrap token");
    }
    if ((await this.prisma.authUser.count()) > 0) {
      throw new Error("Identity bootstrap is already complete");
    }
    const email = normalizeEmail(input.email);
    assertStrongPassword(input.password, email);
    const organizationId =
      input.organizationId ?? this.config.DEFAULT_ORGANIZATION_ID;
    const secret = generateTotpSecret();
    const passwordHash = await hashPassword(input.password);

    const user = await this.prisma.$transaction(async (tx) => {
      await tx.authOrganization.upsert({
        where: { id: organizationId },
        create: {
          id: organizationId,
          displayName: input.organizationName ?? "Imperial Holding",
        },
        update: input.organizationName
          ? { displayName: input.organizationName }
          : {},
      });
      return tx.authUser.create({
        data: {
          email,
          displayName: input.displayName.trim(),
          passwordHash,
          isSystemAdmin: true,
          status: "INVITED",
          mfaSecretCiphertext: encryptSecret(secret, this.encryptionKey),
          memberships: {
            create: {
              organizationId,
              jobRole: "SYSTEM_ADMIN",
              projectIds: [],
              permissionGrants: [],
              permissionDenials: [],
            },
          },
        },
      });
    });
    const challenge = await this.createChallenge(user.id, "MFA_ENROLL", {
      organizationId,
    });
    await this.audit("AUTH_BOOTSTRAPPED", {
      actorId: user.id,
      organizationId,
      targetType: "AuthUser",
      targetId: user.id,
    });
    return {
      enrollmentToken: challenge,
      secret,
      otpAuthUri: buildOtpAuthUri({ secret, email }),
    };
  }

  async createOrganization(
    actor: ActorContext,
    input: { id: string; displayName: string; taxNumber?: string },
  ) {
    this.requireGroupAdministrator(actor);
    const organization = await this.prisma.authOrganization.create({
      data: {
        id: input.id.trim(),
        displayName: input.displayName.trim(),
        taxNumber: input.taxNumber?.trim() || null,
      },
    });
    await this.audit("ORGANIZATION_CREATED", {
      actorId: actor.actorId,
      organizationId: organization.id,
      targetType: "AuthOrganization",
      targetId: organization.id,
    });
    return organization;
  }

  async inviteUser(
    actor: ActorContext,
    input: {
      email: string;
      displayName: string;
      isExecutive?: boolean;
      memberships: MembershipInput[];
    },
  ): Promise<{ userId: string; invitationToken: string; expiresAt: Date }> {
    this.requireGroupAdministrator(actor);
    if (input.memberships.length === 0 && !input.isExecutive) {
      throw new Error("At least one company membership is required");
    }
    const email = normalizeEmail(input.email);
    for (const membership of input.memberships) {
      if (!(membership.jobRole in JOB_ROLE_PERMISSIONS)) {
        throw new Error(`Unknown job role: ${membership.jobRole}`);
      }
    }
    const rawToken = randomToken();
    const expiresAt = new Date(
      this.now().getTime() +
        this.config.AUTH_INVITATION_TTL_HOURS * 60 * 60 * 1000,
    );
    const user = await this.prisma.$transaction(async (tx) => {
      const created = await tx.authUser.create({
        data: {
          email,
          displayName: input.displayName.trim(),
          status: "INVITED",
          isExecutive: Boolean(input.isExecutive),
          memberships: {
            create: input.memberships.map((membership) => ({
              organizationId: membership.organizationId,
              jobRole: membership.jobRole,
              projectIds: membership.projectIds ?? [],
              permissionGrants: membership.permissionGrants ?? [],
              permissionDenials: membership.permissionDenials ?? [],
            })),
          },
        },
      });
      await tx.authInvitation.create({
        data: {
          userId: created.id,
          tokenHash: this.hashToken(rawToken),
          createdBy: actor.actorId,
          expiresAt,
        },
      });
      return created;
    });
    await this.audit("USER_INVITED", {
      actorId: actor.actorId,
      organizationId: actor.organizationId,
      targetType: "AuthUser",
      targetId: user.id,
      metadata: { email, memberships: input.memberships },
    });
    return { userId: user.id, invitationToken: rawToken, expiresAt };
  }

  async updateUserAccess(
    actor: ActorContext,
    userId: string,
    input: { isExecutive: boolean; memberships: MembershipInput[] },
  ) {
    this.requireGroupAdministrator(actor);
    if (input.memberships.length === 0 && !input.isExecutive) {
      throw new Error("At least one company membership is required");
    }
    const uniqueOrganizations = new Set<string>();
    for (const membership of input.memberships) {
      if (!(membership.jobRole in JOB_ROLE_PERMISSIONS)) {
        throw new Error(`Unknown job role: ${membership.jobRole}`);
      }
      if (uniqueOrganizations.has(membership.organizationId)) {
        throw new Error("A company can only be assigned once");
      }
      uniqueOrganizations.add(membership.organizationId);
    }
    const target = await this.prisma.authUser.findUniqueOrThrow({
      where: { id: userId },
      select: { isSystemAdmin: true },
    });
    if (target.isSystemAdmin && userId === actor.actorId && !input.memberships.length) {
      throw new Error("The active system administrator cannot remove own access");
    }
    await this.prisma.$transaction(async (tx) => {
      await tx.authUser.update({
        where: { id: userId },
        data: { isExecutive: input.isExecutive },
      });
      await tx.authMembership.deleteMany({ where: { userId } });
      if (input.memberships.length) {
        await tx.authMembership.createMany({
          data: input.memberships.map((membership) => ({
            userId,
            organizationId: membership.organizationId,
            jobRole: membership.jobRole,
            projectIds: membership.projectIds ?? [],
            permissionGrants: membership.permissionGrants ?? [],
            permissionDenials: membership.permissionDenials ?? [],
          })),
        });
      }
      await tx.authSession.updateMany({
        where: { userId, revokedAt: null },
        data: { revokedAt: this.now() },
      });
    });
    await this.audit("USER_ACCESS_UPDATED", {
      actorId: actor.actorId,
      organizationId: actor.organizationId,
      targetType: "AuthUser",
      targetId: userId,
      metadata: input,
    });
    return { updated: true };
  }

  async acceptInvitation(input: {
    invitationToken: string;
    password: string;
  }): Promise<EnrollmentResult> {
    const invitation = await this.prisma.authInvitation.findUnique({
      where: { tokenHash: this.hashToken(input.invitationToken) },
      include: { user: { include: { memberships: true } } },
    });
    if (
      !invitation ||
      invitation.acceptedAt ||
      invitation.revokedAt ||
      invitation.expiresAt <= this.now() ||
      invitation.user.status !== "INVITED"
    ) {
      throw new Error("Invitation is invalid or expired");
    }
    assertStrongPassword(input.password, invitation.user.email);
    const passwordHash = await hashPassword(input.password);
    const secret = generateTotpSecret();
    const organizationId =
      invitation.user.memberships[0]?.organizationId ??
      this.config.DEFAULT_ORGANIZATION_ID;
    await this.prisma.$transaction(async (tx) => {
      const claimed = await tx.authInvitation.updateMany({
        where: {
          id: invitation.id,
          acceptedAt: null,
          revokedAt: null,
          expiresAt: { gt: this.now() },
        },
        data: { acceptedAt: this.now() },
      });
      if (claimed.count !== 1) {
        throw new Error("Invitation is invalid or expired");
      }
      await tx.authInvitation.updateMany({
        where: {
          userId: invitation.userId,
          id: { not: invitation.id },
          acceptedAt: null,
          revokedAt: null,
        },
        data: { revokedAt: this.now() },
      });
      await tx.authUser.update({
        where: { id: invitation.userId },
        data: {
          passwordHash,
          mfaSecretCiphertext: encryptSecret(secret, this.encryptionKey),
        },
      });
    });
    const enrollmentToken = await this.createChallenge(
      invitation.userId,
      "MFA_ENROLL",
      { organizationId },
    );
    await this.audit("INVITATION_ACCEPTED", {
      actorId: invitation.userId,
      organizationId,
      targetType: "AuthUser",
      targetId: invitation.userId,
    });
    return {
      enrollmentToken,
      secret,
      otpAuthUri: buildOtpAuthUri({
        secret,
        email: invitation.user.email,
      }),
    };
  }

  async confirmMfaEnrollment(
    input: { enrollmentToken: string; code: string },
    context: RequestSecurityContext = {},
  ): Promise<SessionResult & { recoveryCodes: string[] }> {
    const challenge = await this.getChallenge(
      input.enrollmentToken,
      "MFA_ENROLL",
    );
    const user = await this.prisma.authUser.findUniqueOrThrow({
      where: { id: challenge.userId },
    });
    if (
      !user.mfaSecretCiphertext ||
      !verifyTotp(
        decryptSecret(user.mfaSecretCiphertext, this.encryptionKey),
        input.code,
        this.now(),
      )
    ) {
      throw new Error("Invalid authentication code");
    }
    const recoveryCodes = generateRecoveryCodes();
    const metadata = asRecord(challenge.metadata);
    const organizationId = String(
      metadata.organizationId ?? this.config.DEFAULT_ORGANIZATION_ID,
    );
    await this.prisma.$transaction(async (tx) => {
      const claimed = await tx.authChallenge.updateMany({
        where: { id: challenge.id, consumedAt: null },
        data: { consumedAt: this.now() },
      });
      if (claimed.count !== 1) {
        throw new Error("Authentication challenge is invalid or expired");
      }
      await tx.authUser.update({
        where: { id: user.id },
        data: {
          mfaEnabled: true,
          status: "ACTIVE",
          failedLoginAttempts: 0,
          lockedUntil: null,
        },
      });
      await tx.authRecoveryCode.deleteMany({ where: { userId: user.id } });
      await tx.authRecoveryCode.createMany({
        data: recoveryCodes.map((code) => ({
          userId: user.id,
          codeHash: this.hashToken(normalizeRecoveryCode(code)),
        })),
      });
    });
    const session = await this.createSession(user.id, organizationId, context);
    await this.audit("MFA_ENROLLED", {
      actorId: user.id,
      organizationId,
      targetType: "AuthUser",
      targetId: user.id,
      context,
    });
    return { ...session, recoveryCodes };
  }

  async login(
    input: { email: string; password: string; organizationId?: string },
    context: RequestSecurityContext = {},
  ): Promise<{ mfaRequired: true; challengeToken: string; expiresAt: Date }> {
    const email = normalizeEmail(input.email);
    const user = await this.prisma.authUser.findUnique({
      where: { email },
      include: { memberships: true },
    });
    const passwordValid = await verifyPassword(
      input.password,
      user?.passwordHash ?? DUMMY_PASSWORD_HASH,
    );
    if (
      !user ||
      !passwordValid ||
      user.status !== "ACTIVE" ||
      !user.mfaEnabled
    ) {
      if (user) await this.recordFailedLogin(user.id);
      await this.audit("LOGIN_FAILED", {
        actorId: user?.id,
        metadata: { email },
        context,
      });
      throw new Error("Invalid email, password or account state");
    }
    if (user.lockedUntil && user.lockedUntil > this.now()) {
      throw new Error("Account is temporarily locked");
    }
    const organizationId =
      input.organizationId ??
      user.memberships[0]?.organizationId ??
      this.config.DEFAULT_ORGANIZATION_ID;
    this.assertOrganizationAccess(user, organizationId);
    const challengeToken = await this.createChallenge(
      user.id,
      "MFA_LOGIN",
      { organizationId },
    );
    const expiresAt = new Date(
      this.now().getTime() +
        this.config.AUTH_CHALLENGE_TTL_MINUTES * 60 * 1000,
    );
    return { mfaRequired: true, challengeToken, expiresAt };
  }

  async verifyMfa(
    input: {
      challengeToken: string;
      code?: string;
      recoveryCode?: string;
    },
    context: RequestSecurityContext = {},
  ): Promise<SessionResult> {
    const challenge = await this.getChallenge(
      input.challengeToken,
      "MFA_LOGIN",
    );
    const user = await this.prisma.authUser.findUniqueOrThrow({
      where: { id: challenge.userId },
    });
    let verified = false;
    if (input.code && user.mfaSecretCiphertext) {
      verified = verifyTotp(
        decryptSecret(user.mfaSecretCiphertext, this.encryptionKey),
        input.code,
        this.now(),
      );
    } else if (input.recoveryCode) {
      const recovery = await this.prisma.authRecoveryCode.findUnique({
        where: {
          codeHash: this.hashToken(
            normalizeRecoveryCode(input.recoveryCode),
          ),
        },
      });
      if (recovery && recovery.userId === user.id && !recovery.usedAt) {
        const claimed = await this.prisma.authRecoveryCode.updateMany({
          where: { id: recovery.id, usedAt: null },
          data: { usedAt: this.now() },
        });
        verified = claimed.count === 1;
      }
    }
    if (!verified) {
      await this.recordFailedLogin(user.id);
      throw new Error("Invalid authentication code");
    }
    const metadata = asRecord(challenge.metadata);
    const organizationId = String(metadata.organizationId);
    await this.prisma.$transaction(async (tx) => {
      const claimed = await tx.authChallenge.updateMany({
        where: { id: challenge.id, consumedAt: null },
        data: { consumedAt: this.now() },
      });
      if (claimed.count !== 1) {
        throw new Error("Authentication challenge is invalid or expired");
      }
      await tx.authUser.update({
        where: { id: user.id },
        data: {
          failedLoginAttempts: 0,
          lockedUntil: null,
          lastLoginAt: this.now(),
        },
      });
    });
    const session = await this.createSession(user.id, organizationId, context);
    await this.audit("LOGIN_SUCCEEDED", {
      actorId: user.id,
      organizationId,
      targetType: "AuthSession",
      targetId: session.sessionId,
      context,
    });
    return session;
  }

  async authenticateSession(rawToken: string): Promise<ActorContext> {
    const session = await this.prisma.authSession.findUnique({
      where: { tokenHash: this.hashToken(rawToken) },
      include: { user: { include: { memberships: true } } },
    });
    if (
      !session ||
      session.revokedAt ||
      session.expiresAt <= this.now() ||
      session.user.status !== "ACTIVE"
    ) {
      throw new Error("Session is invalid or expired");
    }
    this.assertOrganizationAccess(session.user, session.organizationId);
    const membership = session.user.memberships.find(
      (item) => item.organizationId === session.organizationId,
    );
    const fullAccess =
      session.user.isSystemAdmin || session.user.isExecutive;
    const jobRole = (membership?.jobRole ??
      (session.user.isSystemAdmin ? "SYSTEM_ADMIN" : "EXECUTIVE")) as AuthJobRole;
    const permissions = resolvePermissions({
      jobRole,
      grants: membership?.permissionGrants ?? [],
      denials: membership?.permissionDenials ?? [],
      fullAccess,
    });
    await this.prisma.authSession.update({
      where: { id: session.id },
      data: { lastSeenAt: this.now() },
    });
    return {
      actorId: session.user.id,
      organizationId: session.organizationId,
      roles: [jobRole],
      permissions,
      projectIds: membership?.projectIds ?? [],
      sessionId: session.id,
      isSystemAdmin: session.user.isSystemAdmin,
      isExecutive: session.user.isExecutive,
    };
  }

  async switchOrganization(
    actor: ActorContext,
    organizationId: string,
    context: RequestSecurityContext = {},
  ): Promise<SessionResult> {
    const user = await this.prisma.authUser.findUniqueOrThrow({
      where: { id: actor.actorId },
      include: { memberships: true },
    });
    this.assertOrganizationAccess(user, organizationId);
    return this.createSession(user.id, organizationId, context);
  }

  async logout(sessionId: string): Promise<void> {
    await this.prisma.authSession.updateMany({
      where: { id: sessionId, revokedAt: null },
      data: { revokedAt: this.now() },
    });
  }

  async issueCsrfToken(actor: ActorContext): Promise<{ csrfToken: string }> {
    if (!actor.sessionId) throw new Error("User session is required");
    const csrfToken = randomToken();
    const updated = await this.prisma.authSession.updateMany({
      where: {
        id: actor.sessionId,
        revokedAt: null,
        expiresAt: { gt: this.now() },
      },
      data: { csrfTokenHash: this.hashToken(csrfToken) },
    });
    if (updated.count !== 1) throw new Error("Session is invalid or expired");
    return { csrfToken };
  }

  async createRecoveryInvitation(
    actor: ActorContext,
    userId: string,
  ): Promise<{ invitationToken: string; expiresAt: Date }> {
    this.requireGroupAdministrator(actor);
    const rawToken = randomToken();
    const expiresAt = new Date(
      this.now().getTime() +
        this.config.AUTH_INVITATION_TTL_HOURS * 60 * 60 * 1000,
    );
    await this.prisma.$transaction([
      this.prisma.authSession.updateMany({
        where: { userId, revokedAt: null },
        data: { revokedAt: this.now() },
      }),
      this.prisma.authInvitation.updateMany({
        where: {
          userId,
          acceptedAt: null,
          revokedAt: null,
        },
        data: { revokedAt: this.now() },
      }),
      this.prisma.authInvitation.create({
        data: {
          userId,
          tokenHash: this.hashToken(rawToken),
          createdBy: actor.actorId,
          expiresAt,
        },
      }),
      this.prisma.authUser.update({
        where: { id: userId },
        data: {
          status: "INVITED",
          mfaEnabled: false,
          mfaSecretCiphertext: null,
        },
      }),
    ]);
    await this.audit("ACCOUNT_RECOVERY_STARTED", {
      actorId: actor.actorId,
      organizationId: actor.organizationId,
      targetType: "AuthUser",
      targetId: userId,
    });
    return { invitationToken: rawToken, expiresAt };
  }

  async listUsers(actor: ActorContext) {
    this.requireGroupAdministrator(actor);
    return this.prisma.authUser.findMany({
      select: {
        id: true,
        email: true,
        displayName: true,
        status: true,
        isSystemAdmin: true,
        isExecutive: true,
        mfaEnabled: true,
        lockedUntil: true,
        lastLoginAt: true,
        memberships: {
          select: {
            organizationId: true,
            jobRole: true,
            projectIds: true,
            permissionGrants: true,
            permissionDenials: true,
          },
        },
      },
      orderBy: { email: "asc" },
    });
  }

  async listOrganizations(actor: ActorContext) {
    this.requireGroupAdministrator(actor);
    return this.prisma.authOrganization.findMany({
      select: {
        id: true,
        displayName: true,
        taxNumber: true,
        active: true,
      },
      orderBy: { displayName: "asc" },
    });
  }

  async recordRequestAudit(input: {
    actor: ActorContext;
    method: string;
    route: string;
    statusCode: number;
    context?: RequestSecurityContext;
  }): Promise<void> {
    await this.audit("API_ACCESS", {
      actorId: input.actor.actorId,
      organizationId: input.actor.organizationId,
      metadata: {
        method: input.method,
        route: input.route,
        statusCode: input.statusCode,
        projectIds: input.actor.projectIds ?? [],
      },
      context: input.context,
    });
  }

  private async createSession(
    userId: string,
    organizationId: string,
    context: RequestSecurityContext,
  ): Promise<SessionResult> {
    const organization = await this.prisma.authOrganization.findUnique({
      where: { id: organizationId },
      select: { active: true },
    });
    if (!organization?.active) {
      throw new Error("Company access denied");
    }
    const sessionToken = randomToken();
    const csrfToken = randomToken();
    const expiresAt = new Date(
      this.now().getTime() +
        this.config.AUTH_SESSION_TTL_HOURS * 60 * 60 * 1000,
    );
    const session = await this.prisma.authSession.create({
      data: {
        userId,
        organizationId,
        tokenHash: this.hashToken(sessionToken),
        csrfTokenHash: this.hashToken(csrfToken),
        expiresAt,
        ipHash: context.ip ? this.hashToken(context.ip) : null,
        userAgent: context.userAgent?.slice(0, 500),
      },
    });
    return {
      sessionId: session.id,
      sessionToken,
      csrfToken,
      expiresAt,
    };
  }

  verifyCsrf(sessionId: string, rawCsrfToken: string): Promise<boolean> {
    return this.prisma.authSession
      .findUnique({ where: { id: sessionId } })
      .then(
        (session) =>
          Boolean(session) &&
          safeEqual(session!.csrfTokenHash, this.hashToken(rawCsrfToken)),
      );
  }

  private async createChallenge(
    userId: string,
    purpose: string,
    metadata: Record<string, unknown>,
  ): Promise<string> {
    const token = randomToken();
    await this.prisma.authChallenge.create({
      data: {
        userId,
        purpose,
        tokenHash: this.hashToken(token),
        metadata: toInputJson(metadata),
        expiresAt: new Date(
          this.now().getTime() +
            this.config.AUTH_CHALLENGE_TTL_MINUTES * 60 * 1000,
        ),
      },
    });
    return token;
  }

  private async getChallenge(rawToken: string, purpose: string) {
    const challenge = await this.prisma.authChallenge.findUnique({
      where: { tokenHash: this.hashToken(rawToken) },
    });
    if (
      !challenge ||
      challenge.purpose !== purpose ||
      challenge.consumedAt ||
      challenge.expiresAt <= this.now()
    ) {
      throw new Error("Authentication challenge is invalid or expired");
    }
    return challenge;
  }

  private async recordFailedLogin(userId: string): Promise<void> {
    const user = await this.prisma.authUser.findUnique({
      where: { id: userId },
      select: { failedLoginAttempts: true },
    });
    const attempts = (user?.failedLoginAttempts ?? 0) + 1;
    await this.prisma.authUser.update({
      where: { id: userId },
      data: {
        failedLoginAttempts: attempts,
        lockedUntil:
          attempts >= this.config.AUTH_MAX_FAILED_LOGINS
            ? new Date(
                this.now().getTime() +
                  this.config.AUTH_LOCKOUT_MINUTES * 60 * 1000,
              )
            : null,
      },
    });
  }

  private assertOrganizationAccess(
    user: {
      isSystemAdmin: boolean;
      isExecutive: boolean;
      memberships: Array<{ organizationId: string }>;
    },
    organizationId: string,
  ): void {
    if (
      user.isSystemAdmin ||
      user.isExecutive ||
      user.memberships.some(
        (membership) => membership.organizationId === organizationId,
      )
    ) {
      return;
    }
    throw new Error("Company access denied");
  }

  private requireGroupAdministrator(actor: ActorContext): void {
    if (
      actor.isSystemAdmin ||
      actor.isExecutive ||
      actor.permissions.includes("*")
    ) {
      return;
    }
    throw new Error("System administrator or executive access required");
  }

  private hashToken(value: string): string {
    return createHmac("sha256", this.tokenPepper).update(value).digest("hex");
  }

  private async audit(
    eventType: string,
    input: {
      actorId?: string;
      organizationId?: string;
      targetType?: string;
      targetId?: string;
      metadata?: Record<string, unknown>;
      context?: RequestSecurityContext;
    },
  ): Promise<void> {
    await this.prisma.securityAuditEvent.create({
      data: {
        eventType,
        actorId: input.actorId,
        organizationId: input.organizationId,
        targetType: input.targetType,
        targetId: input.targetId,
        requestId: input.context?.requestId,
        ipHash: input.context?.ip
          ? this.hashToken(input.context.ip)
          : null,
        metadata: toInputJson(input.metadata ?? {}),
      },
    });
  }
}

export interface EnrollmentResult {
  enrollmentToken: string;
  secret: string;
  otpAuthUri: string;
}

export interface SessionResult {
  sessionId: string;
  sessionToken: string;
  csrfToken: string;
  expiresAt: Date;
}

function randomToken(): string {
  return randomBytes(32).toString("base64url");
}

function normalizeRecoveryCode(value: string): string {
  return value.trim().replace(/\s+/g, "").toUpperCase();
}

function safeEqual(left: string, right: string): boolean {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function toInputJson(value: Record<string, unknown>): Prisma.InputJsonValue {
  return JSON.parse(JSON.stringify(value)) as Prisma.InputJsonValue;
}
