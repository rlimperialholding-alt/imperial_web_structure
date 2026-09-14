import { getRuntimeValue } from "@/db";

function tokenDigest(value: string) {
  return crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
}

async function tokensEqual(actual: string, expected: string) {
  const [actualDigest, expectedDigest] = await Promise.all([
    tokenDigest(actual),
    tokenDigest(expected),
  ]);
  const actualBytes = new Uint8Array(actualDigest);
  const expectedBytes = new Uint8Array(expectedDigest);
  let difference = 0;
  for (let index = 0; index < actualBytes.length; index += 1) {
    difference |= actualBytes[index] ^ expectedBytes[index];
  }
  return difference === 0;
}

export async function requireServiceToken(
  request: Request,
  options: { environmentKey: string; header: string },
) {
  const expected = (await getRuntimeValue(options.environmentKey))?.trim();
  const actual = request.headers.get(options.header)?.trim() ?? "";
  if (!expected || expected.length < 32) {
    throw new Response("A szolgáltatás-hitelesítés nincs biztonságosan beállítva.", {
      status: 503,
    });
  }
  if (!actual || !(await tokensEqual(actual, expected))) {
    throw new Response("Érvénytelen szolgáltatás-hitelesítés.", { status: 401 });
  }
}
