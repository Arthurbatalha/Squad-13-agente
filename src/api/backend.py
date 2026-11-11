"""Interface entre as rotas HTTP e o que responde de fato.

As rotas só conhecem `ChatBackend`. Hoje quem implementa é o `MockChatBackend`
(UI-01). O adaptador real (agente + índice + GLPI) entra em RAG-01 e substitui
o mock em `build_backend()` sem mudar rotas nem modelos.
"""

from typing import Literal, Protocol

from src.api.schemas import (
    ChatReply,
    DecisionRequest,
    SessionInfo,
    StaffCharacter,
)


class ChatBackendError(Exception):
    """Erro de negócio com código estável, convertido em {"error": {...}}."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


class ChatBackend(Protocol):
    adapter: Literal["mock", "real"]

    def list_characters(self) -> list[StaffCharacter]: ...

    def create_session(self, character_id: int) -> SessionInfo: ...

    def get_session(self, thread_id: str) -> SessionInfo: ...

    def switch_session(self, thread_id: str, character_id: int) -> SessionInfo: ...

    def handle_message(self, thread_id: str, text: str) -> ChatReply: ...

    def handle_decision(self, thread_id: str, request: DecisionRequest) -> ChatReply: ...
