"""UI-01 — Contrato front–backend (modelos de requisição e resposta).

Regras do contrato:
  * Nomes de campos e códigos em inglês; textos exibidos ao usuário em português.
  * `extra="forbid"` em tudo: um campo desconhecido (ex.: `role`, `token`) é
    rejeitado com 422 em vez de ignorado. O navegador não escolhe papel nem
    envia credenciais do GLPI.
  * Uma resposta de conversa é sempre `{thread_id, reply}`, onde `reply` é uma
    união discriminada por `type`: text | clarification | preview | write_result.
  * Erros HTTP usam sempre `{"error": {code, message, retryable, details}}`.
"""

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_MESSAGE_CHARS = 4000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# Sessão
# --------------------------------------------------------------------------
class StaffCharacter(StrictModel):
    """Usuário fictício do laboratório usado como identidade simulada da sessão."""

    id: int
    name: str


class CreateSessionRequest(StrictModel):
    # Só o personagem é escolhido pelo cliente. O papel é sempre "staff" e é
    # definido pelo servidor; enviar `role` aqui resulta em 422.
    character_id: int


# --------------------------------------------------------------------------
# Ação de escrita pendente (prévia)
# --------------------------------------------------------------------------
class OpenTicketPayload(StrictModel):
    title: str
    description: str
    category_id: int
    priority: int = Field(ge=1, le=5)
    requester_id: int  # usuário fictício validado, pode diferir da sessão


class FollowUpPayload(StrictModel):
    ticket_id: int
    text: str
    is_private: Literal[False] = False  # acompanhamento privado é EXT-04 (desabilitado)


class PendingAction(StrictModel):
    action_id: str
    version: int = Field(ge=1)
    operation: Literal["open_ticket", "add_public_followup"]
    status: Literal["pending"] = "pending"
    staff_user_id: int
    payload: Union[OpenTicketPayload, FollowUpPayload]
    preview_text: str  # texto exato mostrado ao usuário; deve corresponder ao payload


# --------------------------------------------------------------------------
# Fontes e respostas da conversa
# --------------------------------------------------------------------------
class Source(StrictModel):
    source_type: Literal["article", "case"]
    source_id: str
    title: str
    reference: str  # referência verificável (ex.: "GLPI KB #12")
    chunk_id: Optional[str] = None
    excerpt: Optional[str] = None


class TextReply(StrictModel):
    type: Literal["text"] = "text"
    text: str
    sources: list[Source] = Field(default_factory=list)
    # Distingue "respondi com fontes" de "não há evidência" e de "índice fora do ar".
    answer_status: Literal["answered", "no_evidence", "index_unavailable"] = "answered"


class ClarificationReply(StrictModel):
    type: Literal["clarification"] = "clarification"
    question: str
    options: list[str] = Field(default_factory=list)


class PreviewReply(StrictModel):
    type: Literal["preview"] = "preview"
    action: PendingAction


class WriteResultReply(StrictModel):
    type: Literal["write_result"] = "write_result"
    action_id: str
    status: Literal["succeeded", "partial", "uncertain", "cancelled"]
    ticket_id: Optional[int] = None  # preservado em falha parcial
    message: str


class SessionInfo(StrictModel):
    thread_id: str
    role: Literal["staff"] = "staff"
    character: StaffCharacter
    adapter: Literal["mock", "real"]
    pending_action: Optional[PendingAction] = None
    # UI-02: reconciliação após perda de resposta; não é histórico nem checkpoint.
    last_write_result: Optional[WriteResultReply] = None


ChatReply = Annotated[
    Union[TextReply, ClarificationReply, PreviewReply, WriteResultReply],
    Field(discriminator="type"),
]


class MessageRequest(StrictModel):
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


class DecisionRequest(StrictModel):
    action_id: str
    version: int = Field(ge=1)
    decision: Literal["yes", "no", "edit"]
    text: Optional[str] = Field(default=None, max_length=MAX_MESSAGE_CHARS)

    @model_validator(mode="after")
    def _edit_needs_text(self):
        if self.decision == "edit" and not (self.text and self.text.strip()):
            raise ValueError("text is required when decision is 'edit'")
        return self


class MessageResponse(StrictModel):
    thread_id: str
    reply: ChatReply


class CharactersResponse(StrictModel):
    characters: list[StaffCharacter]


class HealthResponse(StrictModel):
    status: Literal["ok"]
    adapter: Literal["mock", "real"]


# --------------------------------------------------------------------------
# Erros
# --------------------------------------------------------------------------
class ErrorDetail(StrictModel):
    field: str
    reason: str


class ErrorBody(StrictModel):
    code: str
    message: str
    retryable: bool = False
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(StrictModel):
    error: ErrorBody
