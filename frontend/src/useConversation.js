import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  createSession,
  getSession,
  sendDecision,
  sendMessage,
  switchSession,
} from "./api.js";

const STORAGE_KEY = "squad13.thread";

// Apenas frases completas. Perguntas, negações compostas e "talvez" não decidem.
export function parseDecision(text) {
  const normalized = text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toLowerCase();
  if (/^(sim|confirmo|confirmar)[.!]?$/.test(normalized))
    return { decision: "yes" };
  if (/^(nao|cancelar|cancelo)[.!]?$/.test(normalized))
    return { decision: "no" };
  const edit = text.trim().match(/^editar\s*:\s*([\s\S]+)$/i);
  return edit?.[1].trim() ? { decision: "edit", text: edit[1] } : null;
}

function rememberedThread() {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}
function remember(thread) {
  try {
    if (thread) sessionStorage.setItem(STORAGE_KEY, thread);
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* A conversa funciona sem armazenamento até recarregar a página. */
  }
}
function errorText(error) {
  if (["session_not_found", "session_expired"].includes(error.code))
    return "Esta sessão expirou ou não está disponível. Escolha um técnico para iniciar outro contexto.";
  if (error.code === "invalid_request")
    return "Requisição inválida. Confira e corrija o texto antes de enviar.";
  if (error.status === 503)
    return "O serviço está temporariamente indisponível. Seu texto foi preservado.";
  return error instanceof ApiError
    ? error.message
    : "Não foi possível concluir a solicitação. Seu texto foi preservado.";
}

