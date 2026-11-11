// Respostas controladas e inteiramente sintéticas para testar estados da UI-02.
export const characters = [
  { id: 101, name: "Técnico Demo A" },
  { id: 102, name: "Técnico Demo B" },
];
export const session = {
  thread_id: "fixture-a",
  role: "staff",
  character: characters[0],
  adapter: "mock",
  pending_action: null,
  last_write_result: null,
};
export const action = {
  action_id: "fixture-action",
  version: 1,
  operation: "open_ticket",
  status: "pending",
  staff_user_id: 101,
  payload: {
    title: "Fixture",
    description: "Texto sintético",
    category_id: 1,
    priority: 3,
    requester_id: 201,
  },
  preview_text:
    "[simulado] Abrir chamado\n  Descrição: Texto sintético\nConfirme os dados.\n",
};
export const result = {
  type: "write_result",
  action_id: action.action_id,
  status: "succeeded",
  ticket_id: 9001,
  message: "[simulado] Ação concluída.",
};
export const textReply = {
  type: "text",
  text: "Orientação sintética.\nOutro passo.",
  answer_status: "answered",
  sources: [
    {
      source_type: "article",
      source_id: "17",
      title: "Artigo sintético",
      reference: "GLPI KB #17",
      chunk_id: "17:0",
      excerpt: "Passo 1.\nPasso 2.",
    },
    {
      source_type: "case",
      source_id: "91",
      title: "Caso sintético",
      reference: "https://example.com/tickets/91",
      excerpt: "Solução sintética.",
    },
  ],
};
export const response = (reply, thread_id = session.thread_id) => ({
  thread_id,
  reply,
});
export function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
