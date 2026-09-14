import { afterEach, describe, expect, it, vi } from "vitest";
import { GoogleCalendarChangesGateway, GoogleDriveChangesGateway } from "../src/connectors/google-api-gateways.js";
afterEach(() => vi.unstubAllGlobals());
describe("Google API gateways", () => {
  it("maps calendar events", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items:[{ id:"e1", summary:"Meeting", start:{dateTime:"2026-07-24T10:00:00Z"}, end:{dateTime:"2026-07-24T11:00:00Z"}, organizer:{email:"a@b.hu"}, attendees:[{email:"c@d.hu"}], status:"confirmed" }], nextSyncToken:"s2" }), {status:200})));
    const result=await new GoogleCalendarChangesGateway().listChanges({accessToken:"x",externalAccountId:"primary"});
    expect(result.events[0].title).toBe("Meeting"); expect(result.nextSyncToken).toBe("s2");
  });
  it("obtains Drive start token then maps changes", async () => {
    const fetchMock=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({startPageToken:"p1"}),{status:200})).mockResolvedValueOnce(new Response(JSON.stringify({changes:[{fileId:"f1",time:"2026-07-24T10:00:00Z",file:{name:"Doc",mimeType:"text/plain",parents:[]}}],newStartPageToken:"p2"}),{status:200}));
    vi.stubGlobal("fetch",fetchMock);
    const result=await new GoogleDriveChangesGateway().listChanges({accessToken:"x"});
    expect(result.changes[0].name).toBe("Doc"); expect(result.nextPageToken).toBe("p2");
  });
});
