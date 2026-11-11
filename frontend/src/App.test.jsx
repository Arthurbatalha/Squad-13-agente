import { StrictMode } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import App from "./App.jsx";
import ChatReply from "./components/ChatReply.jsx";
import * as api from "./api.js";
import {
  action,
  characters,
  deferred,
  response,
  result,
  session,
  textReply,
} from "./test/fixtures.js";

vi.mock("./api.js", async (original) => ({
  ...(await original()),
  getCharacters: vi.fn(),
  createSession: vi.fn(),
  getSession: vi.fn(),
  switchSession: vi.fn(),
  sendMessage: vi.fn(),
  sendDecision: vi.fn(),
}));

beforeEach(() => {
  vi.resetAllMocks();
  api.getCharacters.mockResolvedValue({ characters });
  api.createSession.mockResolvedValue(session);
  api.getSession.mockResolvedValue(session);
  api.switchSession.mockResolvedValue({
    ...session,
    thread_id: "fixture-b",
    character: characters[1],
  });
  api.sendMessage.mockResolvedValue(response(textReply));
  api.sendDecision.mockResolvedValue(response(result));
});

async function start() {
  const user = userEvent.setup();
  render(<App />);
  await user.click(
    await screen.findByRole("button", { name: "Técnico Demo A" }),
  );
  await screen.findByRole("textbox", { name: "Sua mensagem" });
  return user;
}
async function send(user, text) {
  const input = screen.getByRole("textbox", { name: "Sua mensagem" });
  await user.clear(input);
  await user.type(input, text);
  await user.click(screen.getByRole("button", { name: "Enviar" }));
}
async function openPreview(user) {
  api.sendMessage.mockResolvedValueOnce(response({ type: "preview", action }));
  await send(user, "abrir chamado");
  await screen.findByRole("region", { name: "Ação pendente" });
}

test("lista apresenta carregamento, falha, vazio e nova leitura, inclusive em StrictMode", async () => {
  const loading = deferred();
  api.getCharacters.mockReturnValue(loading.promise);
  const user = userEvent.setup();
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  expect(screen.getByText("Carregando personagens…")).toBeInTheDocument();
  await act(async () => loading.reject(new Error("offline")));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "carregar os personagens",
  );
  api.getCharacters.mockResolvedValueOnce({ characters: [] });
  await user.click(
    screen.getByRole("button", { name: "Tentar novamente a leitura" }),
  );
  expect(
    await screen.findByText("Nenhum personagem disponível."),
  ).toBeInTheDocument();
  api.getCharacters.mockResolvedValueOnce({ characters });
  await user.click(
    screen.getByRole("button", { name: "Tentar novamente a leitura" }),
  );
  expect(
    await screen.findByRole("button", { name: "Técnico Demo A" }),
  ).toBeInTheDocument();
});

test("seleção mostra técnico ativo e simulação e impede dupla criação", async () => {
  const creating = deferred();
  api.createSession.mockReturnValueOnce(creating.promise);
  const user = userEvent.setup();
  render(<App />);
  await user.dblClick(
    await screen.findByRole("button", { name: "Técnico Demo A" }),
  );
  expect(api.createSession).toHaveBeenCalledTimes(1);
  await act(async () => creating.resolve(session));
  expect(
    screen.getByRole("region", { name: "Técnico ativo" }),
  ).toHaveTextContent("Técnico Demo A");
  expect(screen.getByText('Simulação · adapter="mock"')).toBeInTheDocument();
});

test.each([false, true])(
  "troca isola resposta e erro atrasados (falha=%s)",
  async (failure) => {
    const user = await start();
    const late = deferred();
    api.sendMessage.mockReturnValueOnce(late.promise);
    await send(user, "mensagem da conversa anterior");
    expect(
      screen.getByText("Aguardando resposta do servidor…"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Trocar personagem" }));
    await user.click(
      await screen.findByRole("button", { name: "Técnico Demo B" }),
    );
    expect(api.switchSession).toHaveBeenCalledWith("fixture-a", 102);
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "Técnico ativo" }),
      ).toHaveTextContent("Técnico Demo B"),
    );
    await act(async () =>
      failure
        ? late.reject(
            new api.ApiError(0, {
              code: "network_error",
              message: "erro antigo",
            }),
          )
        : late.resolve(response({ ...textReply, text: "resposta antiga" })),
    );
    expect(
      screen.queryByText("mensagem da conversa anterior"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("resposta antiga")).not.toBeInTheDocument();
    expect(screen.queryByText("erro antigo")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("");
  },
);

