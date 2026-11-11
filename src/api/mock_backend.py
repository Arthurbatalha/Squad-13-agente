"""Adaptador SIMULADO para desenvolvimento do front até RAG-01.

NÃO é o produto: não consulta GLPI, índice nem Gemini, e roteia por palavra-chave
só para exercitar cada tipo de resposta do contrato. O adaptador real não pode
reaproveitar essa lógica (as perguntas de referência não podem ter resposta fixa).

Gatilhos (texto contém, sem acentos/caixa):
  "abrir"          -> prévia de open_ticket
  "acompanhamento" -> prévia de add_public_followup
  "vpn"            -> resposta com fonte
  "impressora"     -> pedido de esclarecimento
  "indisponivel"   -> índice indisponível
  "abrir simular parcial" / "abrir simular incerto" -> desfechos controlados
  qualquer outro   -> sem evidência
Com ação pendente, "sim"/"não" decidem; qualquer outra coisa é recusada (409)
e nada é gravado.
"""

import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Optional

from src.api.backend import ChatBackendError
from src.glpi_integration.GLPI_Client import GLPICollection
from src.sessions import SessionService
from src.api.schemas import (
    ChatReply,
    ClarificationReply,
    DecisionRequest,
    FollowUpPayload,
    OpenTicketPayload,
    PendingAction,
    PreviewReply,
    SessionInfo,
    Source,
    StaffCharacter,
    TextReply,
    WriteResultReply,
)

# Usuários FICTÍCIOS de desenvolvimento; não foram lidos do laboratório.
# SES-01 resolve os personagens reais a partir de /Administration/User.
_CHARACTERS = [
    StaffCharacter(id=101, name="Técnico Demo A"),
    StaffCharacter(id=102, name="Técnico Demo B"),
]
_DEMO_REQUESTER_ID = 201

_YES = {"sim", "s", "yes", "y"}
_NO = {"nao", "n", "no"}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]", "", text).casefold().strip()


def _render_preview(operation: str, payload) -> str:
    if operation == "open_ticket":
        body = (
            "Vou abrir um chamado com estes dados:\n"
            f"Título: {payload.title}\n"
            f"Descrição: {payload.description}\n"
            f"Categoria (ID): {payload.category_id}\n"
            f"Prioridade: {payload.priority}\n"
            f"Solicitante (ID): {payload.requester_id}"
        )
    else:
        body = (
            f"Vou adicionar este acompanhamento público ao chamado #{payload.ticket_id}:\n"
            f"{payload.text}"
        )
    return body + "\nResponda “sim” para confirmar ou “não” para cancelar."


@dataclass
class _Session:
    thread_id: str
    character: StaffCharacter
    session_id: str  # credencial SES-01 exclusivamente interna ao mock
    pending: Optional[PendingAction] = None
    results: dict[str, WriteResultReply] = field(default_factory=dict)
    result_versions: dict[str, int] = field(default_factory=dict)
    last_write_result: Optional[WriteResultReply] = None


