# CON-01 — Ferramentas gerais de consulta

## Implementação

Entrega uma camada de contratos e serviço para três operações genéricas:

- `query_detail`: detalhe por ID do chamado.
- `query_list`: listagem com filtros combináveis e paginação.
- `query_statistics`: métricas `count`, `by_category` e `by_assignee`.

Arquivos novos:

- `src/query/contracts.py`: contratos, campos fechados, tipos e limites.
- `src/query/catalog.py`: catálogo descritivo das três ferramentas.
- `src/query/resolver.py`: resolve nomes para IDs somente dentro dos registros autorizados; retorna erro em ambiguidade.
- `src/query/service.py`: execução, autorização, filtros, métricas e envelope padronizado.
- `src/query/__init__.py`: exports.
- `test/test_query_contracts.py`: testes unitários com GLPI fake.

## Contratos e validações

- Recurso permitido: `ticket`.
- Campos permitidos: `status`, `category_id`, `assignee_id`, `date_from`, `date_to`, `date_event`.
- Evento temporal permitido: `date`, `date_solve`, `date_close`.
- Período máximo: 366 dias; datas inicial/final devem ser válidas e não invertidas.
- Período requer `date_event`.
- Paginação: `limit` entre 1 e 100; `offset` não negativo.
- Métricas: `count`, `by_category`, `by_assignee`.
- Não aceita código, RSQL, campos arbitrários, identidade ou escopo vindos do LLM.

## Segurança e dependências

As ferramentas usam `AuthorizationService.authorize_tool` e a coleção filtrada por `AuthorizationService._authorized`; o `Principal` deve continuar vindo da sessão no servidor. Resolver nomes ocorre após o filtro de autorização, para não revelar categorias ou responsáveis de registros fora do escopo.

As permissões `query_detail`, `query_list` e `query_statistics` foram adicionadas ao catálogo de políticas para os papéis `client` e `staff`. Podem ser desabilitadas por `disabled_tools`.

A camada não foi ligada ao agente LangChain nesta entrega: o backend atual não tem tool-calling de consulta e o GLPI/AuthorizationService do backend real ainda está criado como placeholder/desabilitado. Integração de execução pelo LLM depende de RAG-02/SES-02 e da conexão de GLPI. A camada pode ser testada diretamente agora.

## Retorno

Todas as operações retornam `status`, `operation`, `scope`, `data`, `filters_applied`, `completeness` e `generated_at`. Status: `success`, `empty`, `access_denied` ou `query_failed`. Argumentos inválidos e ambiguidades são exceções de contrato distintas.

## Testes

Executado: `python -m pytest -q test/test_query_contracts.py` — 7 passed.

A execução da suíte completa foi tentada, mas a coleta parou por dependências ausentes no ambiente (entre elas `html2text`, `langchain` e `langgraph`); não é falha atribuída aos testes CON-01.
