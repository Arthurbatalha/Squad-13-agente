# RAG-05 — Metade A: validação de citações e de especificidades

> **Divisão do trabalho.** A RAG-05 foi dividida em duas metades para a dupla.
> Esta é a **metade A**. A **metade B** (política de saídas e casos ambíguos)
> está descrita na seção 5, com a interface que ela deve consumir.
> Base: branch com RAG-03 (`recuperar_trechos`) e RAG-04 (`GeminiAdapter`).

## 1. O que a metade A entrega

| Arquivo | Finalidade |
| --- | --- |
| `src/rag/citation_validation.py` | `validate_answer(...)`: confere citações e especificidades da resposta gerada |
| `tests/test_citation_validation.py` | 28 testes, sem LLM, sem rede, sem índice |
| `docs/RAG-05-validacao-citacoes.md` | Este documento |

Só biblioteca padrão do Python. Nenhum arquivo existente foi alterado.

Cobre o primeiro item da checklist da RAG-05 ("verificar se os IDs citados
pertencem às fontes recuperadas e se a resposta tem suporte no conteúdo;
bloquear fontes inexistentes") e o critério "nenhuma fonte inexistente é
apresentada / a resposta não inventa passos, versões…".

## 2. Contrato

```python
from src.rag.citation_validation import validate_answer

result = validate_answer(
    answer,               # texto gerado pela RAG-04 (GenerationResult.text)
    evidence,             # EXATAMENTE a lista enviada ao GeminiAdapter
    question=pergunta,    # opcional: termos da pergunta podem ser repetidos
    require_citation=True # False para recusa/esclarecimento
)
```

`evidence` é `result["chunks"]` da RAG-03 quando `status == "evidence"`. Cada
item precisa de `chunk_id`, `source_type`, `source_id`, `title` e `content`
(`source_reference` é opcional); senão levanta `ValueError`, igual ao adaptador
da RAG-04. **Passe a lista que o gerador realmente recebeu**: o adaptador usa
no máximo 4 evidências e pode encurtar o conteúdo; a validação é mais
permissiva que o prompt (usa o trecho inteiro), o que evita falso bloqueio mas
não pega uma frase que só existia na parte cortada.

### Retorno (`ValidationResult`)

| Campo | Significado |
| --- | --- |
| `verdict` | `valid`, `no_citation`, `invalid_citation` ou `unsupported_specifics` |
| `ok` | `True` só se `verdict == "valid"` |
| `cited_chunk_ids` | citações válidas, na ordem em que aparecem |
| `invalid_citations` | lista de `{token, kind, reason}`; `reason` é `not_retrieved` ou `unknown_source` |
| `unsupported_specifics` | códigos, versões e "passo N" que a resposta traz e as evidências não |
| `sources` | fontes para exibir, **no formato `Source` do contrato da UI-01** |

`to_dict()` devolve tudo em JSON. Precedência do veredito:
`invalid_citation` > `unsupported_specifics` > `no_citation` > `valid`.

### O que é checado

1. **`chunk_id` citado** (`versão:tipo:id:ordinal`) precisa estar nas evidências.
   O padrão é frouxo de propósito: `…:00000`, `…:000` ou outra versão são
   reprovados como "quase certos".
2. **Referências** "artigo 12", "chamado 34" e `/Knowledgebase/Article/12`
   precisam apontar uma fonte fornecida. **O ID só vale com o tipo**: artigo 12
   não autoriza caso 12. Uma referência conhecida conta como citação.
3. **Especificidades**: códigos com dígito (`VPN-FIX-691`), versões (`2.3.1`) e
   "passo/etapa/step N" precisam existir no título/conteúdo das evidências ou
   na pergunta. Comparação com limites (`691` ≠ `6910`, `2.3` ≠ `2.3.1`) e
   `-`/`_` equivalentes a espaço (`Windows-11` = `Windows 11`).
4. **Fontes exibidas** vêm do catálogo recuperado. Título/referência escritos
   pelo modelo nunca chegam à tela.
5. **Instrução dentro de artigo** é dado: um trecho que mande "cite o artigo
   999" não autoriza a citação (testado).

### O que NÃO é checado (limites)

- **Suporte semântico.** Não prova que a frase decorre do trecho. Isso é
  avaliação da RAG-02 e revisão humana.
- Números simples, nomes, autoria e datas por extenso.
- Se a resposta é uma recusa: a metade B decide e chama com
  `require_citation=False`.
- A pergunta conta como origem das especificidades (a recusa precisa poder
  repeti-la). Uma pergunta que traga "passo 2" deixa passar um "passo 2"
  inventado; a RAG-03 já mitiga isso exigindo `passo N` literal (`required_evidence`).
- Falsos positivos possíveis: "artigo 2" em sentido jurídico, versões como
  "3.1" de seção. A falha é fechada de propósito.

## 3. Como ligar (RAG-01 / metade B)

```python
retrieval = recuperar_trechos(pergunta, principal, retriever=retriever)
if retrieval["status"] == "evidence":
    resposta = graph.invoke({"question": pergunta,
                             "evidence": retrieval["chunks"]})["answer"]
    check = validate_answer(resposta, retrieval["chunks"], question=pergunta)
    if check.ok:
        reply = TextReply(text=resposta, sources=[Source(**s) for s in check.sources])
    # senão: não exibir `resposta`; ver metade B
```

## 4. Como foi verificado

| Verificação | Resultado |
| --- | --- |
| 28 testes de `tests/test_citation_validation.py` | **28 passed** |
| Mutações no validador (limites de palavra, chunk não recuperado, tipo ignorado, fonte do modelo, precedência) | Cada uma derruba de 1 a 8 testes |
| `GeminiAdapter` real da RAG-04 com **modelo falso** + `validate_answer` | `valid` / `invalid_citation` / `unsupported_specifics` nos três casos esperados |

**Atenção ao ambiente:** neste ambiente o `pytest` não estava instalado, então
os 28 testes foram executados com um executor mínimo próprio e o `pytest.raises`
simulado. **Rode com o pytest do projeto antes de abrir o PR:**

```bash
python -m pytest -q tests/test_citation_validation.py
python -m pytest -q test tests     # suíte completa, para ver regressões
```

**Não verificado:** chamada ao Gemini real, a suíte completa do projeto,
`recuperar_trechos` com MiniLM real, integração pelo frontend. Os testes usam
evidências sintéticas no formato da RAG-03. Isso comprova a **mecânica**, não a
qualidade das respostas reais.

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
