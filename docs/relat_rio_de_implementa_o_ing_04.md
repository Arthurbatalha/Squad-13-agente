# Relatório de Implementação e Decisões Arquiteturais

**Task:** ING-04 — Implementar Delta Sync com geração candidata e manifesto atômico  
**Área:** 03 — Ingestão e sincronização de artigos  
**Objetivo:** Implementar a rotina de sincronização incremental de artigos da Base de Conhecimento para o índice vetorial em ChromaDB, garantindo reaproveitamento de vetores inalterados, atualização de metadados sem reembutir, validação prévia da candidata, proteção contra coletas incompletas e publicação atômica controlada por manifesto.

---

## 1. Módulo de Persistência Atômica do Manifesto

**Arquivo criado:** `src/rag/manifest.py`

* **O que fizemos:**
  * Criamos as funções `empty_manifest()`, `validate_manifest()`, `load_manifest()` e `save_manifest_atomic()`.
  * Definimos o contrato obrigatório do manifesto com 6 campos: `active_generation`, `index_config`, `preparation_version`, `sources`, `last_checked_at` e `last_published_at`.
  * Em `sources`, armazenamos por `source_id` inteiro o `content_hash`, o `metadata_hash` e a lista exata de `chunk_ids`.
  * Implementamos validação estrita de tipos (rejeitando chaves ausentes, booleanos como inteiros, IDs negativos e entradas corrompidas) e conversão automática das chaves de `sources` entre `str` (formato JSON em disco) e `int` (em memória).
  * Implementamos escrita atômica utilizando arquivo temporário no mesmo diretório do destino (`tempfile.NamedTemporaryFile(dir=manifest_path.parent, delete=False)`), seguido de `flush()`, `os.fsync()`, fechamento do descritor e substituição via `os.replace()`, com limpeza automática do `.tmp` em caso de erro.
  * Removemos o arquivo estático `src/rag/sync_manifest.json` do código-fonte para que o manifesto exista apenas como estado em tempo de execução no diretório de persistência (`<persist_dir>/sync_manifest.json`, ao lado de `control.sqlite3` e `chroma/`).

* **Por que fizemos:**
  * **Segurança contra corrupção:** Gravar diretamente sobre o arquivo de manifesto pode corromper o JSON em caso de falha de disco ou queda do processo. Escrever no mesmo diretório, forçar `fsync` e fechar o descritor antes do `os.replace()` garante troca atômica inclusive no Windows, sem deixar arquivos temporários órfãos.
  * **Fidelidade de tipos:** Como JSON aceita apenas chaves `str`, normalizar de volta para `int` na leitura evita falsos positivos na comparação de IDs que causariam reindexação total a cada execução.
  * **Separação de timestamps:** Manter `last_checked_at` separado de `last_published_at` permite registrar verificações bem-sucedidas sem mudanças sem avançar a data de publicação nem criar novas gerações.

---

## 2. Motor de Delta Sync e Orquestração de Publicação

**Arquivo criado:** `src/rag/sync.py`

* **O que fizemos:**
  * Criamos as exceções de domínio `SyncError`, `SyncAlreadyRunningError`, `IncompleteCollectionError` e `CandidateValidationError`, além das estruturas imutáveis `CollectionBatch` e `SyncReport`.
  * Implementamos `_exclusive_sync_lock()` com `threading.Lock` indexado pelo caminho resolvido do manifesto e aquisição não bloqueante (`blocking=False`), com liberação garantida em `finally`.
  * Implementamos `is_article_eligible()`, `compute_content_hash()` (SHA-256 dos pares `[chunk_id, content]`) e `compute_metadata_hash()` (SHA-256 de `source_type`, `source_reference` e `title`).
  * Implementamos a função pura `calculate_delta(manifest_state, fetched_articles, is_complete, force_reembed=False)`, classificando os IDs em 5 categorias (`new`, `content_modified`, `metadata_modified`, `same`, `deleted`), rejeitando IDs duplicados na coleta e bloqueando exclusões quando `is_complete=False`.
  * Implementamos `validate_candidate()` para checar antes da publicação: status `complete`, contagem e sequência exata de `chunk_id`s na candidata e execução de uma consulta vetorial real na coleção candidata.
  * Implementamos `reconcile_store_with_manifest()` para alinhar a geração ativa do `ChromaGenerationStore` ao manifesto após reinícios do processo.
  * Implementamos o orquestrador `run_delta_sync()`, recebendo `store`, `collect_fn`, `prepare_fn`, `encode_fn` e `validator_fn` por injeção de dependência, integrando diretamente com `ChromaGenerationStore` (ING-03), `PreparedChunk` / `PREPARATION_VERSION` (ING-01) e `validate_vectors` (ING-02) sem modificá-los.

