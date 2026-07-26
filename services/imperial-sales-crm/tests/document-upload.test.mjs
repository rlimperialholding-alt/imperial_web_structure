import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { safeFileName, sha256Hex, validateDocumentFile } from "../lib/document-upload.ts";

test("valid PDF content is accepted and receives a deterministic SHA-256", async () => {
  const bytes = new TextEncoder().encode("%PDF-1.7\nMyImperial test document");
  const file = new File([bytes], "terv.pdf", { type: "application/pdf" });
  const data = await validateDocumentFile(file);
  const expected = createHash("sha256").update(bytes).digest("hex");
  assert.equal(await sha256Hex(data), expected);
});

test("a spoofed extension or content signature is rejected", async () => {
  const wrongType = new File(["%PDF-1.7"], "terv.exe", { type: "application/pdf" });
  const wrongSignature = new File(["not a pdf"], "terv.pdf", { type: "application/pdf" });
  await assert.rejects(() => validateDocumentFile(wrongType));
  await assert.rejects(() => validateDocumentFile(wrongSignature));
});

test("download names cannot inject response headers", () => {
  assert.equal(safeFileName("terv.pdf\r\nX-Test: injected"), "terv.pdfX-Test: injected");
});
