# ING-02 — MiniLM e corpus reutilizável (Alternativa C)

Entrega sobre `dev_v2` atualizada em `624b061`, na branch
`feat/ing-02-minilm-embeddings`. O escopo vigente substitui a antiga migração
para multilingual-e5-small: usa **sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2**,
revisão **e8f8c211226b894fcb81acc59f3b34ba3efd5f42**, CPU, 384 dimensões,
float32 e vetores normalizados em L2. Documentos e perguntas recebem texto
puro, sem `query:`/`passage:`, prefixo de título ou prompt adicional.

## Arquivos

| Arquivo | Finalidade |
| --- | --- |
| `src/rag/embeddings.py` | Adaptador lazy, revisão fixa, limites, lotes, validação e contadores. |
| `src/rag/corpus.py` | Snapshot imutável, preparação/publicação em memória e consulta. |
| `src/rag/busca_artigos.py` | Integração com o ponto de busca existente; mantém seus argumentos posicionais e resultados. |
| `src/rag/chunk_contract.py` | Centraliza também a revisão compartilhada com o tokenizer ING-01. |
| `test/test_embeddings.py`, `test/embedding_fakes.py` | Testes de contrato e concorrência com modelo espião sintético. |
| `test/test_contracts.py`, `src/rag/test_busca_artigos.py` | Exercitam os chamadores usando o novo adaptador injetado. |
| `test/test_ingestion_preparation.py` | Usa a revisão central, preservando os critérios da ING-01. |
| `scripts/verificar_embeddings.py` | Integração real em CPU, métricas e tentativa opcional de leitura GLPI. |
| `docs/ING-02-validacao.json` | Saída integral da medição real final, sem credenciais ou conteúdo GLPI. |
| `requirements.txt`, `README.md` | Dependências diretas e referência ao escopo vigente. |

`src/rag/preparation.py`, coleta, cliente GLPI, UI e laboratório não foram
alterados. Os helpers antigos por regex/palavras continuam disponíveis,
mas a busca não os utiliza para preparar entradas do encoder.

## Adaptador e limites

`EmbeddingService(model=None, model_factory=None, batch_size=32,
local_files_only=False, cache_dir=None)` aceita um modelo ou uma fábrica
injetada. A fábrica recebe `EmbeddingConfig`. Importar os módulos ou
construir o serviço não importa SentenceTransformers/Torch nem baixa pesos.
A primeira operação necessária resolve o snapshot fixo e passa a **mesma
pasta de revisão** ao SentenceTransformer para pesos e tokenizer. A partir
desse ponto, a instância é reutilizada. A busca padrão compartilha um serviço
por processo; instâncias explícitas são independentes.

- `load()`: carga explícita opcional, usada para medir essa fase separadamente.
- `prepare_source(source, source_type=...)`: delega ao preparador existente
  da ING-01 usando o tokenizer do modelo carregado.
- `encode_chunks(chunks)`: matriz NumPy `(N, 384)`; coleção vazia produz
  `(0, 384)` sem carregar o modelo. Valida os metadados da ING-01.
- `encode_question(question)`: vetor `(384,)`; rejeita pergunta vazia ou
  de tipo inválido. Não utiliza os embeddings dos documentos como entrada.
- `token_count(text)`, `runtime_info()` e `stats`: inspeção sem expor textos
  nos contadores. Estes contam entradas entregues ao encoder, inclusive se
  o resultado de um lote depois for rejeitado na validação.

Um RLock serializa carga, tokenização e inferência da instância, inclusive
em chamadas concorrentes. Lotes têm tamanho configurado no construtor.
Todos os textos são validados antes do primeiro lote: contagem com
`add_special_tokens=True, truncation=False`, orçamento **128**. O limite
efetivo `model.max_seq_length` e a dimensão são conferidos na carga.
O limite do tokenizer isolado não substitui o orçamento do encoder.

Texto já preparado dentro do orçamento é enviado sem alteração, incluindo
espaços e quebras de linha. Documento ou pergunta excedente gera
`TokenLimitError` com quantidade e limite, antes da inferência. O adaptador
não corta nem redivide silenciosamente trechos recebidos. Use novamente
a preparação da ING-01 para documentos; reduza perguntas longas.

O retorno de cada lote deve ter a quantidade correta, dimensão 384,
valores numéricos finitos e norma L2 próxima de 1 (atol 1e-5, rtol 1e-4).
Vetores zero, dimensão/quantidade errada, NaN/inf e normalização inválida
são recusados. Erros de carga/inferência geram `EmbeddingUnavailable`;
metadados/configurações inválidos geram TypeError/ValueError ou
`IncompatibleConfig`. Não há retorno parcial de corpus.