* **Por que fizemos:**
  * **Separação entre conteúdo e metadados:** Como os embeddings dependem apenas do texto dos chunks e os metadados (`title`, `source_reference`) ficam na tabela `sources` do SQLite da ING-03, dois hashes independentes permitem atualizar metadados passando `reuse_from=previous_active` com **zero** vetores recalculados.
  * **Compatibilidade de versão e modelo:** Alterações em `IndexConfig` (modelo, revisão, dimensão, formato) ou `preparation_version` ativam `force_reembed=True` e desativam `reuse_from`, impedindo reaproveitamento de vetores de outro espaço vetorial (`IncompatibleIndex`).
  * **Edição sem lixo residual (5 para 3 chunks):** Ao montar sempre uma coleção candidata nova a partir da lista completa de chunks atuais via `store.create_candidate()`, trechos removidos deixam de existir automaticamente sem depender de exclusões parciais ou transações condicionais no Chroma.
  * **Proteção contra falhas e concorrência:** Coletas incompletas abortam imediatamente antes de qualquer escrita; falhas na coleta, embeddings, gravação ou validação preservam a geração ativa e o manifesto anterior; se `store.activate()` falhar após gravar o manifesto, o rollback restaura o manifesto prévio; e o lock exclusivo impede duas sincronizações simultâneas no mesmo diretório.
  * **Injeção de dependência:** Receber coleta, preparação, encoder e caminho do manifesto como argumentos evita caminhos fixos globais e permite testes isolados com `tmp_path` e injeção determinística de falhas.

---

## 3. Suíte de Testes Unitários e de Integração

### 3.1. Testes Unitários — `test/test_delta_sync.py` (24 testes)

* **O que cobre:**
  * Leitura inicial de manifesto inexistente, roundtrip com normalização `str` $\leftrightarrow$ `int`, rejeição parametrizada de 9 estruturas inválidas e preservação do arquivo anterior + limpeza de `.tmp` em erro simulado de `os.replace`.
  * Filtragem de elegibilidade de artigos e independência entre `content_hash` e `metadata_hash` (incluindo redução de 5 para 3 chunks).
  * Todas as ramificações de `calculate_delta`: carga inicial, sem mudanças, 5 categorias simultâneas, precedência de `content_modified` sobre `metadata_modified`, `force_reembed=True`, proteção contra exclusões quando `is_complete=False` e rejeição de IDs duplicados.
  * Travas de entrada de `run_delta_sync`: bloqueio de coleta incompleta sem tocar no manifesto nem chamar preparação/embeddings, validação de tipo `CollectionBatch` e trava de execução única com liberação após erro.

### 3.2. Testes de Integração com ChromaDB real — `test/integration/test_sync_publication.py` (6 testes)

* **O que cobre:**
  * **Carga inicial e execução sem mudanças:** confirma `status="no_changes"`, `vectors_computed == 0`, preservação de `last_published_at`, avanço exclusivo de `last_checked_at` e consulta real via `store.capture_active()`.
  * **Atualização somente de metadados:** confirma publicação de nova geração com `vectors_computed == 0` e título atualizado retornado nas consultas.
  * **Edição de 5 para 3 chunks e remoção de inelegíveis:** confirma exatamente 3 chunks remanescentes no Chroma e no manifesto (recalculando apenas o trecho alterado) e exclusão completa de artigo marcado como inelegível.
  * **Mudança de revisão em `IndexConfig`:** confirma recálculo completo dos vetores na nova geração sem reutilizar vetores incompatíveis.
  * **Injeção de falhas em todas as etapas + repetição:** simula erros isolados na coleta (`ConnectionError`), nos embeddings (`EmbeddingUnavailable`), na gravação Chroma (`RuntimeError`) e na validação (`CandidateValidationError`), comprovando preservação da geração ativa e do manifesto, seguido de repetição bem-sucedida.
  * **Reinícios antes e depois da publicação:** simula queda antes da troca atômica do manifesto (mantém geração 1) e queda após gravar o manifesto mas antes de `store.activate()` (ao reiniciar, `reconcile_store_with_manifest()` alinha o store à geração declarada no manifesto).

---

## 4. Evidência de Validação

* **Comando executado (a partir da raiz do repositório):**
  ```bash
  python -m pytest -q test\test_delta_sync.py .\test\integration\test_sync_publication.py
  ```
* **Resultado observado:**
  * `30 passed, 36 warnings in 3.61s` (24 testes unitários + 6 testes de integração).
  * Os 36 avisos são `DeprecationWarning` internos da biblioteca `chromadb` (`opentelemetry` e `CollectionCommon.py`), sem relação com erros no código implementado.
* **Classificação do ensaio:**
  * **Mock / unitário:** `test/test_delta_sync.py` (stubs e `monkeypatch`, sem banco real).
  * **Integração real (ChromaDB + SQLite em `tmp_path`):** `test/integration/test_sync_publication.py`, utilizando `ChromaGenerationStore` real com encoder determinístico fake (norma L2, 384 dimensões).
  * **Fora deste ensaio:** Não houve chamadas reais à API do GLPI, download/inferência real do modelo E5 nem chamadas ao Gemini.

---

## 5. Limites Conhecidos e Próximos Passos

* **Concorrência entre processos:** Assim como o controle de leitores da ING-03, o lock `_exclusive_sync_lock` atua dentro do mesmo processo Python. Caso a rotina de sincronização passe a rodar em múltiplos processos simultâneos em produção, deverá ser complementada por um lock de arquivo no sistema operacional.
* **Integração de coleta real (`GLPI-04`):** Ao conectar `run_delta_sync()` ao `article_source.py` / `GLPIClient` em produção, o adaptador de `collect_fn` deverá preservar explicitamente o indicador de completude da paginação no retorno de `CollectionBatch(articles=..., is_complete=...)`.

**Status da Task:** Implementada e validada por 30 testes automatizados (unitários e de integração real com ChromaDB), pronta para abertura de PR e revisão por outra dupla.