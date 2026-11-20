# ING-03 — Índice local por gerações

Substitui o Chroma/E5 do planejamento antigo (escopo vigente: alternativa C).
Implementação: `src/rag/local_index.py`; raiz padrão `config.INDEX_DIR` (`data/index/`).

## Layout (um `LocalIndexStore` por tipo: `article`, `case`)

```
data/index/<tipo>/ACTIVE                 ponteiro para a geração ativa
data/index/<tipo>/gen-<id>/vectors.npy   float32 (n, 384), norma L2 = 1, sem pickle
data/index/<tipo>/gen-<id>/catalog.json  registros de fonte + trechos (content_hash)
data/index/<tipo>/gen-<id>/manifest.json configuração de embeddings, versão da preparação,
                                         hashes SHA-256, contagens, data, assinatura da fonte
```

## Interface (consumida pela ING-04/05 e RAG-03)

| Chamada | Efeito |
|---|---|
| `create_candidate(PreparedCorpus, source_signature=None)` | grava geração completa em pasta temporária, renomeia, relê e valida; **não** ativa |
| `read_candidate(id)` / `generation_info(id)` | leitura verificada de qualquer geração |
| `activate(id)` | revalida e troca `ACTIVE` por `os.replace` |
| `open_active()` | captura a geração ativa (context manager); termina nela mesmo se a ativa mudar |
| `reusable_vectors(chunks)` | vetores da ativa com mesmo `chunk_id` **e** conteúdo, copiados |
| `cleanup(keep_previous=1)` | remove só gerações antigas não capturadas; nunca a ativa, a anterior ou candidatas pendentes |

Erros: `CorpusUnavailable` (sem geração ativa — não é "sem resultados"), `IncompatibleConfig`
(modelo, revisão, normalização, dispositivo, dimensão ou versão da preparação diferentes),
`IndexCorrupt` (arquivo ausente/alterado, hash, contagem, ponteiro inválido).

## Fora do escopo (de propósito)

Não gera embeddings, não coleta do GLPI, não decide autorização, não sincroniza sozinho e
não define quando publicar: reconstrução, assinatura e política de publicação são da ING-04.
Capturas são contadas por processo; assume um único processo escritor.

## Validação

```
python -m pytest -q tests/integration/test_local_index.py
```
Diretório temporário, sem Gemini, sem Chroma e sem carregar o modelo (vetores sintéticos).
