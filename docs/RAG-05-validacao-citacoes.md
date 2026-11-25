# RAG-05 — Validação de citações e política de respostas

A metade A valida citações e especificidades. A metade B decide o que exibir
após uma busca ou quando falta esclarecer a pergunta. As jornadas do squad
estão em [Casos ambíguos](casos-ambuigos.md).

## 1. Lugar da validação na Alternativa C

A recuperação recebe o `Principal` da sessão. A RAG-03 consulta o escopo
autorizado sobre a matriz e o catálogo da geração publicada. A preparação
usa html2text e o MiniLM multilíngue em CPU, com 384 dimensões normalizadas.
O mesmo encoder vetoriza a pergunta na leitura. A RAG-04 recebe os trechos
selecionados e compõe o prompt. A metade A da RAG-05 confere a resposta
contra as evidências que couberam nesse prompt.

| Arquivo | Responsabilidade |
| --- | --- |
| `src/rag/citation_validation.py` | Conferir identificadores, referências e especificidades e montar a lista de fontes |
| `src/model/gemini_adapter.py` | Devolver em `GenerationResult.prompt_evidence` os trechos enviados, com o texto após o corte de orçamento |
| `src/agent_core.py` | Expor `prompt_evidence` no retorno do grafo de geração |
| `src/rag/evidence_policy.py` | Resolver esclarecimentos, distinguir recusas e entregar a resposta da UI |
| `tests/test_evidence_policy.py`, `tests/integration/test_rag05_flow.py` | Exercitar as duas metades e o caminho desde a pergunta até a fonte exibida |
| `tests/test_citation_validation.py` | Exercitar os vereditos, o orçamento e o fluxo de leitura de um índice publicado |
| `src/api/app.py`, `src/config.py` | Restaurar a configuração do índice, a sincronização no startup, a rota de status e o ciclo de vida do SQLite |
| `.python-version`, `requirements.txt`, `scripts/verify_environment.py`, `README.md`, `docs/setup-dependencias.md` | Registrar Python 3.14 e orientar a instalação e verificação das dependências vigentes |

## 2. Contrato

`validate_answer(answer, evidence, *, question="", require_citation=True)`
recebe texto e uma coleção de evidências. Cada item contém `chunk_id`,
`source_type`, `source_id`, `title` e `content`. O adaptador fornece também
`source_reference`. Ele pode encurtar ou retirar um trecho para cumprir o
orçamento. **Use o campo `prompt_evidence` da mesma geração que produziu a resposta.**

| Campo de `ValidationResult` | Significado |
| --- | --- |
| `verdict` | Em ordem de precedência, `invalid_citation`, `unsupported_specifics`, `no_citation` ou `valid` |
| `ok` | Verdadeiro para `valid` |
| `cited_chunk_ids` | IDs válidos citados explicitamente, em ordem de menção |
| `invalid_citations` | Token encontrado, tipo de referência e motivo (`not_retrieved` ou `unknown_source`) |
| `unsupported_specifics` | Códigos, versões ou menções a passos sem suporte no contexto |
| `sources` | Fontes no formato `Source` da UI, ordenadas pela primeira menção e deduplicadas por trecho |

Um ID de trecho é comparado integralmente. Uma referência como `artigo 12`,
`chamado 12` ou `/Knowledgebase/Article/12` é resolvida por tipo e ID.
Quando a resposta menciona uma fonte e explicita um trecho dela, a lista
exibe esse trecho. Título, referência e excerto da lista vêm das evidências.

Em respostas factuais, códigos como `VPN-FIX-691`, versões como `2.3.1` e
menções a `passo N` precisam de suporte no título ou texto disponível. O
código completo pode usar separadores equivalentes, como em `Windows-11` e
`Windows 11`. Um código que só aparece como parte de outro é reprovado.
Uma recusa ou um esclarecimento pode repetir termos da pergunta quando a
política do chamador usa `require_citation=False`. Citações explícitas
continuam sujeitas à validação nesse modo.

A verificação é lexical. A associação semântica de cada afirmação ao trecho
citado requer avaliação separada. Nomes, números isolados, datas por extenso
e URLs arbitrárias no texto livre estão fora das regras. Expressões como
“artigo 2” em sentido jurídico podem ser interpretadas como referência ao GLPI.

## 3. Entrada para a RAG-01

```python
from src.rag.evidence_policy import respond

outcome = respond(
    pergunta,
    history=historico_anterior,
    retrieve=lambda q: retriever.retrieve(q, principal_da_sessao),
    generate=adapter.generate,
)
reply = outcome.reply
```

`adapter` é o `GeminiAdapter` da RAG-04. O callback de geração devolve
`GenerationResult` com o texto e os trechos do prompt. Quem chama o grafo
diretamente pode passar os dois campos da mesma invocação à política:

```python
from src.rag.evidence_policy import finalize_answer

outcome = finalize_answer(pergunta_efetiva, retrieval, state["answer"],
                          prompt_evidence=state["prompt_evidence"])
```

A política confere ID, tipo, título, referência e conteúdo com o catálogo
autorizado. O conteúdo visível pode ser um prefixo do trecho. Texto gerado
sem o registro das evidências recebe `rejected/missing_prompt_evidence`.
Um registro incompatível recebe `rejected/invalid_prompt_evidence`. A UI
recebe a resposta fixa de reprovação em ambos os casos.

`outcome.kind` distingue `answered`, `clarification`, `no_evidence`,
`access_denied`, `index_unavailable` e `rejected`. A política emite as
respostas previstas em `src/api/schemas.py`. Os logs de diagnóstico contêm
códigos e contagens. A conexão ao chat fica com a RAG-01.

## 4. Verificação da branch integrada

Na raiz, com o Python 3.14 do projeto ativo, execute:

```bash
python -m pip check
python scripts/verify_environment.py
python -m pytest -q test/test_sqlite_state.py::test_create_app_bootstraps_missing_directory_and_closes_sqlite_on_shutdown
python -m pytest -q tests/test_citation_validation.py tests/test_evidence_policy.py tests/test_model_adapter.py tests/integration/test_rag05_flow.py
python -m pytest -q test tests -ra
```

O teste do SQLite cria o banco em subpastas temporárias, consulta o endpoint
de saúde e verifica que a conexão foi fechada ao sair do `TestClient`. Os mesmos
comandos de pytest podem ser usados no PowerShell com o ambiente 3.14 ativo.

| Verificação em Linux, CPython 3.14.10 | Resultado |
| --- | --- |
| Suíte inicial da `feat/rag-05` em `4ac106a` | 503 passaram e 6 falharam. Cinco falhas envolviam `state_file` e uma envolvia `INDEX_DIR` |
| Teste de `state_file` do relato de Windows, repetido isoladamente em Linux | 1 passou em 1,04 s |
| Testes de SQLite, startup e diretório do índice selecionados após o reparo | 12 passaram |
| Citações, política, adaptador e jornada integrada | 137 passaram |
| Suíte completa após integrar as correções da metade A de `0c47386` | 541 passaram em 15,62 s, zero falhas e zero ignorados |
| Suíte completa após a revisão de portabilidade do índice | 547 passaram em 14,84 s, zero falhas e zero ignorados |
| Ambiente | `pip check` sem conflitos e 14 dependências fixadas com versão e import conferidos |

### Relato de Windows sobre o índice

O teste de integridade agora restaura os bytes originais do catálogo.
Alterar o conteúdo ou converter LF em CRLF invalida o SHA-256 em ambos os
casos. A publicação da pasta de uma geração admite novas tentativas para
erros de acesso ou bloqueio do Windows. Uma negação persistente propaga o
erro ao chamador e preserva a geração ativa.

Os dez testes citados no relato passaram em Linux antes dos ajustes. Ao
simular a escrita com CRLF e, separadamente, um único `WinError 5`, foram
reproduzidas duas falhas. Após a correção, os mesmos testes, com duas
variantes para o catálogo, passaram também sob a simulação combinada
(11 casos e uma falha transitória injetada em cada uma de 11 publicações).
Para reproduzir no Windows com o ambiente do projeto ativo:

```powershell
python -m pytest -q tests/integration/test_local_index.py tests/integration/test_sync_startup.py tests/test_retrieval_contract.py -ra
```

### Ensaio offline com MiniLM real

Com a revisão `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` do MiniLM multilíngue
disponível no cache local, execute em Bash:

```bash
HF_HUB_OFFLINE=1 RAG05_TEST_REAL_MINILM=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  python -m pytest -q tests/test_citation_validation.py::test_citations_from_reopened_authorized_index tests/integration/test_rag05_flow.py
```

Os dois testes passaram em 14,60 s. Ambos publicam artigos sintéticos e
reabrem a matriz e o catálogo em diretório temporário. No primeiro ensaio, o
escopo permite apenas o artigo 12 e a validação reprova uma referência ao
artigo 20. No segundo, ambos são autorizados. A pergunta “Como configuro a VPN?”
pede o sistema operacional. A resposta “Windows” leva ao trecho
`ing-01-v2:article:12:0000` e “macOS” ao `ing-01-v2:article:20:0000`.
Nessa jornada, a leitura codificou duas perguntas e zero documentos.

O encoder e o ranking foram reais. O gerador controlado citou o primeiro
trecho do prompt. A qualidade de geração do Gemini, o GLPI ao vivo, o
navegador e a execução nativa em Windows ficam fora desta medição. O
ambiente local estava sem chave Gemini e sem configuração do laboratório.
