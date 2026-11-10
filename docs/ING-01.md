# ING-01 — Contrato e aceite da preparação (Área 3)

Preparação antecipada da Alternativa C: contrato em
`src/rag/chunk_contract.py`, fixtures sintéticas em `test/fixtures/ing01/`
e aceite em `test/test_ingestion_preparation.py`. O preparador ainda não
está implementado; GLPI-04, busca, sessões, UI e laboratório foram preservados.

## Formato comum de trecho

Exemplo **sintético**, após converter o HTML com `html2text`:

```json
{
  "source_type": "article",
  "source_id": 91001,
  "source_reference": "/Knowledgebase/Article",
  "title": "VPN indisponível",
  "chunk_id": "ing-01-v1:article:91001:0000",
  "content": "## VPN indisponível\n\nARTIGO-FIXTURE-91001\n\n  1. Abra o cliente VPN.\n  2. Confira o erro `VPN-FIX-691`.\n  3. Reconecte a VPN.",
  "preparation_version": "ing-01-v1"
}
```

- `source_type`: `article` ou `case`; `source_id`: ID inteiro original do GLPI.
  Casos usam `source_reference: /Assistance/Ticket`. A dupla de casos ainda
  deverá fornecer o adaptador, incluindo a seleção de chamados com solução.
- Entrada: `id`, `title`, `content` HTML e `source_reference`, compatível com
  `source_treatment()`. A GLPI-04 já converte `name` em `title`; esse título é
  o valor canônico. A busca atual ainda lê `name`: alinhar na integração.
- `content` na saída é texto com a estrutura Markdown do `html2text`
  (`body_width=0`), preservando títulos, números, instruções e códigos.
  `title` permanece metadado, sem prefixo adicional obrigatório no texto.
- `chunk_id`: `{preparation_version}:{source_type}:{source_id}:{ordinal:04d}`,
  com ordinal por fonte começando em zero. Nunca usar título ou posição no
  lote como identidade. Mesma entrada e versão produzem os mesmos trechos.
  Alterar regras/configuração exige nova versão. Ao reprocessar conteúdo
  alterado, a futura indexação deverá substituir os trechos antigos da fonte.

## Limite e testes

O MiniLM atual aceita **128 tokens incluindo os especiais**, conforme o
[sentence_bert_config.json do modelo](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/blob/e8f8c211226b894fcb81acc59f3b34ba3efd5f42/sentence_bert_config.json).
Os 512 de `tokenizer.model_max_length` não são o orçamento da preparação.
Contar cada `content` final com o tokenizer real, `add_special_tokens=True`
e `truncation=False`; nenhum trecho pode ultrapassar 128 ou perder a cauda.
Se a integração acrescentar título ao texto enviado ao modelo, recontar tudo.

```bash
python -m pytest -q test/test_ingestion_preparation.py -rx --tb=short
python -m pytest -q test
```

Dependências adicionais mínimas: `python -m pip install html2text==2025.4.15 transformers`
(também fazem parte da stack, diretamente ou via SentenceTransformers).
Os testes não baixam modelos. Para preparar apenas o tokenizer uma vez, se
ele ainda não estiver no cache, execute com rede:

```bash
python -c 'from transformers import AutoTokenizer; AutoTokenizer.from_pretrained("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", revision="e8f8c211226b894fcb81acc59f3b34ba3efd5f42")'
```

A fixture longa tem menos de 120 palavras e mais de 128 tokens reais:
o corte atual por palavras não garante esse limite. Há cenários de mesmo
título para dois artigos, artigo/caso e mesmo ID numérico entre tipos, com
vários trechos e ordem de processamento invertida.

## Próxima dupla

Implementar `src.rag.preparation.prepare_source` com a assinatura `PrepareSource`,
converter via `html2text` e fracionar sem truncamento usando o tokenizer
injetado. Os sete cenários pendentes usam `xfail(strict=True)` **somente**
para a ausência desse módulo; erros internos e asserções falham normalmente.
Ao implementar, retirar as marcas: um sucesso passa a ser XPASS estrito.
Sem dependências/cache, os testes que usam o tokenizer aparecem como skip.
Depois conectar coleta e busca e alinhar `title`/`name` na virada de área.
Embeddings e índice continuam nas próximas tasks.

Validação local sobre a base `408f7d8`: antes, **49 aprovados e 2 falhas**;
depois, teste específico **2 aprovados e 7 xfailed** e suíte **51 aprovados,
2 falhas e 7 xfailed**. Nenhuma falha nova. As duas falhas preexistentes são
`test/test_contracts.py::test_main_displays_search_results[True/False]`:
esperam busca na CLI que hoje coleta artigos. Os sete xfails não comprovam
preparação: aguardam implementação. A fixture longa mediu **96 palavras e
740 tokens**; as curtas, 43 e 44 tokens. Ambiente: Python 3.14.10, pytest
9.2.0, html2text 2025.4.15, transformers 5.22.2 e tokenizers 0.23.3, com
tokenizer real já em cache. Isso não valida a stack completa fixada no projeto.
