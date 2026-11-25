# RAG-01 — Conversa integrada React → FastAPI → agente → RAG-03/04/05

## 1. Objetivo e escopo

Esta entrega conecta a conversa do frontend ao caminho real do agente, sem
substituir os contratos já existentes:

1. o React mantém o contrato da UI-01/UI-02;
2. o FastAPI autentica a conversa por uma credencial opaca em cookie
   `HttpOnly`;
3. o agente LangChain recupera somente trechos autorizados da geração
   publicada pela RAG-03;
4. o adaptador Gemini da RAG-04 gera a resposta com o contexto efetivamente
   enviado;
5. a política da RAG-05 esclarece, recusa ou valida a resposta antes de
   exibi-la;
6. o `SqliteSaver` guarda o histórico canônico e permite retomar a conversa
   depois de reiniciar o backend.

Os commits desta etapa são locais; não há push ou merge. As operações de
escrita do GLPI continuam desabilitadas.

## 2. Arquitetura e ponto de entrada

```
React (repositório Squad-13-frontend)
  └── fetch /api, credentials: include
        └── FastAPI (src/api/app.py)
              ├── cookie rag01_session → hash SHA-256 em ui_sessions
              ├── RealChatBackend (src/api/real_backend.py)
              │     ├── SessionService (identidade em memória)
              │     ├── PublishedRetrieval (RAG-03, geração capturada)
              │     ├── RAGGenerationGraph (src/agent_core.py)
              │     │     ├── create_agent + SqliteSaver
              │     │     └── _AdapterChatModel → GeminiAdapter (RAG-04)
              │     └── evidence_policy.respond (RAG-05)
              └── data/agent_state.sqlite3
                    ├── ui_sessions (thread, personagem, hash do token)
                    └── checkpoints do LangGraph
```

O frontend está em
https://github.com/Anthonnyjda-dev/Squad-13-frontend e não é servido pelo
backend por padrão.

O ponto de entrada é `src/api/app.py:create_app()`. Ele:

- executa a migração de `init_db()` no SQLite;
- abre uma conexão e cria o `SqliteSaver`;
- monta `build_graph(checkpointer)` com `RAG_MAX_HISTORY_MESSAGES` e
  `RAG_AGENT_RECURSION_LIMIT`;
- seleciona o backend por `CHAT_BACKEND` (`mock` por padrão, `real` quando
  configurado);
- no lifespan, inicia o backend em uma thread (`startup()`), e no
  encerramento fecha o backend e a conexão SQLite.

`build_backend()` aceita `graph` e `state_file`; sem eles, o padrão continua
sendo o mock. Testes podem injetar `backend_factory`/`graph_factory` para usar
um provedor determinístico e um índice temporário.

### Arquivos principais

