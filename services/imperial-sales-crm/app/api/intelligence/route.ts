import { getIntelligenceWorkspace } from "@/lib/intelligence-workspace";
import { jsonError, requireInternalCrmIdentity } from "@/lib/crm-auth";

export async function GET(request: Request) {
  try {
    await requireInternalCrmIdentity(request);
    const workspaceId = process.env.CRM_WORKSPACE_ID ?? "imperial-live";
    return Response.json(await getIntelligenceWorkspace(workspaceId));
  } catch (error) {
    return jsonError(error);
  }
}

