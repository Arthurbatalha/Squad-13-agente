# Implementação da coleta paginada do GLPI

## O que foi feito

- Centralizadas no `GLPIClient` as leituras paginadas e de detalhe. `search_all()`
  aceita respostas HTTP 200/206, valida lista de objetos, `Content-Range`,
  offsets, tamanho das páginas e IDs repetidos. A paginação termina pelo total
  confirmado, inclusive quando o total é múltiplo do limite.
- O retorno de `search_all()` continua sendo compatível com uma lista e indica
  `complete`, `total`, `pages` e `endpoint`. Uma resposta parcial ou inválida,
  inclusive uma falha em página intermediária, levanta erro em vez de devolver
  uma coleção parcial como completa. Uma lista vazia HTTP 200 continua válida;
  JSON vazio/inválido em detalhe não é convertido em `{}`.
- `scripts/coletar_dados.py` deixou de implementar HTTP, autenticação e
  paginação separadamente. Usa `GLPIClient` para chamados, categorias, usuários
  e artigos; participantes são derivados do `team` dos chamados, preservando o
  objeto de membro e o vínculo com o ID do chamado.
- Os dados dos chamados não são projetados nem normalizados: `is_deleted`,
  `date`, `date_solve`, `date_close`, campos de `team` e offsets permanecem
  como recebidos.
- [api-glpi-v2.md](./api-glpi-v2.md) registra o contrato de lista/detalhe,
  completude, amostra estrutural e origem da verificação somente leitura.

## Verificação

- `python -m pytest -q test/test_glpi_pagination.py test/test_glpi_auth_client.py`:
  **29 passaram**.
- `python -m pytest -q test`: **36 passaram**.
- A coleta real somente leitura em `http://localhost:8080/api.php/v2` encontrou
  300 chamados em 12 páginas, 6 categorias, 21 usuários e 568 vínculos de
  participantes. Os campos `team`, `is_deleted`, `date`, `date_solve` e
  `date_close` estavam presentes no chamado consultado; `requester` e `assigned`
  foram observados em `team`. Listas e detalhes de chamados, categorias e
  usuários foram lidos pelo cliente comum. Não foram executadas escritas e
  nenhum valor de identidade ou conteúdo foi registrado.
- A execução de `python -m pytest -q` na raiz não concluiu a coleta: o teste
  preexistente `src/rag/test_busca_artigos.py` não pôde importar
  `sentence_transformers`, ausente no ambiente. A pasta `test/` foi executada
  integralmente com sucesso.

## Arquivo de teste

O repositório usa `test/` (singular), não `tests/`. Os novos casos de
paginação, falha intermediária, respostas inesperadas, detalhe e integração do
coletor estão em [test_glpi_pagination.py](../test/test_glpi_pagination.py).
