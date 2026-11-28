# RAG-02 — Relatório de avaliação de recuperação de artigos

**Estado:** avaliação real executada. O conjunto produziu um candidato de
calibração (`0.53`), mas o desempenho no holdout não sustenta promovê-lo como
limiar de produção. O padrão da RAG-03 (`0.45`) permanece provisório.

## Escopo e arquitetura

A avaliação usa MiniLM multilíngue e `LocalIndexStore`, conforme a arquitetura
vigente. E5 e Chroma não fazem parte desta entrega. O pytest padrão não chama
Gemini. A busca real é executada separadamente pelo runner, contra uma geração
publicada, com os resultados de recuperação rotulados. Um ensaio Gemini mede a
interpretação/redação do modelo e não substitui essa medição.

## Artefatos

- [`tests/test_article_retrieval.py`](../tests/test_article_retrieval.py) —
  testes pytest de busca Windows/macOS, ausência de resultado e contratos do
  avaliador com encoder simulado.
- [`tests/data/article_retrieval_cases.json`](../tests/data/article_retrieval_cases.json) —
  perguntas 1–7 e 17–20, paráfrases, split de calibração/holdout, fontes
  esperadas e perguntas ambíguas que exigem esclarecimento.
- [`scripts/avaliar_recuperacao_rag02.py`](../scripts/avaliar_recuperacao_rag02.py) —
  runner opt-in da recuperação publicada, sem Gemini e sem baixar pesos.
- [`RAG-02-resultados.json`](RAG-02-resultados.json) — curva completa de
  calibração/holdout desta geração, scores por caso e configuração do encoder.
- [`RAG-02-matriz-avaliacao.md`](RAG-02-matriz-avaliacao.md) — rótulos,
  métricas e instruções de reprodução.

Os rótulos de fonte usam títulos do catálogo de seed, pois IDs GLPI variam entre
ambientes. O runner valida que todos esses títulos existam no índice ativo e
aborta com uma lista dos ausentes. Se o corpus usado for diferente, os rótulos
precisam ser revisados antes de interpretar métricas.

## Testes e coleta

- `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_article_retrieval.py test/test_embeddings.py` — **67 passaram** na checagem focada final.
- Antes da última ampliação da varredura, a usuária relatou execução completa
  com **553 passaram e 30 pulados** (583 coletados). A reprodução focada de
  `test/test_ingestion_preparation.py`
  identificou os 30 skips como casos que requerem o tokenizer MiniLM no cache
  local; os testes não falharam.
- A coleta e os asserts determinísticos não precisam de Gemini nem do MiniLM
  real. O teste existente de carga tardia confirma que importar/construir o
  serviço não carrega pesos.

## Calibração proposta

O runner varre limiares de `0.20` a `0.80` em incrementos de `0.01`, calcula
Hit@4 por fonte nas consultas respondíveis e taxa de falsa evidência nas
consultas 17–20. O candidato é o que alcança o maior número de recuperações
corretas com zero falsas evidências no split `calibration`; empates favorecem o
maior corte. O split `holdout` é medido em toda a mesma curva, mas não participa
da escolha. Se nenhum corte alcançar zero falsas evidências e pelo menos um
acerto na calibração, o runner não recomenda um candidato.

As perguntas ambíguas 5–7 sem esclarecimento ficam fora do ranking e são
registradas como `clarify_without_retrieval`, de acordo com a política da
RAG-05. As variantes após esclarecimento têm uma única fonte esperada.

## Resultado real

Execução contra a geração `01795826657589367140-2f9823`, com **40 artigos e
82 trechos**, preparada como `ing-01-v2`. Encoder: MiniLM
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, revisão
`e8f8c211226b894fcb81acc59f3b34ba3efd5f42`, CPU, 384 dimensões. Todos os títulos
rotulados foram encontrados nessa geração. Não houve chamada ao Gemini.

| Corte | Calibração: acertos respondíveis | Calibração: falsa evidência | Holdout: acertos respondíveis | Holdout: falsa evidência |
| ---: | ---: | ---: | ---: | ---: |
| `0.45` (padrão atual) | 10/10 | 2/4 | 9/10 | 1/4 |
| `0.53` (candidato da calibração) | 9/10 | 0/4 | 6/10 | 1/4 |
| `0.56` | 6/10 | 0/4 | 5/10 | 0/4 |

O candidato `0.53` cumpre o critério do split de calibração, mas perde três
paráfrases respondíveis no holdout e ainda tem uma falsa evidência. Aumentar o
corte a `0.56` removeu as falsas evidências observadas nos dois splits, ao custo
de recuperar só 6/10 e 5/10 perguntas respondíveis. A consulta de senha com
acesso ao e-mail/segundo fator foi classificada pela busca como artigo de
suporte; uma paráfrase sobre custo de licença ERP recuperou um artigo de
permissão de módulo. Esses casos mostram que um único corte ainda não resolve
os erros de ranking e a falsa evidência desta amostra.

Por isso, não alteramos `RetrievalConfig.min_similarity`: o valor `0.45` segue
provisório e `0.53` fica registrado como candidato experimental, sem promoção a
padrão. A conclusão mensurável da RAG-02 é o trade-off observado; para escolher
um corte de produção com confiança, será necessário ampliar o conjunto rotulado
com mais consultas independentes, em especial negativas e paráfrases de senha,
impressora e ERP.

Para publicar localmente o índice, com GLPI configurado e as dependências
necessárias disponíveis:

```bash
.venv/bin/python -m src.main sync
.venv/bin/python scripts/avaliar_recuperacao_rag02.py --index-dir data/index --output docs/RAG-02-resultados.json
```

O sync usa a configuração local do GLPI e instancia `EmbeddingService()`; se os
pesos não estiverem em cache, o loader pode tentar obtê-los. O runner da RAG-02
usa `local_files_only=True` e não os baixa. A reprodução desta execução foi
gravada em [`RAG-02-resultados.json`](RAG-02-resultados.json). Não registrar
credenciais nem conteúdo dos artigos neste relatório.