test("envio bloqueia duplicação, preserva linhas e ordena usuário/assistente", async () => {
  const user = await start();
  const pending = deferred();
  api.sendMessage.mockReturnValueOnce(pending.promise);
  const input = screen.getByRole("textbox");
  await user.type(input, "Linha um{Shift>}{Enter}{/Shift}Linha dois");
  await user.keyboard("{Enter}");
  fireEvent.submit(input.closest("form"));
  expect(api.sendMessage).toHaveBeenCalledTimes(1);
  expect(api.sendMessage).toHaveBeenCalledWith(
    "fixture-a",
    "Linha um\nLinha dois",
  );
  expect(input).toBeDisabled();
  await act(async () => pending.resolve(response(textReply)));
  expect(input).toHaveValue("");
  const messages = within(screen.getByRole("log")).getAllByRole("article");
  expect(messages[0]).toHaveTextContent("Você");
  expect(messages[0].querySelector(".message-text").textContent).toBe(
    "Linha um\nLinha dois",
  );
  expect(messages[1]).toHaveTextContent("Assistente");
});

test("fontes exibem metadados e trechos; apenas http/https viram links, conteúdo é texto seguro", () => {
  render(
    <ChatReply
      reply={{
        ...textReply,
        text: '<img src=x onerror="alert(1)">',
        sources: [
          ...textReply.sources,
          {
            source_type: "case",
            source_id: "92",
            title: "Referência perigosa",
            reference: "javascript:alert(1)",
            excerpt: "<script>fixture</script>",
          },
          {
            source_type: "case",
            source_id: "93",
            title: "Arquivo local",
            reference: "file:///etc/passwd",
          },
        ],
      }}
    />,
  );
  expect(screen.getByText("Artigo sintético")).toBeInTheDocument();
  expect(screen.getByText(/Artigo · ID 17 · Trecho 17:0/)).toBeInTheDocument();
  expect(screen.getByText("Passo 1. Passo 2.")).toBeInTheDocument();
  expect(screen.getAllByRole("link")).toHaveLength(1);
  expect(screen.getByRole("link")).toHaveAttribute(
    "href",
    "https://example.com/tickets/91",
  );
  expect(screen.getByText("javascript:alert(1)")).toBeInTheDocument();
  expect(document.querySelector("img, script")).toBeNull();
});

test.each([
  ["no_evidence", "Sem evidência suficiente nas fontes."],
  [
    "index_unavailable",
    "Índice indisponível. Tente consultar novamente mais tarde.",
  ],
])("apresenta %s", (status, label) => {
  render(<ChatReply reply={{ ...textReply, answer_status: status }} />);
  expect(screen.getByText(label)).toBeInTheDocument();
});

test("esclarecimento preenche uma resposta que segue pelo chat", async () => {
  const user = await start();
  api.sendMessage.mockResolvedValueOnce(
    response({
      type: "clarification",
      question: "Qual problema?",
      options: ["Atolamento de papel"],
    }),
  );
  await send(user, "impressora");
  await user.click(
    await screen.findByRole("button", { name: "Atolamento de papel" }),
  );
  expect(screen.getByRole("textbox")).toHaveValue("Atolamento de papel");
  await user.click(screen.getByRole("button", { name: "Enviar" }));
  expect(api.sendMessage).toHaveBeenLastCalledWith(
    "fixture-a",
    "Atolamento de papel",
  );
});

test.each([
  ["Sim!", "yes", "succeeded", "Ação concluída"],
  ["não", "no", "cancelled", "Ação cancelada"],
])(
  "decisão textual %s usa somente decisions e a versão exibida",
  async (text, decision, status, label) => {
    const user = await start();
    await openPreview(user);
    expect(
      screen.getByRole("region", { name: "Ação pendente" }).querySelector("pre")
        .textContent,
    ).toBe(action.preview_text);
    api.sendDecision.mockResolvedValueOnce(response({ ...result, status }));
    await send(user, text);
    expect(api.sendDecision).toHaveBeenCalledWith("fixture-a", {
      action_id: action.action_id,
      version: 1,
      decision,
    });
    expect(api.sendMessage).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByRole("region", { name: label }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Ação pendente" }),
    ).not.toBeInTheDocument();
  },
);

