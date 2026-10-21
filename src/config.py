"""Configuração central da aplicação, carregada da raiz do repositório."""

from dataclasses import dataclass
from pathlib import Path
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class AppSettings:
    project_root: Path
    env_file: Path
    glpi_base_url_v1: str | None
    glpi_base_url_v2: str | None
    glpi_client_id: str | None
    glpi_client_secret: str | None
    glpi_username: str
    glpi_password: str
    app_timezone: str
    timezone: ZoneInfo


def _read(name: str) -> str | None:
    """Ignora espaços e trata valores vazios como ausentes."""
    return os.environ.get(name, "").strip() or None


def load_settings(*, require_glpi: bool = False) -> AppSettings:
    """Lê .env sem sobrescrever variáveis já definidas no ambiente.

    `require_glpi=True` só é usado quando a aplicação precisa chamar o GLPI.
    """
    load_dotenv(dotenv_path=ENV_FILE, override=False)

    timezone_name = os.environ.get("APP_TIMEZONE", "America/Fortaleza").strip()
    try:
        timezone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"APP_TIMEZONE inválido: {timezone_name!r}. "
            "Use um fuso IANA, por exemplo America/Fortaleza, "
            "e instale tzdata quando necessário."
        ) from exc

    values = {
        name: _read(name)
        for name in (
            "GLPI_BASE_URL_V1", "GLPI_BASE_URL_V2",
            "GLPI_CLIENT_ID", "GLPI_CLIENT_SECRET",
        )
    }
    if require_glpi:
        missing = [name for name, value in values.items() if value is None]
        if missing:
            raise ValueError("Configuração GLPI ausente no .env: " + ", ".join(missing))

    for name in ("GLPI_BASE_URL_V1", "GLPI_BASE_URL_V2"):
        value = values[name]
        if value and not value.startswith(("http://", "https://")):
            raise ValueError(f"{name} deve começar com http:// ou https://")

    return AppSettings(
        project_root=PROJECT_ROOT,
        env_file=ENV_FILE,
        glpi_base_url_v1=(values["GLPI_BASE_URL_V1"] or "").rstrip("/") or None,
        glpi_base_url_v2=(values["GLPI_BASE_URL_V2"] or "").rstrip("/") or None,
        glpi_client_id=values["GLPI_CLIENT_ID"],
        glpi_client_secret=values["GLPI_CLIENT_SECRET"],
        glpi_username=_read("GLPI_USERNAME") or "glpi",
        glpi_password=_read("GLPI_PASSWORD") or "glpi",
        app_timezone=timezone_name,
        timezone=timezone,
    )
