"""RAG-01: backend real (React → FastAPI → agente → índice → Gemini).

A identidade vem do vínculo durável thread/personagem/token emitido pelo
servidor. O token é entregue apenas em cookie HttpOnly; o ``thread_id``
sozinho não autoriza leitura, mensagem ou troca. O histórico canônico fica no
checkpoint do agente; a recuperação usa a geração publicada da RAG-03 e a
política/validação da RAG-05.

Operações de escrita do GLPI permanecem desabilitadas nesta etapa.
"""

from __future__ import annotations

from hashlib import sha256
import hmac
import logging
import os
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from src.api.backend import ChatBackendError
from src.api.schemas import (
    ChatReply,
    DecisionRequest,
    SessionInfo,
    Source,
    StaffCharacter,
    TextReply,
)
from src.authorization.policies import AccessDenied, Principal
from src.authorization.service import AuthorizationService
from src.model.gemini_adapter import (
    ModelAdapterError,
    ModelNotConfigured,
    ModelRateLimited,
    ModelTimeout,
    ModelUnavailable,
    PromptBudgetExceeded,
)
from src.rag.corpus import CorpusUnavailable
from src.rag.embeddings import (
    EmbeddingService,
    EmbeddingUnavailable,
    IncompatibleConfig,
)
from src.rag.evidence_policy import (
    INCOMPLETE_NOTE,
    KIND_ANSWERED,
    KIND_CLARIFICATION,
    PolicyOutcome,
    detect_ambiguity,
    effective_question,
    outcome_without_answer,
    respond,
)
from src.rag.local_index import IndexCorrupt
from src.rag.retrieval import RetrievalConfig, build_published_retrieval
from src.session_store import (
    create_ui_session,
    get_ui_session_by_token_hash,
    switch_ui_session,
)
from src.sessions import (
    DirectoryUnavailable,
    InvalidCharacter,
    SessionService,
    SessionUnavailable,
)

logger = logging.getLogger(__name__)

SESSION_COOKIE = "rag01_session"

# Somente a coleção de artigos é publicada pela ING-05. Ferramentas de casos e
# de escrita ficam explicitamente desabilitadas até as áreas seguintes.
DISABLED_TOOLS = frozenset({
    "get_ticket",
    "list_tickets",
    "ticket_statistics",
    "similar_cases",
    "ranking_global",
})

# Falhas esperadas da recuperação: a política RAG-05 transforma em
# `index_unavailable`; nunca em "não encontrei".
_INDEX_ERRORS = (
    EmbeddingUnavailable,
    CorpusUnavailable,
    IndexCorrupt,
    IncompatibleConfig,
    OSError,
    ValueError,
    KeyError,
    TypeError,
)


def _token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _display_name(login: str) -> str:
    parts = [part for part in login.replace("_", ".").split(".") if part]
    return " ".join(part[:1].upper() + part[1:] for part in parts) or login


def _model_error(exc: BaseException) -> ChatBackendError:
    """Converte falhas do provedor em erro estável e sanitizado."""
    if isinstance(exc, ModelNotConfigured):
        return ChatBackendError(
            "model_not_configured",
            "O modelo de linguagem não está configurado no servidor.",
            status_code=503,
            retryable=False,
        )
    if isinstance(exc, ModelTimeout):
        return ChatBackendError(
            "model_timeout",
            "O modelo de linguagem excedeu o tempo limite. Tente novamente.",
            status_code=503,
            retryable=True,
        )
    if isinstance(exc, ModelRateLimited):
        return ChatBackendError(
            "model_rate_limited",
            "O limite ou a cota do modelo foi atingido. Tente novamente mais tarde.",
            status_code=503,
            retryable=True,
        )
    if isinstance(exc, PromptBudgetExceeded):
        return ChatBackendError(
            "prompt_budget_exceeded",
            "O contexto da pergunta excede o limite configurado.",
            status_code=503,
            retryable=False,
        )
    return ChatBackendError(
        "model_unavailable",
        "O modelo de linguagem está indisponível no momento.",
        status_code=503,
        retryable=True,
    )


