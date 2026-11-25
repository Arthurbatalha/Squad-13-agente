"""Aplicação FastAPI (executada pelo Uvicorn).

    uvicorn src.api.app:app --reload --port 8000

O navegador só fala com estas rotas. Tokens do GLPI, modelo de embeddings e
regras de autorização ficam no servidor.
"""

import asyncio
import logging
import os
import sqlite3
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.session_store import init_db
from src.agent_core import build_graph
from src.config import STATE_FILE

from langgraph.checkpoint.sqlite import SqliteSaver

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
    IndexStatusResponse,
    MessageRequest,
    MessageResponse,
    SessionInfo,
)
from src.rag.sync_runtime import build_default_article_sync_coordinator

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        if app.state.sync_coordinator_factory is not None:
            try:
                coordinator = app.state.sync_coordinator_factory()
                app.state.article_sync_coordinator = coordinator
                app.state.article_sync_ledger = coordinator.ledger
                app.state.article_index_store = getattr(
                    coordinator.engine, "store", None
                )
                run = await asyncio.to_thread(coordinator.run, "startup")
                app.state.article_sync_run = run
                if run.status == "failed":
                    app.state.article_index_state = (
                        "stale" if run.active_generation else "unavailable"
                    )
                    logger.warning(
                        "Article index startup sync failed (%s).", run.error_code
                    )
                else:
                    app.state.article_index_state = (
                        "available" if run.active_generation else "unavailable"
                    )
            except Exception as exc:
                # A failed initial sync must not prevent the API from reporting
                # index unavailability or serving routes that do not need it.
                app.state.article_sync_run = None
                app.state.article_index_state = "unavailable"
                logger.warning(
                    "Article index startup could not be initialized (%s).",
                    type(exc).__name__,
                )
        yield
    finally:
        app.state.sqlite_conn.close()


def create_app(
    backend: Optional[ChatBackend] = None,
    cors_origins: Optional[list[str]] = None,
    frontend_dist: Optional[Path] = FRONTEND_DIST,
    state_file: Optional[Path] = None,
    sync_coordinator_factory: Optional[Callable] = None,
) -> FastAPI:
    backend = backend or build_backend()
    origins = cors_origins
    if origins is None:
        raw = os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
        origins = [o.strip() for o in raw.split(",") if o.strip()]

    app = FastAPI(title="Chatbot GLPI — API", version="0.1.0", lifespan=lifespan)
    app.state.sync_coordinator_factory = sync_coordinator_factory
    app.state.article_sync_run = None
    app.state.article_index_state = "unavailable"
    app.state.article_sync_coordinator = None
    app.state.article_sync_ledger = None
    app.state.article_index_store = None

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

    @app.get("/api/index/status", response_model=IndexStatusResponse)
    def article_index_status():
        ledger = app.state.article_sync_ledger
        if ledger is None:
            return IndexStatusResponse(state="unavailable")

        latest = ledger.latest()
        latest_success = ledger.latest_success()
        recorded_generation = latest.active_generation if latest else None
        store = app.state.article_index_store
        active_info = None
        active_generation = None
        if store is not None:
            try:
                with store.open_active() as active:
                    active_generation = active.generation_id
                    active_info = active.info
            except Exception:
                active_generation = None
                active_info = None

        if active_generation is None:
            state = "unavailable"
        elif latest and (
            latest.status == "failed"
            or latest.source_api_status == "unavailable"
            or (
                latest.status != "running"
                and recorded_generation != active_generation
            )
        ):
            state = "stale"
        else:
            state = "available"

        return IndexStatusResponse(
            state=state,
            active_generation=active_generation,
            last_attempt_at=latest.started_at if latest else None,
            last_attempt_result=latest.status if latest else None,
            last_success_at=latest_success.finished_at if latest_success else None,
            last_published_at=(
                latest_success.published_at if latest_success else None
            ),
            source_api_status=(
                latest.source_api_status if latest else "unknown"
            ),
            index_config=(latest_success.index_config if latest_success else None),
            sources_total=(
                active_info.source_count if active_info is not None
                else latest_success.sources_total if latest_success else None
            ),
            chunks_total=(
                active_info.chunk_count if active_info is not None
                else latest_success.chunks_total if latest_success else None
            ),
            error_code=latest.error_code if latest else None,
        )

    @app.get("/api/characters", response_model=CharactersResponse)
    def characters():
        return CharactersResponse(characters=backend.list_characters())

    @app.post("/api/sessions", response_model=SessionInfo, status_code=201, responses=_ERRORS)
    def create_session(body: CreateSessionRequest):
        return backend.create_session(body.character_id)

    @app.get("/api/sessions/{thread_id}", response_model=SessionInfo, responses=_ERRORS)
    def get_session(thread_id: str):
        return backend.get_session(thread_id)

    @app.post("/api/sessions/{thread_id}/switch", response_model=SessionInfo, responses=_ERRORS)
    def switch_session(thread_id: str, body: CreateSessionRequest):
        return backend.switch_session(thread_id, body.character_id)

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

    # EST-01: Inicialização da checkpoint database
    target_file = Path(state_file) if state_file is not None else STATE_FILE
    target_file.parent.mkdir(parents=True, exist_ok=True)
    init_db(target_file)

    conn = sqlite3.connect(target_file, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()
    app.state.graph = build_graph(checkpointer)

    app.state.checkpointer = checkpointer
    app.state.sqlite_conn = conn

    return app


app = create_app(sync_coordinator_factory=build_default_article_sync_coordinator)
