# RAG-03 — Recuperação autorizada de trechos publicados

Entrega na branch `feat/rag-03-recuperacao-trechos`, baseada em `origin/dev_v2`
atualizada por fetch em 21/11/2026. A referência continuava em `b500cde`;
a árvore inicial estava limpa e não havia `AGENTS.md`. Sem commit/push.

Segue a Alternativa C: MiniLM multilíngue em CPU, revisão
`e8f8c211226b894fcb81acc59f3b34ba3efd5f42`, 384 dimensões, float32,
normalização L2 e matriz + catálogo da ING-03. E5/Chroma do cartão antigo
não participam desta entrega. Foram lidos ING-05 e seu relatório,
ING-02, ING-03 e AUTH-01; o formato persistido existente foi preservado.

## Arquivos

| Arquivo | Finalidade |
| --- | --- |
| `src/rag/retrieval.py` | Serviço de leitura, autorização anterior ao ranking, seleção, orçamento e contrato para RAG-01. |
| `src/rag/busca_artigos.py` | Acrescenta `recuperar_trechos`; mantém a assinatura e o comportamento legado de `buscar_artigos`. |
| `src/authorization/service.py` | `retrieval_source_ids`: política compartilhada de artigos e checagem atual de casos por ID. |
| `src/rag/sync_runtime.py` | `SyncRunLedger.read_observation`: consulta operacional read-only, sem criação/migração do banco nem sync. |
| `tests/test_retrieval_contract.py` | 60 testes com encoder espião, fixtures sintéticas e stores persistidos em diretórios temporários. |
| `scripts/verificar_recuperacao.py` | Ensaio separado com MiniLM real, publicação anterior à leitura, reabertura, duas consultas, tempos e RSS. |
| `docs/RAG-03-validacao.json` | Evidência das execuções reais com fixtures e laboratório, sem conteúdo/credenciais do GLPI. |
| `docs/RAG-03.md` | Contrato, reprodução, resultados e pendências. |

Os chamadores de `buscar_artigos` encontrados são o ensaio da ING-02 e os
testes/exemplo locais. Continuam recebendo `id`, `title`, `content`, `score`
e os campos adicionais anteriores. Esse caminho legado ainda aceita fontes
para preparação em memória; a **nova recuperação publicada** usa outra
entrada e não chama esse preparador. RAG-01 deve usar `recuperar_trechos`.

## Fluxo de leitura e autorização

1. Recebe o `Principal` confiável da sessão e verifica `search_articles` /
   `similar_cases` pelo `AuthorizationService`, incluindo `disabled_tools`.
2. Se houver `scope_resolver(principal, source_type)`, aplica a restrição de
   IDs fornecida pelo backend. Conjunto vazio, `None`, erro ou valores
   malformados negam a coleção antes de abri-la. O resolver é reavaliado a
   cada consulta; não é parâmetro do navegador ou decisão do modelo.
3. Captura `store.open_active()` uma vez por coleção habilitada/publicada.
   Mantém o contexto aberto até a resposta estar pronta. Todas as linhas,
   referências e geração de uma coleção vêm dessa mesma captura.
4. Filtra IDs autorizados antes do produto matricial e do top-k. Artigos
   seguem a regra AUTH-01 de base técnica compartilhada. Para casos,
   consulta os originais por ID, exige `can_read_original`, chamado fora
   da lixeira, equipe estrutural válida e `date_solve`/`date_close`; confirma
   a projeção de solução pela timeline, como `similar_cases`. Falha na
   leitura/ACL desconhecida exclui o caso. Nunca coleta toda a lista de
   chamados/artigos para autorizar uma busca. Não há cache de ACL.
5. Confere a configuração integral do encoder e dos stores; uma coleção
   incompatível é indisponível, mesmo com 384 dimensões. Codifica **uma
   pergunta**, uma vez, e compartilha o vetor entre as coleções compatíveis.
6. Consulta só os vetores persistidos. Não chama sync, coleta completa,
   `prepare_source`, `encode_chunks` ou reconstrução no caminho de leitura.

ING-05 publica artigos em produção. A fábrica padrão reconhece casos sem
`ACTIVE` como `not_published`, sem disparar ingestão e sem prejudicar a
consulta de artigos. Caso publicado só entra com autorização atual. Os
testes combinam stores reais de `article` e `case` em diretório temporário;
não foi criada ingestão de casos.

## Ranking, complemento e orçamento

