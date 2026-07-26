import { afterEach, describe, expect, it } from "vitest";
import Fastify, { type FastifyInstance } from "fastify";
import { registerOpenApi } from "../src/api/openapi.js";

describe("OpenAPI documentation", () => {
  let app: FastifyInstance | undefined;

  afterEach(async () => {
    await app?.close();
    app = undefined;
  });

  it("serves Swagger UI and the generated OpenAPI document", async () => {
    app = Fastify();
    await registerOpenApi(app);

    const ui = await app.inject({ method: "GET", url: "/docs/" });
    expect(ui.statusCode).toBe(200);
    expect(ui.headers["content-type"]).toContain("text/html");

    const document = await app.inject({ method: "GET", url: "/docs/json" });
    expect(document.statusCode).toBe(200);
    expect(document.json().info.title).toContain("ITEP API");
  });
});
