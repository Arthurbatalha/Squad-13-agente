# API do GLPI 11 (v2) — o que você precisa saber

Base: `http://localhost:8080/api.php`

Tudo abaixo foi confirmado ao vivo contra o lab local (GLPI 11.0.8), rodando
`docker compose up -d` na pasta `lab/`. Nada aqui é presumido.

## Antes de tudo: a API v2 vem desligada

Numa instalação nova, a "High-Level API" (a v2) está **desabilitada por
padrão**. Toda chamada em `/api.php/v2/...` retorna `403` com
`"detail":"The High-Level API is disabled"`, mesmo com um token válido, até
que as chaves `enable_api` e `enable_hlapi` sejam ligadas em `glpi_configs`
(contexto `core`) e o cache seja limpo (`php bin/console cache:clear`). No
lab isso já vem feito: o `lab/seed.sql` carrega o banco com a API habilitada
e o cliente OAuth já criado — você não precisa rodar nenhum script. Veja
`lab/oauth-client.md` para as credenciais.

## Autenticação (OAuth2)

`POST /api.php/token` com JSON:

    {"grant_type":"password","client_id":"...","client_secret":"...",
     "username":"glpi","password":"glpi","scope":"api"}

Devolve `{token_type, expires_in: 3600, access_token, refresh_token}`. Todas
as demais chamadas levam o header `Authorization: Bearer <access_token>`.

As credenciais estão em `lab/oauth-client.md`. O token expira em 1 hora —
seu agente precisa renovar (mesmo endpoint, `grant_type: refresh_token`).

O swagger completo (schema OpenAPI) fica em `GET /api.php/v2/doc.json` — é
**público**: responde `200` com o schema inteiro (1219 rotas) sem nenhum
header `Authorization`, testado tanto de fora do container quanto de dentro
dele. Ainda assim precisa da API habilitada (ver seção acima).

## Armadilhas que custam horas

- **Paginação** é por `?start=N&limit=M` (não `?range=0-199` como em notas
  de outra instância — esse parâmetro é ignorado). Confirmado ao vivo: sem
  `start`/`limit`, ou com `limit` igual ou maior que o total de registros, a
  listagem retorna **HTTP 200** com o corpo completo. Com `start`/`limit`
  cobrindo só uma fatia de uma coleção maior (confirmado com os 300
  chamados reais e `?start=0&limit=10`), a mesma rota retorna **HTTP 206
  Partial Content**. Ou seja: "listagens retornam 206" só vale quando a
  resposta é de fato parcial — uma página que cobre tudo retorna 200. Em
  ambos os casos o header `Content-Range: <inicio>-<fim>/<total>` vem
  presente. **Trate qualquer código 200–299 como sucesso** — é a regra que
  cobre os dois casos e não quebra quando a base cresce.
- **Não existe filtro server-side.** Confirmado ao vivo contra os 300
  chamados: `?filter=status==1` e `?status=1` são **ignorados
  silenciosamente** — a resposta continua sendo a listagem inteira
  (paginada), sem nenhum erro. A sintaxe com colchetes (`?filter[status]=1`)
  se comporta diferente: devolve `400 ERROR_INVALID_PARAMETER`, porque é
  interpretada como uma consulta RSQL malformada, não como um filtro por
  campo. Nas três formas, o resultado é o mesmo na prática: não tem como
  pedir ao servidor "só os chamados abertos" ou "só os de rede". Pagine a
  coleção inteira (`start`/`limit`) e filtre/agregue no código do seu
  próprio agente.
- A API legada `/apirest.php` **não existe** nesta instalação (não há
  `apirest.php` nem `api.php` como arquivo físico em `public/`; tudo é
  roteado via `index.php`/Symfony). Não use.
- Tickets na lixeira têm `is_deleted: true` — confirmado no schema do
  `PATCH /Assistance/Ticket/{id}`, mas o filtro de listagem não foi testado
  ao vivo.

## Base de conhecimento

Rota confirmada ao vivo — **não é** `/Assistance/KnowbaseItem`,
`/Tools/KnowbaseItem` nem `/KnowBaseItem` como cogitado inicialmente:

- Lista: `GET /api.php/v2/Knowledgebase/Article`
- Detalhe: `GET /api.php/v2/Knowledgebase/Article/{id}`
- Criar: `POST /api.php/v2/Knowledgebase/Article`

Campos confirmados: `id`, `name` (título), `content` (conteúdo HTML — **não**
`answer`), `date_creation`, `date_mod`, `categories` (array), `entity`,
`is_faq`, `views`. O conteúdo é **HTML** — converta para texto antes de
indexar.