`RetrievalConfig()` começa com 8 candidatos únicos autorizados por coleção,
4 trechos finais no total, 2 por `(source_type, source_id)` e **640 tokens de
contexto**. Os limites são configuráveis e aceitam zero (sem inferência).
O score é `cosine_similarity`, produto de vetores normalizados: **maior é
mais semelhante**, não uma distância. Desempata por tipo, ID numérico da
fonte, ordinal e ID do trecho. Deduplica texto igual após normalizar espaços
dentro da mesma fonte; tipos/fontes distintos preservam sua rastreabilidade.

O corte inicial `min_similarity=0.45` é **provisório**, herdado da ING-02,
sem alegação de qualidade validada. RAG-02 pode passá-lo no construtor.
Âncoras de ranking devem superar ou igualar o corte. Um complemento da mesma
fonte pode ter score inferior: recebe `selection_reason=same_source_support`.

A seleção verifica pedidos literais de `passo N`, solução/correção e frases
adicionais em `required_evidence`. Uma simples menção a “consulte o passo 2”
não substitui a instrução “Passo 2: ...”. Procura complemento **autorizado da
mesma fonte**, entre os candidatos, dentro dos limites global/por fonte e
do orçamento. Se a unidade de evidência não couber ou não existir, não
entrega sua parte incompleta. Títulos iguais ou IDs numéricos iguais entre
tipos não permitem juntar instruções de fontes diferentes.

Termos obrigatórios respeitam limites de palavra/identificador: exigir
`VPN-FIX-691` não aceita `VPN-FIX-6910`, `XVPN-FIX-691` nem variantes com
prefixo/sufixo hifenizado. Rótulos Markdown vazios como `**Solução:**` ou
`**Passo 2:**` não contam como instrução. O texto complementar precisa
estar presente no mesmo conjunto selecionado, dentro do orçamento.

Os marcadores são uma verificação determinística de suporte explícito, não
uma prova semântica da solução. RAG-01 pode fornecer frases obrigatórias;
RAG-02 ainda precisa avaliar pedidos implícitos, recall e suficiência. Não
há chamada ao Gemini para fazer essa verificação.

Ordena fontes pela melhor similaridade e os trechos de cada fonte pela
ordem original, preservando passos. O orçamento conta com o tokenizer
MiniLM a **serialização exata de `context`**, incluindo rótulos, títulos,
referências e tokens especiais. Reutiliza `as_model_data` da AUTH-01, com
`trust=untrusted_data`. Não corta trechos silenciosamente para caber.

640 é o orçamento do contexto selecionado, separado dos **128 tokens**
máximos de cada documento/pergunta enviados ao encoder. O contexto inteiro
nunca é enviado ao encoder. A futura composição do prompt em RAG-01 deve
reservar o restante da janela para instruções, pergunta e resposta.

## Consumo pela RAG-01

Construa/reutilize o serviço e o encoder uma vez na composição do backend.
Credenciais e escopos ficam no servidor. Exemplo (variáveis de sessão vêm
do fluxo SES-01 já existente):

```python
from scripts.coletar_dados import create_client
from src.authorization.policies import Principal
from src.authorization.service import AuthorizationService
from src.rag.busca_artigos import recuperar_trechos
from src.rag.embeddings import EmbeddingService
from src.rag.retrieval import RetrievalConfig, build_published_retrieval

# Uma vez por serviço/processo; pode injetar o encoder compartilhado da aplicação.
encoder = EmbeddingService(local_files_only=True)
authorization = AuthorizationService(create_client(), disabled_tools=frozenset())
retriever = build_published_retrieval(
    authorization, encoder=encoder,
    config=RetrievalConfig(min_similarity=0.45, context_max_tokens=640),
)

# A cada consulta: nunca montar o Principal a partir do texto/corpo do navegador.
principal = Principal.from_session(sessions, session_id, thread_id)
result = recuperar_trechos(
    "Qual é o passo 2 para conferir o erro VPN-FIX-691?",
    principal, retriever=retriever, required_evidence=("VPN-FIX-691",),
)
if result["status"] == "evidence":
    selected_context = result["context"]
    citations = result["chunks"]
# Chamada ao Gemini, composição do chat e resposta final pertencem à RAG-01.
```

Campos principais de um retorno ilustrativo com **fixture sintética**
(campos operacionais adicionais omitidos neste exemplo):