class RealChatBackend:
    """Contrato da UI-01 sobre os componentes da Alternativa C."""

    adapter = "real"

    def __init__(
        self,
        *,
        graph,
        state_file: str | Path,
        session_service: SessionService | None = None,
        session_service_factory: Callable[[], SessionService] | None = None,
        encoder: EmbeddingService | None = None,
        authorization: AuthorizationService | None = None,
        retriever=None,
        retrieval_config: RetrievalConfig | None = None,
        response_mode: str = "gemini",
    ):
        if response_mode == "auto":
            response_mode = "gemini" if os.getenv("GEMINI_API_KEY", "").strip() else "excerpts"
        if response_mode not in {"gemini", "excerpts"}:
            raise ValueError("CHAT_RESPONSE_MODE deve ser auto, gemini ou excerpts.")
        self.response_mode = response_mode
        self.graph = graph
        self.state_file = Path(state_file)
        self.session_service = session_service
        self.session_service_factory = session_service_factory
        self.encoder = encoder
        self.authorization = authorization
        self.retriever = retriever
        self.retrieval_config = retrieval_config or RetrievalConfig()
        self._started = False
        self._startup_error: str | None = None
        self._startup_lock = RLock()
        self._locks: dict[str, RLock] = {}
        self._locks_lock = RLock()

    # ----- ciclo de vida -------------------------------------------------
    @property
    def available(self) -> bool:
        return self._startup_error is None

    def startup(self) -> None:
        """Monta os serviços compartilhados uma vez por processo."""
        if self._started:
            return
        with self._startup_lock:
            if self._started:
                return
            try:
                if self.session_service is None:
                    factory = self.session_service_factory
                    if factory is None:
                        from src.main import build_session_service

                        factory = build_session_service
                    self.session_service = factory()
                if self.encoder is None:
                    self.encoder = EmbeddingService(local_files_only=True)
                if self.authorization is None:
                    # Artigos são a coleção publicada; nenhuma operação de
                    # escrita ou de casos é exposta nesta etapa.
                    self.authorization = AuthorizationService(
                        None, disabled_tools=DISABLED_TOOLS
                    )
                if self.retriever is None:
                    self.retriever = build_published_retrieval(
                        self.authorization,
                        encoder=self.encoder,
                        config=self.retrieval_config,
                    )
                self._started = True
                self._startup_error = None
            except Exception as exc:
                # Nunca expor caminho, URL, token ou mensagem do provedor.
                self._startup_error = type(exc).__name__
                logger.warning(
                    "Backend real indisponível no startup (%s).",
                    self._startup_error,
                )

    def close(self) -> None:
        """O checkpointer/conexão SQLite pertencem ao lifespan da API."""
        return None

    def _require_ready(self) -> None:
        if not self._started:
            self.startup()
        if self._startup_error is not None:
            raise ChatBackendError(
                "backend_unavailable",
                "O backend real não pôde ser inicializado.",
                status_code=503,
                retryable=True,
            )

    def _lock_for(self, thread_id: str) -> RLock:
        with self._locks_lock:
            return self._locks.setdefault(thread_id, RLock())

    def _forget_lock(self, thread_id: str) -> None:
        with self._locks_lock:
            self._locks.pop(thread_id, None)

    # ----- personagens e sessão -----------------------------------------
    def _characters(self) -> dict[int, StaffCharacter]:
        try:
            options = self.session_service.staff_options()
        except DirectoryUnavailable:
            raise ChatBackendError(
                "directory_unavailable",
                "O diretório de personagens do laboratório está indisponível.",
                status_code=503,
                retryable=True,
            ) from None
        return {
            user_id: StaffCharacter(id=user_id, name=_display_name(login))
            for user_id, login in options.items()
        }

    def list_characters(self) -> list[StaffCharacter]:
        self._require_ready()
        return sorted(self._characters().values(), key=lambda item: item.id)

    def _character(self, character_id: int) -> StaffCharacter:
        character = self._characters().get(character_id)
        if character is None:
            raise ChatBackendError(
                "character_not_found",
                "Personagem desconhecido.",
                status_code=404,
            )
        return character

    def _info(self, record: dict) -> SessionInfo:
        return SessionInfo(
            thread_id=record["thread_id"],
            role="staff",
            character=StaffCharacter(
                id=record["character_id"],
                name=record["character_name"] or f"Técnico {record['character_id']}",
            ),
            adapter=self.adapter,
            response_mode=self.response_mode,
            pending_action=None,
            last_write_result=None,
        )

    def _authorized(self, thread_id: str, session_token: str | None) -> dict:
        self._require_ready()
        if not isinstance(session_token, str) or not session_token:
            raise ChatBackendError(
                "session_not_found", "Sessão não encontrada.", status_code=404
            )
        record = get_ui_session_by_token_hash(
            _token_hash(session_token), db_path=self.state_file
        )
        if (
            record is None
            or not hmac.compare_digest(str(record["thread_id"]), str(thread_id))
            or record.get("role") != "staff"
        ):
            raise ChatBackendError(
                "session_not_found", "Sessão não encontrada.", status_code=404
            )
        try:
            self.session_service.restore(
                session_token,
                record["thread_id"],
                staff_user_id=record["character_id"],
            )
        except (SessionUnavailable, InvalidCharacter):
            raise ChatBackendError(
                "session_not_found", "Sessão não encontrada.", status_code=404
            ) from None
        return record

    def create_session_credential(
        self, character_id: int
    ) -> tuple[SessionInfo, str]:
        self._require_ready()
        character = self._character(character_id)
        try:
            token, view = self.session_service.start(staff_user_id=character.id)
        except InvalidCharacter:
            raise ChatBackendError(
                "character_not_found", "Personagem desconhecido.", status_code=404
            ) from None
        except DirectoryUnavailable:
            raise ChatBackendError(
                "directory_unavailable",
                "O diretório de personagens do laboratório está indisponível.",
                status_code=503,
                retryable=True,
            ) from None
        create_ui_session(
            view["thread_id"],
            character.id,
            character.name,
            _token_hash(token),
            db_path=self.state_file,
        )
        info = SessionInfo(
            thread_id=view["thread_id"],
            role="staff",
            character=character,
            adapter=self.adapter,
            response_mode=self.response_mode,
        )
        return info, token

    def create_session(self, character_id: int) -> SessionInfo:
        return self.create_session_credential(character_id)[0]

    def get_session(
        self, thread_id: str, *, session_token: str | None = None
    ) -> SessionInfo:
        with self._lock_for(thread_id):
            return self._info(self._authorized(thread_id, session_token))

    def switch_session_credential(
        self, thread_id: str, character_id: int, *, session_token: str | None = None
    ) -> tuple[SessionInfo, str]:
        with self._lock_for(thread_id):
            self._authorized(thread_id, session_token)
            character = self._character(character_id)
            try:
                new_token, view = self.session_service.switch(
                    session_token,
                    thread_id,
                    staff_user_id=character.id,
                )
            except InvalidCharacter:
                raise ChatBackendError(
                    "character_not_found", "Personagem desconhecido.", status_code=404
                ) from None
            except DirectoryUnavailable:
                raise ChatBackendError(
                    "directory_unavailable",
                    "O diretório de personagens do laboratório está indisponível.",
                    status_code=503,
                    retryable=True,
                ) from None
            except SessionUnavailable:
                raise ChatBackendError(
                    "session_not_found", "Sessão não encontrada.", status_code=404
                ) from None
            switch_ui_session(
                thread_id,
                view["thread_id"],
                character.id,
                character.name,
                _token_hash(new_token),
                db_path=self.state_file,
            )
            # A conversa anterior deixa de existir também no checkpoint. A
            # troca espera qualquer resposta em andamento desta thread.
            self.graph.discard_thread(thread_id)
            self._forget_lock(thread_id)
            info = SessionInfo(
                thread_id=view["thread_id"],
                role="staff",
                character=character,
                adapter=self.adapter,
                response_mode=self.response_mode,
            )
            return info, new_token

    def switch_session(
        self, thread_id: str, character_id: int, *, session_token: str | None = None
    ) -> SessionInfo:
        return self.switch_session_credential(
            thread_id, character_id, session_token=session_token
        )[0]

    # ----- conversa ------------------------------------------------------
    def handle_message(
        self, thread_id: str, text: str, *, session_token: str | None = None
    ) -> ChatReply:
        with self._lock_for(thread_id):
            self._authorized(thread_id, session_token)
            try:
                principal = Principal.from_session(
                    self.session_service, session_token, thread_id
                )
            except (AccessDenied, SessionUnavailable):
                raise ChatBackendError(
                    "session_not_found", "Sessão não encontrada.", status_code=404
                ) from None

            history = self.graph.history(thread_id)
            generation: dict[str, Any] = {}

            def retrieve(question: str):
                try:
                    return self.retriever.retrieve(question, principal)
                except PermissionError:
                    raise
                except _INDEX_ERRORS as exc:
                    logger.warning(
                        "Índice indisponível durante a consulta (%s).",
                        type(exc).__name__,
                    )
                    return {
                        "status": "index_unavailable",
                        "reason": "index_unavailable",
                        "chunks": [],
                        "incomplete": True,
                    }

            def generate(question: str, chunks: list):
                result = self.graph.generate(
                    question, chunks, thread_id=thread_id
                )
                generation["result"] = result.result
                generation["assistant_message_id"] = result.assistant_message_id
                return result.result

            def retrieve_excerpts():
                """Entrega apenas os trechos publicados; não sintetiza resposta factual."""
                ambiguity = detect_ambiguity(text, history)
                if ambiguity is not None:
                    return ambiguity
                question = effective_question(text, history)
                try:
                    result = retrieve(question)
                except PermissionError:
                    result = {"status": "no_evidence", "reason": "empty_authorized_scope", "chunks": []}
                early = outcome_without_answer(question, result)
                if early is not None:
                    return early
                sources = [
                    Source(
                        source_type=chunk["source_type"],
                        source_id=str(chunk["source_id"]),
                        title=chunk["title"],
                        reference=chunk["source_reference"],
                        chunk_id=chunk["chunk_id"],
                        excerpt=chunk["content"],
                    )
                    for chunk in result["chunks"]
                ]
                message = (
                    "Encontrei estes trechos na base de conhecimento. "
                    "Confira as fontes abaixo; esta consulta ainda não gera uma resposta com IA."
                )
                if result.get("incomplete"):
                    message += INCOMPLETE_NOTE
                reply = TextReply(text=message, sources=sources, answer_status="answered")
                return PolicyOutcome(KIND_ANSWERED, reply, "published_excerpts", question)

            try:
                if self.response_mode == "excerpts":
                    outcome = retrieve_excerpts()
                else:
                    outcome = respond(
                        text,
                        history=history,
                        retrieve=retrieve,
                        generate=generate,
                    )
            except (ModelAdapterError, PromptBudgetExceeded) as exc:
                logger.warning("Falha de geração (%s).", type(exc).__name__)
                raise _model_error(exc) from None

            logger.info("Resposta RAG-01: %s", outcome.to_log())

            if outcome.kind == KIND_CLARIFICATION:
                self.graph.append_turn(
                    thread_id,
                    text,
                    outcome.reply.question,
                    assistant_metadata={"clarification": True},
                )
            elif outcome.kind == KIND_ANSWERED:
                metadata = {
                    "policy": outcome.kind,
                    "sources": [source.model_dump() for source in outcome.reply.sources],
                }
                if "assistant_message_id" in generation:
                    self.graph.replace_assistant(
                        thread_id, generation["assistant_message_id"],
                        outcome.reply.text, metadata=metadata,
                    )
                else:
                    self.graph.append_turn(
                        thread_id, text, outcome.reply.text, assistant_metadata=metadata,
                    )
            else:
                if "assistant_message_id" in generation:
                    self.graph.replace_assistant(
                        thread_id,
                        generation["assistant_message_id"],
                        outcome.reply.text,
                        metadata={"policy": outcome.kind},
                    )
                else:
                    self.graph.append_turn(
                        thread_id,
                        text,
                        outcome.reply.text,
                        assistant_metadata={"policy": outcome.kind},
                    )
            return outcome.reply

    def handle_decision(
        self,
        thread_id: str,
        request: DecisionRequest,
        *,
        session_token: str | None = None,
    ) -> ChatReply:
        with self._lock_for(thread_id):
            self._authorized(thread_id, session_token)
            raise ChatBackendError(
                "write_disabled",
                "Operações de escrita não estão habilitadas nesta etapa.",
                status_code=409,
            )
