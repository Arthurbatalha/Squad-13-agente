# ING-03 — Chroma persistente com coleções por geração

Escopo: MVP, nova implementação. O índice passa a sobreviver ao reinício do
processo. Cada atualização do corpus vira uma **geração** (uma coleção Chroma
própria), que só se torna a ativa quando quem chama decide. Este módulo
**armazena e lê**; não gera embeddings, não decide autorização e não sincroniza
com o GLPI sozinho.

> Substitui, para o MVP, a decisão de `docs/armazenamento-indice.md`
> (arquivo SQLite com vetores em JSON e busca em memória). O SQLite continua
> presente, mas apenas como **controle** (ver abaixo); os vetores ficam no Chroma.

## Arquivos

| Arquivo | Finalidade |
| --- | --- |
| `src/rag/chroma_config.py` | `IndexConfig` (identidade do índice) e diretório de persistência. |
| `src/rag/chroma_store.py` | `ChromaGenerationStore`, `GenerationReader` e exceções. |
| `tests/integration/test_chroma_generations.py` | 22 testes com Chroma real em diretório temporário. |
| `.gitignore` | Ignora `data/chroma/`. |

Reaproveita, sem alterá-los, `validate_chunks` e `validate_vectors`
(`src/rag/embeddings.py`) e o contrato `PreparedChunk` da ING-01
(`src/rag/chunk_contract.py`).

## Onde os dados ficam

Diretório de persistência: variável `CHROMA_PERSIST_DIR`, ou `data/chroma/` na
raiz do projeto quando ausente (`persist_dir_from_env()`).

```
<persist_dir>/
├── chroma/            # PersistentClient: uma coleção chunks_gNNNNNN por geração
└── control.sqlite3    # controle: gerações, fontes e geração ativa
```

| Onde | O que guarda |
| --- | --- |
| Coleção Chroma `chunks_gNNNNNN` | ID = `chunk_id`; vetor; `content` como documento; metadados mínimos (`source_type`, `source_id`, `position`, `content_hash`). Métrica **cosseno** declarada na criação. |
| SQLite, tabela `generations` | **Informações da geração:** status (`building` / `complete` / `retired`), configuração, contagens, data UTC, nome da coleção. |
| SQLite, tabela `sources` | **Registros de fonte:** tipo, ID, `source_reference`, título e `chunk_ids` de cada fonte, por geração. |
| SQLite, tabela `state` | Ponteiro da geração ativa. |

Título e referência de fonte não são repetidos em cada trecho: são juntados a
partir de `sources` na leitura.

## Configuração do índice

```python
from src.rag.chroma_config import IndexConfig

config = IndexConfig(
    model="intfloat/multilingual-e5-small",
    revision="<revisão fixa do modelo>",
    dimension=384,
)
```

Campos: `model`, `revision`, `dimension`, `normalize` (sempre `True`),
`input_format` (padrão `e5:query/passage`; prefixos mudam o espaço vetorial) e
`metric` (sempre `cosine`). Valores inválidos levantam `ValueError`.

Os embeddings são produzidos **fora** do armazenamento. O `EmbeddingService`
atual aceita só MiniLM de 384 dimensões; quem produzir os vetores E5 deve
registrar aqui a revisão real do modelo.

## API

```python
from src.rag.chroma_config import persist_dir_from_env
from src.rag.chroma_store import ChromaGenerationStore

store = ChromaGenerationStore(persist_dir_from_env(), config)
```

| Método | Comportamento |
| --- | --- |
| `create_candidate(chunks, vectors=None, *, encode_missing=None, reuse_from=None) -> int` | Cria uma geração **completa, sem ativá-la**. Tudo ou nada. |
| `read_generation(n) -> GenerationSnapshot` | Lê uma geração completa (ativa ou candidata): `info`, `chunks` e `vectors` na ordem original. |
| `activate(n)` | Aponta a geração ativa para `n` (troca atômica). Exige geração completa e compatível. |
| `capture_active() -> GenerationReader` | Captura a ativa agora e abre um leitor preso a ela. |
| `active_generation()` | Número da ativa ou `None`. |
| `generations()`, `generation_info(n)`, `sources(n)` | Inspeção de gerações e dos registros de fonte. |
| `cleanup(keep_previous=1) -> list[int]` | Remove gerações descartáveis e devolve os números removidos. |

`GenerationReader` (use com `with` ou chame `close()`):

