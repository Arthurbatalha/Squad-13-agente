import pytest
from pathlib import Path
from types import SimpleNamespace
from datetime import timezone

from scripts import coletar_dados
from scripts.coletar_dados import (
    build_diagnostic,
    render_diagnostic,
    save_diagnostic,
)

from scripts.coletar_dados import build_diagnostic, render_diagnostic
from src.glpi_integration.GLPI_Client import (
    GLPICollection,
    GLPIProtocolError,
)


COLLECTION_NAMES = ("tickets", "categories", "users", "articles")


def make_data(tickets=None, articles=None):
    """Monta coleções fictícias, sem acessar o laboratório."""
    records = {
        "tickets": tickets if tickets is not None else [],
        "categories": [],
        "users": [],
        "articles": articles if articles is not None else [],
    }

    return {
        name: GLPICollection(
            endpoint=f"/fake/{name}",
            items=items,
            total=len(items),
            pages=1,
        )
        for name, items in records.items()
    }


def test_diagnostic_calculates_totals_and_distributions():
    data = make_data(
        tickets=[
            {
                "id": 1,
                "status": {"name": "Novo"},
                "category": {"name": "Rede"},
            },
            {
                "id": 2,
                "status": {"name": "Novo"},
                "category": {"name": "Software"},
            },
            {
                "id": 3,
                "status": {"name": "Fechado"},
                "category": {"name": "Rede"},
            },
        ],
        articles=[{"id": 10}, {"id": 20}],
    )

    result = build_diagnostic(data)

    assert result["totals"] == {
        "tickets": 3,
        "categories": 0,
        "users": 0,
        "articles": 2,
    }
    assert result["status_counts"] == {"Novo": 2, "Fechado": 1}
    assert result["category_counts"] == {"Rede": 2, "Software": 1}


def test_diagnostic_accepts_empty_complete_collections():
    result = build_diagnostic(make_data())

    assert result["totals"] == {
        "tickets": 0,
        "categories": 0,
        "users": 0,
        "articles": 0,
    }
    assert result["status_counts"] == {}
    assert result["category_counts"] == {}


@pytest.mark.parametrize("collection_name", COLLECTION_NAMES)
def test_diagnostic_rejects_incomplete_collection(collection_name):
    data = make_data()
    data[collection_name].complete = False

    with pytest.raises(GLPIProtocolError, match="incompleta"):
        build_diagnostic(data)


@pytest.mark.parametrize("collection_name", COLLECTION_NAMES)
def test_diagnostic_rejects_inconsistent_total(collection_name):
    data = make_data()
    data[collection_name].total = 1

    with pytest.raises(GLPIProtocolError, match="não corresponde"):
        build_diagnostic(data)

REPORT_METADATA = {
    "collected_at": "2026-11-04T18:00:00-03:00",
    "glpi_version": "não verificada neste teste",
    "source": "dados simulados",
}


def test_report_contains_counts_metadata_and_sanitized_sample():
    data = make_data(
        tickets=[
            {
                "id": 1,
                "name": "Título reservado",
                "content": "Descrição reservada",
                "status": {"name": "Novo"},
                "category": {"name": "Rede"},
            }
        ],
        articles=[{"id": 10, "name": "VPN", "content": "Procedimento"}],
    )

    report = render_diagnostic(data, **REPORT_METADATA)

    assert "| Chamados | 1 | 1 |" in report
    assert "| Artigos | 1 | 1 |" in report
    assert "| Novo | 1 |" in report
    assert "| Rede | 1 |" in report
    assert "2026-11-04T18:00:00-03:00" in report
    assert "não verificada neste teste" in report
    assert "dados simulados" in report
    assert '"id": 1,' in report
    assert '"name": "<texto omitido>"' in report
    assert "Título reservado" not in report
    assert "Descrição reservada" not in report


def test_report_handles_empty_collections_without_inventing_examples():
    report = render_diagnostic(make_data(), **REPORT_METADATA)

    assert "| Chamados | 0 | 1 |" in report
    assert "| Artigos | 0 | 1 |" in report
    assert report.count("Coleção vazia nesta coleta; não há amostra.") == 2
    assert "```json" not in report


def test_report_rejects_incomplete_collection():
    data = make_data()
    data["articles"].complete = False

    with pytest.raises(GLPIProtocolError, match="incompleta"):
        render_diagnostic(data, **REPORT_METADATA)

def test_save_diagnostic_creates_markdown_file(tmp_path):
    output = tmp_path / "docs" / "diagnostico.md"

    saved_path = save_diagnostic(
        make_data(),
        output,
        **REPORT_METADATA,
    )

    assert saved_path == output.resolve()
    assert output.is_file()
    assert "# Diagnóstico do laboratório GLPI" in output.read_text(
        encoding="utf-8"
    )


def test_incomplete_collection_preserves_previous_report(tmp_path):
    output = tmp_path / "diagnostico.md"
    output.write_text("Relatório anterior", encoding="utf-8")

    data = make_data()
    data["articles"].complete = False

    with pytest.raises(GLPIProtocolError):
        save_diagnostic(data, output, **REPORT_METADATA)

    assert output.read_text(encoding="utf-8") == "Relatório anterior"


def test_publication_failure_preserves_report_and_removes_temporary_file(
    tmp_path, monkeypatch
):
    output = tmp_path / "diagnostico.md"
    output.write_text("Relatório anterior", encoding="utf-8")

    def fail_replace(self, target):
        raise OSError("Falha simulada na publicação.")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError):
        save_diagnostic(make_data(), output, **REPORT_METADATA)

    assert output.read_text(encoding="utf-8") == "Relatório anterior"
    assert set(tmp_path.iterdir()) == {output}


def test_main_returns_failure_without_publishing_report(
    tmp_path, monkeypatch, capsys
):
    output = tmp_path / "diagnostico.md"
    output.write_text("Relatório anterior", encoding="utf-8")

    settings = SimpleNamespace(
        timezone=timezone.utc,
        glpi_base_url_v2="http://glpi.test/api.php/v2",
    )

    monkeypatch.setattr(
        coletar_dados,
        "load_settings",
        lambda **kwargs: settings,
    )
    monkeypatch.setattr(
        coletar_dados,
        "create_client",
        lambda: object(),
    )

    def fail_collection(client):
        raise ConnectionError("API indisponível neste teste.")

    monkeypatch.setattr(
        coletar_dados,
        "collect_data",
        fail_collection,
    )

    result = coletar_dados.main([
        "--glpi-version", "TESTE",
        "--output", str(output),
    ])

    captured = capsys.readouterr()

    assert result == 1
    assert "Nenhum relatório novo foi publicado." in captured.err
    assert "Relatório salvo em:" not in captured.out
    assert output.read_text(encoding="utf-8") == "Relatório anterior"