Confirmado ao vivo: `POST /api.php/v2/Knowledgebase/Article` com
`{"name": "...", "content": "<p>...</p>"}` retorna `201 Created` com
`{"id": ..., "href": "/Knowledgebase/Article/{id}"}`.

## Categoria de chamado

Rota confirmada ao vivo — **não é** `/Assistance/ITILCategory` como cogitado
no brief original:

- Lista: `GET /api.php/v2/Dropdowns/ITILCategory`
- Detalhe: `GET /api.php/v2/Dropdowns/ITILCategory/{id}`

(A categoria de artigos da base de conhecimento é uma rota separada:
`GET /api.php/v2/Knowledgebase/Category`.)

## Usuário

Rota confirmada ao vivo — bate com a suposição do brief:

- Lista: `GET /api.php/v2/Administration/User`
- Detalhe: `GET /api.php/v2/Administration/User/{id}`
- Usuário autenticado: `GET /api.php/v2/Administration/User/Me`

## Chamados

- Lista: `GET /api.php/v2/Assistance/Ticket`
- Detalhe: `GET /api.php/v2/Assistance/Ticket/{id}` (mesmo shape da lista)
- Dropdowns já vêm expandidos inline: `status`, `category`, `entity` são
  objetos `{id, name}`, não IDs soltos (confirmado no `PATCH` de teste).

Campos confirmados: `id`, `name` (título), `content` (HTML), `status`,
`priority`, `urgency`, `impact`, `category`, `entity`, `user_recipient`,
`date`, `date_creation`, `date_mod`, `date_solve`, `date_close`, `team`.

**Atenção com as datas — é a armadilha mais silenciosa da API.** Medido ao
vivo contra os 300 chamados do corpus: `date_creation` **não** é a data de
abertura do chamado. Ela reflete o instante em que o laboratório foi
gerado — os 300 chamados têm `date_creation` concentrado numa janela de
poucos minutos (o tempo que o seed levou para rodar), não os últimos meses.
É inútil para qualquer análise temporal ("chamados dos últimos 60 dias",
distribuição por mês etc.). A data de abertura real, que cobre cerca de 18
meses de histórico, é o campo **`date`**. Use `date` para qualquer pergunta
sobre quando um chamado foi aberto; use `date_creation` só se precisar saber
quando o registro foi gravado no banco — raramente é o que se quer.

O campo `team[]` está presente e confirmado ao vivo. É um array de objetos,
um por pessoa envolvida no chamado, no formato:

    {
      "role": "requester" | "assigned",
      "name": "ana.ribeiro",
      "realname": "Ribeiro",
      "firstname": "Ana",
      "display_name": "Ribeiro Ana",
      "id": 7,
      "href": "/front/user.form.php?id=7",
      "type": "User"
    }

`role: "requester"` é quem abriu o chamado; `role: "assigned"` é o técnico
responsável. Um chamado pode ter os dois papéis ocupados pela mesma
pessoa — confira o `id`/`name` de cada entrada antes de assumir que são
pessoas diferentes.

## Contrato de leitura do cliente compartilhado

As leituras do coletor usam `GLPIClient.search_all()` para chamados,
categorias (`/Dropdowns/ITILCategory`), usuários (`/Administration/User`)
e artigos (`/Knowledgebase/Article`). Participantes são extraídos do campo
`team` já embutido nos chamados e mantêm o `ticket_id` e o objeto original
do membro, incluindo `role`, `id`, `name` e os demais campos recebidos.
Nenhum campo do chamado é projetado ou normalizado: `is_deleted`, `date`,
`date_solve`, `date_close`, valores `team` e seus offsets são preservados.
Não há filtro local que descarte chamados da lixeira.

O cliente aceita somente HTTP 200 ou 206 para listagens e exige que a
resposta JSON seja uma lista de objetos. Em respostas 206, valida
`Content-Range`, o offset e a quantidade de registros antes de buscar a
próxima página. Página 206 vazia, intervalo inconsistente, IDs repetidos,
JSON inesperado ou falha de transporte interrompem a operação com erro;
uma coleção parcial nunca é retornada como resultado completo. HTTP 200
com lista vazia é uma coleção vazia válida.

O retorno de `search_all()` continua compatível com `list` e expõe
`complete`, `total`, `pages` e `endpoint`. `complete` só é verdadeiro para
uma coleta que terminou sem lacunas; `total` é o total indicado pela API
quando há `Content-Range`. `get_by_id()` usa o mesmo transporte/autenticação
e exige HTTP 200 com um objeto JSON não vazio.

### Amostra de contrato e origem