```json
{
  "status": "evidence",
  "reason": "selected",
  "trust": "untrusted_data",
  "metric": "cosine_similarity",
  "higher_is_more_similar": true,
  "threshold_provisional": true,
  "incomplete": false,
  "chunks": [{
    "chunk_id": "ing-01-v2:article:91001:0000",
    "source_type": "article",
    "source_id": 91001,
    "title": "VPN indisponível",
    "content": "Passo 2: confira o erro VPN-FIX-691. (fixture sintética)",
    "source_reference": "/Knowledgebase/Article",
    "preparation_version": "ing-01-v2",
    "score": 0.82,
    "metric": "cosine_similarity",
    "generation": "01795290764361102902-276c36",
    "source_modified_at": null,
    "selection_reason": "ranked"
  }],
  "collections": {
    "article": {
      "state": "available",
      "generation": "01795290764361102902-276c36",
      "generation_created_at": "2026-11-21T19:52:44+00:00",
      "update": {"state": "unknown"}
    },
    "case": {"state": "not_published"}
  }
}
```

`context` é a serialização dos registros selecionados e `context_tokens`
é a contagem real; `config` registra os limites aplicados. `source_reference`
é preservada do catálogo (por exemplo, endpoint GLPI), sem inventar URL.

| Sinal | Como tratar |
| --- | --- |
| `status=evidence` | Há contexto selecionado; usar seus IDs/referências para citar. Não é garantia de correção semântica. |
| `status=no_evidence` | Busca válida sem contexto; pedir esclarecimento/recusar por evidência insuficiente. Não chamar isso de falha do índice. |
| `reason=insufficient_evidence` | Corte, suporte obrigatório ou orçamento impediu uma unidade completa de evidência. `chunks=[]`, `context=""`. |
| `reason=empty_index` | Geração válida e vazia; não dispara carga/inferência. |
| `reason=empty_authorized_scope` | Nenhum contexto permitido; não ampliar permissões nem revelar IDs excluídos. |
| `reason=context_disabled` | Algum limite configurado em zero; sem inferência. |
| `status=index_unavailable` | Não houve contexto e alguma coleção necessária falhou/está ausente/incompatível/corrompida; não alegar falta de conhecimento. |
| `collections[tipo].state=stale` | Geração capturada continua utilizável após tentativa de atualização fracassada; `update.state=failed`. |
| `incomplete=true` com evidência | Outra coleção falhou; há contexto autorizado parcial. Expor a limitação da consulta. |

`generation_created_at` vem do manifesto imutável da geração; **não é a
data de edição do artigo**. O catálogo ING-03 não persiste `date_mod`:
`source_modified_at=null` deixa essa ausência explícita. Não se consulta o
GLPI para inventar a data durante a leitura. ING-04/05 poderão acrescentar
metadado de edição de forma versionada em outra entrega.

`update` separa tentativa (`last_attempt_at`, resultado, erro sanitizado e
estado da API) de último sucesso/checagem/publicação da **geração capturada**.
Lê ledger com SQLite `mode=ro` e transação de leitura; não cria diretórios,
locks ou banco. Também aproveita datas de `sync_manifest.json` quando seu
ID coincide com a captura. Histórico ausente => `unknown`; ilegível =>
`unavailable` só na informação operacional, preservando o índice válido.
Uma publicação ocorrida depois da captura pode aparecer em
`update.observed_generation` / `generation_changed`, sem trocar os trechos
ou atribuir a eles datas da geração nova.

## Instalação e comandos reproduzíveis

Usado o `.venv` existente, Python 3.14.10. Inicialmente faltavam dependências
já declaradas pelo projeto: a primeira coleta de testes falhou em quatro
módulos sem `langgraph.checkpoint.sqlite`; após instalar o checkpoint,
restou `langgraph.graph`. Foram instalados:

```bash
.venv/bin/python -m pip install langgraph-checkpoint-sqlite==3.1.2 langgraph==1.2.12
.venv/bin/python -m pip check
```

Nenhuma dependência direta nova foi necessária; requisitos existentes
preservados. Em ambiente novo, use os arquivos de requisitos do projeto,
incluindo `requirements-api.txt` para os testes da API. Ative o venv para
usar `python` nos comandos abaixo (`source .venv/bin/activate`).

```bash
python -m pytest -q tests/test_retrieval_contract.py
python -m pytest -q tests/test_retrieval_contract.py test/test_embeddings.py test/test_ingestion_preparation.py test/test_authorization.py test/test_delta_sync.py test/integration/test_sync_publication.py tests/integration/test_local_index.py tests/integration/test_sync_startup.py tests/test_main_sync.py src/rag/test_busca_artigos.py
python -m pytest -q test tests
python -m pip check

# MiniLM real no cache, fixtures sintéticas, publicação temporária e reabertura:
python -m scripts.verificar_recuperacao --output /tmp/rag03-fixtures.json
# MiniLM real + artigos GLPI, só HTTP de leitura e índice temporário via ING-05:
python -m scripts.verificar_recuperacao --glpi --output /tmp/rag03-glpi.json
# Somente leitura de um índice não vazio já publicado no diretório indicado:
python -m scripts.verificar_recuperacao --index-dir data/index --output /tmp/rag03-publicado.json
```

