# Relatório de Implementação — ING-05

**Task:** integração da sincronização de artigos no startup e por comando manual  
**Branch:** `ING-05`  
**Base:** `8d679d8` (`dev_v2` atualizado, conforme conferência do usuário)  
**Arquitetura:** Alternativa C — MiniLM e `LocalIndexStore`, sem ChromaDB

## 1. Resultado

A API e o CLI agora acionam o mesmo coordenador de sincronização de artigos.
No startup, a API executa uma tentativa; o comando `python -m src.main sync`
permite dispará-la manualmente. O ledger SQLite registra tentativas e resultados
sem armazenar corpos de artigos nem mensagens de exceção. Um lock SQLite separado
impede sobreposição entre processos da API e do CLI.

A rota `GET /api/index/status` informa se o snapshot local está `available`,
`stale` ou `unavailable`. Ela abre a geração efetivamente ativa no store e a
compara ao ledger quando a última tentativa terminou. Enquanto uma execução
está registrada como `running`, reflete o ponteiro atômico do store, inclusive
se a nova geração já foi publicada e o ledger ainda não recebeu o fechamento.
Uma atualização malsucedida mantém o snapshot anterior; sem snapshot válido, a
API continua iniciando e responde com índice `unavailable`.

## 2. Implementação

### 2.1 Runtime compartilhado

`src/rag/sync_runtime.py` concentra o contrato injetável, o adaptador local, o
coordenador, o coletor, o ledger e o lock entre processos.

- `LocalArticleSyncEngine` chama `reconcile_store_with_manifest()` e `run_sync()`
  da ING-04 com `LocalIndexStore` e MiniLM. Não recria o pipeline de indexação.
- O coletor usa `GLPIClient.search_all("/Knowledgebase/Article")` e preserva
  `GLPICollection`. Confere `complete`, total de registros e formato estrutural
  dos artigos antes de pedir publicação. Um registro ativo sem ID inteiro,
  título textual ou corpo textual faz a tentativa falhar; registros marcados
  explicitamente inelegíveis ou removidos continuam sob a política da ING-04.
- O ledger registra escopo, trigger, estado, horários, duração, geração ativa e
  anterior, configuração, contagens, código de erro e situação da API de origem.
  Persiste apenas o tipo da exceção. Ledgers anteriores recebem a nova coluna
  `source_api_status` durante a inicialização.
- `SyncProcessLock` mantém uma transação `BEGIN IMMEDIATE` em um arquivo SQLite
  separado, compartilhado entre processos.

### 2.2 Startup e estado da API

`src/api/app.py` injeta a fábrica padrão no app exportado para Uvicorn e chama
`run("startup")` durante o lifespan, em thread de trabalho. `create_app()` aceita
uma fábrica injetável; sem ela, não chama o GLPI nem o modelo. Falhas de sync são
registradas e não impedem a aplicação de iniciar.

`GET /api/index/status` responde com escopo, estado, geração ativa, última
tentativa, resultado da última tentativa, última execução bem-sucedida, última
publicação, situação da API de origem, configuração do índice, contagens e tipo
do erro. Ele não retorna URL, credenciais ou conteúdo de artigos. `available`
significa que a geração efetivamente ativa pôde ser aberta. `stale` significa
que essa geração válida existe, mas a tentativa mais recente falhou, a origem foi
marcada indisponível ou o ledger terminou com uma geração diferente. Sem geração
válida, o estado é `unavailable`.

### 2.3 Comando manual

`python -m src.main sync` executa `run("manual")` pelo mesmo runtime usado no
startup, imprime o resultado em JSON e retorna código de saída não zero quando a
tentativa falha. O comportamento legado sem argumentos continua chamando a
verificação simples de coleta. O runtime de indexação é importado somente quando
o comando `sync` é solicitado.

## 3. Cobertura e evidências

Todos os comandos abaixo foram executados com o Python da `.venv` do checkout.

| Comando | Resultado |
|---|---:|
| `.venv/bin/python -m pytest tests/integration/test_sync_startup.py tests/test_main_sync.py -q` | 12 passed |
| `.venv/bin/python -m pytest test/test_contracts.py -q` | 4 passed |
| `.venv/bin/python -m pytest test/test_delta_sync.py test/integration/test_sync_publication.py -q` | 36 passed |
| `.venv/bin/python -m pytest tests/integration/test_local_index.py -q` | 22 passed |

Os testes novos usam GLPI e encoder sintéticos, `LocalIndexStore` real em
diretório temporário e ledger SQLite temporário. Eles cobrem startup, execução
única durante mensagens, índice inicialmente indisponível, falha com preservação
da geração publicada, registro malformado, coleção incompleta, concorrência,
migração do ledger, rejeição de lock sem reutilizar estado antigo da API de
origem e a janela entre a publicação no store e o fechamento do ledger. O
comando manual e a preservação da verificação legada também foram exercitados.

**Limite do teste HTTP neste ambiente:** os testes de rota novos executam o
lifespan real e chamam diretamente os handlers registrados. O `TestClient` da
instalação fica bloqueado até com uma aplicação FastAPI vazia; o transporte ASGI
assíncrono também bloqueia ao despachar um handler síncrono simples. Portanto, os
resultados acima não são apresentados como teste HTTP ponta a ponta. Os testes
existentes `tests/test_api_contract.py` e `tests/test_ui02_contract.py` não foram
incluídos nessa validação.

A suíte completa do repositório não foi concluída em uma única execução. Uma
execução agregada foi interrompida; nela, os dois erros identificados eram do
teste legado que chamava `src/main.py` via `runpy` herdando os argumentos do
pytest. O teste foi ajustado para simular a chamada sem argumentos e o arquivo
foi reexecutado isoladamente (`4 passed`). A tabela acima registra as suítes
focadas concluídas; ela não representa aprovação da suíte completa.

Não foram feitas chamadas reais ao GLPI nem carregados pesos do MiniLM. O teste
de publicação e persistência foi feito localmente com vetores sintéticos. A
execução em ambiente com GLPI configurado e teste HTTP com dependências
compatíveis permanecem validações operacionais posteriores.

## 4. Arquivos principais

- `src/rag/sync_runtime.py` — integração do motor, coleta, ledger e lock.
- `src/api/app.py` e `src/api/schemas.py` — startup e contrato da rota de estado.
- `src/main.py` — subcomando `sync`.
- `tests/integration/test_sync_startup.py` e `tests/test_main_sync.py` — cobertura
  de startup e CLI.
- [`ING-05.md`](ING-05.md) — contrato e progresso das oito etapas.
