import assert from "node:assert/strict";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  collectLockedPackages,
  extractPublishTime,
  fetchPackument,
  findTooYoung,
  runPackageAgeCheck,
} from "../scripts/check-package-age.mjs";
// Futó-független regisztráció: a node --test (imperial-sales-crm) a
// node:test API-t, a vitest (itep-core) a vitest.it API-t gyűjti; a
// teszttörzsek közösek. A VITEST környezeti változót a vitest runner
// állítja be a workerben (a node --test futtatásnál nem definiált).
let defineTest;
if (typeof process !== "undefined" && process.env.VITEST === "true") {
  ({ it: defineTest } = await import("vitest"));
} else {
  ({ default: defineTest } = await import("node:test"));
}


const DAY = 24 * 60 * 60 * 1000;
const NOW = 1_800_000_000_000; // determinisztikus „most”

function packument(name, version, publishedDaysAgo) {
  const published = new Date(NOW - publishedDaysAgo * DAY).toISOString();
  return { name, time: { [version]: published } };
}

defineTest("collectLockedPackages includes dev/devOptional/optional by default (CI), skips link/file", () => {
  const lock = {
    lockfileVersion: 3,
    packages: {
      "node_modules/old-pkg": { version: "1.0.0", resolved: "https://registry.npmjs.org/old-pkg/-/old-pkg-1.0.0.tgz" },
      "node_modules/young-pkg": { version: "2.0.0", resolved: "https://registry.npmjs.org/young-pkg/-/young-pkg-2.0.0.tgz" },
      "node_modules/linked": { version: "1.0.0", link: true },
      "node_modules/file-dep": { version: "1.0.0", resolved: "file:../local" },
      "node_modules/dev-only": { version: "3.0.0", dev: true },
      "node_modules/dev-optional": { version: "4.0.0", devOptional: true },
      "node_modules/optional": { version: "5.0.0", optional: true },
      "": { name: "root", version: "0.0.0" },
    },
  };
  const packages = collectLockedPackages(lock); // CI-default: includeDev=true
  assert.deepEqual(
    new Set(packages.map((p) => p.name)),
    new Set(["old-pkg", "young-pkg", "dev-only", "dev-optional", "optional"]),
  );
  const prodOnly = collectLockedPackages(lock, { includeDev: false });
  assert.deepEqual(
    new Set(prodOnly.map((p) => p.name)),
    new Set(["old-pkg", "young-pkg", "optional"]),
  );
});

defineTest("collectLockedPackages skips lock entries without version metadata", () => {
  const lock = {
    lockfileVersion: 3,
    packages: {
      "node_modules/with-version": { version: "1.0.0" },
      "node_modules/versionless-dev": { dev: true },
      "": { name: "root", version: "0.0.0" },
    },
  };
  const packages = collectLockedPackages(lock);
  assert.deepEqual(new Set(packages.map((p) => p.name)), new Set(["with-version"]));
});

defineTest("extractPublishTime returns the registry time or null", () => {
  const pack = packument("pkg", "1.0.0", 30);
  assert.equal(extractPublishTime(pack, "1.0.0"), pack.time["1.0.0"]);
  assert.equal(extractPublishTime(pack, "9.9.9"), null);
});

defineTest("findTooYoung enforces the floor and fails closed on missing evidence", () => {
  const packages = [
    { name: "old-pkg", version: "1.0.0" },
    { name: "young-pkg", version: "2.0.0" },
    { name: "boundary-pkg", version: "3.0.0" },
    { name: "no-time-pkg", version: "4.0.0" },
    { name: "no-packument-pkg", version: "5.0.0" },
  ];
  const packuments = new Map([
    ["old-pkg", packument("old-pkg", "1.0.0", 30)],
    ["young-pkg", packument("young-pkg", "2.0.0", 1)],
    ["boundary-pkg", packument("boundary-pkg", "3.0.0", 7)],
    ["no-time-pkg", { name: "no-time-pkg", time: {} }],
  ]);
  const tooYoung = findTooYoung({ packages, packuments, nowMs: NOW, minAgeDays: 7 });
  const flagged = new Map(tooYoung.map((item) => [item.name, item.reason]));
  assert.ok(!flagged.has("old-pkg"));
  assert.ok(!flagged.has("boundary-pkg"), "a pontosan 7 napos csomag a küszöb felett van");
  assert.match(flagged.get("young-pkg"), /age 1d < 7d floor/);
  assert.match(flagged.get("no-time-pkg"), /not provable/);
  assert.match(flagged.get("no-packument-pkg"), /unavailable/);
});