export function useConversation() {
  const [session, setSession] = useState(null);
  const [items, setItems] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [needsRecovery, setNeedsRecovery] = useState(false);
  const [expired, setExpired] = useState(false);
  const current = useRef(null);
  const generation = useRef(0);
  const sending = useRef(false);
  const starting = useRef(false);

  function adopt(info) {
    current.current = info;
    setSession(info);
    remember(info.thread_id);
  }
  function appendReply(reply) {
    setItems((previous) => {
      if (reply.type === "write_result") {
        const existing = previous.findIndex(
          (item) =>
            item.reply?.type === "write_result" &&
            item.reply.action_id === reply.action_id,
        );
        if (existing >= 0)
          return previous.map((item, index) =>
            index === existing ? { ...item, reply } : item,
          );
      }
      return [...previous, { from: "assistant", reply }];
    });
  }
  function markExpired(cause) {
    if (["session_not_found", "session_expired"].includes(cause.code)) {
      setExpired(true);
      remember(null);
    }
    setError(errorText(cause));
  }
  async function loadSnapshot(epoch, thread, reason, actionId) {
    const info = await getSession(thread);
    if (generation.current !== epoch) return;
    if (info.thread_id !== thread)
      throw new ApiError(502, {
        code: "invalid_response",
        message: "Sessão divergente na resposta.",
      });
    adopt(info);
    setNeedsRecovery(false);
    setExpired(false);
    if (
      info.last_write_result &&
      (!actionId || info.last_write_result.action_id === actionId)
    )
      appendReply(info.last_write_result);
    if (reason === "restore")
      setNotice(
        "Sessão recuperada. O histórico anterior não está disponível; mostramos a pendência e o último resultado disponíveis.",
      );
    else if (info.pending_action)
      setNotice(
        "Prévia atual carregada. Confira os dados e digite uma nova decisão; nenhuma tentativa foi repetida automaticamente.",
      );
    else
      setNotice(
        info.last_write_result
          ? "Estado consultado. Confira o resultado recuperado antes de iniciar outra ação."
          : "Não há prévia pendente. O servidor não informou um resultado de escrita; verifique antes de repetir a operação.",
      );
    return info;
  }

  useEffect(() => {
    const thread = rememberedThread();
    const epoch = ++generation.current;
    if (!thread) setRestoring(false);
    else
      loadSnapshot(epoch, thread, "restore")
        .catch((cause) => {
          if (generation.current !== epoch) return;
          markExpired(cause);
          if (!["session_not_found", "session_expired"].includes(cause.code))
            setNeedsRecovery(true);
        })
        .finally(() => {
          if (generation.current === epoch) setRestoring(false);
        });
    return () => {
      generation.current++;
    };
  }, []);

  async function start(characterId) {
    if (starting.current) return false;
    starting.current = true;
    const previousThread = current.current?.thread_id ?? rememberedThread();
    const epoch = ++generation.current;
    setSwitching(true);
    setBusy(false);
    sending.current = false;
    setError("");
    try {
      const info =
        previousThread && !expired
          ? await switchSession(previousThread, characterId)
          : await createSession(characterId);
      if (generation.current !== epoch) return false;
      adopt(info);
      setItems([]);
      setDraft("");
      setExpired(false);
      setNeedsRecovery(false);
      setNotice(
        "Novo contexto iniciado. A conversa e a pendência anteriores não serão utilizadas.",
      );
      return true;
    } catch (cause) {
      if (generation.current !== epoch) return false;
      markExpired(cause);
      if (
        previousThread &&
        !["session_not_found", "session_expired"].includes(cause.code)
      ) {
        setNeedsRecovery(true);
        try {
          await loadSnapshot(epoch, previousThread, "switch");
        } catch (recoveryError) {
          if (generation.current === epoch) markExpired(recoveryError);
        }
      }
      return false;
    } finally {
      if (generation.current === epoch) {
        setSwitching(false);
        starting.current = false;
      }
    }
  }

  async function recover() {
    if (sending.current || starting.current) return;
    const thread = current.current?.thread_id ?? rememberedThread();
    if (!thread) return;
    const epoch = generation.current;
    sending.current = true;
    setBusy(true);
    setError("");
    try {
      await loadSnapshot(epoch, thread, "manual");
    } catch (cause) {
      if (generation.current === epoch) {
        setNeedsRecovery(true);
        markExpired(cause);
      }
    } finally {
      if (generation.current === epoch) {
        sending.current = false;
        setBusy(false);
      }
    }
  }

  async function submit() {
    const info = current.current;
    if (
      !info ||
      !draft.trim() ||
      sending.current ||
      starting.current ||
      needsRecovery ||
      expired
    )
      return;
    const decision = parseDecision(draft);
    if (info.pending_action && !decision) {
      setError(
        "A prévia continua pendente. Digite “sim”, “não” ou “editar: texto corrigido”. Mensagens ambíguas não confirmam ações.",
      );
      return;
    }
    if (!info.pending_action && decision) {
      setError(
        "Não há prévia exibida para esta decisão. Atualize a sessão e confira a ação antes de decidir.",
      );
      return;
    }
    sending.current = true;
    const epoch = generation.current;
    const message = draft;
    const attempt = { from: "user", text: message, status: "sending" };
    setItems((previous) => [...previous, attempt]);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = info.pending_action
        ? await sendDecision(info.thread_id, {
            ...decision,
            action_id: info.pending_action.action_id,
            version: info.pending_action.version,
          })
        : await sendMessage(info.thread_id, message);
      if (generation.current !== epoch) return;
      if (response.thread_id !== info.thread_id || !response.reply)
        throw new ApiError(502, {
          code: "invalid_response",
          message: "Resposta da conversa incompleta.",
        });
      const reply = response.reply;
      adopt({
        ...info,
        pending_action:
          reply.type === "preview"
            ? reply.action
            : reply.type === "write_result"
              ? null
              : info.pending_action,
        last_write_result:
          reply.type === "write_result" ? reply : info.last_write_result,
      });
      setItems((previous) =>
        previous.map((item) =>
          item === attempt ? { ...item, status: "sent" } : item,
        ),
      );
      appendReply(reply);
      setDraft("");
    } catch (cause) {
      if (generation.current !== epoch) return;
      setItems((previous) =>
        previous.map((item) =>
          item === attempt ? { ...item, status: "failed" } : item,
        ),
      );
      markExpired(cause);
      if (
        ["stale_action_version", "no_pending_action"].includes(cause.code) ||
        cause.status === 0 ||
        cause.status >= 500
      ) {
        // Uma confirmação antiga nunca fica pronta para enviar sobre uma prévia nova.
        if (decision && decision.decision !== "edit") setDraft("");
        setNeedsRecovery(true);
        setNotice(
          "Consultando o estado no servidor antes de permitir outra tentativa…",
        );
        try {
          const fresh = await loadSnapshot(
            epoch,
            info.thread_id,
            "failure",
            info.pending_action?.action_id,
          );
          if (
            generation.current === epoch &&
            decision?.decision === "edit" &&
            fresh &&
            (fresh.pending_action?.version !== info.pending_action.version ||
              fresh.pending_action?.action_id !== info.pending_action.action_id)
          )
            setDraft("");
        } catch (recoveryError) {
          if (generation.current === epoch) markExpired(recoveryError);
        }
      }
    } finally {
      if (generation.current === epoch) {
        sending.current = false;
        setBusy(false);
      }
    }
  }

  return {
    session,
    items,
    draft,
    setDraft,
    busy,
    switching,
    restoring,
    error,
    notice,
    needsRecovery,
    expired,
    start,
    recover,
    submit,
  };
}
