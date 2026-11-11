# ING-01 — Contrato e aceite da preparação (Área 3)

Preparação da Alternativa C implementada em `src/rag/preparation.py`: contrato em
`src/rag/chunk_contract.py`, fixtures sintéticas em `test/fixtures/ing01/`
e aceite em `test/test_ingestion_preparation.py`. GLPI-04, busca, sessões,
UI e laboratório foram preservados. Não há embeddings, índice ou acesso à rede
no preparador. O escopo segue este contrato e os critérios da ING-01;
não foi encontrado outro arquivo local do plano atualizado da Alternativa C.

## Formato comum de trecho

Exemplo **sintético**, após converter o HTML com `html2text`:

```json
{
  "source_type": "article",
  "source_id": 91001,
  "source_reference": "/Knowledgebase/Article",
  "title": "VPN indisponível",
  "chunk_id": "ing-01-v2:article:91001:0000",
  "content": "## VPN indisponível\n\nARTIGO-FIXTURE-91001\n\n  1. Abra o cliente VPN.\n  2. Confira o erro `VPN-FIX-691`.\n  3. Reconecte a VPN.",
  "preparation_version": "ing-01-v2"
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

A fixture longa tem menos de 120 palavras e mais de 128 tokens reais:
o corte atual por palavras não garante esse limite. Há cenários de mesmo
título para dois artigos, artigo/caso e mesmo ID numérico entre tipos, com
vários trechos e ordem de processamento invertida.

## Implementação e validação da entrada

`prepare_source` recebe o tokenizer por injeção, converte com `html2text`
(`body_width=0`) e agrupa linhas enquanto o texto final cabe no orçamento.
Uma linha longa é dividida entre palavras; uma palavra que sozinha excede
o orçamento é dividida entre caracteres. As fatias mantêm o texto original
convertido, sem decodificar subwords, truncar a cauda ou adicionar overlap.
Títulos e códigos que cabem na unidade são mantidos; uma unidade maior que
o limite pode continuar no trecho seguinte. O título de metadados não é
prefixado ao conteúdo. A entrada não é modificada.

Na versão **ing-01-v2**, a numeração respeita `ol start`, `li value` e
`ol reversed`. `value` redefine o número do item e a sequência seguinte;
`reversed` decrementa a sequência. Sem `start`, uma lista invertida começa
na quantidade de seus próprios itens, sem contar itens das sublistas.
Cada lista aninhada mantém contador independente; `value` em lista não
numerada não altera seus marcadores. Zero e números negativos são preservados.
Atributos numéricos inválidos usam a sequência implícita.

Uma primeira passagem com `HTMLParser` conta os itens. Uma extensão pequena
de `HTML2Text` ajusta apenas o contador antes de converter cada `li`; o
restante da conversão continua no html2text, sem reescrever o conteúdo HTML.
Essa extensão depende de `HTML2Text.list` e `ListElement.num` da versão
fixada 2025.4.15; executar os testes de numeração ao atualizar a biblioteca.
A mudança de regra exige a nova versão, conforme o contrato. Trechos v1
eventualmente persistidos devem ser substituídos na futura reindexação.

- `TypeError`: entrada não é mapeamento; `id` não é inteiro (inclusive bool);
  campos textuais não são strings; orçamento não é inteiro (inclusive bool);
  tokenizer não fornece `encode` chamável.
- `ValueError`: campo obrigatório ausente; ID negativo; string vazia;
  tipo de fonte inválido; referência incompatível com artigo/caso;
  HTML sem texto após conversão; orçamento fora de 1 a 128 ou insuficiente
  para especiais/conteúdo. ID zero é aceito, coerente com a coleta existente.
- `max_tokens` pode reduzir o orçamento, nunca aumentá-lo além de 128.
  Usar a mesma configuração e revisão de tokenizer por versão da preparação;
  mudar esses parâmetros na futura indexação exige nova versão e reprocessamento.

Os testes adicionais cobrem campos inválidos, limites configuráveis, HTML
sem texto, linhas e palavras extensas, listas aninhadas e blocos de código.
Também comparam a concatenação dos trechos com o Markdown completo das
fixtures, além de verificar os metadados e a contagem real de tokens.

## Ambiente e reprodução (Windows / PowerShell)

Em 10/11/2026, somente CPython **3.14.5** estava disponível no gerenciador;
não havia Python 3.11/3.12 instalado. A `.venv` foi criada com esse Python,
com `include-system-site-packages = false`, e já era ignorada pelo `.gitignore`.
Nenhum pacote foi instalado no Python global. Ao consultar `py list`, o
gerenciador informou atualização automática dele próprio para 26.4;
o interpretador continuou 3.14.5.

Compatibilidade do subconjunto usado: [pytest 9.1.1](https://pypi.org/project/pytest/9.1.1/)
requer Python >=3.10; [html2text 2025.4.15](https://pypi.org/project/html2text/2025.4.15/)
requer >=3.9; [transformers 5.22.2](https://pypi.org/project/transformers/5.22.2/)
requer >=3.11 e lista suporte a 3.14. Instalação e testes confirmaram este
subconjunto em 3.14.5. O `requirements.txt` recomenda 3.13 para a validação
da stack completa; essa validação continua fora desta task.

Foram preservados todos os pins existentes. Instalado apenas o necessário
à preparação e às importações dos testes, sem PyTorch/SentenceTransformers,
ChromaDB ou LangChain. `transformers` não tem pin direto no requirements;
5.22.2 foi escolhido para reproduzir a versão registrada no aceite anterior.
O resolvedor instalou `tokenizers==0.23.3`. `requirements.txt` não foi alterado.

```powershell
# Apenas para um checkout sem ambiente:
python -m venv .venv
# Na retomada, a .venv já existia, mas faltava pip:
.\.venv\Scripts\python.exe -m ensurepip --upgrade
.\.venv\Scripts\python.exe -m pip install --disable-pip-version-check pytest==9.1.1 html2text==2025.4.15 requests==2.34.2 python-dotenv==1.2.4 tzdata==2026.4 transformers==5.22.2
.\.venv\Scripts\python.exe -m pip check

