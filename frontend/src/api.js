// Único ponto de contato com o backend. Nenhum token ou papel é enviado daqui.
// Em dev, o proxy do Vite encaminha /api; em produção o FastAPI serve o build.
const BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  constructor(status, error) {
    super(error?.message ?? "Erro inesperado.");
    this.status = status;
    this.code = error?.code ?? "unknown_error";
    this.retryable = Boolean(error?.retryable);
    this.details = error?.details ?? [];
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch {
    throw new ApiError(0, {
      code: "network_error",
      message: "Não foi possível falar com o servidor.",
      retryable: true,
    });
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, body?.error);
  return body;
}

const post = (path, data) => request(path, { method: "POST", body: JSON.stringify(data) });

export const getCharacters = () => request("/api/characters");
export const createSession = (characterId) => post("/api/sessions", { character_id: characterId });
export const getSession = (threadId) => request(`/api/sessions/${threadId}`);
export const sendMessage = (threadId, text) => post(`/api/sessions/${threadId}/messages`, { text });
export const sendDecision = (threadId, { action_id, version, decision, text }) =>
  post(`/api/sessions/${threadId}/decisions`, { action_id, version, decision, text });