`--download` permite obter a revisão se faltar no cache; não foi necessário
nesta execução. `--question` pode ser passado exatamente duas vezes para
trocar as perguntas. `--glpi` e `--index-dir` são mutuamente exclusivos:
preparação de teste e leitura de produção não são misturadas. Sem
`--index-dir`, o diretório temporário é removido ao encerrar, e uma nova
execução terá outro ID de geração.

O laboratório estava com os contêineres existentes parados. Foi consultado
com `docker compose --env-file lab/.env -f lab/docker-compose.yml ps --all`
e iniciado com `up -d --no-recreate --no-build --pull never` sobre os mesmos
serviços. Nenhum volume, credencial, dado ou artigo do laboratório foi
alterado. Os serviços foram deixados em execução. `data/index` não tinha
publicação inicial neste workspace: o ensaio GLPI usou o coordenador real
ING-05 em diretório temporário, sem criar um índice paralelo de produção.

## Testes observados em 21/11/2026

| Execução | Resultado |
| --- | --- |
| Base, antes de editar, após corrigir as dependências do venv | 343 passed em 18,79 s |
| `tests/test_retrieval_contract.py` | 60 passed em 1,07 s |
| Regressões de recuperação, embeddings, ING-01, autorização, índice, sync, startup e busca legada (comando acima) | 297 passed em 18,54 s |
| Suíte final `python -m pytest -q test tests` | 403 passed em 21,44 s |
| `python -m pip check` | No broken requirements found |
| `git diff --check` | Sem erros de whitespace |

Sem falhas novas, sem falhas preexistentes de código e sem testes ignorados.
As falhas iniciais de coleta foram do ambiente e foram resolvidas antes das
edições. Base e execução final tiveram os mesmos 17 DeprecationWarnings de
LangSmith / `asyncio.iscoroutinefunction`, fora do código alterado.

A revisão antes do PR acrescentou 20 cenários de regressão para códigos de
erro parcialmente coincidentes e rótulos Markdown sem instrução, com e sem
complemento disponível. A suíte da entrega inicial tinha 383 testes; após
as duas correções e os novos cenários, os 403 passaram. Os ensaios com
MiniLM/GLPI abaixo são as medições reais já realizadas; esta revisão alterou
a checagem textual de suporte e foi validada pelas suítes acima, sem nova
coleta do laboratório ou nova medição do modelo.

Nos 60 testes novos o encoder é **simulado**, os dados são **fixtures
sintéticas**, e matriz/catálogo/ACTIVE são persistidos pelo `LocalIndexStore`
real em `tmp_path`. Incluem: vetor único entre coleções, proibição global de
vetorização/preparação de documentos na leitura, filtro antes do top-k,
escopo vazio/indeterminado, revogação/erro de ACL, ferramentas desabilitadas,
deduplicação, colisão de IDs/títulos, limites globais, suporte complementar,
orçamento exato, pergunta longa, índice corrompido/incompatível/vazio,
datas de atualização e publicação concorrente durante a inferência. O teste
concorrente publica outra geração enquanto a consulta está suspensa e
confirma que todos os trechos/IDs retornados continuam na geração capturada.

## Pendências para as próximas tasks

- **RAG-01:** montar o `Principal.from_session`, injetar encoder/autorização
  compartilhados e consumir este contrato no agente/chat; tratar estados,
  citar referências e manter conteúdo recuperado como dado não confiável.
  Gemini não foi chamado nesta entrega.
- **RAG-02:** calibrar `min_similarity`, candidatos, orçamento e suficiência
  com perguntas e relevâncias anotadas. Os ensaios abaixo validam mecânica,
  rastreabilidade e reutilização, sem medir qualidade de ranking/recusa.
- **ING-04/05 / futura ingestão de casos:** publicar apenas projeção técnica
  permitida e manter atualização/revogação. Casos reais não foram ingeridos
  nem validados no laboratório; combinação coberta com fixtures e ACL
  simulada. Acrescentar `date_mod` ao catálogo exige contrato versionado.
- **ING-03:** continua valendo a limitação documentada de leases dentro do
  processo/store e coordenação do escritor. A resposta usa um snapshot
  completo em memória e não relê arquivos de outra geração durante ranking.