test.each([
  "talvez",
  "sim?",
  "sim, mas altere a prioridade",
  "não cancelar",
  "editar:",
])("mensagem ambígua %s preserva prévia sem decidir", async (text) => {
  const user = await start();
  await openPreview(user);
  await send(user, text);
  expect(api.sendDecision).not.toHaveBeenCalled();
  expect(api.sendMessage).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("region", { name: "Ação pendente" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("textbox")).toHaveValue(text);
});

test("editar gera nova prévia e exige confirmação com a versão nova", async () => {
  const user = await start();
  await openPreview(user);
  const edited = {
    ...action,
    version: 2,
    preview_text: "Prévia corrigida\nExige confirmação.",
  };
  api.sendDecision.mockResolvedValueOnce(
    response({ type: "preview", action: edited }),
  );
  await send(user, "editar: descrição corrigida");
  expect(api.sendDecision).toHaveBeenLastCalledWith("fixture-a", {
    action_id: action.action_id,
    version: 1,
    decision: "edit",
    text: "descrição corrigida",
  });
  expect(
    screen.getByRole("region", { name: "Ação pendente" }).querySelector("pre")
      .textContent,
  ).toBe(edited.preview_text);
  expect(api.sendDecision).toHaveBeenCalledTimes(1);
  await send(user, "sim");
  expect(api.sendDecision).toHaveBeenLastCalledWith("fixture-a", {
    action_id: action.action_id,
    version: 2,
    decision: "yes",
  });
});

test("versão vencida recarrega prévia atual e pede confirmação nova", async () => {
  const user = await start();
  await openPreview(user);
  api.sendDecision.mockRejectedValueOnce(
    new api.ApiError(409, {
      code: "stale_action_version",
      message: "A ação mudou.",
    }),
  );
  api.getSession.mockResolvedValueOnce({
    ...session,
    pending_action: {
      ...action,
      version: 2,
      preview_text: "Versão mais recente",
    },
  });
  await send(user, "sim");
  expect(await screen.findByText(/Prévia atual carregada/)).toBeInTheDocument();
  expect(screen.getByRole("textbox")).toHaveValue("");
  expect(api.sendDecision).toHaveBeenCalledTimes(1);
  await send(user, "sim");
  expect(api.sendDecision.mock.calls[1][1].version).toBe(2);
});

test("falha de rede na mensagem preserva rascunho e consulta estado sem reenvio", async () => {
  const user = await start();
  api.sendMessage.mockRejectedValueOnce(
    new api.ApiError(0, { code: "network_error", message: "Sem conexão." }),
  );
  await send(user, "texto para corrigir");
  await waitFor(() => expect(api.getSession).toHaveBeenCalledWith("fixture-a"));
  expect(screen.getByRole("textbox")).toHaveValue("texto para corrigir");
  expect(api.sendMessage).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("alert")).toHaveTextContent("Sem conexão");
});

test("perda da resposta da decisão recupera resultado sem repetir escrita", async () => {
  const user = await start();
  await openPreview(user);
  const reading = deferred();
  api.sendDecision.mockRejectedValueOnce(
    new api.ApiError(0, { code: "network_error", message: "Sem conexão." }),
  );
  api.getSession.mockReturnValueOnce(reading.promise);
  await send(user, "sim");
  expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
  expect(screen.getByText(/Consultando o estado/)).toBeInTheDocument();
  await act(async () =>
    reading.resolve({
      ...session,
      last_write_result: { ...result, status: "partial" },
    }),
  );
  expect(
    screen.getByRole("region", { name: "Conclusão parcial" }),
  ).toHaveTextContent("Chamado #9001");
  expect(api.sendDecision).toHaveBeenCalledTimes(1);
  expect(
    screen.queryByRole("region", { name: "Ação pendente" }),
  ).not.toBeInTheDocument();
});

test("se consulta após falha também falha, bloqueia envio até recuperar pendência", async () => {
  const user = await start();
  await openPreview(user);
  const offline = new api.ApiError(0, {
    code: "network_error",
    message: "Sem conexão.",
  });
  api.sendDecision.mockRejectedValueOnce(offline);
  api.getSession.mockRejectedValueOnce(offline);
  await send(user, "sim");
  const consult = await screen.findByRole("button", {
    name: "Consultar estado",
  });
  await waitFor(() => expect(consult).toBeEnabled());
  expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
  api.getSession.mockResolvedValueOnce({ ...session, pending_action: action });
  await user.click(consult);
  await waitFor(() => expect(screen.getByRole("textbox")).toBeEnabled());
  expect(api.sendDecision).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("region", { name: "Ação pendente" }),
  ).toBeInTheDocument();
});

