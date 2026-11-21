"""Integração ING-05: startup, estado persistido e isolamento do índice local."""

import asyncio
import sqlite3

import numpy as np
import pytest

from src.api.app import create_app
from src.api.mock_backend import MockChatBackend
from src.api.schemas import CreateSessionRequest, MessageRequest
from src.glpi_integration.GLPI_Client import GLPICollection
from src.rag.chunk_contract import PREPARATION_VERSION
from src.rag.embeddings import DEFAULT_CONFIG
from src.rag.local_index import LocalIndexStore
from src.rag.sync_runtime import (
    ArticleSyncCoordinator,
    LocalArticleSyncEngine,
    SyncAlreadyRunningError,
    SyncProcessLock,
    SyncRunLedger,
    make_glpi_article_collector,
)


class FakeEncoder:
    config = DEFAULT_CONFIG

    def prepare_source(self, article, *, source_type):
        return [{
            "source_type": source_type,
            "source_id": article["id"],
            "source_reference": "/Knowledgebase/Article",
            "title": article["title"],
            "chunk_id": (
                f"{PREPARATION_VERSION}:{source_type}:{article['id']}:0000"
            ),
            "content": article["content"],
            "preparation_version": PREPARATION_VERSION,
        }]

    def encode_chunks(self, chunks):
        vectors = np.zeros((len(chunks), self.config.dimension), dtype=np.float32)
        for row, chunk in enumerate(chunks):
            vectors[row, chunk["source_id"] % self.config.dimension] = 1.0
        return vectors


class FakeGLPIClient:
    def __init__(self, articles):
        self.articles = articles
        self.calls = 0

    def search_all(self, endpoint):
        self.calls += 1
        return GLPICollection(
            endpoint, self.articles, total=len(self.articles), pages=1
        )


class BrokenGLPIClient:
    def search_all(self, endpoint):
        raise RuntimeError("private token and URL must not be persisted")


class IncompleteGLPIClient:
    def __init__(self, articles):
        self.articles = articles

    def search_all(self, endpoint):
        return GLPICollection(
            endpoint, self.articles, total=len(self.articles) + 1, pages=1
        )


def make_coordinator(tmp_path, client):
    store = LocalIndexStore(tmp_path / "index", "article")
    engine = LocalArticleSyncEngine(
        store=store,
        collect_fn=make_glpi_article_collector(lambda: client),
        encoder=FakeEncoder(),
    )
    ledger = SyncRunLedger(tmp_path / "article_sync_runs.sqlite3")
    lock = SyncProcessLock(tmp_path / "article_sync.lock.sqlite3")
    return ArticleSyncCoordinator(engine, ledger, lock)


def make_app(tmp_path, coordinator):
    return create_app(
        MockChatBackend(),
        frontend_dist=None,
        state_file=tmp_path / "api_state.sqlite3",
        sync_coordinator_factory=lambda: coordinator,
    )


def endpoint(app, path, method="GET"):
    return next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == path
        and method in getattr(route, "methods", set())
    )


def run_with_app(app, exercise):
    """Executa o lifespan real e inspeciona handlers sem o TestClient bloqueante."""
    async def run():
        original_to_thread = asyncio.to_thread

        async def inline_startup(function, *args, **kwargs):
            return function(*args, **kwargs)

        asyncio.to_thread = inline_startup
        try:
            async with app.router.lifespan_context(app):
                return exercise(app)
        finally:
            asyncio.to_thread = original_to_thread

    return asyncio.run(run())


def test_startup_publishes_once_and_messages_do_not_resync(tmp_path):
    glpi = FakeGLPIClient([
        {"id": 17, "name": "VPN", "content": "Configuração da VPN"}
    ])
    coordinator = make_coordinator(tmp_path, glpi)

    def exercise(app):
        assert "/api/index/status" in app.openapi()["paths"]
        body = endpoint(app, "/api/index/status")().model_dump()
        assert body["scope"] == "articles"
        assert body["state"] == "available"
        assert body["last_attempt_result"] == "published"
        assert body["source_api_status"] == "available"
        assert body["sources_total"] == body["chunks_total"] == 1
        assert body["active_generation"]

        session = endpoint(app, "/api/sessions", "POST")(
            CreateSessionRequest(character_id=101)
        )
        endpoint(app, "/api/sessions/{thread_id}/messages", "POST")(
            session.thread_id, MessageRequest(text="oi")
        )
        assert endpoint(app, "/api/index/status")().state == "available"

    run_with_app(make_app(tmp_path, coordinator), exercise)

    assert glpi.calls == 1


def test_failed_startup_without_snapshot_keeps_api_available_and_sanitizes_error(
    tmp_path,
):
    coordinator = make_coordinator(tmp_path, BrokenGLPIClient())
    def exercise(app):
        assert endpoint(app, "/api/health")().status == "ok"
        body = endpoint(app, "/api/index/status")().model_dump()
        assert body["state"] == "unavailable"
        assert body["last_attempt_result"] == "failed"
        assert body["source_api_status"] == "unavailable"
        assert body["error_code"] == "RuntimeError"
        assert "private token" not in str(body)

    run_with_app(make_app(tmp_path, coordinator), exercise)