## Corpus e consultas

`PreparedCorpus` contém:

- `chunks`: tupla de mapeamentos imutáveis com todos os campos do
  `PreparedChunk`: `source_type`, `source_id`, `source_reference`, `title`,
  `chunk_id`, `content` e `preparation_version`.
- `vectors`: matriz float32 imutável, com uma linha para cada trecho.
- `metadata`: configuração completa do embedding, versão `ing-01-v2` e
  tupla ordenada de `chunk_ids`. `metadata.to_dict()` pode ser convertido
  para JSON pela futura persistência; vetores podem usar `.tolist()`.

IDs duplicados, vínculo divergente entre chunk_id e fonte, fontes com
metadados contraditórios e ordem de IDs diferente da matriz são rejeitados.
Título nunca é identidade: artigo/caso com o mesmo título e até o mesmo
ID numérico continuam distintos pelo tipo da fonte.

Exemplo com fonte **sintética**, preparação uma vez e duas consultas:

```python
from src.rag.embeddings import EmbeddingService
from src.rag.corpus import CorpusService
from src.rag.busca_artigos import buscar_artigos

encoder = EmbeddingService(batch_size=8, local_files_only=True)
search = CorpusService(encoder)
source = {
    "id": 91001, "title": "VPN (fixture sintética)",
    "content": "<ol><li>Abra a VPN.</li><li>Confira o erro VPN-FIX-691.</li></ol>",
    "source_reference": "/Knowledgebase/Article",
}
corpus = search.prepare_sources([("article", source)])
first = buscar_artigos("Como abrir a VPN?", corpus, service=search)
second = buscar_artigos("O que conferir no erro VPN-FIX-691?", corpus, service=search)
print(encoder.stats)  # documentos permanecem iguais; question_texts aumenta em 2
```

Também há `prepare_chunks(chunks)` para material já preparado e
`prepare_articles(articles)` para a coleção GLPI-04. A chamada anterior
`buscar_artigos(pergunta, artigos, limit=3)` continua válida: o serviço
padrão compara uma assinatura do conteúdo, ordem das fontes e configuração
recebidos. A segunda pergunta sobre o mesmo material reutiliza o snapshot,
inclusive quando recebe outra lista com os mesmos dados. Essa comparação
não faz nova coleta nem detecta alterações remotas sozinha.

`title` é canônico; `name` é aceito quando `title` está ausente nos exemplos
antigos. O resultado mantém `id`, `title`, `content`, `score` e acrescenta
`source_type`, `source_reference`, `chunk_id` do trecho mais pontuado. O
conteúdo é a concatenação em ordem dos trechos Markdown da fonte. Usa-se a
maior pontuação dos trechos por fonte. **0.45 é apenas o limiar provisório
anterior**, não uma qualidade de recuperação ou recusa validada.

Uma falha ao preparar uma substituição mantém o corpus válido anterior e
propaga o erro; não serve o anterior silenciosamente como se fosse o novo.
Consultas usam o snapshot capturado e permanecem alinhadas mesmo se outra
chamada publicar novo corpus. Configurações diferentes de modelo, revisão,
normalização, formato, precisão ou limite são recusadas mesmo com dimensão
igual. `batch_size` é parâmetro de execução, registrado no ensaio, não uma
identidade semântica diferente.

Sem preparação, `search.corpus`/`search.search` lançam `CorpusUnavailable`.
Um corpus válido vazio retorna `[]`, sem carga/inferência. Na interface
legada, `articles=None` representa coleção vazia. Pergunta `None`/vazia e
limite zero/negativo retornam `[]` antes de preparar; outros tipos inválidos
de pergunta ou limite são rejeitados. Um gerador de artigos deve ser
materializado uma vez, ou substituído pelo `PreparedCorpus`, para consultas
posteriores: não é possível reler um iterador já consumido.

## Ambiente e reprodução

Foi mantida a `.venv` do projeto; instalado somente o subconjunto necessário.
Os pins anteriores do requirements não foram trocados. NumPy, huggingface-hub
e psutil foram declarados como dependências diretas. O hub ficou em 1.33.0,
compatível com SentenceTransformers 6.1.0. A stack completa não foi instalada
nem declarada validada como conjunto.

Comandos Linux da reprodução (CPU, sem instalar Chroma/LangChain/Gemini):

