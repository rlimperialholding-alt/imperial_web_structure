import type { Clock, IdGenerator } from "../application/ports.js";
import type { ConnectorAccountRepository } from "./ports.js";
import type { ConnectorKind } from "./types.js";

export interface OAuthProvider {
  buildAuthorizationUrl(input: {
    state: string;
    redirectUri: string;
    scopes: string[];
    loginHint?: string;
  }): Promise<string>;

  exchangeCode(input: {
    code: string;
    redirectUri: string;
  }): Promise<{
    accessToken: string;
    refreshToken?: string;
    expiresAt?: Date;
    externalAccountId: string;
    displayName: string;
    grantedScopes: string[];
  }>;
}

export interface OAuthStateStore {
  save(input: {
    state: string;
    organizationId: string;
    kind: ConnectorKind;
    redirectUri: string;
    requestedScopes: string[];
    createdBy: string;
    expiresAt: Date;
  }): Promise<void>;

  consume(state: string): Promise<{
    organizationId: string;
    kind: ConnectorKind;
    redirectUri: string;
    requestedScopes: string[];
    createdBy: string;
  } | null>;
}

export interface ConnectorCredentialVault {
  store(input: {
    connectorAccountId: string;
    accessToken: string;
    refreshToken?: string;
    expiresAt?: Date;
  }): Promise<void>;

  delete(connectorAccountId: string): Promise<void>;
}

export class ConnectorOAuthService {
  constructor(
    private readonly accounts: ConnectorAccountRepository,
    private readonly providers: Partial<Record<ConnectorKind, OAuthProvider>>,
    private readonly stateStore: OAuthStateStore,
    private readonly vault: ConnectorCredentialVault,
    private readonly clock: Clock,
    private readonly ids: IdGenerator,
  ) {}

  async begin(input: {
    organizationId: string;
    kind: ConnectorKind;
    redirectUri: string;
    scopes: string[];
    createdBy: string;
    loginHint?: string;
  }) {
    const provider = this.providers[input.kind];
    if (!provider) throw new Error(`OAuth provider missing: ${input.kind}`);

    const state = this.ids.next();
    const expiresAt = new Date(this.clock.now().getTime() + 10 * 60 * 1000);

    await this.stateStore.save({
      state,
      organizationId: input.organizationId,
      kind: input.kind,
      redirectUri: input.redirectUri,
      requestedScopes: input.scopes,
      createdBy: input.createdBy,
      expiresAt,
    });

    const authorizationUrl = await provider.buildAuthorizationUrl({
      state,
      redirectUri: input.redirectUri,
      scopes: input.scopes,
      ...(input.loginHint ? { loginHint: input.loginHint } : {}),
    });

    return { state, authorizationUrl, expiresAt };
  }

  async complete(input: { state: string; code: string }) {
    const pending = await this.stateStore.consume(input.state);
    if (!pending) {
      throw new Error("OAuth state is invalid, expired or already used");
    }

    const provider = this.providers[pending.kind];
    if (!provider) throw new Error(`OAuth provider missing: ${pending.kind}`);
    const token = await provider.exchangeCode({
      code: input.code,
      redirectUri: pending.redirectUri,
    });

    const now = this.clock.now();
    const accountId = this.ids.next();

    await this.vault.store({
      connectorAccountId: accountId,
      accessToken: token.accessToken,
      ...(token.refreshToken ? { refreshToken: token.refreshToken } : {}),
      ...(token.expiresAt ? { expiresAt: token.expiresAt } : {}),
    });

    await this.accounts.save({
      id: accountId,
      organizationId: pending.organizationId,
      kind: pending.kind,
      externalAccountId: token.externalAccountId,
      displayName: token.displayName,
      status: "ACTIVE",
      scopes: token.grantedScopes,
      createdAt: now,
      updatedAt: now,
    });

    return {
      connectorAccountId: accountId,
      kind: pending.kind,
      externalAccountId: token.externalAccountId,
      displayName: token.displayName,
      scopes: token.grantedScopes,
    };
  }

  async disconnect(accountId: string) {
    const account = await this.accounts.getById(accountId);
    if (!account) throw new Error(`Connector account not found: ${accountId}`);

    await this.vault.delete(accountId);
    const { lastError: _lastError, ...withoutError } = account;
    await this.accounts.save({
      ...withoutError,
      status: "DISCONNECTED",
      updatedAt: this.clock.now(),
    });
  }
}
