# SES-01 — Sessões dos técnicos fictícios

A Alternativa C define o papel `staff` no backend. A pessoa escolhe um personagem fictício do laboratório para a demonstração. A autenticação individual de técnicos fica fora desse mecanismo. O usuário de integração e o Bearer são usados pelo servidor para consultar o GLPI.

## Implementação

| Arquivo | Uso |
| --- | --- |
| [src/sessions.py](../src/sessions.py) | Valida a seleção, cria conversas, confere o vínculo da sessão, guarda mensagens e uma referência de ação pendente. |
| [src/main.py](../src/main.py) | Expõe `build_session_service()` para a aplicação da UI-01. A função usa a configuração central e a fábrica `create_client()` já presente no coletor. |
| [scripts/verificar_sessoes.py](../scripts/verificar_sessoes.py) | Exercita duas identidades na instância GLPI configurada. |
| [test/test_sessions.py](../test/test_sessions.py) | Verifica isolamento, manipulação de campos e troca de personagem. O teste do ponto de entrada usa configuração, autenticação e cliente do projeto com transporte HTTP simulado. |

O serviço consulta `/Administration/User` por meio de `search_all` e exige uma coleção completa. Os logins permitidos correspondem aos cinco registros com `tecnico: true` no [catálogo do seed](../seed/src/catalogo/usuarios.ts). Os IDs vêm dos registros da instância. O login configurado em `GLPI_USERNAME` é excluído. Quando a listagem fornece `is_active` ou `is_deleted`, o serviço também verifica esses indicadores. Se o catálogo mudar, alinhe a lista `DEMO_TECHNICIANS` com a equipe.

## Integração com a UI-01

Crie **uma instância de serviço por aplicação** no startup/lifespan do FastAPI e reutilize-a em todas as requisições. Esta implementação em memória atende a uma execução com um worker. Reiniciar o processo encerra as sessões. EST-01 implementará a persistência por `thread_id` e a retomada após reinício.

| Operação no backend | Dados e resultado |
| --- | --- |
| `service.staff_options()` | Mapa de ID GLPI para login de demonstração. Oferecer somente essas opções no React. |
| `session_id, view = service.start(staff_user_id=id_escolhido)` | A API guarda o identificador opaco em cookie de sessão HttpOnly. O corpo JSON enviado ao React contém apenas `view`. |
| `service.resume(session_id, thread_id)` | Confere o vínculo e retorna `thread_id`, `role`, `staff_user_id` e `has_pending_action`. |
| `service.add_user_message(session_id, thread_id, text=texto)` | Recebe texto e atribui a origem `user` no servidor. |
| `service.add_assistant_message(session_id, thread_id, text=resposta)` | Método interno para registrar uma resposta produzida pelo backend. |
| `service.model_context(session_id, thread_id)` | Retorna uma cópia de papel, ID do personagem e mensagens daquela conversa. |
| `service.switch(session_id, thread_id, staff_user_id=novo_id)` | Retorna novo identificador privado e nova visão pública. Substitua o cookie e atualize a conversa no React. |

A UI-01 define os caminhos HTTP e os modelos públicos. Na criação e troca, o corpo fornece `staff_user_id`. No envio de mensagem, o único conteúdo fornecido é o texto. Obtenha `session_id` do cookie emitido pelo backend e confira seu vínculo com o `thread_id` da requisição. Use modelos de entrada com campos extras proibidos. Atribuir `role`, identidade, permissões ou origem da mensagem a partir do corpo permitiria que o navegador decidisse o estado do servidor.

O `session_id` funciona como credencial temporária da demonstração. Encaminhe somente `view` no corpo de resposta. Para o agente, use `model_context()`. Monte os modelos públicos explicitamente para que configurações, objetos GLPI e cabeçalhos fiquem restritos ao backend. Para o cookie usado pela UI, adote HttpOnly, política SameSite compatível com a implantação e Secure quando servido via HTTPS.

Sugestão de mapeamento para o contrato da dupla UI-01:

| Situação | Tratamento na API |
| --- | --- |
| `InvalidCharacter` ou entrada inválida | Recusar a seleção ou a mensagem e pedir correção. |
| `SessionUnavailable` | Informar que a conversa está indisponível e permitir iniciar outra. Mesmo tratamento para vínculo incorreto e sessão expirada. |
| `DirectoryUnavailable` | Informar indisponibilidade do diretório do laboratório e preservar a sessão atual. |
| `PendingConflict` | Manter o estado existente e solicitar a atualização da prévia. |

## Identidade, pendência e limites de integração

- Cada criação gera um identificador de sessão privado e um `thread_id` próprio, inclusive quando duas pessoas escolhem o mesmo técnico.
- Mensagens comuns são gravadas como texto. A identidade e o papel vêm do estado mantido no backend.
- `set_pending(..., action_id=...)` e `clear_pending(..., action_id=...)` recebem referências de prévias internas. Uma conversa admite uma pendência por vez. A referência esperada precisa coincidir para ser removida.
- Ao aceitar uma troca, o serviço cria um contexto vazio e invalida o anterior em uma única seção protegida por lock. Uma troca recusada ou uma falha no diretório preserva a conversa original.
- SES-02 define ferramentas e autorização dos alvos. As tasks de ações implementam prévia versionada, confirmação e escrita. O requester de uma abertura continua a ser indicado e validado explicitamente.
- Assim que EST-01 conectar checkpoints e propostas duráveis, a troca deverá invalidar também as referências persistidas pela implementação integrada. Mantenha o vínculo com a sessão antes de retomar o agente ou usar uma proposta.

## Validação e evidências

Na raiz do projeto, com o ambiente Python ativo:

```bash
python -m pytest -q test/test_sessions.py
python -m pytest -q test
```

No snapshot `Squad-13-agente-dev_v2(3).zip`, o teste específico resultou em **11 aprovados**. Antes da implementação a suíte completa teve **38 aprovados e 2 falhas**. Com a SES-01, foram **49 aprovados e as mesmas 2 falhas** em `test_main_displays_search_results[True/False]`. Esses testes do snapshot esperam resultados de busca no CLI, enquanto o CLI presente coleta artigos. A branch da equipe pode já conter a correção da GLPI-05. Use o resultado que observar nela ao registrar o PR.

Ambiente desta execução com simulações: Python 3.12.14, pytest 9.2.0, requests 2.34.2 e python-dotenv 1.2.4. A validação web integrada com React/FastAPI depende da UI-01.

### Ensaio no laboratório da equipe

Com Docker ativo, `lab/.env` configurado e `.env` da aplicação preenchido conforme o README, execute no diretório do repositório:

```bash
docker compose --env-file lab/.env -f lab/docker-compose.yml up -d
python -m scripts.verificar_sessoes
```

O ensaio consulta os usuários pela API, seleciona dois técnicos presentes na instância e cria duas sessões em memória. Registra uma mensagem e uma pendência no primeiro contexto, verifica o isolamento, tenta cruzar os identificadores e troca o personagem. As operações de laboratório são autenticação e leitura dos usuários. A saída de sucesso mostra os IDs dos dois técnicos e o resultado das verificações.

Registre no PR a versão do GLPI conferida, os comandos, o resultado local e o commit testado. Identifique a execução de pytest como simulada e o ensaio acima como integração real **depois de executá-lo com sucesso**. O Gemini não participa da SES-01. Vincule o PR em **Evidência** e solicite a revisão de outra dupla antes de **Done**.

## Validação no laboratório

- Testes de sessões: `python -m pytest -q test/test_sessions.py` — 11 passaram.
- Integração real: `python -m scripts.verificar_sessoes` — SES-01 OK. Técnicos fictícios 7 e 8 validados no GLPI.
- Comportamento observado no backend: conversas isoladas, papel `staff` preservado e contexto anterior invalidado após a troca de personagem.
- Gemini e interface ficaram fora deste ensaio.
- Suíte completa (`python -m pytest -q test`): 49 aprovados e 2 falhas preexistentes em `test/test_contracts.py::test_main_displays_search_results[True/False]`. O teste espera que a CLI exiba resultados de busca, enquanto a implementação atual executa a coleta de artigos.