```bash
source .venv/bin/activate
python -m pip install torch==2.15.0+cpu --index-url https://download.pytorch.org/whl/cpu
python -m pip install sentence-transformers==6.1.0 numpy==2.5.4 huggingface-hub==1.33.0 psutil==7.2.2 transformers==5.22.2 html2text==2025.4.15 requests==2.34.2 python-dotenv==1.2.4 pytest==9.2.0
python -m pip check
python -m pytest -q test/test_embeddings.py test/test_ingestion_preparation.py test/test_contracts.py src/rag/test_busca_artigos.py
python -m pytest -q test tests
python -m scripts.verificar_embeddings --batch-size 2 --threads 2 --glpi --output /tmp/ing02.json
```

Instale primeiro o PyTorch CPU para que o resolvedor não escolha CUDA.
A validação abaixo usou cache existente. Para um checkout sem pesos,
autorize explicitamente o download para a `.venv` já ignorada pelo Git:

```bash
python -m scripts.verificar_embeddings --download --cache-dir .venv/huggingface/hub --output /tmp/ing02.json
```

Sem `--download`, o ensaio é offline para o modelo e falha se a revisão
não estiver em cache. `--download` mede o tempo do snapshot_download,
incluindo checagem de cache/rede; não é uma medição isolada de vazão.
`--glpi` tenta autenticar e ler artigos por `create_client` e
`source_treatment`, sem escrita. Falha nessa leitura fica separada no JSON:
saída 0 do ensaio de embeddings não significa que o GLPI foi validado.

## Resultados e medições observadas

| Verificação | Base inicial | Final |
| --- | --- | --- |
| `python -m pytest -q test tests` | 209 aprovados (13,16 s) | 269 aprovados |
| Embeddings + ING-01 + chamadores + busca | — | 122 aprovados |
| `python -m pip check` | Sem dependências quebradas | Sem dependências quebradas |
| MiniLM real, CPU e revisão fixa | — | Concluído com fixtures e 40 artigos do GLPI |

Nenhuma falha nova ou preexistente e nenhum skip/xfail nesses comandos.
Os 122 testes específicos incluem 60 de embeddings, 55 da ING-01,
4 dos chamadores e 3 de busca. Os testes novos não carregam pesos; os
testes ING-01 usam o tokenizer real em cache, sem download.

O JSON integral em `ING-02-validacao.json` foi medido em 14/11/2026,
Linux 7.3.3-200.fc44.x86_64/glibc 2.43, Python 3.14.10, AMD Ryzen 5 3500U,
8 CPUs lógicas, 2 threads OMP/MKL e lotes de 2. Versões: SentenceTransformers
6.1.0, Torch 2.15.0+cpu, Transformers 5.22.2, tokenizers 0.23.3, NumPy
2.5.4, psutil 7.2.2, huggingface-hub 1.33.0, scikit-learn 1.9.1 e html2text
2025.4.15. Pytest no ambiente existente: 9.2.0.

| Etapa do ensaio final | Medição |
| --- | --- |
| Consulta ao cache da revisão | 0,000807 s |
| Download dos pesos | Não executado: pesos já presentes no cache |
| Carga, incluindo imports lazy de ST/Torch | 13,290 s |
| Preparação ING-01, 3 fontes sintéticas | 0,0310 s |
| Codificação de 4 trechos em 2 lotes | 0,574 s |
| Primeira pergunta de fixture, 16 tokens | 0,0780 s |
| Segunda pergunta de fixture, 19 tokens | 0,0914 s |
| RSS antes/depois da carga | 57,98 / 762,09 MiB |
| RSS depois do corpus de fixtures | 854,57 MiB |
| RSS final, após validar também o GLPI | 927,38 MiB |
| Matriz de vetores | 6.144 bytes |
| Coleta dos 40 artigos GLPI, incluindo autenticação | 2,485 s |
| Preparação e codificação dos 82 trechos GLPI | 12,358 s |
| Perguntas sobre VPN e impressora no corpus GLPI | 0,0546 / 0,0508 s |

RSS é o conjunto residente instantâneo do processo via psutil: inclui
bibliotecas, pesos e runtime. Não é pico, memória exclusiva dos vetores ou
medida de consumo total do sistema. Este é um ensaio local individual,
com cache previamente populado, sem controle de carga externa; não é SLA
nem avaliação estatística de desempenho.

As fontes são as duas fixtures ING-01 e uma longa derivada do artigo,
explicitamente sintética. Os quatro trechos tinham 43, 44, 125 e 125 tokens;
vetores finitos, normas mínima/máxima 1.0. A configuração efetiva carregada
foi 128 tokens e 384 dimensões. Nessa versão do ST, o tokenizer carregado
também ficou com model_max_length=128; o tokenizer isolado da revisão pode
declarar 512. A origem física de pesos/tokenizer foi a mesma pasta do hash.