A forma abaixo representa o contrato observado na instância GLPI 11.0.8 do
lab local. Em leitura somente GET realizada em 2026-10-24 contra
`http://localhost:8080/api.php/v2`, o cliente recebeu 300 chamados em 12
páginas, 6 categorias e 21 usuários; todas as três coleções foram completas.
As rotas de detalhe de chamado, categoria e usuário também retornaram objeto
JSON via `get_by_id()`. Nos 300 chamados, `team` era lista e foram observados
os papéis `requester` e `assigned` (568 vínculos no total). O detalhe de
chamado continha `is_deleted`, `date`, `date_solve` e `date_close`; os três
valores de data presentes no detalhe consultado tinham offset explícito.
Nenhum valor de identidade ou conteúdo do chamado foi gravado neste registro.

A amostra estrutural abaixo omite valores reais de identidade. Seus valores
de data/ID são ilustrativos; o que foi verificado ao vivo são os campos e
formatos descritos acima:

```json
{
  "id": 123,
  "date": "2025-01-15 09:30:00",
  "date_solve": null,
  "date_close": null,
  "is_deleted": false,
  "team": [
    {
      "role": "requester",
      "id": 7,
      "type": "User",
      "name": "<identidade omitida>"
    },
    {
      "role": "assigned",
      "id": 8,
      "type": "User",
      "name": "<identidade omitida>"
    }
  ]
}
```

Os campos `date`, `date_solve`, `date_close` e `is_deleted` são mantidos sem
transformação. As datas devem ser preservadas como retornadas pelo GLPI, sem
remover offset ou assumir conversão de fuso.

## Timeline (comentários e solução)

`GET /api.php/v2/Assistance/Ticket/{id}/Timeline` — confirmado ao vivo,
retorna `200` com a lista de itens do chamado (acompanhamentos, solução
etc.); um chamado sem nenhuma interação registrada devolve lista vazia.

Cada item tem a forma `{"type": "...", "item": {...}}`. Use o campo `type`
para distinguir o subtipo, não a forma do objeto em `item`:

- `type: "Followup"` — um acompanhamento (comentário). `item` confirmado ao
  vivo com: `id`, `itemtype`, `items_id`, `content` (HTML), `is_private`,
  `date`, `date_creation`, `date_mod`, `timeline_position`, `user` (objeto
  `{id, name}` de quem escreveu), `user_editor`, `request_type`.
- `type: "Solution"` — a solução registrada do chamado. `item` confirmado
  ao vivo com: `id`, `itemtype`, `items_id`, `content` (HTML), `status`,
  `date_creation`, `date_mod`, `date_approval`, `user`, `user_editor`,
  `approver`, `approval_followup`. **Não tem** `is_private` nem
  `timeline_position` — mais um jeito de distinguir de um `Followup`, mas
  o campo `type` já é suficiente e é o que você deve checar.

Sub-recurso de escrita confirmado ao vivo:
`POST /api.php/v2/Assistance/Ticket/{id}/Timeline/Followup` com
`{"content": "..."}` retorna `201 Created` com
`{"id": ..., "href": "/Assistance/Ticket/{id}/Timeline/Followup/{id}"}`.
Isso funciona mesmo em um chamado **fechado** — confirmado ao vivo (ver a
seção de escrita abaixo, que contrasta com o comportamento do `PATCH`).

## Escrita (Sprint 4)

Confirmado ao vivo:

- Criar chamado: `POST /api.php/v2/Assistance/Ticket` com `{name, content}`
  — corpo achatado, sem envelope `input`. Resposta: `201 Created` com
  `{"id": ...,"href": "..."}`.
- Comentar: `POST /api.php/v2/Assistance/Ticket/{id}/Timeline/Followup` com
  `{content}`. É o sub-recurso `/Followup`, não `/Timeline` direto (esse é
  só GET). **Funciona em chamados fechados** — confirmado ao vivo contra um
  chamado com `status: Fechado`, retornou `201` normalmente.
- Atualizar: `PATCH /api.php/v2/Assistance/Ticket/{id}` com JSON parcial —
  confirmado com `{"name": "..."}`. O comportamento **depende do status do
  chamado**, e isso não é detalhe menor: **59% do corpus está fechado**.
  - Em chamado **não fechado** (confirmado com um chamado `Novo`): retorna
    `200` com o objeto completo atualizado, como esperado.
  - Em chamado **fechado** (confirmado com um chamado `Fechado`): retorna
    `500` com `{"status":"ERROR","title":"Failed to update item(s)",
    "detail":null}` — sem detalhe do motivo. O GLPI recusa a edição de um
    chamado fechado pela regra de negócio padrão, e a API devolve isso como
    erro genérico de servidor em vez de um `4xx` explicativo. Trate `PATCH`
    em chamado fechado como uma falha **esperada**, não um bug do seu
    código — tentar de novo ou mudar o corpo da requisição não resolve. Se
    seu agente precisa registrar algo num chamado fechado, use o
    `Followup` acima, que não tem essa restrição.
