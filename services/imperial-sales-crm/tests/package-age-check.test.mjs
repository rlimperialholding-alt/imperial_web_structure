import assert from "node:assert/strict";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  collectLockedPackages,
  extractPublishTime,
  fetchPackument,
  findTooYoung,
  runPackageAgeCheck,
} from "../scripts/check-package-age.mjs";

const DAY = 24 * 60 * 60 * 1000;
const NOW = 1_800_000_000_000; // determinisztikus „most”

function packument(name, version, publishedDaysAgo) {
  const published = new Date(NOW - publishedDaysAgo * DAY).toISOString();
  return { name, time: { [version]: published } };
}

test("collectLockedPackages skips link, file and dev-only entries", () => {
  const lock = {
    lockfileVersion: 3,
    packages: {
      "node_modules/old-pkg": { version: "1.0.0", resolved: "https://registry.npmjs.org/old-pkg/-/old-pkg-1.0.0.tgz" },
      "node_modules/young-pkg": { version: "2.0.0", resolved: "https://registry.npmjs.org/young-pkg/-/young-pkg-2.0.0.tgz" },
      "node_modules/linked": { version: "1.0.0", link: true },
      "node_modules/file-dep": { version: "1.0.0", resolved: "file:../local" },
      "node_modules/dev-only": { version: "3.0.0", dev: true },
      "": { name: "root", version: "0.0.0" },
    },
  };
  const packages = collectLockedPackages(lock);
  const names = packages.map((p) => p.name);
  assert.deepEqual(names, ["old-pkg", "young-pkg"]);
  const withDev = collectLockedPackages(lock, { includeDev: true });
  assert.ok(withDev.some((p) => p.name === "dev-only"));
});

test("extractPublishTime returns the registry time or null", () => {
  const pack = packument("pkg", "1.0.0", 30);
  assert.equal(extractPublishTime(pack, "1.0.0"), pack.time["1.0.0"]);
  assert.equal(extractPublishTime(pack, "9.9.9"), null);
});

test("findTooYoung enforces the floor and fails closed on missing evidence", () => {
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

test("findTooYoung respects a custom floor", () => {
  const packages = [{ name: "pkg", version: "1.0.0" }];
  const packuments = new Map([["pkg", packument("pkg", "1.0.0", 5)]]);
  assert.equal(findTooYoung({ packages, packuments, nowMs: NOW, minAgeDays: 7 }).length, 1);
  assert.equal(findTooYoung({ packages, packuments, nowMs: NOW, minAgeDays: 3 }).length, 0);
});

test("fetchPackument encodes scoped names and requests the full packument", async () => {
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

test("runPackageAgeCheck passes an all-old lockfile offline", async () => {
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
    const fetchImpl = async () => ({
      ok: true,
      json: async () => packument("old-pkg", "1.0.0", 30),
    });
    const stdout = [];
    const exitCode = await runPackageAgeCheck({
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

test("runPackageAgeCheck fails closed on a young package", async () => {
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

test("runPackageAgeCheck fails closed when the registry is unreachable", async () => {
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
