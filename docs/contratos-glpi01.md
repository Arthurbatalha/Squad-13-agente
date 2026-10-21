# GLPI-01 — Contratos internos e plano de migração

> Estado: contrato atual testado com mocks; contrato completo de RAG ainda
> precisa ser definido e implementado pelas tarefas subsequentes.

## API externa versus contrato interno

A API do GLPI 11 devolve campos como `id`, `name` e `content`. Esses nomes
**não** devem ser renomeados dentro das requisições à API; a tradução deve
ocorrer quando os dados entram nos módulos internos.

O módulo `src/rag/busca_artigos.py` devolve atualmente resultados com:

```python
{
    "id": 123,
    "title": "Título do artigo",
    "content": "Texto do artigo sem HTML",
    "score": 0.82,
}
```

- `id`: identificador do artigo obtido do GLPI.
- `title`: título legível extraído de `name`.
- `content`: texto convertido do campo `content` recebido.
- `score`: pontuação numérica de similaridade calculada pela busca atual.

Os consumidores em `src/main.py` e no exemplo de
`src/rag/busca_artigos.py` leem `id`, `title`, `content` e `score`.
Os quatro cenários de `test/test_contracts.py` validam resultado encontrado
ou lista vazia nos dois consumidores usando mocks (sem GLPI real).

**Limites:** esse retorno não contém referências completas de fonte,
identificadores dos trechos, gerações do índice nem informações de controle
de acesso. A busca atual utiliza MiniLM, limpeza manual de HTML, chunks por
palavras e limiar de 0,45. Isso **não** atende ainda ao contrato final
aprovado na Decisão 4.

## Evolução aprovada no Planning Refactor (Decisão 4)

A próxima implementação de ingestão/RAG deverá:

1. Converter e sanitizar HTML por meio de `html2text`.
2. Dividir por estrutura e até **256 tokens**, com overlap de **32 tokens**
   apenas ao dividir a mesma unidade.
3. Gerar embeddings com `intfloat/multilingual-e5-small` via
   SentenceTransformers e armazená-los no Chroma persistente.
4. Recuperar **8 candidatos por coleção** e escolher até **4 trechos** no
   total, com no máximo **2 trechos por fonte**.
5. Apresentar referências das fontes autorizadas; aplicar regras de acesso
   por perfil antes de incluir dados nas respostas.
6. Recalibrar o limiar anterior `0.45` usando testes de recuperação; não
   transportar automaticamente o limiar do MiniLM para o E5.

O esquema definitivo de metadados, IDs de trecho, fonte e geração não
está inteiramente definido neste snapshot; deve ser fechado com a equipe e
com a Decisão 4 detalhada. **Não inventar chaves de integração nesta task.**

## Verificação

Os testes unitários atuais comprovam apenas que os consumidores leem o
contrato em inglês e tratam lista vazia. Eles não comprovam ingestão com
`html2text`, recuperação com Chroma/E5, controle de permissões, GLPI real,
Gemini, LangGraph ou front-end.

A Decisão 7 aprova frontend obrigatório para o produto final; sua
implementação é outra entrega e não faz parte da correção de ambiente.

Referência de planejamento: `Planning Refactor` exportado do Notion
(20/10/2026) e `Passagem_GLPI01_Anthonny_para_Julio.md`.
