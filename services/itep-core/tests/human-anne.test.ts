import { describe, expect, it } from "vitest";
import {
  HumanAnneIncidentService,
  type HumanAnneIncidentRepository,
} from "../src/human-anne/incident-service.js";
import type { HumanAnneIncident } from "../src/human-anne/types.js";

class MemoryIncidentRepository implements HumanAnneIncidentRepository {
  items = new Map<string, HumanAnneIncident>();
  async create(value: HumanAnneIncident) { this.items.set(value.id, value); }
  async getById(id: string) { return this.items.get(id) ?? null; }
  async listOpen() {
    return [...this.items.values()].filter((x) =>
      ["OPEN", "ACKNOWLEDGED", "IN_PROGRESS"].includes(x.status),
    );
  }
  async save(value: HumanAnneIncident) { this.items.set(value.id, value); }
}

describe("HumanAnneIncidentService", () => {
  it("opens and resolves an incident", async () => {
    const repo = new MemoryIncidentRepository();
    let id = 0;
    const service = new HumanAnneIncidentService(
      repo,
      { now: () => new Date("2026-07-24T08:00:00Z") },
      { next: () => `incident-${++id}` },
    );

    const opened = await service.open({
      taskId: "task-1",
      category: "LEGAL_RISK",
      severity: "CRITICAL",
      title: "Jogi beavatkozás szükséges",
      description: "Emberi döntés szükséges.",
      recommendedAction: "Human Anne ellenőrizze.",
      source: "digital-anne",
    });

    const resolved = await service.resolve(
      opened.id,
      "human-anne-1",
      "Jogász bevonva.",
    );

    expect(resolved.status).toBe("RESOLVED");
    expect(resolved.resolution).toBe("Jogász bevonva.");
  });
});
