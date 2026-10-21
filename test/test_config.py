"""Testes da configuração, sem servidor GLPI ou chave de modelo."""

import pytest

from src.config import PROJECT_ROOT, load_settings


def test_load_settings_from_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # a raiz deve continuar sendo a do projeto
    monkeypatch.setenv("GLPI_BASE_URL_V1", "http://localhost:8080/api.php/")
    monkeypatch.setenv("GLPI_BASE_URL_V2", "http://localhost:8080/api.php/v2/")
    monkeypatch.setenv("GLPI_CLIENT_ID", "client-test")
    monkeypatch.setenv("GLPI_CLIENT_SECRET", "secret-test")
    monkeypatch.setenv("APP_TIMEZONE", "America/Fortaleza")
    settings = load_settings(require_glpi=True)
    assert settings.project_root == PROJECT_ROOT
    assert settings.glpi_base_url_v1 == "http://localhost:8080/api.php"
    assert settings.glpi_base_url_v2 == "http://localhost:8080/api.php/v2"
    assert settings.glpi_client_id == "client-test"
    assert settings.app_timezone == "America/Fortaleza"
    assert settings.timezone.key == "America/Fortaleza"


def test_missing_required_glpi_config(monkeypatch):
    for name in ("GLPI_CLIENT_ID", "GLPI_CLIENT_SECRET", "GLPI_BASE_URL_V1", "GLPI_BASE_URL_V2"):
        monkeypatch.setenv(name, "")  # não permite fallback para .env local
    monkeypatch.setenv("APP_TIMEZONE", "America/Fortaleza")
    with pytest.raises(ValueError, match="GLPI_CLIENT_ID"):
        load_settings(require_glpi=True)


def test_invalid_timezone(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "Not/A_Real_Timezone")
    with pytest.raises(ValueError, match="APP_TIMEZONE inválido"):
        load_settings()