# Cache isolado dentro da .venv; download apenas do tokenizer, uma vez:
$env:HF_HOME = Join-Path (Get-Location) '.venv/huggingface'
.\.venv\Scripts\python.exe -c 'from transformers import AutoTokenizer; AutoTokenizer.from_pretrained("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", revision="e8f8c211226b894fcb81acc59f3b34ba3efd5f42")'

# Evita o cache do pytest que sofreu restrição de permissão neste ambiente:
$env:PYTEST_ADDOPTS = '-p no:cacheprovider'
.\.venv\Scripts\python.exe -m pytest -q -rx test/test_ingestion_preparation.py
.\.venv\Scripts\python.exe -m pytest -q -rx test --tb=short
```

Os testes usam `local_files_only=True`: não baixam o tokenizer. Sem
`transformers` ou sem tokenizer em cache, os cenários que dependem dele
aparecem como skip, não como aceite. Já `html2text` é dependência obrigatória
importada diretamente pelo preparador: sua ausência causa erro de importação
na coleta dos testes, não skip. As dependências das importações de GLPI/config
também precisam estar instaladas.
O aviso de ausência de PyTorch é esperado: apenas tokenização é necessária.
No Windows o cache funcionou por cópia, sem exigir habilitação de symlinks.

## Resultados reais desta implementação

Branch `feat/ing-01-contrato-testes`, HEAD inicial `bc4193b`, base
`origin/dev_v2` local em `408f7d8`. Árvore inicialmente limpa.

| Execução | Resultado |
| --- | --- |
| Inicial, antes do cache do tokenizer | 1 passed, 8 skipped; 1 aviso de permissão no cache do pytest |
| Inicial com tokenizer real, antes da implementação | 2 passed, 7 xfailed (6,62 s) |
| Implementação com marcas antigas | 2 passed, 7 XPASS(strict), saída 1: requisitos antigos satisfeitos |
| ING-01 com marcas removidas e testes adicionais | 43 passed (8,58 s), sem skips/xfails |
| Suíte completa dentro do sandbox | 91 passed, 2 failed, 1 error de permissão em tmp_path |
| Suíte completa fora do sandbox | 92 passed, 2 failed (5,42 s) |
| `pip check` | No broken requirements found |

Após a revisão final, ainda em 10/11/2026, a correção de numeração especial
foi validada com os mesmos comandos e ambiente:

| Execução após a correção (ing-01-v2) | Resultado |
| --- | --- |
| ING-01 | **55 passed (8,01 s)**, sem skips/xfails |
| Suíte completa fora do sandbox | **104 passed, 2 failed (5,57 s)** |

Os 43 cenários anteriores continuam passando. Os 12 novos verificam
`start`, `value`, `reversed` com e sem início explícito, redefinição da
sequência, zero/negativos, atributo booleano presente, atributos inválidos,
listas aninhadas e independentes, lista não numerada e documento dividido
em vários trechos. Os resultados esperados são explícitos e não usam
html2text como oráculo. O cenário longo também verifica título, ordem das
etapas, código de erro, cauda, metadados e limite real de 128 tokens.

O `ensurepip` precisou ser repetido fora do sandbox após `PermissionError`
no temporário do Windows. A suíte completa também precisou dessa repetição
por acesso negado em `Temp/pytest-of-julio`; o erro de configuração desapareceu.
Instalação/download foram feitos com autorização de acesso fora do sandbox.

As duas falhas restantes, já registradas antes da ING-01, são
`test/test_contracts.py::test_main_displays_search_results[True/False]`:
esperam resultados da busca na CLI, enquanto a implementação atual coleta
artigos e o mock retorna uma lista em vez de `GLPICollection`. CLI e coleta
não foram alteradas. A suíte completa não está verde; a ING-01 está.

## Limitações e próximas tasks

- Conectar preparação à coleta/busca e alinhar `title`/`name` na integração.
- A dupla de casos deverá fornecer o adaptador e selecionar chamados com solução.
- Implementar embeddings, persistência e substituição de trechos antigos por fonte
  em tasks próprias. Não foram implementados ChromaDB, E5, agente ou frontend.
- A conversão segue o comportamento do html2text, não preserva HTML bruto.
  Um bloco maior que o orçamento pode atravessar trechos; não se garante
  Markdown renderizável isoladamente em cada trecho nem desempenho em grandes lotes.
- HTML vazio é rejeitado explicitamente, em vez de gerar trecho vazio.
  A revisão do tokenizer e o orçamento precisam permanecer constantes para
  estabilidade dos IDs/conteúdo dentro da mesma versão.
- O preparador converte conteúdo, mas não sanitiza URLs. Links potencialmente
  inseguros (por exemplo, `javascript:`) podem permanecer no Markdown.
  A futura interface deverá validar protocolos e renderizar conteúdo com
  segurança. Também deverá respeitar os números explícitos do texto:
  renderizadores Markdown podem renumerar listas invertidas ou descontínuas.
  Nenhuma funcionalidade de interface foi implementada nesta task.
- Esta execução valida preparação e testes locais com simulações, não GLPI real,
  embeddings, qualidade de busca nem compatibilidade da stack completa fixada.
