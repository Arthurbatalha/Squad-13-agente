"""Aplicação FastAPI (executada pelo Uvicorn).

    uvicorn src.api.app:app --reload --port 8000

O navegador só fala com estas rotas. Tokens do GLPI, modelo de embeddings e
regras de autorização ficam no servidor.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.backend import ChatBackend, ChatBackendError
from src.api.mock_backend import MockChatBackend
from src.api.schemas import (
    CharactersResponse,
    CreateSessionRequest,
    DecisionRequest,
    ErrorBody,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    MessageRequest,
    MessageResponse,
    SessionInfo,
)

logger = logging.getLogger(__name__)

DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

_ERRORS = {
    404: {"model": ErrorResponse, "description": "session_not_found | character_not_found"},
    409: {
        "model": ErrorResponse,
        "description": "action_pending | no_pending_action | stale_action_version",
    },
    422: {"model": ErrorResponse, "description": "invalid_request"},
    503: {"model": ErrorResponse, "description": "backend_unavailable"},
}


def build_backend() -> ChatBackend:
    kind = os.getenv("CHAT_BACKEND", "mock").strip().lower()
    if kind == "mock":
        return MockChatBackend()
    raise RuntimeError(
        f"CHAT_BACKEND={kind!r} ainda não existe. Valor suportado: 'mock' "
        "(o adaptador real entra com RAG-01)."
    )


def _error_json(
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    details: Optional[list[ErrorDetail]] = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code, message=message, retryable=retryable, details=details or []
        )
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


def create_app(
    backend: Optional[ChatBackend] = None,
    cors_origins: Optional[list[str]] = None,
    frontend_dist: Optional[Path] = FRONTEND_DIST,
) -> FastAPI:
    backend = backend or build_backend()
    origins = cors_origins
    if origins is None:
        raw = os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
        origins = [o.strip() for o in raw.split(",") if o.strip()]

    app = FastAPI(title="Chatbot GLPI — API", version="0.1.0")

    # Origem restrita ao front; sem credenciais/cookies.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    # ----- erros -----------------------------------------------------------
    @app.exception_handler(ChatBackendError)
    async def _backend_error(_: Request, exc: ChatBackendError):
        return _error_json(exc.status_code, exc.code, exc.message, exc.retryable)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        # Só nomes de campo e motivo: nunca devolve o valor enviado (poderia ser segredo).
        details = [
            ErrorDetail(
                field=".".join(str(p) for p in err["loc"] if p != "body"),
                reason=str(err["msg"]),
            )
            for err in exc.errors()
        ]
        return _error_json(422, "invalid_request", "Requisição inválida.", details=details)

    @app.exception_handler(Exception)
    async def _unexpected_error(_: Request, exc: Exception):
        logger.exception("Unhandled error")
        return _error_json(500, "internal_error", "Erro interno.", retryable=True)

    # ----- rotas -----------------------------------------------------------
    @app.get("/api/health", response_model=HealthResponse)
    def health():
        return HealthResponse(status="ok", adapter=backend.adapter)

    @app.get("/api/characters", response_model=CharactersResponse)
    def characters():
        return CharactersResponse(characters=backend.list_characters())

    @app.post("/api/sessions", response_model=SessionInfo, status_code=201, responses=_ERRORS)
    def create_session(body: CreateSessionRequest):
        return backend.create_session(body.character_id)

    @app.get("/api/sessions/{thread_id}", response_model=SessionInfo, responses=_ERRORS)
    def get_session(thread_id: str):
        return backend.get_session(thread_id)

    @app.post(
        "/api/sessions/{thread_id}/messages",
        response_model=MessageResponse,
        responses=_ERRORS,
    )
    def send_message(thread_id: str, body: MessageRequest):
        reply = backend.handle_message(thread_id, body.text)
        return MessageResponse(thread_id=thread_id, reply=reply)

    @app.post(
        "/api/sessions/{thread_id}/decisions",
        response_model=MessageResponse,
        responses=_ERRORS,
    )
    def send_decision(thread_id: str, body: DecisionRequest):
        reply = backend.handle_decision(thread_id, body)
        return MessageResponse(thread_id=thread_id, reply=reply)

    # Apresentação: serve o build do React junto da API (npm run build).
    if frontend_dist is not None and Path(frontend_dist).is_dir():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


app = create_app()
