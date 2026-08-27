export async function GET() {
  return Response.json({
    ok: true,
    service: "imperial-sales-crm",
    storage: "cloudflare-d1-r2-local-test",
  });
}
