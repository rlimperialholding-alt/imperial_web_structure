import {
  randomBytes,
  scrypt as nodeScrypt,
  timingSafeEqual,
} from "node:crypto";

const N = 32_768;
const R = 8;
const P = 1;
const KEY_LENGTH = 64;
const MAX_MEMORY = 64 * 1024 * 1024;

export function normalizeEmail(email: string): string {
  return email.trim().toLocaleLowerCase("en-US");
}

export function assertStrongPassword(password: string, email?: string): void {
  if (password.length < 14 || password.length > 128) {
    throw new Error("Password must contain between 14 and 128 characters");
  }
  const lowered = password.toLocaleLowerCase("en-US");
  const localPart = email?.split("@")[0]?.toLocaleLowerCase("en-US");
  if (
    ["password", "jelszo", "imperial", "123456", "qwerty"].some((part) =>
      lowered.includes(part)
    ) ||
    (localPart && localPart.length >= 4 && lowered.includes(localPart))
  ) {
    throw new Error("Password contains an easily guessed word");
  }
}

export async function hashPassword(password: string): Promise<string> {
  const salt = randomBytes(16);
  const derived = await scrypt(password, salt, KEY_LENGTH, {
    N,
    r: R,
    p: P,
    maxmem: MAX_MEMORY,
  });
  return [
    "scrypt",
    N,
    R,
    P,
    salt.toString("base64url"),
    derived.toString("base64url"),
  ].join("$");
}

export async function verifyPassword(
  password: string,
  encoded: string,
): Promise<boolean> {
  const [algorithm, n, r, p, saltValue, expectedValue] = encoded.split("$");
  if (
    algorithm !== "scrypt" ||
    !saltValue ||
    !expectedValue ||
    Number(n) !== N ||
    Number(r) !== R ||
    Number(p) !== P
  ) {
    return false;
  }
  const expected = Buffer.from(expectedValue, "base64url");
  const actual = await scrypt(
    password,
    Buffer.from(saltValue, "base64url"),
    expected.length,
    { N, r: R, p: P, maxmem: MAX_MEMORY },
  );
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

function scrypt(
  password: string,
  salt: Buffer,
  keyLength: number,
  options: { N: number; r: number; p: number; maxmem: number },
): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    nodeScrypt(password, salt, keyLength, options, (error, derivedKey) => {
      if (error) reject(error);
      else resolve(derivedKey);
    });
  });
}
