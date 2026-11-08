# UI-01 — Contrato front–backend

> Estado: implementado e **executado em 08/11/2026 com o adaptador simulado
> (mock)**. Nada foi testado contra GLPI real, índice de recuperação ou Gemini.
> Evidência na seção 8.

## 1. Decisões registradas

| Tema | Escolha | Observação |
| --- | --- | --- |
| Front | React + Vite (JavaScript) | Vite é ferramenta de build, trocável. |
| Back | FastAPI executado por Uvicorn | Rotas sob `/api`. |
| Transporte | JSON sobre HTTP, uma resposta por requisição | Sem streaming nesta task. |
| Identidade | Papel **sempre** `staff`, definido no servidor | O cliente só escolhe `character_id`. |
| Segredos | Nenhum token/credencial do GLPI cruza a API | Testado. |
| Confirmação | Textual ("sim"/"não") pela rota de mensagens; rota `decisions` já existe para os botões de ACO-03 | Ambas vinculadas a `action_id` + `version`. |
| Dev vs. demo | Dev: Vite (5173) com proxy para Uvicorn (8000). Demo: `npm run build` e o FastAPI serve `frontend/dist` | CORS restrito a `CORS_ORIGINS`. |

## 2. Rotas

| Método e rota | Entrada | Saída |
| --- | --- | --- |
| `GET /api/health` | — | `{status, adapter}` |
| `GET /api/characters` | — | `{characters: [{id, name}]}` |
| `POST /api/sessions` | `{character_id}` | `SessionInfo` (201) |
| `GET /api/sessions/{thread_id}` | — | `SessionInfo` (inclui `pending_action`) |
| `POST /api/sessions/{thread_id}/messages` | `{text}` (1–4000, não vazio) | `{thread_id, reply}` |
| `POST /api/sessions/{thread_id}/decisions` | `{action_id, version, decision: yes\|no\|edit, text?}` | `{thread_id, reply}` |

`SessionInfo`: `thread_id`, `role` (`"staff"`), `character`, `adapter` (`mock`\|`real`), `pending_action`.

## 3. Tipos de `reply` (campo `type`)

| `type` | Quando | Campos principais |
| --- | --- | --- |
| `text` | Resposta/recusa | `text`, `sources[]`, `answer_status`: `answered` \| `no_evidence` \| `index_unavailable` |
| `clarification` | Pergunta ambígua | `question`, `options[]` |
| `preview` | Escrita aguardando confirmação | `action`: `action_id`, `version`, `operation` (`open_ticket` \| `add_public_followup`), `staff_user_id`, `payload`, `preview_text` |
| `write_result` | Desfecho da escrita | `action_id`, `status`: `succeeded` \| `partial` \| `uncertain` \| `cancelled`, `ticket_id?`, `message` |

`Source`: `source_type` (`article`\|`case`), `source_id`, `title`, `reference`, `chunk_id?`, `excerpt?`.

Os estados `confirmed` e `executing` do plano são internos do backend/registro de execução (ACO-04) e não aparecem como `reply`; a API só devolve o desfecho.

## 4. Erros

Sempre `{"error": {"code", "message", "retryable", "details": [{"field", "reason"}]}}`. Nunca devolve o valor enviado.

| HTTP | `code` | Causa |
| --- | --- | --- |
| 404 | `session_not_found`, `character_not_found` | IDs inexistentes |
| 409 | `action_pending` | Mensagem que não é sim/não com ação pendente (nada é gravado) |
| 409 | `no_pending_action` | Decisão sem ação pendente |
| 409 | `stale_action_version` | `action_id`/`version` não é a prévia atual |
| 422 | `invalid_request` | Corpo inválido, campo extra (`role`, `token`…), texto vazio/longo, `edit` sem `text` |
| 503 | `backend_unavailable` | Reservado ao adaptador real |
| 500 | `internal_error` | Falha inesperada (mensagem genérica) |

Confirmar de novo uma ação já decidida devolve o **mesmo** `write_result`, sem executar outra vez.