As medições reais e os IDs de cada consulta estão registrados a seguir e
no JSON de evidência; não há impedimento restante nos ensaios de artigos.

## Medições com MiniLM real

Sistema observado: `Linux-7.3.4-200.fc44.x86_64-x86_64-with-glibc2.43`, Python 3.14.10, CPU AMD Ryzen 5 3500U with Radeon Vega Mobile Gfx (8 CPUs lógicas), 2 threads e lote 8.

Versões: sentence-transformers 6.1.0, torch 2.15.0+cpu, transformers 5.22.2, tokenizers 0.23.3, numpy 2.5.4, psutil 7.2.2, huggingface-hub 1.33.0.

Ambos os ensaios passaram com pesos/tokenizer reais na revisão fixa, CPU e configuração de 128 tokens. O cache já estava disponível; **nenhum download foi feito**. A resolução do cache, carga e fase de publicação foram medidas separadamente. Publicação inclui preparação/vetorização/gravação e, no laboratório, coleta HTTP; não é tempo isolado de inferência dos documentos.

| Medida | Fixtures sintéticas | GLPI do laboratório (somente leitura) |
| --- | --- | --- |
| Fontes / trechos | 2 / 3 | 40 / 82 |
| Consulta ao cache (s) | 0.000293 | 0.000276 |
| Carga do modelo (s) | 12.573 | 11.398 |
| Preparação/publicação local (s) | 0.505 | 13.346 |
| Pergunta 1 / 2 (s) | 0.067 / 0.077 | 0.090 / 0.090 |
| RSS antes / após carga (MiB) | 66.223 / 767.805 | 66.156 / 767.211 |
| RSS após consultas (MiB) | 861.637 | 948.289 |
| Máximo tokens/trecho | 125 | 128 |
| Tokens de contexto consulta 1 / 2 | 421 / 421 | 469 / 626 |
| Vetorizações de documentos durante leitura | 0 | 0 |
| Vetorizações de perguntas durante leitura | 2 | 2 |

RSS é a memória residente do **processo inteiro**, obtida por `psutil.Process().memory_info().rss / 1024**2`. São amostras, não pico de memória, nem consumo exclusivo dos pesos. Tempos são observações locais, não benchmark de capacidade.

As matrizes reabertas foram verificadas como finitas, `(N, 384)`, L2 unitária; normas observadas no laboratório: 0.999999881 a 1.000000119. Perguntas passaram pelo `encode_question` com validação de limite/forma/norma. O tokenizer pode avisar sobre contagens acima de 128 ao contar rascunhos/contexto: essa contagem não é inferência. Os trechos efetivamente codificados ficaram dentro de 128, e o contexto selecionado dentro de 640.

### Fixtures sintéticas

Geração: `01795290764361102902-276c36`, criada em `2026-11-21T19:52:44+00:00`.

- O que conferir no erro VPN-FIX-691? → `evidence`; `ing-01-v2:article:91001:0000`, `ing-01-v2:article:93003:0000`.
- Como abrir o cliente VPN? → `evidence`; `ing-01-v2:article:91001:0000`, `ing-01-v2:article:93003:0000`.

Contadores antes/depois da leitura: `document_texts=3 → 3`, `question_texts=0 → 2`. `prepare_source` e `encode_chunks` foram substituídos por uma função que falha se chamada durante a leitura. Cada pergunta usou a mesma geração indicada acima.

### Artigos do GLPI do laboratório

Geração: `01795290816065757247-2f0fb9`, criada em `2026-11-21T19:53:36+00:00`.

- Como configurar a VPN no Windows? → `evidence`; `ing-01-v2:article:1:0000`, `ing-01-v2:article:1:0001`.
- Como instalar uma impressora? → `evidence`; `ing-01-v2:article:17:0000`, `ing-01-v2:article:5:0000`, `ing-01-v2:article:21:0000`.

Contadores antes/depois da leitura: `document_texts=82 → 82`, `question_texts=0 → 2`. `prepare_source` e `encode_chunks` foram substituídos por uma função que falha se chamada durante a leitura. Cada pergunta usou a mesma geração indicada acima.

Os dados sintéticos são as fixtures de artigos da ING-01 e uma variação longa identificada como fixture; não vieram do laboratório. O segundo ensaio usou artigos reais **da API do laboratório**, não dados de produção; a escrita foi exclusivamente no índice local temporário via coordenador ING-05, antes de construir o leitor. Não houve chamada ao Gemini.
