# Relatório de Correção e Adequação (`fix/`)

**Task:** `fix/ING-04` — Migração da Sincronização e Publicação Atômica para `LocalIndexStore` (Alternativa C)

**Área:** 03 — Ingestão, indexação e sincronização do corpus (RAG)

**Objetivo:** Remover integralmente o acoplamento ao ChromaDB/E5 da entrega anterior da ING-04 e adaptar o manifesto atômico, o motor de reconstrução controlada e a suíte de testes ao contrato do `LocalIndexStore` (MiniLM + matrizes NumPy por gerações) entregue pela ING-03 na Alternativa C.

## 1. Motivação do `fix/`

Com a adoção da **Alternativa C** e a entrega da nova **ING-03** (`src/rag/local_index.py`), o armazenamento do índice local deixou de usar coleções ChromaDB com IDs numéricos sequenciais e passou a persistir gerações imutáveis em disco (`vectors.npy`, `catalog.json`, `manifest.json` e ponteiro atômico `ACTIVE`), isoladas por tipo de fonte (`article` e `case`) e com validação criptográfica via SHA-256.

Para alinhar a **ING-04** ao novo contrato sem perder as garantias já validadas (trava de concorrência, bloqueio de coleta incompleta, escrita atômica do manifesto e proteção contra falhas parciais), foi necessário:

1. **Atualizar o schema do manifesto de sincronização** para suportar `generation_id` textual (formato ordenável por nanosegundo `\d{20}-[0-9a-f]{6}`), `source_type`, `embedding_config` (MiniLM) e `source_signature`.
2. **Desacoplar o orquestrador do ChromaDB**, passando a construir instâncias válidas de `PreparedCorpus`, publicar via `LocalIndexStore.create_candidate()` + `activate()` e validar candidatas por produto escalar cosseno direto em NumPy.
3. **Generalizar elegibilidade e validação** para atender `article` e deixar o pipeline pronto para `case` (SIM-05), respeitando a checagem exata de `source_reference` definida em `src/rag/embeddings.py`.

## 2. Alterações Realizadas

### 2.1. Evolução do manifesto atômico em `src/rag/manifest.py`

* **O que foi alterado:**
  * Adicionada a constante `VALID_SOURCE_TYPES = frozenset({"article", "case"})`.
  * Atualizadas `REQUIRED_MANIFEST_KEYS` e `empty_manifest()`: substituída a chave `index_config` por `embedding_config` e incluídas as chaves obrigatórias `source_type` e `source_signature`.
  * Ajustada a validação em `validate_manifest()`:
    * `active_generation` passou a aceitar string não vazia ou `None` (em vez de inteiro positivo).
    * `source_type` valida pertencimento a `VALID_SOURCE_TYPES` com checagem prévia de tipo (`isinstance(..., str)`).
    * `embedding_config` aceita `dict` ou `None` (com `deepcopy` no retorno).
    * `preparation_version`, `source_signature`, `last_checked_at` e `last_published_at` rejeitam strings vazias ou compostas apenas por espaços.
  * Mantida intacta a persistência atômica em `save_manifest_atomic()` (arquivo temporário no mesmo diretório + `flush()` + `os.fsync()` + `os.replace()`, com remoção do `.tmp` em caso de falha) e a normalização das chaves de `sources` entre `str` (JSON) e `int` (Python).

* **Por que foi feito:**
  * Alinha a rastreabilidade do sincronizador aos identificadores textuais e à configuração `EmbeddingConfig` da ING-02/ING-03.
  * Impede a mistura acidental de manifestos entre índices de `article` e `case` e permite detectar rapidamente se o corpus global mudou pela `source_signature` sem reprocessar vetores.

### 2.2. Reconstrução controlada e publicação em `src/rag/sync.py`

