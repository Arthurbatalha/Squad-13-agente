"""RAG-01: agente LangChain com checkpointer e geração RAG-04.

A recuperação autorizada e a política de respostas continuam fora do grafo
(``src.rag.retrieval`` e ``src.rag.evidence_policy``). Este módulo é a única
memória conversacional: ``create_agent`` persiste as mensagens no
``SqliteSaver`` da EST-01. O adaptador Gemini da RAG-04 é chamado como modelo
do agente, devolvendo o ``prompt_evidence`` efetivamente enviado.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import logging
from threading import Lock
from typing import Any, Iterable, Mapping
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.model.gemini_adapter import (
    GeminiAdapter,
    GenerationResult,
    ModelUnavailable,
)

logger = logging.getLogger(__name__)

_EVIDENCE: ContextVar[tuple[dict[str, Any], ...]] = ContextVar(
    "rag01_prompt_evidence", default=()
)


@dataclass(frozen=True)
class AgentGeneration:
    """Resultado de uma geração feita pelo agente e já persistida."""

    result: GenerationResult
    user_message_id: str
    assistant_message_id: str


def _history_from_messages(
    messages: Iterable[Any], *, limit: int | None = None
) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, AIMessage):
            role = "assistant"
        else:
            continue
        content = str(message.content)
        if content.strip():
            history.append({"role": role, "content": content})
    if limit is not None and limit >= 0:
        history = history[-limit:] if limit else []
    return history


class _AdapterChatModel(BaseChatModel):
    """Expõe o adaptador RAG-04 como modelo de chat do ``create_agent``.

    O agente fornece o histórico persistido e a mensagem atual; o backend
    injeta no contexto apenas as evidências já autorizadas e selecionadas.
    """

    graph: Any
    model_config = {"arbitrary_types_allowed": True}

    @property
    def _llm_type(self) -> str:
        return "rag04-gemini-adapter"

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        current = next(
            (index for index in range(len(messages) - 1, -1, -1)
             if isinstance(messages[index], HumanMessage)),
            None,
        )
        if current is None:
            raise ModelUnavailable("O agente não recebeu uma pergunta do usuário.")
        question = str(messages[current].content)
        history = _history_from_messages(
            messages[:current], limit=self.graph.max_history_messages
        )
        result = self.graph._adapter().generate(
            question, list(_EVIDENCE.get()), history
        )
        self.graph._last_generation.set(result)
        message = AIMessage(
            content=result.text,
            additional_kwargs={
                "prompt_evidence": [dict(item) for item in result.prompt_evidence],
                "model": result.model,
                "input_tokens_estimated": result.input_tokens_estimated,
            },
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


class RAGGenerationGraph:
    """Grafo único de geração com memória no checkpointer.

    ``invoke`` mantém o contrato antigo da RAG-04 para chamadas diretas. A API
    real usa ``generate``/``append_turn``/``replace_assistant``, que operam
    sobre a mesma thread do ``SqliteSaver``.
    """

    def __init__(
        self,
        adapter=None,
        *,
        checkpointer=None,
        max_history_messages: int = 20,
        recursion_limit: int = 8,
    ):
        if type(max_history_messages) is not int or max_history_messages < 0:
            raise ValueError("max_history_messages deve ser inteiro não negativo.")
        if type(recursion_limit) is not int or recursion_limit <= 0:
            raise ValueError("recursion_limit deve ser inteiro positivo.")
        self.adapter = adapter
        self.checkpointer = checkpointer
        self.max_history_messages = max_history_messages
        self.recursion_limit = recursion_limit
        self._agent = None
        self._agent_lock = Lock()
        self._last_generation: ContextVar[GenerationResult | None] = ContextVar(
            "rag01_last_generation", default=None
        )

    def _adapter(self):
        if self.adapter is None:
            self.adapter = GeminiAdapter.from_env()
        return self.adapter

    @property
    def agent(self):
        if self._agent is None:
            with self._agent_lock:
                if self._agent is None:
                    self._agent = create_agent(
                        _AdapterChatModel(graph=self),
                        tools=[],
                        checkpointer=self.checkpointer,
                    )
        return self._agent

    def _config(self, thread_id: str) -> dict[str, Any]:
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise ValueError("thread_id deve ser texto não vazio.")
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.recursion_limit,
        }

    def _state_messages(self, thread_id: str) -> list[Any]:
        try:
            state = self.agent.get_state(self._config(thread_id))
        except Exception:
            return []
        return list((state.values or {}).get("messages", []))

    def history(self, thread_id: str) -> list[dict[str, str]]:
        """Histórico canônico completo da conversa, lido do checkpoint.

        O limite de ``max_history_messages`` vale para o prompt enviado ao
        modelo (aplicado no adaptador), não para a auditoria/retomada.
        """
        return _history_from_messages(self._state_messages(thread_id))

    def generate(
        self,
        question: str,
        evidence: Iterable[Mapping[str, Any]],
        *,
        thread_id: str,
        user_message_id: str | None = None,
    ) -> AgentGeneration:
        """Executa o agente uma vez e devolve a geração efetivamente validável."""
        user_id = user_message_id or f"user-{uuid4().hex}"
        token = _EVIDENCE.set(tuple(dict(item) for item in evidence))
        self._last_generation.set(None)
        try:
            output = self.agent.invoke(
                {"messages": [HumanMessage(content=question, id=user_id)]},
                config=self._config(thread_id),
            )
        except BaseException:
            self._rollback(thread_id, user_id)
            raise
        finally:
            _EVIDENCE.reset(token)
        result = self._last_generation.get()
        self._last_generation.set(None)
        assistant = next(
            (message for message in reversed(output.get("messages", []))
             if isinstance(message, AIMessage)),
            None,
        )
        if result is None and assistant is not None:
            metadata = assistant.additional_kwargs or {}
            raw_evidence = metadata.get("prompt_evidence")
            if isinstance(raw_evidence, list):
                result = GenerationResult(
                    text=str(assistant.content),
                    model=str(metadata.get("model", "unknown")),
                    input_tokens_estimated=int(
                        metadata.get("input_tokens_estimated", 0)
                    ),
                    prompt_evidence=tuple(
                        dict(item) for item in raw_evidence
                        if isinstance(item, Mapping)
                    ),
                )
        if result is None or assistant is None:
            raise ModelUnavailable("O agente não produziu uma resposta utilizável.")
        return AgentGeneration(result, user_id, str(assistant.id))

    def _rollback(self, thread_id: str, user_message_id: str) -> None:
        """Remove a pergunta se a geração falhar, evitando turno fantasma."""
        try:
            messages = self._state_messages(thread_id)
            if any(getattr(message, "id", None) == user_message_id
                   for message in messages):
                self.agent.update_state(
                    self._config(thread_id),
                    {"messages": [RemoveMessage(id=user_message_id)]},
                )
        except Exception:
            logger.warning("Não foi possível remover o turno incompleto.")

    def append_turn(
        self,
        thread_id: str,
        user_text: str,
        assistant_text: str,
        *,
        assistant_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Persiste um turno que não passou pelo modelo (esclarecimento/recusa)."""
        self.agent.update_state(
            self._config(thread_id),
            {"messages": [
                HumanMessage(content=user_text, id=f"user-{uuid4().hex}"),
                AIMessage(
                    content=assistant_text,
                    id=f"assistant-{uuid4().hex}",
                    additional_kwargs=dict(assistant_metadata or {}),
                ),
            ]},
        )

    def replace_assistant(
        self,
        thread_id: str,
        assistant_message_id: str,
        text: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Substitui a resposta do modelo por uma saída aprovada/política."""
        self.agent.update_state(
            self._config(thread_id),
            {"messages": [
                RemoveMessage(id=assistant_message_id),
                AIMessage(
                    content=text,
                    id=f"assistant-{uuid4().hex}",
                    additional_kwargs=dict(metadata or {}),
                ),
            ]},
        )

    def discard_thread(self, thread_id: str) -> None:
        """Invalida também o checkpoint ao trocar de personagem."""
        try:
            delete = getattr(self.checkpointer, "delete_thread", None)
            if callable(delete):
                delete(thread_id)
        except Exception:
            logger.warning("Não foi possível descartar o checkpoint anterior.")

    def invoke(self, state, config=None):
        """Contrato legado da RAG-04 e execução persistida quando há thread."""
        if not isinstance(state, dict):
            raise TypeError("state deve ser um dicionário.")
        question = state.get("question") or state.get("input")
        evidence = state.get("evidence", [])
        configurable = (config or {}).get("configurable", {})
        thread_id = configurable.get("thread_id")
        if thread_id:
            generation = self.generate(
                question, evidence, thread_id=thread_id,
                user_message_id=state.get("user_message_id"),
            )
            return {
                **state,
                "answer": generation.result.text,
                "prompt_evidence": generation.result.prompt_evidence,
                "model": generation.result.model,
                "input_tokens_estimated": (
                    generation.result.input_tokens_estimated
                ),
                "user_message_id": generation.user_message_id,
                "assistant_message_id": generation.assistant_message_id,
            }
        result = self._adapter().generate(
            question, evidence, state.get("history")
        )
        return {
            **state,
            "answer": result.text,
            "prompt_evidence": result.prompt_evidence,
            "model": result.model,
            "input_tokens_estimated": result.input_tokens_estimated,
        }


def build_graph(
    checkpointer=None,
    *,
    model_adapter=None,
    max_history_messages: int | None = None,
    recursion_limit: int | None = None,
):
    """Compõe o agente sem exigir chave Gemini no startup.

    O adaptador real é criado sob demanda na primeira geração; a injeção de
    ``model_adapter`` mantém os testes determinísticos.
    """
    if max_history_messages is None or recursion_limit is None:
        try:
            from src.config import load_settings

            settings = load_settings()
            max_history_messages = (
                settings.rag_max_history_messages
                if max_history_messages is None else max_history_messages
            )
            recursion_limit = (
                settings.rag_agent_recursion_limit
                if recursion_limit is None else recursion_limit
            )
        except Exception:
            max_history_messages = (
                20 if max_history_messages is None else max_history_messages
            )
            recursion_limit = 8 if recursion_limit is None else recursion_limit
    return RAGGenerationGraph(
        model_adapter,
        checkpointer=checkpointer,
        max_history_messages=max_history_messages,
        recursion_limit=recursion_limit,
    )
