# Módulos de autenticação e cliente GLPI

Este documento descreve os módulos `src/glpi_integration/auth.py` e `src/glpi_integration/GLPI_Client.py`, responsáveis pela autenticação OAuth2 e pelas chamadas à API v2 do GLPI.

## Visão geral

- `auth.py`: valida as configurações necessárias, obtém tokens e renova a sessão.
- `GLPI_Client.py`: envia requisições autenticadas à API, renova o token uma vez quando recebe `401` e oferece operações para consultar e alterar chamados.
- `config.py`: carrega as configurações do `.env` localizado na raiz do repositório. A autenticação usa `GLPI_BASE_URL_V1`; o cliente deve receber a base da API v2, `GLPI_BASE_URL_V2`.

Fluxo típico:

1. Carregar as configurações com `load_settings(require_glpi=True)`.
2. Chamar `fazer_login(...)` para obter `access_token` e `refresh_token`.
3. Criar `GLPIClient` usando a URL v2, os tokens e as credenciais do cliente OAuth.
4. Fazer chamadas pelos métodos públicos de `GLPIClient`.
5. Se uma chamada receber `401`, o cliente tenta renovar o token e repete a chamada uma única vez.

## Configuração

Configure os valores no `.env` da raiz. Não versione esse arquivo nem registre credenciais ou tokens em logs.

| Variável | Uso |
|---|---|
| `GLPI_BASE_URL_V1` | Base de autenticação, normalmente terminada em `/api.php`; o módulo acrescenta `/token`. |
| `GLPI_BASE_URL_V2` | Base dos recursos, normalmente terminada em `/api.php/v2`; deve ser passada ao `GLPIClient`. |
| `GLPI_CLIENT_ID` | Identificador OAuth do cliente backend. |
| `GLPI_CLIENT_SECRET` | Segredo OAuth do cliente backend. |
| `GLPI_USERNAME` | Usuário GLPI usado no fluxo de login; se ausente, a configuração atual usa `glpi`. |
| `GLPI_PASSWORD` | Senha desse usuário; se ausente, a configuração atual usa `glpi`. |

A URL v1 e as credenciais do cliente são obrigatórias para autenticar. O usuário e a senha também precisam estar configurados ou ter os valores padrão definidos pelo projeto. Os valores de laboratório não devem ser reutilizados em produção.

## `auth.py`

### `fazer_login(client_id, client_secret, username=None, password=None)`

Realiza o fluxo OAuth2 `password` em `POST {GLPI_BASE_URL_V1}/token`, com escopo `api`. Quando `client_id` ou `client_secret` são `None`, usa os valores carregados do `.env`. O mesmo vale para `username` e `password`.

Retorna o objeto JSON recebido do GLPI, que deve conter um `access_token` não vazio. Pode conter também `refresh_token`.

### `renovar_token(client_id, client_secret, refresh_token)`

Realiza o fluxo `refresh_token` no mesmo endpoint. Retorna o JSON do GLPI após validar os tokens.

### Timeout e erros

As chamadas HTTP de autenticação usam `REQUEST_TIMEOUT_SECONDS`, atualmente 10 segundos.

| Exceção | Significado |
|---|---|
| `ValueError` | Configuração obrigatória ausente ou inválida. |
| `GLPIAuthenticationError` | Credenciais ou refresh token rejeitados/ausentes (inclui HTTP `401`). |
| `GLPIProtocolError` | Resposta de token inválida, não JSON ou sem `access_token` válido. |
| `ConnectionError` | Falha de comunicação ou erro HTTP diferente de `401` durante a autenticação. |

As mensagens de erro evitam incluir segredos. A exceção original de rede pode ficar disponível como causa (`__cause__`); por isso, não exponha tracebacks indiscriminadamente em respostas a usuários.

## `GLPI_Client.py`

### `GLPIClient(base_url, access_token, refresh_token, client_id, client_secret)`

Mantém a URL v2 e os dados necessários para enviar requisições e renovar a sessão. `base_url` deve ser a base de recursos, por exemplo `http://localhost:8080/api.php/v2`.

O cliente adiciona o header `Authorization: Bearer ...` e um timeout de 10 segundos. Para métodos diferentes de `GET`, envia também `Content-type: application/json`.

