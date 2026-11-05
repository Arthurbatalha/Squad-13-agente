"""Coleta dados do GLPI e gera um diagnóstico Markdown reproduzível."""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from requests.exceptions import RequestException


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_settings
from src.glpi_integration.auth import GLPIAuthenticationError, fazer_login
from src.glpi_integration.GLPI_Client import (
    GLPIClient,
    GLPICollection,
    GLPIProtocolError,
)


def create_client():
    """Autentica e cria o cliente comum da API v2."""
    settings = load_settings(require_glpi=True)

    tokens = fazer_login(
        settings.glpi_client_id,
        settings.glpi_client_secret,
        username=settings.glpi_username,
        password=settings.glpi_password,
    )

    return GLPIClient(
        base_url=settings.glpi_base_url_v2,
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
        client_id=settings.glpi_client_id,
        client_secret=settings.glpi_client_secret,
    )


def extract_participants(tickets):
    """Preserva a equipe embutida e seu vínculo com cada chamado."""
    participants = []

    for ticket in tickets:
        team = ticket.get("team")

        if not isinstance(team, list):
            raise GLPIProtocolError(
                f"Chamado {ticket.get('id', '<sem id>')} "
                "sem team em formato de lista."
            )

        for member in team:
            if not isinstance(member, dict):
                raise GLPIProtocolError(
                    f"Chamado {ticket.get('id', '<sem id>')} "
                    "contém membro inválido."
                )

            participants.append({
                "ticket_id": ticket.get("id"),
                "participant": member,
            })

    return participants


def collect_data(client):
    """Lê recursos pelo cliente compartilhado, sem escrever no GLPI."""
    tickets = client.search_all("/Assistance/Ticket")
    categories = client.search_all("/Dropdowns/ITILCategory")
    users = client.search_all("/Administration/User")
    articles = client.search_all("/Knowledgebase/Article")
    participants = extract_participants(tickets)

    return {
        "tickets": tickets,
        "categories": categories,
        "users": users,
        "articles": articles,
        "participants": participants,
        "participants_complete": tickets.complete,
        "participants_source": f"{tickets.endpoint} (campo team)",
    }


def dropdown_name(value, default="Não informado"):
    """Extrai um nome legível dos campos retornados pela API."""
    if isinstance(value, dict):
        return value.get("name") or str(value.get("id", default))

    if value is None or value == "":
        return default

    return str(value)


def _print_summary(name, collection):
    """Exibe os metadados de uma coleção completa no terminal."""
    if not collection.complete:
        raise GLPIProtocolError(
            f"A coleção {collection.endpoint} está incompleta."
        )

    print(
        f"{name}: {collection.total} registros "
        f"({collection.pages} páginas; completa; "
        f"origem {collection.endpoint})"
    )


def build_diagnostic(data):
    """Valida as coleções e organiza as contagens sem consultar a API."""
    totals = {}

    for name in ("tickets", "categories", "users", "articles"):
        collection = data.get(name)

        if not isinstance(collection, GLPICollection):
            raise GLPIProtocolError(
                f"A coleção {name} não possui o contrato esperado."
            )

        if collection.complete is not True:
            raise GLPIProtocolError(
                f"A coleção {name} está incompleta."
            )

        if collection.total != len(collection):
            raise GLPIProtocolError(
                f"O total informado para {name} não corresponde "
                "à quantidade de registros recebidos."
            )

        totals[name] = len(collection)

    tickets = data["tickets"]

    status_counts = Counter(
        dropdown_name(ticket.get("status"))
        for ticket in tickets
    )

    category_counts = Counter(
        dropdown_name(ticket.get("category"))
        for ticket in tickets
    )

    return {
        "totals": totals,
        "status_counts": dict(status_counts),
        "category_counts": dict(category_counts),
    }


