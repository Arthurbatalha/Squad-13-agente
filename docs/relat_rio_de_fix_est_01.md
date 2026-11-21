# Relatório de Correção e Adequação (`fix/`)

**Task:** `fix/EST-01` — Correções de Persistência SQLite, Ciclo de Vida da API e Adequação à Alternativa C  
**Área:** 02 — Sessão, interface e persistência de estado  
**Objetivo:** Corrigir falhas de inicialização encontradas na primeira entrega da EST-01 e adequar a camada SQLite aos requisitos vigentes do plano de execução (Alternativa C), separando o checkpointer durável do registro atômico de execução de escritas.

---

## 1. Motivação do `fix/`

Na revisão da entrega original da **EST-01** frente ao plano de execução da **Alternativa C**, foram identificados dois grupos de ajustes necessários antes de avançar para a integração com o agente (`RAG-01`) e com o fluxo de escrita confirmada (`ACO-04`):

1. **Falhas técnicas de arranque e ciclo de vida:** importação relativa quebrada ao subir o Uvicorn pela raiz do repositório, ausência de criação automática da pasta pai/schema antes da conexão SQLite em máquinas limpas e ausência de encerramento explícito da conexão ao desligar o servidor.
2. **Lacunas de escopo da Alternativa C:** ausência da tabela independente de registro de execução de escritas (com transição indivisível para `executing` por `action_id`) e falta de teste comprovando a retomada real do `SqliteSaver` após fechamento e reabertura da conexão.

---

## 2. Alterações Realizadas

### 2.1. Inicialização limpa e ciclo de vida em `src/api/app.py`

* **O que foi alterado:**
  * Corrigido o import `from agent_core import build_graph` para importação absoluta `from src.agent_core import build_graph`.
  * Removida a importação não utilizada de `save_session` e adicionada a importação de `init_db` de `src.session_store`.
  * Adicionado o parâmetro opcional `state_file: Optional[Path] = None` em `create_app()`, resolvendo `target_file = Path(state_file) if state_file is not None else STATE_FILE`.
  * Garantida a criação da pasta pai (`target_file.parent.mkdir(parents=True, exist_ok=True)`) e a execução de `init_db(target_file)` antes de abrir a conexão SQLite.
  * Adicionada a chamada explícita `checkpointer.setup()` sobre `SqliteSaver(conn)`, armazenando `checkpointer`, `sqlite_conn` e `graph` em `app.state`.
  * Criado o gerenciador `@asynccontextmanager async def lifespan(app: FastAPI)` no nível do módulo, conectado ao `FastAPI(..., lifespan=lifespan)` para executar `app.state.sqlite_conn.close()` no encerramento da aplicação.

* **Por que foi feito:**
  * Garante que `uvicorn src.api.app:app` suba normalmente a partir da raiz do projeto, inclusive em máquinas recém-clonadas sem a pasta `data/` criada (requisito de reprodutibilidade da `FIN-01`).
  * Evita vazamento de descritores e arquivos `.sqlite3` travados no Windows ao encerrar o servidor ou executar testes com `TestClient`.

---

### 2.2. Gerenciador de conexão e registro atômico de escritas em `src/session_store.py`

* **O que foi alterado:**
  * Criada a constante `VALID_STATES` (`frozenset`) com os 7 estados definidos no plano da Alternativa C: `pending`, `confirmed`, `executing`, `succeeded`, `partial`, `uncertain` e `cancelled`.
  * Criado o context manager `_connect(db_path: Optional[Path] = None)`, que garante a criação do diretório pai, gerencia a transação via `with conn:` (commit automático em sucesso / rollback em exceção) e fecha a conexão no bloco `finally: conn.close()`.
  * Atualizadas `init_db`, `save_session` e `get_session` para aceitar `db_path` opcional, utilizar `_connect(db_path)` e padronizar comparações com `is None` / `is not None`.
  * Adicionada no `init_db` a tabela independente `action_executions`, com `action_id TEXT PRIMARY KEY`, `thread_id`, `version`, `operation`, `payload_json`, `staff_user_id`, `target`, `status`, `result_json`, `created_at` e `updated_at`.
  * Implementadas as quatro operações de controle de escrita:
    * `create_action_record(...)`: valida o status em `VALID_STATES`, serializa `payload`/`result` em JSON e usa `INSERT` puro (sem `OR REPLACE`) para impedir sobrescrita acidental de ações já registradas.
    * `get_action_record(action_id, db_path=None)`: retorna o registro completo já desserializado (`dict`) ou `None`.
    * `claim_action_execution(action_id, expected_version, db_path=None)`: executa um único `UPDATE` condicional (`SET status = 'executing' WHERE action_id = ? AND version = ? AND status IN ('pending', 'confirmed')`), verifica `cursor.rowcount == 1` dentro da transação e retorna `(claimed, record)` após o commit.
    * `finish_action_execution(action_id, status, result=None, db_path=None)`: valida status final (`succeeded`, `partial`, `uncertain`, `cancelled`), atualiza status e resultado em JSON e levanta `ValueError` caso o registro não exista.