* **O que foi alterado:**
  * Removidos todos os imports e chamadas ao antigo `ChromaGenerationStore`; integrados `LocalIndexStore`, `GenerationInfo`, `IndexCorrupt`, `PreparedCorpus`, `CorpusMetadata` e `IncompatibleConfig`.
  * Atualizado `SyncReport` para `generation: str`, `previous_generation: str | None`, além de incluir `source_type` e `source_signature`.
  * Adicionados `_extract_title()` (priorizando `title` e usando `name` apenas como fallback quando `title` está ausente) e `is_source_eligible(item, source_type)` com suporte explícito a:
    * `"article"`: exige `source_reference == "/Knowledgebase/Article"` e conteúdo textual válido.
    * `"case"`: exige `source_reference == "/Assistance/Ticket"` (alinhado exatamente à validação de `validate_chunks` em `src/rag/embeddings.py`) e presença de texto em `content`, `solution` ou `problem`.
  * Adicionada `compute_source_signature()`, gerando SHA-256 determinístico sobre `source_type` e todas as fontes elegíveis ordenadas por `source_id`.
  * Adaptada `validate_candidate()` para inspecionar a candidata via `store.generation_info()` e `store.read_candidate()`, conferir a lista exata de `chunk_id`s e executar validação de busca cosseno direta na matriz `float32` normalizada (`corpus.vectors @ query_vec[0]`).
  * Criada a função auxiliar `_build_prepared_corpus()`, que monta o `PreparedCorpus` completo (inclusive para corpus vazio), reaproveita vetores compatíveis via `store.reusable_vectors(all_chunks)` quando permitido e captura `(IncompatibleConfig, IndexCorrupt)` para forçar recálculo completo em trocas de modelo/revisão ou corrupção prévia.
  * Atualizada `reconcile_store_with_manifest()` para reconciliar o ponteiro `ACTIVE` do `LocalIndexStore` com `sync_manifest.json` após reinícios (inclusive se o ponteiro estiver ausente ou corrompido).
  * Consolidado o orquestrador principal em `run_sync()` (mantendo o alias `run_delta_sync = run_sync` para retrocompatibilidade): verifica saúde da geração ativa no disco, preserva o caminho rápido `no_changes` (zero embeddings, atualizando apenas `last_checked_at`), grava a candidata com `source_signature`, valida antes de publicar, grava o manifesto atomicamente, ativa o ponteiro `ACTIVE` com rollback do manifesto em caso de exceção e aciona `store.cleanup(keep_previous=...)`.

* **Por que foi feito:**
  * Elimina a dependência do ChromaDB e garante que leitores (`RAG-03`) só enxerguem gerações íntegras e previamente validadas via `LocalIndexStore.open_active()`.
  * Garante recuperação limpa diante de mudanças de configuração do MiniLM (`IncompatibleConfig`), falhas intermediárias e quedas entre a gravação do manifesto e a troca do ponteiro `ACTIVE`.

### 2.3. Atualização da suíte de testes (`test/test_delta_sync.py` e `test/integration/test_sync_publication.py`)

* **O que foi alterado:**
  * **Unitários (`test/test_delta_sync.py`):** atualizados para o novo schema do manifesto (`active_generation` textual, `source_type`, `embedding_config`, `source_signature`), validação de escrita atômica com limpeza de `.tmp`, elegibilidade de `article` (com fallback `name`) e `case` (incluindo rejeição de sufixo em `/Assistance/Ticket/100`), determinismo de `compute_source_signature`, classificações do `calculate_delta`, bloqueio de coleta incompleta e liberação da trava de execução única em erro.
  * **Integração (`test/integration/test_sync_publication.py`):** migrados do ChromaDB para `LocalIndexStore` real em `tmp_path` com vetores `float32` determinísticos de 384 dimensões (compatíveis com `DEFAULT_CONFIG`), cobrindo:
    1. Carga inicial e repetição sem mudanças (`no_changes` com zero embeddings e preservação de `last_published_at`).
    2. Atualização apenas de metadados sem reembutir vetores (`vectors_computed == 0`).
    3. Edição reduzindo um artigo de 5 para 3 chunks e exclusão completa de artigos inelegíveis.
    4. Troca de `EmbeddingConfig` forçando recálculo integral de todos os vetores sem falha por `IncompatibleConfig`.
    5. Isolamento entre stores `article` e `case` sob o mesmo diretório raiz.
    6. Injeção de falhas em coleta, encoder, gravação no `LocalIndexStore` e validação, garantindo preservação da geração ativa e sucesso na repetição posterior.
    7. Proteção de leitura concorrente via `open_active()` durante publicação + `cleanup(keep_previous=0)` e remoção posterior após liberação do *lease*.
    8. Reinícios simulados antes e depois da gravação do manifesto, validando alinhamento do ponteiro `ACTIVE` por `reconcile_store_with_manifest()`.

