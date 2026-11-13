# AUTH-01 — Políticas de acesso e projeção de dados

Dependências: SES-01 (identidade/sessão) e GLPI-03 (`search_all`/`get_by_id`, só leitura).

| Arquivo | Papel |
| --- | --- |
| `src/authorization/policies.py` | `Principal`, regras por recurso, tabela de ferramentas, erros. |
| `src/authorization/projections.py` | Projeções por lista de campos: original, resumo, caso preparado, artigo. |
| `src/authorization/service.py` | `AuthorizationService` (tools, API do front) e `as_model_data` (retorno ao modelo). |
| `test/test_authorization.py` | 49 testes com GLPI simulado e `test/fixtures/authorization/tickets.json`. |

Ordem em toda operação: ferramenta permitida → recurso autorizado → projeção → só então cálculo ou envio ao Gemini. Nada é cacheado, então uma revogação vale na chamada seguinte.

## Regras

- **Cliente** lê o original só se estiver em `team` com `type: User`, `role: requester` e `id` igual ao da sessão. Estatística e lista cobrem só os próprios chamados.
- **Staff** lê qualquer chamado fora da lixeira e tem estatística global. Vê acompanhamentos privados apenas nos chamados em que integra a equipe.
- **Lixeira** (`is_deleted`) é excluída para todos. `is_deleted`, `team` ou `is_private` ausentes ou malformados negam (fail closed).
- **Acompanhamento privado**: só `is_private` booleano falso sai para o cliente; `Task` e tipos desconhecidos nunca saem.
- **Ranking global** (`ranking_global`) é bloqueado para todos. Ferramenta desconhecida ou em `disabled_tools` é negada.
- **Artigos** são base compartilhada para qualquer sessão válida; `is_faq` não é critério (regra de `source_treatment`).
- **Conjunto autorizado vazio** levanta `EmptyAuthorizedSet`: nada é calculado nem enviado.
- **Inexistente e não autorizado** devolvem a mesma mensagem (`Recurso indisponível.`), sem enumeração de IDs.
- **Conteúdo recuperado é dado**: nenhuma regra lê texto de chamado/artigo. O que vai ao modelo passa por `as_model_data`, que marca `trust: untrusted_data`.

## Projeções

- Original (cliente): `id, title, content, status, category, priority, date, date_solve, date_close, followups (públicos), solution, assigned_to`. Staff acrescenta `team`.
- Caso técnico preparado: `id, title, problem, solution, source_reference`. Sem pessoas, equipe nem acompanhamentos. Exige solução registrada.

## Suposições a confirmar com a equipe

1. "Escopo previsto" do staff não está definido nos documentos; adotei o descrito acima.
2. Casos preparados para cliente só vêm dos próprios chamados; o histórico de outras pessoas é do staff.
3. SES-01 só cria sessões `staff`. `Principal.client(id)` existe, mas falta o fluxo de sessão de cliente.
4. `similar_cases` só lê a timeline de chamados com `date_solve`/`date_close`.

## Validação

```bash
python -m pytest -q test/test_authorization.py
```