defineTest("findTooYoung fails closed on a future publish time (clock skew)", () => {
  const packages = [{ name: "future-pkg", version: "1.0.0" }];
  const packuments = new Map([["future-pkg", packument("future-pkg", "1.0.0", -2)]]);
  const tooYoung = findTooYoung({ packages, packuments, nowMs: NOW, minAgeDays: 7 });
  assert.equal(tooYoung.length, 1);
  assert.match(tooYoung[0].reason, /age -2d < 7d floor/);
});

defineTest("findTooYoung respects a custom floor", () => {
  const packages = [{ name: "pkg", version: "1.0.0" }];
  const packuments = new Map([["pkg", packument("pkg", "1.0.0", 5)]]);
  assert.equal(findTooYoung({ packages, packuments, nowMs: NOW, minAgeDays: 7 }).length, 1);
  assert.equal(findTooYoung({ packages, packuments, nowMs: NOW, minAgeDays: 3 }).length, 0);
});

defineTest("fetchPackument encodes scoped names and requests the full packument", async () => {
  const seen = [];
  const fetchImpl = async (url, options) => {
    seen.push([url, options]);
    return { ok: true, json: async () => ({ name: "x", time: {} }) };
  };
  await fetchPackument("@scope/pkg", "https://registry.npmjs.org/", fetchImpl);
  assert.equal(seen[0][0], "https://registry.npmjs.org/@scope%2Fpkg");
  // A teljes packument kell: az abbreviated (install-v1) válasz nem
  // tartalmazza a verziónkénti `time` publikálási időpontokat.
  assert.equal(seen[0][1].headers.accept, "application/json");
});