* **Por que foi feito:**
  * Separa definitivamente o histórico conversacional (`SqliteSaver`) e os metadados de interface (`ui_sessions`) do livro-razão de efeitos colaterais (`action_executions`).
  * A transição atômica (*Compare-And-Swap*) em `claim_action_execution` impede que confirmações duplicadas ("Sim" enviado duas vezes) ou versões obsoletas disparem múltiplos `POST` no GLPI.
  * Passar `db_path` por parâmetro elimina a necessidade de mutar a variável global `STATE_FILE` durante os testes.

---

### 2.3. Ampliação da suíte de testes em `test/test_sqlite_state.py`

* **O que foi alterado:**
  * Substituída a sobrescrita global de `store.STATE_FILE` pela passagem explícita de `db_path=db_file` em `tmp_path`.
  * Implementados 4 testes automatizados cobrindo todas as camadas da EST-01:
    1. `test_session_persistence_and_thread_isolation`: valida gravação, leitura e isolamento entre duas threads distintas (`thread-A` e `thread-B`), além do retorno `None` para thread inexistente.
    2. `test_action_execution_lifecycle_and_atomic_claim`: valida unicidade da `PRIMARY KEY` (`sqlite3.IntegrityError`), rejeição de status inválido (`ValueError`), recusa de ação inexistente e de versão obsoleta, transição atômica para `executing`, bloqueio de confirmação repetida, gravação do resultado final em JSON e bloqueio após conclusão.
    3. `test_sqlite_saver_recovers_checkpoint_after_restart`: executa um `StateGraph` mínimo do LangGraph com `SqliteSaver`, fecha explicitamente a primeira conexão (`conn1.close()`) simulando queda/reinício do processo, abre uma nova conexão (`conn2`) sobre o mesmo arquivo `.sqlite3` e comprova a recuperação intacta do estado da thread (e isolamento de outra thread).
    4. `test_create_app_bootstraps_missing_directory_and_closes_sqlite_on_shutdown`: instancia `create_app()` apontando para subpastas ainda inexistentes, consulta `GET /api/health` via `TestClient` e comprova que a conexão SQLite é fechada pelo `lifespan` ao sair do contexto (`sqlite3.ProgrammingError` em consulta posterior).

---

## 3. Evidência de Validação

* **Arquivo validado:** `test/test_sqlite_state.py`
* **Resultado observado:** `4 passed` (100% dos testes aprovados).
* **Classificação do ensaio:**
  * **Integração local real (SQLite + LangGraph `SqliteSaver` + FastAPI `TestClient` em `tmp_path`):** valida criação real de tabelas, transações atômicas, persistência de checkpoints em disco após fechamento de conexão e ciclo de vida `lifespan` da API.
  * **Fora deste ensaio:** Não houve chamadas reais à API do GLPI nem inferência real com o Gemini (o `StateGraph` usado no teste de reinício é um grafo mínimo determinístico).

---

## 4. Alinhamento com Próximas Tasks

* **RAG-01:** `app.state.checkpointer` e `app.state.graph` já estão prontos para receber a implementação real de `build_graph(checkpointer)` com `create_agent`.
* **ACO-04:** A tabela `action_executions` e as funções `create_action_record`, `claim_action_execution` e `finish_action_execution` já fornecem a camada de idempotência necessária para proteger `open_ticket` e `add_public_followup`.
* **Documentação:** Este relatório complementa o `docs/Conclusao_task_EST-01.md` original (corrigindo também a referência ao nome do arquivo de testes para `test/test_sqlite_state.py`).

**Status do `fix/EST-01`:** Concluído e validado com 4 testes automatizados aprovados, pronto para PR e revisão.