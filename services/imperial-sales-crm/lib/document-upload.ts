const MAX_FILE_SIZE = 15 * 1024 * 1024;

const acceptedTypes: Record<string, string[]> = {
  "application/pdf": ["pdf"],
  "image/jpeg": ["jpg", "jpeg"],
  "image/png": ["png"],
  "image/webp": ["webp"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ["docx"],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ["xlsx"],
};

function hasSignature(bytes: Uint8Array, type: string) {
  if (type === "application/pdf") return String.fromCharCode(...bytes.slice(0, 5)) === "%PDF-";
  if (type === "image/jpeg") return bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
  if (type === "image/png") return bytes.slice(0, 8).every((value, index) => value === [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a][index]);
  if (type === "image/webp") return String.fromCharCode(...bytes.slice(0, 4)) === "RIFF" && String.fromCharCode(...bytes.slice(8, 12)) === "WEBP";
  return bytes[0] === 0x50 && bytes[1] === 0x4b;
}

export async function validateDocumentFile(file: File) {
  if (!file.size || file.size > MAX_FILE_SIZE) throw new Response("A fájl mérete legfeljebb 15 MB lehet.", { status: 413 });
  const extension = file.name.split(".").pop()?.toLowerCase() || "";
  const allowedExtensions = acceptedTypes[file.type];
  if (!allowedExtensions?.includes(extension)) throw new Response("Csak PDF, JPG, PNG, WebP, DOCX vagy XLSX fájl tölthető fel.", { status: 415 });
  const data = await file.arrayBuffer();
  if (!hasSignature(new Uint8Array(data.slice(0, 16)), file.type)) throw new Response("A fájl tartalma nem egyezik a kiterjesztésével.", { status: 415 });
  return data;
}

export async function sha256Hex(data: ArrayBuffer) {
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}

export function safeFileName(value: string) {
  return value.replace(/[\r\n]/g, "").trim().slice(0, 180) || "dokumentum";
}