class MockChatBackend:
    adapter = "mock"

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.RLock()
        self._next_ticket_id = 9001
        # Exercita SES-01 sem consultar GLPI: os IDs continuam sendo fixtures.
        self._session_service = SessionService(
            lambda: GLPICollection("/Administration/User", [
                {"id": 101, "username": "ana.ribeiro"},
                {"id": 102, "username": "bruno.tavares"},
            ], 2, 1),
            integration_username="glpi",
        )

    # ----- sessões -------------------------------------------------------
    def list_characters(self) -> list[StaffCharacter]:
        return list(_CHARACTERS)

    def create_session(self, character_id: int) -> SessionInfo:
        character = next((c for c in _CHARACTERS if c.id == character_id), None)
        if character is None:
            raise ChatBackendError(
                "character_not_found", "Personagem desconhecido.", status_code=404
            )
        with self._lock:
            session_id, view = self._session_service.start(staff_user_id=character_id)
            session = _Session(thread_id=view["thread_id"], character=character, session_id=session_id)
            self._sessions[session.thread_id] = session
            return self._info(session)

    def switch_session(self, thread_id: str, character_id: int) -> SessionInfo:
        with self._lock:
            previous = self._get(thread_id)
            character = next((c for c in _CHARACTERS if c.id == character_id), None)
            if character is None:
                raise ChatBackendError("character_not_found", "Personagem desconhecido.", 404)
            session_id, view = self._session_service.switch(
                previous.session_id, thread_id, staff_user_id=character_id,
            )
            session = _Session(view["thread_id"], character, session_id)
            del self._sessions[thread_id]  # descarta pendência e resultados do contexto anterior
            self._sessions[session.thread_id] = session
            return self._info(session)

    def get_session(self, thread_id: str) -> SessionInfo:
        with self._lock:
            return self._info(self._get(thread_id))

    # ----- conversa ------------------------------------------------------
    def handle_message(self, thread_id: str, text: str) -> ChatReply:
        with self._lock:
            session = self._get(thread_id)
            if session.pending is not None:
                # Mantém a rota legada, mas perguntas como “sim?” não confirmam.
                answer = _normalize(text) if re.fullmatch(r"\w+[.!]?", text.strip()) else ""
                pending = session.pending
                if answer in _YES:
                    return self._decide(session, pending.action_id, pending.version, "yes", None)
                if answer in _NO:
                    return self._decide(session, pending.action_id, pending.version, "no", None)
                raise ChatBackendError(
                    "action_pending",
                    "Há uma ação aguardando confirmação. Responda “sim” ou “não”.",
                    status_code=409,
                )
            return self._route(session, text)

    def handle_decision(self, thread_id: str, request: DecisionRequest) -> ChatReply:
        with self._lock:
            session = self._get(thread_id)
            return self._decide(
                session, request.action_id, request.version, request.decision, request.text
            )

    # ----- internos ------------------------------------------------------
    def _get(self, thread_id: str) -> _Session:
        session = self._sessions.get(thread_id)
        if session is None:
            raise ChatBackendError(
                "session_not_found", "Sessão não encontrada.", status_code=404
            )
        return session

    def _info(self, session: _Session) -> SessionInfo:
        return SessionInfo(
            thread_id=session.thread_id,
            character=session.character,
            adapter=self.adapter,
            pending_action=session.pending,
            last_write_result=session.last_write_result,
        )

    def _new_action(self, session: _Session, operation: str, payload) -> PendingAction:
        action = PendingAction(
            action_id=uuid.uuid4().hex,
            version=1,
            operation=operation,
            staff_user_id=session.character.id,
            payload=payload,
            preview_text=_render_preview(operation, payload),
        )
        session.pending = action
        self._session_service.set_pending(session.session_id, session.thread_id, action_id=action.action_id)
        return action

    def _route(self, session: _Session, text: str) -> ChatReply:
        key = _normalize(text)
        if "abrir" in key:
            payload = OpenTicketPayload(
                title="Chamado aberto pelo chat (simulado)",
                description=text,
                category_id=1,
                priority=3,
                requester_id=_DEMO_REQUESTER_ID,
            )
            return PreviewReply(action=self._new_action(session, "open_ticket", payload))
        if "acompanhamento" in key:
            payload = FollowUpPayload(ticket_id=1, text=text)
            return PreviewReply(action=self._new_action(session, "add_public_followup", payload))
        if "vpn" in key:
            return TextReply(
                text="[simulado] Para configurar a VPN, siga o artigo indicado.",
                sources=[
                    Source(
                        source_type="article",
                        source_id="1",
                        title="Configurar a VPN corporativa (exemplo)",
                        reference="GLPI KB #1",
                        chunk_id="1:0",
                        excerpt="Abra Configurações, Rede e Internet e depois VPN.",
                    )
                ],
            )
        if "impressora" in key:
            return ClarificationReply(
                question="Qual problema ocorre com a impressora?",
                options=["Não imprime", "Atolamento de papel", "Outro"],
            )
        if "indisponivel" in key:
            return TextReply(
                text="[simulado] O índice de conhecimento está indisponível.",
                answer_status="index_unavailable",
            )
        return TextReply(
            text="[simulado] Não encontrei evidência suficiente nas fontes.",
            answer_status="no_evidence",
        )

    def _decide(
        self,
        session: _Session,
        action_id: str,
        version: int,
        decision: str,
        text: Optional[str],
    ) -> ChatReply:
        # Confirmação repetida devolve o resultado já registrado, sem reexecutar.
        if action_id in session.results:
            if session.result_versions[action_id] != version:
                raise ChatBackendError("stale_action_version", "A ação mudou; confira a versão atual.", 409)
            return session.results[action_id]

        pending = session.pending
        if pending is None:
            raise ChatBackendError(
                "no_pending_action", "Não há ação pendente.", status_code=409
            )
        if pending.action_id != action_id or pending.version != version:
            raise ChatBackendError(
                "stale_action_version",
                "A ação mudou; confirme a prévia mais recente.",
                status_code=409,
            )

        if decision == "no":
            result = WriteResultReply(
                action_id=action_id,
                status="cancelled",
                message="Ação cancelada. Nada foi gravado.",
            )
        elif decision == "yes":
            if pending.operation == "open_ticket":
                ticket_id = self._next_ticket_id
                self._next_ticket_id += 1
            else:
                ticket_id = pending.payload.ticket_id
            result = WriteResultReply(
                action_id=action_id,
                status="succeeded",
                ticket_id=ticket_id,
                message="[simulado] Ação concluída. Nenhuma chamada ao GLPI foi feita.",
            )
            # Fixtures de demonstração: não representam uma execução no GLPI.
            description = pending.payload.description if pending.operation == "open_ticket" else pending.payload.text
            if "simular parcial" in _normalize(description):
                result = result.model_copy(update={
                    "status": "partial",
                    "message": "[simulado] Chamado criado; uma etapa posterior falhou. Confira antes de repetir.",
                })
            elif "simular incerto" in _normalize(description):
                result = result.model_copy(update={
                    "status": "uncertain", "ticket_id": None,
                    "message": "[simulado] Não foi possível determinar o resultado. Verifique antes de repetir.",
                })
        else:  # "edit": nova versão, exige nova confirmação
            if pending.operation == "open_ticket":
                payload = pending.payload.model_copy(update={"description": text})
            else:
                payload = pending.payload.model_copy(update={"text": text})
            edited = pending.model_copy(
                update={
                    "version": pending.version + 1,
                    "payload": payload,
                    "preview_text": _render_preview(pending.operation, payload),
                }
            )
            session.pending = edited
            return PreviewReply(action=edited)

        session.pending = None
        self._session_service.clear_pending(session.session_id, session.thread_id, action_id=action_id)
        session.results[action_id] = result
        session.result_versions[action_id] = version
        session.last_write_result = result
        return result