defineTest("runPackageAgeCheck passes an all-old lockfile offline (dev included by default)", async () => {
  const dir = await mkdtemp(join(tmpdir(), "pkg-age-"));
  try {
    const lock = {
      lockfileVersion: 3,
      packages: {
        "node_modules/old-pkg": {
          version: "1.0.0",
          resolved: "https://registry.npmjs.org/old-pkg/-/old-pkg-1.0.0.tgz",
        },
        "node_modules/old-dev": {
          version: "4.0.0",
          devOptional: true,
          resolved: "https://registry.npmjs.org/old-dev/-/old-dev-4.0.0.tgz",
        },
      },
    };
    const lockfilePath = join(dir, "package-lock.json");
    await writeFile(lockfilePath, JSON.stringify(lock));
    const fetchImpl = async (url) => {
      const name = decodeURIComponent(url.split("/").pop());
      return {
        ok: true,
        json: async () => packument(name, name === "old-pkg" ? "1.0.0" : "4.0.0", 30),
      };
    };
    const stdout = [];
    const exitCode = await runPackageAgeCheck({
      fetchImpl,
      nowMs: NOW,
      lockfilePath,
      stdout: (line) => stdout.push(line),
    });
    assert.equal(exitCode, 0, stdout.join("\n"));
    assert.match(stdout.join("\n"), /2 locked package\(s\) verified/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

defineTest("runPackageAgeCheck fails closed on a young package", async () => {
  const dir = await mkdtemp(join(tmpdir(), "pkg-age-"));
  try {
    const lock = {
      lockfileVersion: 3,
      packages: {
        "node_modules/young-pkg": {
          version: "2.0.0",
          resolved: "https://registry.npmjs.org/young-pkg/-/young-pkg-2.0.0.tgz",
        },
      },
    };
    const lockfilePath = join(dir, "package-lock.json");
    await writeFile(lockfilePath, JSON.stringify(lock));
    const fetchImpl = async () => ({
      ok: true,
      json: async () => packument("young-pkg", "2.0.0", 1),
    });
    const stderr = [];
    const exitCode = await runPackageAgeCheck({
      fetchImpl,
      nowMs: NOW,
      lockfilePath,
      stderr: (line) => stderr.push(line),
    });
    assert.equal(exitCode, 1);
    assert.match(stderr.join("\n"), /young-pkg@2\.0\.0/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

defineTest("runPackageAgeCheck fails closed on a young dev dependency by default", async () => {
  const dir = await mkdtemp(join(tmpdir(), "pkg-age-"));
  try {
    const lock = {
      lockfileVersion: 3,
      packages: {
        "node_modules/old-pkg": {
          version: "1.0.0",
          resolved: "https://registry.npmjs.org/old-pkg/-/old-pkg-1.0.0.tgz",
        },
        "node_modules/young-dev": {
          version: "2.0.0",
          dev: true,
          resolved: "https://registry.npmjs.org/young-dev/-/young-dev-2.0.0.tgz",
        },
      },
    };
    const lockfilePath = join(dir, "package-lock.json");
    await writeFile(lockfilePath, JSON.stringify(lock));
    const fetchImpl = async (url) => {
      const name = decodeURIComponent(url.split("/").pop());
      return {
        ok: true,
        json: async () =>
          packument(
            name,
            name === "old-pkg" ? "1.0.0" : "2.0.0",
            name === "old-pkg" ? 30 : 1,
          ),
      };
    };
    const stderr = [];
    const exitCode = await runPackageAgeCheck({
      fetchImpl,
      nowMs: NOW,
      lockfilePath,
      stderr: (line) => stderr.push(line),
    });
    assert.equal(exitCode, 1);
    assert.match(stderr.join("\n"), /young-dev@2\.0\.0/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

defineTest("runPackageAgeCheck --prod-only skips dev entries (explicit prod gate)", async () => {
  const dir = await mkdtemp(join(tmpdir(), "pkg-age-"));
  try {
    const lock = {
      lockfileVersion: 3,
      packages: {
        "node_modules/old-pkg": {
          version: "1.0.0",
          resolved: "https://registry.npmjs.org/old-pkg/-/old-pkg-1.0.0.tgz",
        },
        "node_modules/young-dev": {
          version: "2.0.0",
          dev: true,
          resolved: "https://registry.npmjs.org/young-dev/-/young-dev-2.0.0.tgz",
        },
      },
    };
    const lockfilePath = join(dir, "package-lock.json");
    await writeFile(lockfilePath, JSON.stringify(lock));
    const fetchImpl = async () => ({
      ok: true,
      json: async () => packument("old-pkg", "1.0.0", 30),
    });
    const stdout = [];
    const exitCode = await runPackageAgeCheck({
      argv: ["--prod-only"],
      fetchImpl,
      nowMs: NOW,
      lockfilePath,
      stdout: (line) => stdout.push(line),
    });
    assert.equal(exitCode, 0, stdout.join("\n"));
    assert.match(stdout.join("\n"), /1 locked package\(s\) verified/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

defineTest("runPackageAgeCheck fails closed when the registry is unreachable", async () => {
  const dir = await mkdtemp(join(tmpdir(), "pkg-age-"));
  try {
    const lock = {
      lockfileVersion: 3,
      packages: {
        "node_modules/old-pkg": {
          version: "1.0.0",
          resolved: "https://registry.npmjs.org/old-pkg/-/old-pkg-1.0.0.tgz",
        },
      },
    };
    const lockfilePath = join(dir, "package-lock.json");
    await writeFile(lockfilePath, JSON.stringify(lock));
    const fetchImpl = async () => ({ ok: false, status: 503 });
    const stderr = [];
    const exitCode = await runPackageAgeCheck({
      fetchImpl,
      nowMs: NOW,
      lockfilePath,
      stderr: (line) => stderr.push(line),
    });
    assert.equal(exitCode, 1);
    assert.match(stderr.join("\n"), /floor is fail-closed/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

defineTest("runPackageAgeCheck fails closed when the registry fetch throws", async () => {
  const dir = await mkdtemp(join(tmpdir(), "pkg-age-"));
  try {
    const lock = {
      lockfileVersion: 3,
      packages: {
        "node_modules/old-pkg": {
          version: "1.0.0",
          resolved: "https://registry.npmjs.org/old-pkg/-/old-pkg-1.0.0.tgz",
        },
      },
    };
    const lockfilePath = join(dir, "package-lock.json");
    await writeFile(lockfilePath, JSON.stringify(lock));
    const fetchImpl = async () => {
      throw new Error("network unreachable");
    };
    const stderr = [];
    const exitCode = await runPackageAgeCheck({
      fetchImpl,
      nowMs: NOW,
      lockfilePath,
      stderr: (line) => stderr.push(line),
    });
    assert.equal(exitCode, 1);
    assert.match(stderr.join("\n"), /network unreachable/);
    assert.match(stderr.join("\n"), /floor is fail-closed/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