- `generation`: geração capturada.
- `query(vector, limit=3)`: lista de dicts com `chunk_id`, `content`, `score`
  (similaridade de cosseno, `1 − distância`), `source_type`, `source_id`,
  `source_reference` e `title`.

### Criar, ativar e consultar

```python
# vectors: matriz float32 (N, dimension), L2-normalizada, alinhada a chunks
gen = store.create_candidate(chunks, vectors)
store.activate(gen)                      # decisão de quem chama

with store.capture_active() as reader:   # leitura termina nesta geração
    hits = reader.query(question_vector, limit=3)
```

### Reaproveitar vetores compatíveis

```python
gen = store.create_candidate(
    novos_chunks,
    encode_missing=lambda faltantes: encoder(faltantes),  # (len, dimension)
    reuse_from=store.active_generation(),
)
```

Com `reuse_from`, o vetor é **copiado** quando o `chunk_id` existe na geração de
origem com o **mesmo conteúdo**. Só os trechos novos ou alterados vão para
`encode_missing`. Sem `vectors` e sem `encode_missing` para trechos faltantes,
levanta `ValueError`. A geração de origem precisa ser completa e ter a mesma
`IndexConfig` (senão `IncompatibleIndex`).

## Validações e erros

| Situação | Resultado |
| --- | --- |
| `chunk_id` duplicado, campos ou versão de preparação inválidos | `ValueError` / `IncompatibleConfig` (contrato ING-01); nada é criado. |
| Vetores com dimensão, quantidade, norma ≠ 1, NaN/inf | `ValueError`; nada é criado. |
| Falha no meio da criação (inclusive em `encode_missing`) | Coleção e linhas removidas; a ativa não muda. |
| Geração criada com outra `IndexConfig` (modelo, revisão, dimensão, formato) | `IncompatibleIndex` em `activate`, `capture_active`, `read_generation` e `reuse_from`. |
| Nenhuma geração ativa | `NoActiveGeneration`. |
| Geração inexistente ou já removida | `GenerationNotFound`. |
| Geração não completa em `activate`/`read_generation` | `ValueError`. |
| Coleção ausente, métrica diferente de cosseno ou contagem divergente do controle | `CorruptGeneration`. |
| Consulta com vetor sem norma 1 ou de outra dimensão | `ValueError`. |

Uma geração vazia (zero trechos) é válida; `query` nela devolve `[]`.

## Leitores e limpeza

- Um leitor capturado **termina na sua geração**, mesmo que outra seja ativada
  depois. Ele guarda a coleção e os registros de fonte daquela geração.
- `cleanup` **nunca altera a ativa** nem remove candidatas mais novas que ela.
  Remove: (a) restos de construções interrompidas (`building` sem criação em
  andamento neste processo) e (b) gerações completas **anteriores** à ativa,
  exceto as `keep_previous` mais recentes e as que têm leitor aberto.
- A remoção marca a geração como `retired` antes de apagar a coleção; se o
  processo cair no meio, a próxima limpeza conclui o trabalho.

**Limite conhecido:** a contagem de leitores vale **dentro do processo**. Se API
e rotina de sincronização rodarem em processos diferentes, a limpeza de um não
enxerga os leitores do outro; nesse caso será preciso um registro persistente de
leitores (não implementado no MVP).

## Fora do escopo

- Autorização: quem pode ver cada fonte é decidido pela camada de autorização.
- Sincronização: o armazenamento não consulta o GLPI nem ativa gerações
  sozinho; a rotina de sync chama `create_candidate` e `activate`.
- Cálculo de embeddings e ranking/limiar de recusa.

## Como validar

Na raiz do repositório, com `chromadb` e `html2text` instalados:

```
python -m pytest -q tests/integration/test_chroma_generations.py
```

Os testes usam Chroma real em diretório temporário e cobrem: reinício real
(processo separado), IDs duplicados, vetores/configuração incompatíveis,
cosseno (ângulo de 60° → score 0,5, o que L2 não produziria), candidata sem
ativação, separação entre fontes e geração, cópia de vetores, falha sem
efeito sobre a ativa, leitor preso à geração, limpeza (leitor aberto,
`keep_previous`, restos de construção) e geração vazia.

Se o arquivo de teste ficar em `test/` em vez de `tests/integration/`, ajuste
`ROOT = Path(__file__).resolve().parents[2]` para `parents[1]` e rode com
`python -m pytest` a partir da raiz.