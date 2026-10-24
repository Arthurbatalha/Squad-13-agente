import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_settings
from src.glpi_integration.auth import fazer_login
from src.glpi_integration.GLPI_Client import GLPIClient, GLPIProtocolError


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
                f"Chamado {ticket.get('id', '<sem id>')} sem team em formato de lista."
            )
        for member in team:
            if not isinstance(member, dict):
                raise GLPIProtocolError(
                    f"Chamado {ticket.get('id', '<sem id>')} contém membro inválido."
                )
            participants.append({
                "ticket_id": ticket.get("id"),
                "participant": member,
            })
    return participants


def collect_data(client):
    """Lê recursos completos pelo cliente compartilhado, sem executar escritas."""
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


def _print_summary(name, collection):
    if not collection.complete:
        raise GLPIProtocolError(f"A coleção {collection.endpoint} está incompleta.")
    print(
        f"{name}: {collection.total} registros "
        f"({collection.pages} páginas; completa; origem {collection.endpoint})"
    )


def main():
    data = collect_data(create_client())
    _print_summary("Chamados", data["tickets"])
    _print_summary("Categorias", data["categories"])
    _print_summary("Usuários", data["users"])
    _print_summary("Artigos", data["articles"])
    print(
        f"Participantes: {len(data['participants'])} vínculos "
        f"({'completa' if data['participants_complete'] else 'incompleta'}; "
        f"origem {data['participants_source']})"
    )

    tickets = data["tickets"]
    status_counts = Counter(
        dropdown_name(ticket.get("status"))
        for ticket in tickets
    )
    category_counts = Counter(
        dropdown_name(ticket.get("category"))
        for ticket in tickets
    )

    print("\n--- DISTRIBUIÇÃO POR STATUS ---")
    for status, count in sorted(status_counts.items()):
        print(f"{status}: {count}")

    print("\n--- DISTRIBUIÇÃO POR CATEGORIA ---")
    for category, count in sorted(category_counts.items()):
        print(f"{category}: {count}")


def dropdown_name(value, default="Não informado"):
    """Extrai um nome legível de dropdowns expandidos da API v2."""
    if isinstance(value, dict):
        return value.get("name") or str(value.get("id", default))
    if value is None or value == "":
        return default
    return str(value)


if __name__ == "__main__":
    main()