def render_diagnostic(data, *, collected_at, glpi_version, source):
    """Monta o Markdown somente após validar as coleções."""
    diagnostic = build_diagnostic(data)

    def table_cell(value):
        """Evita que caracteres dos dados quebrem as tabelas Markdown."""
        return (
            str(value)
            .replace("\\", "\\\\")
            .replace("|", "\\|")
            .replace("\n", " ")
            .replace("\r", " ")
        )

    lines = [
        "# Diagnóstico do laboratório GLPI",
        "",
        f"- Coleta concluída em: {table_cell(collected_at)}",
        f"- Versão GLPI informada: {table_cell(glpi_version)}",
        f"- Origem: {table_cell(source)}",
        "- Escopo: registros retornados pelas rotas, sem filtros locais.",
        "- Não há descarte local de chamados da lixeira.",
        "- Os números são calculados sobre a coleta, não copiados do seed.",
        "",
        "## Totais e origem das coleções",
        "",
        "| Recurso | Total | Páginas | Endpoint |",
        "| --- | ---: | ---: | --- |",
    ]

    labels = {
        "tickets": "Chamados",
        "categories": "Categorias",
        "users": "Usuários",
        "articles": "Artigos",
    }

    for key, label in labels.items():
        collection = data[key]
        total = diagnostic["totals"][key]
        endpoint = table_cell(collection.endpoint)

        lines.append(
            f"| {label} | {total} | {collection.pages} | {endpoint} |"
        )

    distributions = (
        ("Distribuição por status", "Status", "status_counts"),
        ("Distribuição por categoria", "Categoria", "category_counts"),
    )

    for title, column, key in distributions:
        lines.extend([
            "",
            f"## {title}",
            "",
            f"| {column} | Quantidade |",
            "| --- | ---: |",
        ])

        counts = diagnostic[key]

        if not counts:
            lines.append("| Sem registros | 0 |")
        else:
            for name, count in sorted(counts.items()):
                lines.append(f"| {table_cell(name)} | {count} |")

    examples = (
        (
            "Exemplo JSON de chamado",
            "tickets",
            (
                "id", "name", "content", "status", "category",
                "date", "date_solve", "date_close", "is_deleted",
            ),
        ),
        (
            "Exemplo JSON de artigo",
            "articles",
            ("id", "name", "content", "date_mod"),
        ),
    )

    for title, key, fields in examples:
        lines.extend(["", f"## {title}", ""])

        if not data[key]:
            lines.append("Coleção vazia nesta coleta; não há amostra.")
            continue

        record = data[key][0]
        sample = {
            field: record[field]
            for field in fields
            if field in record
        }

        # Preserva os campos e omite os textos do título e do conteúdo.
        for field in ("name", "content"):
            if isinstance(sample.get(field), str):
                sample[field] = "<texto omitido>"

        lines.extend([
            "Campos selecionados do primeiro registro da listagem.",
            "Os textos de `name` e `content` foram omitidos.",
            "",
            "```json",
            json.dumps(sample, ensure_ascii=False, indent=2),
            "```",
        ])

    return "\n".join(lines) + "\n"


def save_diagnostic(data, output_path, **metadata):
    """Valida, monta e publica o relatório sem gravar conteúdo parcial."""
    content = render_diagnostic(data, **metadata)

    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = None

    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)

        temporary_path.replace(destination)

    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Gera o diagnóstico reproduzível do laboratório GLPI."
    )

    parser.add_argument(
        "--glpi-version",
        required=True,
        help="Versão da instância GLPI, conferida pelo operador.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "docs" / "diagnostico-glpi.md",
        help="Caminho do relatório Markdown.",
    )

    args = parser.parse_args(argv)
    glpi_version = args.glpi_version.strip()

    if not glpi_version:
        parser.error("--glpi-version não pode ser vazio.")

    try:
        settings = load_settings(require_glpi=True)
        client = create_client()
        data = collect_data(client)

        collected_at = datetime.now(
            settings.timezone
        ).isoformat(timespec="seconds")

        report_path = save_diagnostic(
            data,
            args.output,
            collected_at=collected_at,
            glpi_version=glpi_version,
            source=settings.glpi_base_url_v2,
        )

    except (
        GLPIAuthenticationError,
        GLPIProtocolError,
        RequestException,
        OSError,
        ValueError,
    ) as exc:
        print(
            f"Falha ao gerar o diagnóstico ({type(exc).__name__}). "
            "Nenhum relatório novo foi publicado.",
            file=sys.stderr,
        )
        return 1

    _print_summary("Chamados", data["tickets"])
    _print_summary("Categorias", data["categories"])
    _print_summary("Usuários", data["users"])
    _print_summary("Artigos", data["articles"])

    print(f"\nRelatório salvo em: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

