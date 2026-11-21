"""Contrato do comando manual ING-05 sem GLPI ou modelo real."""

from src import main
from src.rag.sync_runtime import SyncRun


def test_sync_subcommand_uses_manual_trigger_and_prints_safe_json(monkeypatch, capsys):
    calls = []
    run = SyncRun(
        run_id=3,
        trigger="manual",
        status="published",
        started_at="2026-11-21T12:00:00+00:00",
        finished_at="2026-11-21T12:00:01+00:00",
        duration_seconds=1.0,
        active_generation="00000000000000000001-a1b2c3",
        previous_generation=None,
        checked_at="2026-11-21T12:00:00+00:00",
        published_at="2026-11-21T12:00:01+00:00",
        index_config={"model": "MiniLM"},
        sources_total=2,
        chunks_total=2,
        error_code=None,
        source_api_status="available",
    )

    class Coordinator:
        def run(self, trigger):
            calls.append(trigger)
            return run

    monkeypatch.setattr(
        main, "build_default_article_sync_coordinator", lambda: Coordinator()
    )
    assert main.main(["sync"]) == 0
    assert calls == ["manual"]
    output = capsys.readouterr().out
    assert '"status": "published"' in output
    assert '"source_api_status": "available"' in output
    assert "secret" not in output.lower()


def test_sync_subcommand_returns_failure_for_failed_attempt(monkeypatch, capsys):
    failed = SyncRun(
        run_id=4,
        trigger="manual",
        status="failed",
        started_at="2026-11-21T12:00:00+00:00",
        finished_at="2026-11-21T12:00:01+00:00",
        duration_seconds=1.0,
        active_generation=None,
        previous_generation=None,
        checked_at=None,
        published_at=None,
        index_config={},
        sources_total=None,
        chunks_total=None,
        error_code="RuntimeError",
        source_api_status="unavailable",
    )

    class Coordinator:
        def run(self, trigger):
            return failed

    monkeypatch.setattr(
        main, "build_default_article_sync_coordinator", lambda: Coordinator()
    )
    assert main.main(["sync"]) == 1
    assert '"error_code": "RuntimeError"' in capsys.readouterr().out
