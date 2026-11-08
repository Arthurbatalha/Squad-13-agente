"""Sessões de demonstração staff. Uma instância por processo do backend."""

from collections.abc import Callable
from dataclasses import dataclass, field
from secrets import token_urlsafe
from threading import Lock
from uuid import uuid4

from src.glpi_integration.GLPI_Client import GLPICollection


# Personagens marcados tecnico:true em seed/src/catalogo/usuarios.ts.
# O ID de cada personagem é resolvido na instância GLPI em uso.
DEMO_TECHNICIANS = frozenset({
    "ana.ribeiro", "bruno.tavares", "carla.menezes", "diego.fontes", "elisa.moraes",
})


class DirectoryUnavailable(RuntimeError):
    """A leitura do diretório do laboratório falhou."""


class InvalidCharacter(ValueError):
    """O personagem solicitado não está disponível para a demonstração."""


class SessionUnavailable(LookupError):
    """O vínculo entre sessão e conversa é inválido ou expirou."""


class PendingConflict(ValueError):
    """A referência de pendência diverge da registrada nesta conversa."""


@dataclass
class _Conversation:
    staff_user_id: int
    thread_id: str = field(default_factory=lambda: str(uuid4()))
    history: list[tuple[str, str]] = field(default_factory=list)
    pending_action_id: str | None = None

    def public(self) -> dict:
        return {
            "thread_id": self.thread_id,
            "role": "staff",
            "staff_user_id": self.staff_user_id,
            "has_pending_action": self.pending_action_id is not None,
        }


class SessionService:
    def __init__(self, read_users: Callable[[], GLPICollection], *, integration_username: str):
        self._read_users = read_users
        self._integration_username = integration_username.strip().casefold()
        self._sessions: dict[str, _Conversation] = {}
        self._lock = Lock()

    def staff_options(self) -> dict[int, str]:
        """Retorna somente ID e login de personagens disponíveis no laboratório."""
        try:
            users = self._read_users()
        except (OSError, ValueError, RuntimeError):
            # Exceções do transporte podem conter detalhes internos.
            raise DirectoryUnavailable("Falha ao consultar usuários do laboratório.") from None

        if (not isinstance(users, GLPICollection) or users.complete is not True
                or users.total != len(users)):
            raise DirectoryUnavailable("Lista de usuários incompleta.")

        options = {}
        for user in users:
            if not isinstance(user, dict):
                raise DirectoryUnavailable("Formato de usuário inválido.")
            login = user.get("username")
            if not isinstance(login, str) or login not in DEMO_TECHNICIANS:
                continue
            if login == self._integration_username:
                continue
            if user.get("is_deleted", False) not in (False, "0"):
                continue
            if user.get("is_active", True) not in (True, "1"):
                continue
            user_id = user.get("id")
            if type(user_id) is not int or user_id <= 0 or user_id in options or login in options.values():
                raise DirectoryUnavailable("Identificação de técnico inconsistente.")
            options[user_id] = login
        return options

    def _validate_character(self, staff_user_id: int) -> None:
        if type(staff_user_id) is not int or staff_user_id <= 0:
            raise InvalidCharacter("Selecione um técnico disponível.")
        if staff_user_id not in self.staff_options():
            raise InvalidCharacter("Selecione um técnico disponível.")

    def _open(self, staff_user_id: int) -> tuple[str, dict]:
        # Métodos que alteram o registro chamam este trecho sob o lock.
        session_id = token_urlsafe(32)
        conversation = _Conversation(staff_user_id)
        self._sessions[session_id] = conversation
        return session_id, conversation.public()

    def start(self, *, staff_user_id: int) -> tuple[str, dict]:
        """Devolve o identificador privado da sessão e a projeção pública."""
        self._validate_character(staff_user_id)
        with self._lock:
            return self._open(staff_user_id)

    def _owned(self, session_id: str, thread_id: str) -> _Conversation:
        conversation = self._sessions.get(session_id) if isinstance(session_id, str) else None
        if conversation is None or conversation.thread_id != thread_id:
            raise SessionUnavailable("Conversa indisponível.")
        return conversation

    def resume(self, session_id: str, thread_id: str) -> dict:
        with self._lock:
            return self._owned(session_id, thread_id).public()

    def switch(self, session_id: str, thread_id: str, *, staff_user_id: int) -> tuple[str, dict]:
        self.resume(session_id, thread_id)
        self._validate_character(staff_user_id)
        with self._lock:
            # Outra troca pode ter ocorrido durante a consulta ao GLPI.
            self._owned(session_id, thread_id)
            result = self._open(staff_user_id)
            del self._sessions[session_id]
            return result

    def _append(self, session_id: str, thread_id: str, sender: str, text: str) -> None:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("A mensagem deve conter texto.")
        with self._lock:
            self._owned(session_id, thread_id).history.append((sender, text))

    def add_user_message(self, session_id: str, thread_id: str, *, text: str) -> None:
        self._append(session_id, thread_id, "user", text)

    def add_assistant_message(self, session_id: str, thread_id: str, *, text: str) -> None:
        """Ponto de integração interno do agente."""
        self._append(session_id, thread_id, "assistant", text)

    def model_context(self, session_id: str, thread_id: str) -> dict:
        with self._lock:
            conversation = self._owned(session_id, thread_id)
            return {
                "role": "staff",
                "staff_user_id": conversation.staff_user_id,
                "messages": [
                    {"role": sender, "content": text} for sender, text in conversation.history
                ],
            }

    def set_pending(self, session_id: str, thread_id: str, *, action_id: str) -> None:
        """Guarda a referência da prévia criada pelo backend."""
        if not isinstance(action_id, str) or not action_id.strip():
            raise ValueError("Referência de ação inválida.")
        with self._lock:
            conversation = self._owned(session_id, thread_id)
            if conversation.pending_action_id not in (None, action_id):
                raise PendingConflict("Já existe outra pendência nesta conversa.")
            conversation.pending_action_id = action_id

    def clear_pending(self, session_id: str, thread_id: str, *, action_id: str) -> None:
        with self._lock:
            conversation = self._owned(session_id, thread_id)
            if conversation.pending_action_id is None or conversation.pending_action_id != action_id:
                raise PendingConflict("A pendência indicada não pertence a esta conversa.")
            conversation.pending_action_id = None