Antes das perguntas: model_loads=1, document_batches=2, document_texts=4.
Depois das duas consultas pela função pública `buscar_artigos`: os mesmos
valores, mais question_batches=2/question_texts=2. A matriz permaneceu
byte a byte igual. Uma entrada de 642 tokens, como pergunta e documento,
foi rejeitada sem aumentar os contadores do encoder. Há um aviso do
tokenizer durante as sondagens de candidatos longos do preparador;
nenhuma dessas entradas excedentes foi enviada ao modelo.

### Integração com o GLPI e resolução da conexão

A primeira tentativa retornou `ConnectionError`, inclusive fora do sandbox.
O diagnóstico posterior confirmou `ConnectionRefusedError` (errno 111) em
`localhost:8080`, antes da autenticação. O Docker estava ativo, mas os
containers `lab-db-1` e `lab-glpi-1` estavam parados havia seis dias. O
`.env` da aplicação já continha a configuração necessária; faltava o
`lab/.env`, que configura o Compose e foi copiado de `lab/.env.example`.
Esse arquivo permanece ignorado pelo Git.

Foram iniciados os containers, imagens e volumes existentes:

```bash
# Na raiz; copia o arquivo somente se ainda não existir:
if [ ! -f lab/.env ]; then
  cp lab/.env.example lab/.env
fi
docker compose --env-file lab/.env -f lab/docker-compose.yml up -d --no-recreate --no-build --pull never
docker compose --env-file lab/.env -f lab/docker-compose.yml ps
python -m scripts.verificar_embeddings --batch-size 2 --threads 2 --glpi --output /tmp/ing02.json
```

Esse comando de inicialização pressupõe os containers/imagens já disponíveis,
como nesta execução. Para a primeira instalação do laboratório, siga o README.
O banco ficou saudável e o GLPI publicou a porta 8080. Não houve recriação
de containers, rebuild ou remoção de volumes. Nenhum código GLPI precisou
ser alterado. O laboratório permaneceu iniciado para revisão local.

O ensaio final leu **40 artigos reais da instância** pelo cliente comum e
preparou **82 trechos**, com máximo de **128 tokens**. As perguntas
“Como configurar a VPN no Windows?” e “Como instalar uma impressora de rede?”
passaram pela função pública de busca. O contador de documentos ficou em
86 antes e depois dessas consultas (4 das fixtures + 82 do GLPI), com 43
lotes de documentos e uma única carga do modelo. Apenas question_texts
aumentou de 2 para 4; a matriz permaneceu byte a byte igual.

O JSON de evidência foi atualizado com essa execução bem-sucedida às
22:44:33 UTC de 14/11/2026 (`glpi.executed=true`, `read_only=true`). Foram
realizados autenticação e leitura; não houve gravações de artigos/chamados
nem cópia de segredos para saídas ou documentos. As contagens e consultas
validam a integração de embeddings, não a qualidade completa de ranking/recusa.

## Divergências documentais e integrações seguintes

- A descrição antiga da ING-02 menciona E5. O escopo vigente fornecido para
  a Alternativa C substitui essa migração por consolidação do MiniLM.
- `armazenamento-indice.md` aponta `app/` ausente, busca lexical e contrato
  `artigo_id/titulo/texto/url/vetor`, diferente do `PreparedChunk` atual.
  Esse exemplo não foi importado nem recriado. ING-03 deverá adaptar a
  persistência ao contrato inglês e conferir toda a configuração, não só
  dimensão/modelo. Esta entrega não cria SQLite/Chroma ou outro armazenamento.
- `justificativa-arquitetura.md` descreve busca híbrida, exclusão de frameworks
  e afirmações de qualidade de uma PoC anterior. Esta entrega comprova
  codificação/reutilização, não essas afirmações nem ranking/recusa completos.
- `setup-dependencias.md` descreve BeautifulSoup, restrição de frameworks e
  download ao importar. Aqui a preparação é html2text/ING-01 e a carga é
  lazy; a importação foi testada com bloqueio de imports de modelos.
- README contém referências anteriores a E5/Chroma e validação da stack;
  foi acrescentado apenas um link de escopo para esta implementação.

**ING-03:** persistir chunks, ordem, vetores e metadados completos e rejeitar
compatibilidade parcial. **ING-04/05:** reconstrução/publicação e sincronização
com o GLPI; a troca atômica de referência aqui é somente local em memória.
**RAG-01:** manter um CorpusService por aplicação, coletar/preparar no momento
adequado e consultar o snapshot. A API ainda usa seu mock; o CLI principal
continua sendo o coletor da GLPI-04. Casos reais precisam vir do adaptador
responsável e de suas regras de elegibilidade, fora desta entrega.
