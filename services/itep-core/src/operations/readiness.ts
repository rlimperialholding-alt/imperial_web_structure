export interface DependencyCheck {
  name: string;
  critical: boolean;
  check(): Promise<{ ok: boolean; details?: string }>;
}

export class ReadinessAggregator {
  constructor(private readonly dependencies: DependencyCheck[]) {}

  async inspect() {
    const checks = await Promise.all(
      this.dependencies.map(async (dependency) => {
        try {
          const result = await dependency.check();
          return {
            name: dependency.name,
            critical: dependency.critical,
            ...result,
          };
        } catch (error) {
          return {
            name: dependency.name,
            critical: dependency.critical,
            ok: false,
            details:
              error instanceof Error ? error.message : "Unknown failure",
          };
        }
      }),
    );

    const ready = checks.every(
      (check) => check.ok || !check.critical,
    );

    return { ready, checks };
  }
}