| Arquivo | Papel |
| --- | --- |
| `src/api/app.py` | Rotas, cookie, CORS, lifespan, seleção mock/real. |
| `src/api/real_backend.py` | Autorização por token, fluxo RAG, persistência e erros sanitizados. |
| `src/agent_core.py` | `create_agent`, checkpointer, histórico, geração, rollback e troca de contexto. |
| `src/session_store.py` | Migração e vínculo durável thread/personagem/hash do token. |
| `src/sessions.py` | Identidade em memória, `restore()` após reinício e `switch()`. |
| `src/api/backend.py` | Protocolo do backend, preservando o mock. |
| `src/api/mock_backend.py` | Backend de demonstração, agora com `session_token` opcional. |
| `src/config.py` | Limites de histórico, iterações, tentativas e timeout. |
| [Squad-13-frontend/src/api.js](https://github.com/Anthonnyjda-dev/Squad-13-frontend/blob/main/src/api.js) | `credentials: "include"` e nenhum segredo no navegador. |
| [Squad-13-frontend/src/useConversation.js](https://github.com/Anthonnyjda-dev/Squad-13-frontend/blob/main/src/useConversation.js) | Mensagens de erro sanitizadas e descarte de respostas atrasadas. |
| `tests/rag01_fixtures.py` | Índice real temporário, SQLite real e provedor fake. |
| `tests/test_rag_graph.py` | Cenários de grafo, política, sessão e segurança. |
| `tests/integration/test_graph_resume.py` | HTTP real com cookie e retomada após reinício. |

## 3. Configuração

Copie o exemplo e preencha apenas no `.env` local (que não é versionado):

```bash
cp .env.example .env
```

Variáveis da conversa real:

```dotenv
CHAT_BACKEND=real
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_TIMEOUT_SECONDS=30
GEMINI_MAX_RETRIES=0
RAG_MAX_PROMPT_TOKENS=8192
RAG_MAX_HISTORY_MESSAGES=20
RAG_AGENT_RECURSION_LIMIT=8
RAG01_COOKIE_SECURE=0
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

O laboratório GLPI usa `GLPI_BASE_URL_V1`, `GLPI_BASE_URL_V2`,
`GLPI_CLIENT_ID`, `GLPI_CLIENT_SECRET`, `GLPI_USERNAME` e `GLPI_PASSWORD`.
Esses valores ficam somente no backend e nunca são enviados ao React, ao
prompt ou ao checkpoint.

`CHAT_BACKEND=mock` mantém a demonstração antiga, sem Gemini, MiniLM ou GLPI.
`CHAT_BACKEND` inválido interrompe a inicialização com erro explícito.

### Limites configuráveis

| Variável | Padrão | Efeito |
| --- | ---: | --- |
| `RAG_MAX_PROMPT_TOKENS` | 8192 | Orçamento total do prompt da RAG-04. |
| `RAG_MAX_HISTORY_MESSAGES` | 20 | Últimas mensagens enviadas ao modelo; o checkpoint preserva a conversa completa. |
| `RAG_AGENT_RECURSION_LIMIT` | 8 | Limite de iterações do grafo LangGraph. |
| `GEMINI_TIMEOUT_SECONDS` | 30 | Timeout de cada chamada ao provedor. |
| `GEMINI_MAX_RETRIES` | 0 | Tentativas adicionais do adaptador Gemini. |
| `RAG01_COOKIE_SECURE` | 0 | Use `1` atrás de HTTPS. |

Os limites de recuperação vêm de `RetrievalConfig`: 8 candidatos por coleção,
4 trechos no total, 2 por fonte, 640 tokens de contexto e
`min_similarity=0.45` (provisório, herdado da RAG-03).

## 4. Sessão, autorização e retomada

- `POST /api/sessions` cria um `thread_id` e um token aleatório. O token vai
  apenas no `Set-Cookie: rag01_session`, `HttpOnly`, `SameSite=Lax`,
  `Path=/api`; o banco guarda somente `SHA-256(token)`.
- `GET /api/sessions/{thread_id}`, mensagens e troca exigem o cookie. O
  `thread_id` sozinho nunca autoriza: o backend compara hash, thread e papel
  `staff`.
- Tentar ler ou escrever em thread alheia retorna `404 session_not_found`,
  sem revelar se a thread existe.
- O `SessionService` em memória é reidratado por `restore()` a partir do
  vínculo já validado do SQLite. Não há consulta ao GLPI por mensagem.
- O histórico canônico está no checkpoint. Depois de reiniciar o processo,
  uma nova instância do backend reabre o mesmo SQLite e continua a conversa.
- A troca de personagem cria uma nova thread, invalida o cookie antigo,
  remove o checkpoint anterior e descarta o lock. Uma resposta atrasada da
  conversa antiga não recria o contexto novo; o frontend também ignora a
  resposta usando a época da conversa.
- Escritas retornam `409 write_disabled`. A rota de decisões existe para
  preservar o contrato, mas não executa ações nesta etapa.

## 5. Fluxo de uma mensagem

1. O backend valida o cookie e recupera a identidade da sessão.
2. Lê o histórico do checkpoint.
3. A política RAG-05 verifica ambiguidade antes da recuperação. Se faltar um
   dado que muda o procedimento, devolve `clarification` sem chamar o modelo.
4. `PublishedRetrieval` abre a geração ativa da RAG-03, aplica a autorização
   atual, captura a geração e vetoriza **uma única vez** a pergunta.
5. Sem evidência, o modelo não é chamado; a resposta é `no_evidence`.
   Índice indisponível e acesso negado têm textos próprios e não são
   apresentados como falta de conhecimento.
6. Com evidência, o agente chama o adaptador Gemini com o histórico limitado
   e publica `prompt_evidence` da mesma geração.
7. A RAG-05 valida citações e detalhes contra esse `prompt_evidence`. Uma
   citação inválida bloqueia o texto do modelo e persiste apenas a recusa
   fixa.
8. O turno é gravado no checkpoint: pergunta + resposta aprovada, ou
   pergunta + esclarecimento/recusa. Falha do modelo remove a pergunta
   incompleta (rollback) e retorna erro sanitizado.

## 6. Catálogo e coleções

A ING-05 publica **artigos** em produção. A coleção de casos pode existir no
diretório, mas sem `ACTIVE` ela é tratada como `not_published`, sem disparar
ingestão e sem prejudicar a consulta de artigos. Nesta etapa:

- `search_articles` é a única ferramenta de recuperação usada;
- `get_ticket`, `list_tickets`, `ticket_statistics`, `similar_cases` e
  `ranking_global` estão explicitamente desabilitadas;
- URLs, métodos, papel e escopo são definidos pelo servidor, não pelo texto
  do usuário nem pelo navegador;
- mensagens não disparam sync, coleta, `prepare_source` nem embeddings de
  documentos. Testes verificam `document_texts` inalterado e apenas uma
  vetorização de pergunta por consulta.

Uma geração anterior válida continua utilizável; o estado `stale` da ING-05
aparece em `GET /api/index/status` e não é convertido em “não encontrei”.
Falha do provedor de modelo vira `503`, nunca `no_evidence`.

## 7. Erros e privacidade

| Código | HTTP | Retryable | Quando |
| --- | ---: | --- | --- |
| `session_not_found` | 404 | não | Cookie ausente, inválido ou de outra thread. |
| `character_not_found` | 404 | não | Personagem fora do diretório. |
| `directory_unavailable` | 503 | sim | Diretório GLPI indisponível. |
| `write_disabled` | 409 | não | Decisão de escrita nesta etapa. |
| `model_not_configured` | 503 | não | Chave/modelo ausente. |
| `model_timeout` | 503 | sim | Timeout do provedor. |
| `model_rate_limited` | 503 | sim | Cota/limite do provedor. |
| `model_unavailable` | 503 | sim | Falha transitória do provedor. |
| `prompt_budget_exceeded` | 503 | não | Instruções/histórico/pergunta excedem o orçamento. |
| `invalid_request` | 422 | não | Corpo inválido; detalhes não ecoam valores. |
| `internal_error` | 500 | sim | Falha inesperada, sem detalhes internos. |

Respostas de política usam `answer_status` `answered`, `no_evidence` ou
`index_unavailable`. Acesso negado e resposta reprovada mantêm
`no_evidence` por compatibilidade com o contrato atual da UI, mas têm textos
fixos distintos. O frontend exibe o texto, as fontes, o esclarecimento, o
aviso de índice e as mensagens de erro acima.

Nenhuma resposta, prompt ou checkpoint contém chave Gemini, segredo GLPI,
token de sessão ou credencial de integração. O teste
`test_checkpoint_and_responses_do_not_contain_credentials` procura sentinelas
no SQLite e no JSON devolvido à UI.

## 8. Como executar

Backend:

```bash
source .venv/bin/activate
CHAT_BACKEND=real uvicorn src.api.app:app --reload --port 8000
```

O frontend fica no repositório separado
[Squad-13-frontend](https://github.com/Anthonnyjda-dev/Squad-13-frontend).
Nos exemplos abaixo, ele é clonado como repositório irmão em
`../Squad-13-frontend`. Em desenvolvimento, o proxy `/api` encaminha para a
porta 8000:

```bash
cd ../Squad-13-frontend
npm ci
npm run dev
```

O backend não serve o build do React por padrão. Para uma demonstração em uma
única URL, gere o build no repositório do frontend e sirva `dist/` com um
servidor estático, ou injete o caminho explicitamente em
`create_app(frontend_dist=...)`. Em produção, use HTTPS e
`RAG01_COOKIE_SECURE=1`.

## 9. Testes e resultados

Baseline antes das alterações (seleção curta existente):

```text
131 passed in 3.67s
```

Durante a implementação, a seleção ampliada chegou a `188 passed`. Na
validação final:

```bash
python -m pytest -q tests/test_rag_graph.py tests/integration/test_graph_resume.py
# 26 passed

python -m pytest -q test tests
# 573 passed in 17.34s

python -m pip check
# No broken requirements found.

cd ../Squad-13-frontend && npm test
# 2 arquivos, 36 testes passed

cd ../Squad-13-frontend && npm run build
# vite 6.4.6: 31 módulos, build concluído
```

Os testes RAG-01 usam SQLite real em diretório temporário, `SqliteSaver`,
índice publicado temporário e um adaptador determinístico injetado. Cobrem:

- resposta com fontes e persistência do turno;
- esclarecimento + resposta curta “Windows”;
- falta de evidência sem chamar o modelo;
- citação inválida bloqueada e texto do modelo descartado;
- índice indisponível distinto de falta de conhecimento;
- erros de modelo sanitizados (configuração, timeout, cota, indisponibilidade,
  orçamento) e rollback;
- duas sessões isoladas e tentativa de usar thread alheia;
- tentativa de alterar identidade/catálogo pelo texto;
- troca de personagem e resposta atrasada;
- retomada após reinício com nova instância e mesmo SQLite;
- limites de histórico/iterações;
- ausência de reindexação e de chamada ao diretório GLPI nas mensagens.

## 10. Ensaios independentes

### 10.1 Fixtures com MiniLM real

Além dos testes com encoder espião, foi executado um ensaio HTTP com
`EmbeddingService(local_files_only=True)` real, índice temporário publicado e
modelo **fake determinístico** (não Gemini), usando artigos fictícios:

- modelo: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`,
  revisão `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`;
- geração publicada temporária, 3 artigos, 3 trechos;
- “Como configuro a VPN?” → `clarification`;
- “Windows” → resposta `answered` citando o artigo fictício 12, com fonte e
  trecho;
- uma única vetorização de pergunta e nenhum embedding de documento durante
  as mensagens;
- reinício com nova instância do app: sem cookie `404`, com o mesmo cookie
  `200` e conversa retomada do SQLite.

O ensaio da RAG-03 com MiniLM real também foi reexecutado:

```bash
HF_HUB_OFFLINE=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  python -m scripts.verificar_recuperacao --output /tmp/rag01-minilm.json
```

Resultado: validação `passed`, 2 consultas com evidência, 2 vetorizações de
pergunta, 0 vetorizações de documento na leitura, índice reaberto com 3
vetores de 384 dimensões.

### 10.2 Laboratório GLPI real e índice publicado

O laboratório local foi iniciado com `cd lab && docker compose up -d --build`
e validado com `bash scripts/verificar-lab.sh`:

```text
ok   GLPI responde na raiz
ok   instalador não está exposto
ok   token OAuth obtido
ok   chamados no corpus: 300
ok   artigos de KB: 40
TUDO OK
```

O índice de produção foi publicado a partir desses artigos:

```bash
python -m src.main sync
# status=published
# 40 fontes, 82 trechos
# geração 01795619916454339153-f3416d
```

Observação operacional: `build_default_article_sync_coordinator()` usa
`EmbeddingService()` com `local_files_only=False`. Em uma máquina sem rede e
com `HF_HUB_OFFLINE=1`, o sync falha com `EmbeddingUnavailable`; nesse caso
execute o sync uma vez com rede/cache disponível ou ajuste o runtime para
`local_files_only=True`. O backend real já carrega o MiniLM com
`local_files_only=True`.

Com o índice publicado, foi executado o caminho HTTP completo usando o
diretório real do GLPI, MiniLM real e **modelo fake determinístico injetado
apenas no harness de teste**:

- `GET /api/characters` → `200`, cinco técnicos do laboratório;
- `POST /api/sessions` → `201`, cookie presente;
- “Como configuro a VPN?” → `clarification`;
- “Windows” → `answered`, artigo 1
  (“Configurar a VPN corporativa no Windows”);
- reinício com nova instância do app: sem cookie `404`, com o mesmo cookie
  `200`;
- “Como configuro a VPN no macOS?” → `answered`, artigo 2
  (“Configurar a VPN corporativa no macOS”);
- durante as mensagens: `document_texts` delta `0` e `question_texts` delta
  `2`.

A API real também foi aberta com o coordenador de sync:

- `GET /api/health` → `{"status":"ok","adapter":"real"}`;
- `GET /api/index/status` → `state=available`, geração
  `01795619916454339153-f3416d`, 40 fontes, 82 trechos e último sync
  `no_changes`.

Esse ensaio comprova o laboratório GLPI, o índice publicado, a recuperação
real, a política, o SQLite e a retomada. O modelo fake não comprova Gemini.

### 10.3 Caminho de produção sem a chave Gemini

O backend real também foi inicializado sem injeção de modelo, usando
`CHAT_BACKEND=real`, o laboratório e o índice publicados:

- `GET /api/characters` → `200`;
- `POST /api/sessions` → `201`;
- “Como configuro a VPN?” → `200 clarification`;
- “Windows” → `503 model_not_configured`, com mensagem sanitizada
  “O modelo de linguagem não está configurado no servidor.”;
- nenhum detalhe de chave, URL ou credencial na resposta.

Isso confirma que a ausência da chave não é apresentada como falta de
conhecimento e que o restante do caminho está operacional.

## 11. Limites do ensaio e pendências

O único bloqueio para o ensaio **Gemini real** é a ausência de
`GEMINI_API_KEY` no `.env` local. O laboratório GLPI, o índice publicado e o
caminho HTTP já foram validados.

- `.env` local com GLPI configurado e `CHAT_BACKEND=real`;
- `GEMINI_API_KEY` vazia; `GeminiAdapter.from_env()` retorna
  `ModelNotConfigured`;
- `data/index` publicado com 40 artigos e 82 trechos;
- laboratório GLPI respondendo com 300 chamados e 40 artigos;
- não há navegador instalado, então a validação visual não foi feita.

Portanto, os resultados acima comprovam o caminho HTTP, a política, o índice
publicado, o SQLite e a retomada com MiniLM real e GLPI real. **Eles não
comprovam chave, cota, modelo ou resposta do Gemini real.**

Para concluir o ensaio real, com dados fictícios e o laboratório já ativo:

1. Adicione uma `GEMINI_API_KEY` válida ao `.env`; mantenha
   `CHAT_BACKEND=real`.
2. Confirme `GET /api/index/status` com `state=available` e a geração
   publicada.
3. Inicie `uvicorn src.api.app:app --port 8000` e, no repositório do
   frontend, `npm run dev`.
4. Abra o frontend, escolha um técnico, pergunte “Como configuro a VPN?”,
   responda “Windows” e confira resposta, fontes e o aviso de índice.
5. Reinicie o backend sem apagar `data/agent_state.sqlite3`, recarregue a
   página e confirme que a conversa e o esclarecimento continuam.
6. Registre o modelo retornado pelo adaptador e o número de chamadas; limite
   o ensaio a poucas perguntas para não consumir cota.


Roteiro visual curto (quando houver navegador):

- a tela inicial lista os técnicos do laboratório;
- após escolher um técnico, envie a pergunta de VPN;
- o cartão de esclarecimento mostra as opções “Windows” e “macOS”;
- ao escolher “Windows”, a resposta traz o texto validado e “Fontes
  consultadas” com artigo, ID, trecho e referência;
- uma pergunta sem relação mostra “Sem evidência suficiente nas fontes”;
- parar o índice e perguntar de novo mostra “Índice indisponível”, não
  “sem evidência”;
- trocar de técnico limpa a conversa e invalida a sessão anterior.

Pendências fora do escopo desta task: calibração de recall/suficiência da
RAG-02, publicação de casos, ferramentas de escrita e validação com o Gemini
real.