## 5. Adaptador simulado

`src/api/mock_backend.py` existe só para o front se desenvolver até RAG-01. Não consulta GLPI, índice nem Gemini; roteia por palavra-chave (lista no topo do arquivo). **Não reutilizar** essa lógica no adaptador real. Respostas simuladas trazem `[simulado]`, e a sessão informa `adapter: "mock"`.

Para trocar pelo real (RAG-01): implementar `ChatBackend` (`src/api/backend.py`) e ligá-lo em `build_backend()` (`src/api/app.py`) com `CHAT_BACKEND=real`. Rotas e modelos não mudam.

## 6. Comandos

Python (na raiz do repositório):

```bash
pip install -r requirements-api.txt
python -m pytest tests/test_api_contract.py -v
uvicorn src.api.app:app --reload --port 8000
```

Front, em outro terminal:

```bash
cd frontend
npm install        # gera package-lock.json — versione-o
npm run dev        # http://localhost:5173
```

Demonstração (um processo só):

```bash
cd frontend && npm run build && cd ..
uvicorn src.api.app:app --port 8000     # abre http://localhost:8000
```

Variáveis opcionais: `CORS_ORIGINS` (lista separada por vírgula), `CHAT_BACKEND` (`mock`).

## 7. Arquivos

`src/api/{schemas,backend,mock_backend,app}.py`, `tests/{conftest,test_api_contract}.py`, `requirements-api.txt`, `frontend/*`. `src/main.py` **não foi alterado**: ele continua como ponto de inicialização do GLPI-04; o servidor sobe por `uvicorn src.api.app:app`.

## 8. Evidência

Ambiente: Windows, Python 3.14.7, pytest 9.2.0, FastAPI 0.162.2, Node 24.15.0, Vite 5.4.21. Tudo com o adaptador **mock**.

- [x] `python -m pytest tests/test_api_contract.py -v` → **25 passed**, 1 warning (aviso de depreciação do `httpx` no TestClient do Starlette; não afeta o resultado)
- [x] `python -m uvicorn src.api.app:app --port 8000` sobe; `GET /api/health` → 200 `{"status":"ok","adapter":"mock"}`
- [x] Fluxo manual pelo `/docs` (Swagger): sessão `staff` (201) → prévia `open_ticket` (200) → `sim` → `write_result` `succeeded`, `ticket_id` 9001 → mesma confirmação repetida devolve o mesmo `ticket_id` (sem duplicar). `thread_id` com espaços → 404 `session_not_found` no formato padrão de erro
- [x] `npm install` (63 pacotes) e `npm run dev` → `http://localhost:5173`; o front lista os dois técnicos fictícios (chamando a API pelo proxy do Vite)
- [x] Chat no navegador: mensagem sobre VPN → resposta simulada com fonte; "quero abrir um chamado" → prévia; "sim" → "Chamado #9002"
- [x] `npm run build` + `python -m uvicorn src.api.app:app --port 8000` servindo `frontend/dist`: o chat abre em `http://localhost:8000` (sem o Vite) e o log do Uvicorn mostra `GET /` e `GET /assets/...`
- [x] Na interface: com prévia pendente, `talvez` → erro vermelho "Há uma ação aguardando confirmação" (HTTP 409, nada gravado); `não` → "Ação cancelada. Nada foi gravado."
- [x] Na interface: com o Uvicorn desligado (Ctrl+C), nova mensagem → erro vermelho "Não foi possível falar com o servidor.", sem tela em branco
- [ ] PR/commit: `________`
- [ ] Revisão de outra dupla: `________`

Observação: `npm audit` apontou 2 vulnerabilidades (1 moderate, 1 high) em dependências de desenvolvimento do Vite; não foi aplicado `npm audit fix --force`.

Distinção exigida pela task: o que foi validado é o **contrato com adaptador simulado**. Integração real com o laboratório GLPI e ensaio com Gemini continuam pendentes (RAG-01 em diante).
