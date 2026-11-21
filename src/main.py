import argparse
from dataclasses import asdict
import json
import logging
import sys
from pathlib import Path

# Resolve a raiz do projeto (Squad-13-agente) a partir de src/main.py
RAIZ_PROJETO = Path(__file__).resolve().parent.parent

if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from src.config import load_settings
from src.glpi_integration.auth import fazer_login
from src.glpi_integration.GLPI_Client import GLPIClient
from src.rag.article_source import source_treatment


def build_default_article_sync_coordinator():
    """Carrega o runtime de indexação apenas quando o comando sync é usado."""
    from src.rag.sync_runtime import build_default_article_sync_coordinator as build

    return build()

def build_session_service():
    """Crie uma instância compartilhada no lifespan da aplicação FastAPI."""
    from scripts.coletar_dados import create_client
    from src.sessions import SessionService

    settings = load_settings(require_glpi=True)

    def read_users():
        return create_client().search_all("/Administration/User")

    return SessionService(read_users, integration_username=settings.glpi_username)


def _legacy_collection_check() -> int:
    """Preserva o comportamento antigo de `python -m src.main` para GLPI."""
    settings = load_settings(require_glpi=True)
    auth = fazer_login(
        settings.glpi_client_id,
        settings.glpi_client_secret
    )
    client = GLPIClient(
        settings.glpi_base_url_v2,
        auth.get("access_token"),
        auth.get("refresh_token"),
        settings.glpi_client_id,
        settings.glpi_client_secret
    )
    try:
        data_list = source_treatment(client)

        if data_list:
            print(f"Tudo está rodando corretamente... Artigos Carregados:{len(data_list)}")
        else:
            print("Coleta bem-sucedida, mas a base de artigos está vazia.")
    
    except (ConnectionError, ValueError) as e:
        logging.error(f"Erro nas ferramentas: {e}")
        print(f"Erro na coleta de artigos: {e}")
        return 1
    return 0


def _sync_articles() -> int:
    try:
        run = build_default_article_sync_coordinator().run("manual")
    except Exception as exc:
        # Não imprimir a mensagem original: pode conter URL ou dado de conexão.
        print(f"Falha ao sincronizar artigos ({type(exc).__name__}).", file=sys.stderr)
        return 1

    print(json.dumps(asdict(run), sort_keys=True, ensure_ascii=False))
    return 1 if run.status == "failed" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Operações da aplicação GLPI")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("sync", help="sincroniza manualmente o índice de artigos")
    args = parser.parse_args(argv)

    if args.command == "sync":
        return _sync_articles()
    return _legacy_collection_check()


if __name__ == "__main__":
    exit_code = main()
    # A verificação legada sem argumentos sempre terminava com exit code zero.
    # O comando novo precisa propagar falhas para automação e shell.
    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        raise SystemExit(exit_code)
