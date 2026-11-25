# RAG-05 — Metade A: validação de citações e de especificidades

> **Divisão do trabalho.** A RAG-05 foi dividida em duas metades para a dupla.
> Esta é a **metade A**. A **metade B** (política de saídas e casos ambíguos)
> está descrita na seção 5, com a interface que ela deve consumir.
> Base: branch com RAG-03 (`recuperar_trechos`) e RAG-04 (`GeminiAdapter`).

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

## 3. Como a RAG-01 e a metade B consomem o resultado

```python
from src.api.schemas import Source, TextReply
from src.rag.busca_artigos import recuperar_trechos
from src.rag.citation_validation import validate_answer

retrieval = recuperar_trechos(pergunta, principal, retriever=retriever)
if retrieval["status"] == "evidence":
    state = graph.invoke({"question": pergunta, "evidence": retrieval["chunks"]})
    check = validate_answer(state["answer"], state["prompt_evidence"], question=pergunta)
    if check.ok:
        reply = TextReply(text=state["answer"], sources=[Source(**s) for s in check.sources])
    # Os demais vereditos seguem para a política de saída da metade B.
```

## 4. Reprodução e resultados

Na raiz, com o ambiente Python 3.14 ativo e as dependências do README instaladas:

```bash
python --version
python -m pip check
python scripts/verify_environment.py
python -m pytest -q tests/test_citation_validation.py tests/test_model_adapter.py
python -m pytest -q test tests
```

Para repetir o ensaio com os pesos reais já disponíveis no cache local:

```bash
HF_HUB_OFFLINE=1 RAG05_TEST_REAL_MINILM=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  python -m pytest -q tests/test_citation_validation.py::test_citations_from_reopened_authorized_index
```

A fixture publica os artigos sintéticos 12 e 20 em uma geração temporária.
O leitor reabre o índice e o escopo do técnico permite apenas o artigo 12.
O gerador simulado cita `ing-01-v2:article:12:0000`. A checagem aceita esse
trecho, valida o objeto `Source` da UI e rejeita uma referência ao artigo 20.
Os contadores verificam uma pergunta e zero documentos codificados na leitura.
A execução padrão injeta um encoder espião. A execução offline usa o
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` da revisão
`e8f8c211226b894fcb81acc59f3b34ba3efd5f42` em CPU. Nos dois ensaios, o
conteúdo de origem e a resposta do gerador são sintéticos.

| Verificação local em CPython 3.14.10 | Resultado observado |
| --- | --- |
| Dependências | `pip check` sem conflitos, 14 versões fixadas e seus imports conferidos |
| Citações e adaptador Gemini com gerador simulado | 58 testes passaram |
| Suíte completa | 462 passaram em 16,05 s, zero falhas e zero ignorados |
| MiniLM real em CPU, cache local, índice reaberto | 1 teste passou em 13,78 s |

A auditoria inicial havia registrado 439 testes aprovados e seis falhas na
suíte completa. As mesmas seis ocorrências se reproduziam retirando os testes
de citações. Cinco envolviam o startup da API, o SQLite e o status da
sincronização. A sexta envolvia o diretório padrão da recuperação. Os 11
casos adicionais da auditoria também passaram após a correção, incluindo
as seis combinações de citações e identificadores que falhavam inicialmente.
O uso de GLPI e Gemini ao vivo e a jornada pelo navegador ficam para a integração.

## 5. Metade B (para a outra pessoa da dupla)

Itens restantes da RAG-05:

- [ ] **Política de saídas distintas** (sugestão: `src/rag/evidence_policy.py`)
  mapeando o retorno da RAG-03 + o veredito da metade A para a resposta final:

  | Situação | Origem | Saída |
  | --- | --- | --- |
  | Sem evidência | `status=no_evidence` (`insufficient_evidence`, `empty_index`) | recusa honesta, `answer_status="no_evidence"` |
  | Acesso negado | `reason=empty_authorized_scope` | negação **sem revelar IDs excluídos**, sem ampliar permissões |
  | Base indisponível | `status=index_unavailable` | `answer_status="index_unavailable"`; não alegar falta de conhecimento |
  | Ambiguidade | pergunta de VPN, senha ou impressora sem sistema/caminho/tipo | `ClarificationReply` perguntando sistema operacional, caminho ou tipo |
  | Resposta reprovada | `verdict != "valid"` | **não exibir a resposta gerada**; recusar ou pedir esclarecimento; nunca mostrar a fonte inválida |
  | Resposta que é recusa | resposta sem fatos novos | chamar `validate_answer(..., require_citation=False)` |

- [ ] **`docs/casos-ambuigos.md`** com pergunta, alternativas, esclarecimento e
  resultado esperado; tratar instruções encontradas nos artigos como dados.
- [ ] **`tests/test_evidence_policy.py`** (nome citado no cartão do Notion),
  sem LLM real.
- [ ] Os formatos de saída (`TextReply`, `ClarificationReply`, `answer_status`)
  são os do contrato da UI-01 (`src/api/schemas.py`).

Os arquivos da metade B não colidem com os da metade A.

## 6. Pendências e decisões em aberto

- Decidir com a RAG-01 o que fazer quando o veredito não é `valid`: recusar
  direto ou regenerar uma vez. Esta metade só entrega o veredito.
- Calibrar com perguntas reais (RAG-02) se as regras de especificidades geram
  bloqueios demais.
- Aceite completo da RAG-05 continua dependendo da metade B e de um ensaio com
  o Gemini real.