### Métodos públicos

| Método | Operação |
|---|---|
| `search_all(endpoint, start=0, limit=25)` | Consulta uma coleção paginada usando `start` e `limit`. |
| `get_by_id(endpoint, item_id)` | Consulta um item por identificador. |
| `add_ticket(title, content, category_id, priority=3)` | Cria um chamado e valida que a resposta contenha um ID inteiro positivo. |
| `update_ticket(ticket_id, data)` | Atualiza dados de um chamado com `PATCH`. |
| `add_solution(ticket_id, text)` | Adiciona uma solução à timeline do chamado. |
| `add_follow_up(ticket_id, text)` | Adiciona um acompanhamento à timeline. |
| `assign_member(ticket_id, user_id, role="assigned")` | Associa um usuário ao chamado; `role="requester"` o associa como solicitante. |
| `open_ticket(title, content, category_id, user_id, priority=3)` | Cria o chamado e, em seguida, tenta associar o solicitante. |

Os métodos de consulta e escrita retornam o JSON da resposta quando existe corpo. Para algumas escritas sem corpo, retornam um objeto de confirmação local; esse objeto não é uma resposta literal da API.

### Renovação e repetição de requisições

Uma resposta `401` provoca uma única tentativa de renovação. Com tokens válidos, o cliente atualiza `self.token` e `self.refresh_token` e repete a requisição uma vez. Uma segunda resposta `401` resulta em `GLPIAuthenticationError`; não há ciclo ilimitado de tentativas.

Falhas de transporte não são repetidas automaticamente. Para métodos de leitura (`GET`, `HEAD`, `OPTIONS`), `_send_request` converte falhas de rede em `ConnectionError`. Para outros métodos, uma falha de transporte gera `GLPIWriteOutcomeUnknownError`: a escrita pode ter sido aplicada pelo GLPI antes da conexão falhar. Verifique o estado remoto antes de tentar novamente, para evitar duplicações.

`open_ticket` cria o chamado antes de atribuir o solicitante. Se a atribuição falhar, lança `TicketRequesterAssignError`, que contém `ticket_id`. Quando `outcome_uncertain` é `True`, o resultado da atribuição é incerto; isso não significa que o chamado deixou de existir.

### Exemplos de uso

```python
from src.config import load_settings
from src.glpi_integration.auth import fazer_login
from src.glpi_integration.GLPI_Client import GLPIClient

settings = load_settings(require_glpi=True)
tokens = fazer_login(settings.glpi_client_id, settings.glpi_client_secret)

client = GLPIClient(
    base_url=settings.glpi_base_url_v2,
    access_token=tokens["access_token"],
    refresh_token=tokens.get("refresh_token"),
    client_id=settings.glpi_client_id,
    client_secret=settings.glpi_client_secret,
)

artigos = client.search_all("/Knowledgebase/Article", limit=25)
```

Em código de produção, trate as exceções documentadas e evite imprimir tokens, segredos ou payloads sensíveis.

## Limitações conhecidas do estado atual

- `search_all` deve ser revisado em conjunto com o comportamento de paginação da instância: a API pode retornar `200` quando a página cobre a coleção inteira e `206` quando o resultado é parcial. A implementação atual encerra o loop ao receber `200`, então uma coleção maior que `limit` pode não ser completamente coletada se a primeira resposta vier com esse status. A paginação e o comportamento de status devem ser cobertos por testes antes de depender da coleta integral.
- As operações são voltadas aos endpoints e formatos atuais da API v2 do laboratório. Consulte [api-glpi-v2.md](api-glpi-v2.md) para as rotas, campos e particularidades confirmadas.
- Os testes com mocks de [test_glpi_auth_client.py](../test/test_glpi_auth_client.py) cobrem autenticação, renovação, timeout, respostas inválidas e falhas de transporte. Eles não substituem uma validação integrada contra o GLPI real.

## Executar os testes

Na raiz do repositório, execute os testes do módulo com o ambiente Python do projeto:

```powershell
.\.venv\Scripts\python.exe -m pytest -q test/test_glpi_auth_client.py
```
