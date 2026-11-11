import { afterEach, expect, test, vi } from "vitest";
import {
  createSession,
  getSession,
  sendDecision,
  sendMessage,
  switchSession,
} from "./api.js";

afterEach(() => vi.unstubAllGlobals());
function mockFetch(body = {}) {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => body });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
test("transporta somente campos públicos e decisions preserva action_id/version", async () => {
  const fetch = mockFetch();
  await createSession(101);
  await switchSession("thread/a", 102);
  await sendMessage("thread/a", "mensagem");
  await sendDecision("thread/a", {
    action_id: "a",
    version: 2,
    decision: "edit",
    text: "correção",
    role: "admin",
    token: "não enviar",
  });
  expect(
    fetch.mock.calls.map(([url, options]) => [url, JSON.parse(options.body)]),
  ).toEqual([
    ["/api/sessions", { character_id: 101 }],
    ["/api/sessions/thread%2Fa/switch", { character_id: 102 }],
    ["/api/sessions/thread%2Fa/messages", { text: "mensagem" }],
    [
      "/api/sessions/thread%2Fa/decisions",
      { action_id: "a", version: 2, decision: "edit", text: "correção" },
    ],
  ]);
});
test("converte falha de rede e erro HTTP no formato comum", async () => {
  const fetch = mockFetch();
  fetch.mockRejectedValueOnce(new TypeError("offline"));
  await expect(getSession("a")).rejects.toMatchObject({
    code: "network_error",
    status: 0,
  });
  fetch.mockResolvedValueOnce({
    ok: false,
    status: 409,
    json: async () => ({
      error: { code: "stale_action_version", message: "Confira a versão." },
    }),
  });
  await expect(getSession("a")).rejects.toMatchObject({
    code: "stale_action_version",
    status: 409,
  });
});
test("resposta de sucesso ilegível exige reconciliação e não é reenviada", async () => {
  const fetch = mockFetch();
  fetch.mockResolvedValueOnce({
    ok: true,
    json: async () => {
      throw new Error("invalid json");
    },
  });
  await expect(
    sendDecision("a", { action_id: "b", version: 1, decision: "yes" }),
  ).rejects.toMatchObject({ code: "invalid_response", status: 502 });
  expect(fetch).toHaveBeenCalledTimes(1);
});