def test_failed_refresh_keeps_previous_generation_readable_and_marks_stale(
    tmp_path,
):
    first_glpi = FakeGLPIClient([
        {"id": 17, "name": "VPN", "content": "Configuração da VPN"}
    ])
    def first_startup(app):
        return endpoint(app, "/api/index/status")().model_dump()

    initial_status = run_with_app(
        make_app(tmp_path, make_coordinator(tmp_path, first_glpi)), first_startup
    )
    first_generation = initial_status["active_generation"]
    assert initial_status["state"] == "available"

    failing = make_coordinator(tmp_path, BrokenGLPIClient())

    def failed_startup(app):
        body = endpoint(app, "/api/index/status")().model_dump()
        assert body["state"] == "stale"
        assert body["active_generation"] == first_generation
        assert body["source_api_status"] == "unavailable"
        with failing.engine.store.open_active() as active:
            assert active.generation_id == first_generation

    run_with_app(make_app(tmp_path, failing), failed_startup)


@pytest.mark.parametrize(
    "invalid_article",
    [
        {"id": "17", "name": "VPN", "content": "Conteúdo"},
        {"id": 17, "name": "VPN", "content": "  "},
    ],
)
def test_malformed_source_record_aborts_refresh_without_replacing_snapshot(
    tmp_path, invalid_article
):
    good = FakeGLPIClient([
        {"id": 17, "name": "VPN", "content": "Configuração da VPN"}
    ])
    first = make_coordinator(tmp_path, good)
    published = first.run("startup")
    assert published.status == "published"

    malformed = FakeGLPIClient([invalid_article])
    failed = make_coordinator(tmp_path, malformed).run("manual")
    assert failed.status == "failed"
    assert failed.error_code == "ValueError"
    assert failed.source_api_status == "unavailable"
    assert failed.active_generation == published.active_generation

    with LocalIndexStore(tmp_path / "index", "article").open_active() as active:
        assert active.generation_id == published.active_generation


def test_incomplete_collection_aborts_refresh_without_replacing_snapshot(tmp_path):
    articles = [{"id": 17, "name": "VPN", "content": "Configuração da VPN"}]
    published = make_coordinator(tmp_path, FakeGLPIClient(articles)).run("startup")
    failed = make_coordinator(tmp_path, IncompleteGLPIClient(articles)).run("manual")

    assert failed.status == "failed"
    assert failed.error_code == "IncompleteCollectionError"
    assert failed.source_api_status == "unavailable"
    assert failed.active_generation == published.active_generation


def test_status_uses_published_snapshot_while_cli_ledger_run_is_in_progress(
    tmp_path,
):
    glpi = FakeGLPIClient([
        {"id": 17, "name": "VPN", "content": "Versão inicial"}
    ])
    coordinator = make_coordinator(tmp_path, glpi)
    first = coordinator.run("startup")
    coordinator.ledger.begin(
        "manual", "2026-11-21T12:00:00+00:00", coordinator.engine.index_config
    )
    glpi.articles[0]["content"] = "Versão publicada pelo CLI"
    refreshed = coordinator.engine.sync_articles(trigger="manual")
    assert refreshed.active_generation != first.active_generation

    app = create_app(
        MockChatBackend(),
        frontend_dist=None,
        state_file=tmp_path / "api_state.sqlite3",
    )
    app.state.article_sync_ledger = coordinator.ledger
    app.state.article_index_store = coordinator.engine.store

    def exercise(app):
        body = endpoint(app, "/api/index/status")().model_dump()
        assert body["state"] == "available"
        assert body["active_generation"] == refreshed.active_generation
        assert body["last_attempt_result"] == "running"

    run_with_app(app, exercise)


def test_process_lock_is_shared_by_independent_lock_instances(tmp_path):
    lock_path = tmp_path / "article_sync.lock.sqlite3"
    first, second = SyncProcessLock(lock_path), SyncProcessLock(lock_path)
    with first.hold():
        with pytest.raises(SyncAlreadyRunningError):
            with second.hold():
                pass


def test_lock_rejection_does_not_reuse_previous_source_api_status(tmp_path):
    glpi = FakeGLPIClient([
        {"id": 17, "name": "VPN", "content": "Configuração da VPN"}
    ])
    coordinator = make_coordinator(tmp_path, glpi)
    assert coordinator.run("startup").source_api_status == "available"

    with coordinator.process_lock.hold():
        rejected = coordinator.run("manual")

    assert rejected.status == "failed"
    assert rejected.error_code == "SyncAlreadyRunningError"
    assert rejected.source_api_status == "unknown"


def test_ledger_migrates_existing_runs_table(tmp_path):
    path = tmp_path / "old_runs.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE article_sync_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL, trigger TEXT NOT NULL, status TEXT NOT NULL,
                started_at TEXT NOT NULL, finished_at TEXT, duration_seconds REAL,
                active_generation TEXT, previous_generation TEXT, checked_at TEXT,
                published_at TEXT, index_config_json TEXT, sources_total INTEGER,
                chunks_total INTEGER, error_code TEXT
            )"""
        )

    SyncRunLedger(path)
    with sqlite3.connect(path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(article_sync_runs)")}
    assert "source_api_status" in columns