## 3. Evidência de Validação

* **Comando executado (ING-04):**
  ```powershell
  python -m pytest -q test\test_delta_sync.py test\integration\test_sync_publication.py
  ```
* **Resultado observado:** `36 passed` (100% dos testes aprovados, zero *warnings* de ChromaDB).
* **Validação conjunta com `fix/EST-01`:**
  ```powershell
  python -m pytest -q test\test_delta_sync.py test\integration\test_sync_publication.py test\test_sqlite_state.py
  ```
  Resultado: `40 passed` (36 da ING-04 + 4 da EST-01).
* **Classificação do ensaio:**
  * **Unitários e integração local real (`LocalIndexStore` + `PreparedCorpus` + sistema de arquivos em `tmp_path`):** valida escrita binária `.npy`, validação SHA-256, troca atômica de `ACTIVE` e `sync_manifest.json`, *leases* de leitura e recuperação pós-reinício.
  * **Fora deste ensaio:** Não houve chamadas reais à API do GLPI, inferência no Gemini nem carregamento dos pesos do modelo MiniLM (foram utilizados coletores e vetores unitários determinísticos de 384 dimensões).
* **Observação de verificação cruzada com a suíte da ING-03 (`tests/integration/test_local_index.py`):**
  * Ao executar a suíte da ING-03 em conjunto no Windows (Python 3.14), 61 testes passaram no total e houve 1 falha isolada em `tests/integration/test_local_index.py::test_detects_tampered_or_missing_files_and_never_activates_them`.
  * A causa está exclusivamente no teste da ING-03 no Windows: ao restaurar `catalog.json` com `write_text()`, o Python converte `\n` (`LF`) em `\r\n` (`CRLF`), divergindo do `catalog_sha256` gravado em modo binário (`"wb"`) pelo `LocalIndexStore`. O achado foi registrado para ajuste pela dupla responsável pela ING-03 (uso de `read_bytes()`/`write_bytes()` ou `newline="\n"`), sem alterações fora do escopo deste PR.

## 4. Alinhamento com Próximas Tasks

* **ING-05:** `run_sync()` e `SyncReport` já fornecem contrato observável completo (`status`, `generation`, `source_type`, `source_signature`, `delta`, `chunks_total`, `vectors_computed`, `checked_at`, `published_at`) para integração com o ponto de entrada de sincronização.
* **RAG-03:** A publicação atualiza atomicamente o ponteiro `ACTIVE` do `LocalIndexStore`, permitindo leitura segura via `store.open_active()` sem risco de observar gerações parciais ou removidas durante a consulta.
* **SIM-05:** O suporte a `source_type="case"` em `manifest.py` e `sync.py` (com elegibilidade validada para `/Assistance/Ticket`) permite reaproveitar o mesmo motor de reconstrução e publicação para o índice de casos históricos.

**Status do `fix/ING-04`:** Concluído e validado com 36 testes automatizados aprovados (40 em conjunto com `fix/EST-01`), pronto para PR e revisão.