test("recupera sessão e pendência ao recarregar, sem inventar histórico", async () => {
  sessionStorage.setItem("squad13.thread", "fixture-a");
  api.getSession.mockResolvedValueOnce({ ...session, pending_action: action });
  render(<App />);
  expect(
    await screen.findByRole("region", { name: "Ação pendente" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/O histórico anterior não está disponível/),
  ).toBeInTheDocument();
  expect(api.createSession).not.toHaveBeenCalled();
  expect(
    within(screen.getByRole("log")).queryAllByRole("article"),
  ).toHaveLength(0);
});

test("resposta perdida de edição recupera nova versão e não repete a edição", async () => {
  const user = await start();
  await openPreview(user);
  api.sendDecision.mockRejectedValueOnce(
    new api.ApiError(0, { code: "network_error", message: "Sem conexão." }),
  );
  api.getSession.mockResolvedValueOnce({
    ...session,
    pending_action: {
      ...action,
      version: 2,
      preview_text: "Edição já aplicada",
    },
  });
  await send(user, "editar: descrição corrigida");
  await waitFor(() => expect(screen.getByRole("textbox")).toBeEnabled());
  expect(screen.getByRole("textbox")).toHaveValue("");
  expect(
    screen.getByRole("region", { name: "Ação pendente" }),
  ).toHaveTextContent("Edição já aplicada");
  expect(api.sendDecision).toHaveBeenCalledTimes(1);
});

test("sem resultado disponível após falha não inventa sucesso nem repete decisão", async () => {
  const user = await start();
  await openPreview(user);
  api.sendDecision.mockRejectedValueOnce(
    new api.ApiError(0, { code: "network_error", message: "Sem conexão." }),
  );
  api.getSession.mockResolvedValueOnce({
    ...session,
    last_write_result: undefined,
  });
  await send(user, "sim");
  expect(
    await screen.findByText(/O servidor não informou um resultado de escrita/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "Ação concluída" }),
  ).not.toBeInTheDocument();
  expect(api.sendDecision).toHaveBeenCalledTimes(1);
});

test("nova consulta atualiza o resultado da mesma ação sem duplicar mensagens", async () => {
  const user = await start();
  await openPreview(user);
  api.sendDecision.mockResolvedValueOnce(
    response({ ...result, status: "uncertain", ticket_id: null }),
  );
  await send(user, "sim");
  expect(
    screen.getByRole("region", { name: "Resultado incerto" }),
  ).toBeInTheDocument();
  api.getSession.mockResolvedValueOnce({
    ...session,
    last_write_result: { ...result, status: "partial" },
  });
  await user.click(screen.getByRole("button", { name: "Atualizar sessão" }));
  expect(
    await screen.findByRole("region", { name: "Conclusão parcial" }),
  ).toHaveTextContent("Chamado #9001");
  expect(
    screen.queryByRole("region", { name: "Resultado incerto" }),
  ).not.toBeInTheDocument();
  expect(api.sendDecision).toHaveBeenCalledTimes(1);
});

test("troca recusada mantém conversa e pendência recuperável", async () => {
  const user = await start();
  await openPreview(user);
  api.switchSession.mockRejectedValueOnce(
    new api.ApiError(503, { code: "backend_unavailable" }),
  );
  api.getSession.mockResolvedValueOnce({ ...session, pending_action: action });
  await user.click(screen.getByRole("button", { name: "Trocar personagem" }));
  await user.click(
    await screen.findByRole("button", { name: "Técnico Demo B" }),
  );
  await waitFor(() => expect(screen.getByRole("textbox")).toBeEnabled());
  expect(
    screen.getByRole("region", { name: "Técnico ativo" }),
  ).toHaveTextContent("Técnico Demo A");
  expect(
    screen.getByRole("region", { name: "Ação pendente" }),
  ).toBeInTheDocument();
});

test("falha de retomada não permite abandonar contexto conhecido sem invalidá-lo", async () => {
  sessionStorage.setItem("squad13.thread", "fixture-a");
  api.getSession.mockRejectedValueOnce(
    new api.ApiError(0, { code: "network_error", message: "Sem conexão." }),
  );
  const user = userEvent.setup();
  render(<App />);
  await user.click(
    await screen.findByRole("button", { name: "Técnico Demo B" }),
  );
  expect(api.switchSession).toHaveBeenCalledWith("fixture-a", 102);
  expect(api.createSession).not.toHaveBeenCalled();
});

test.each([
  [422, "invalid_request", "Requisição inválida"],
  [503, "backend_unavailable", "temporariamente indisponível"],
  [404, "session_not_found", "expirou"],
])("trata erro %s sem apagar rascunho", async (status, code, label) => {
  const user = await start();
  api.sendMessage.mockRejectedValueOnce(new api.ApiError(status, { code }));
  await send(user, "texto a preservar");
  expect(await screen.findByRole("alert")).toHaveTextContent(label);
  expect(screen.getByRole("textbox")).toHaveValue("texto a preservar");
  if (status === 404)
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
});

test.each([
  ["partial", "Conclusão parcial"],
  ["uncertain", "Resultado incerto"],
  ["cancelled", "Ação cancelada"],
])("apresenta %s preservando ID disponível", (status, label) => {
  render(<ChatReply reply={{ ...result, status }} />);
  expect(screen.getByRole("region", { name: label })).toHaveTextContent(
    "Chamado #9001",
  );
});
