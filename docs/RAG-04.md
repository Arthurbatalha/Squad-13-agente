# RAG-04 — Integração do Gemini com contexto limitado

## 1. Objetivo

Implementar a camada de geração do MVP usando LangChain e o modelo Gemini configurável, mantendo a recuperação MiniLM independente do provedor. O modelo deve receber somente a pergunta, o histórico permitido e as evidências previamente selecionadas/autorizadas pelo fluxo chamador.

A implementação desta task é uma camada de integração por contrato. A conexão completa do agente, ferramentas, estado e frontend continua dependendo das tasks de integração, especialmente RAG-01 e CON-02.

## 2. Arquivos criados

| Arquivo | O que foi implementado |
|---|---|
| `src/model/__init__.py` | Inicializa o pacote de adaptadores de modelo. |
| `src/model/gemini_adapter.py` | Adaptador Gemini, preparação do prompt, limite total de contexto, normalização de erros e injeção de modelo para testes. |
| `tests/test_model_adapter.py` | Testes isolados com modelo falso, sem chamada à API Google. |
| `.env.example` | Exemplo das variáveis de configuração do Gemini, sem chave real. |
| `docs/RAG-04.md` | Esta documentação da task. |

## 3. Arquivos modificados

| Arquivo | Alteração |
|---|---|
| `src/config.py` | Adicionadas configurações `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_TIMEOUT_SECONDS` e `RAG_MAX_PROMPT_TOKENS`, com valores padrão para modelo, timeout e orçamento. |
| `src/agent_core.py` | Criada uma fachada mínima de geração (`RAGGenerationGraph`) que recebe pergunta, evidências e histórico e delega ao adaptador. Permite injetar adaptador falso nos testes e inicializa o Gemini somente quando a geração é solicitada. |
| `src/api/app.py` | Corrigido o import para `from src.agent_core import build_graph`, compatível com a execução do backend como pacote `src`. |
| `test/test_config.py` | Adicionado teste das configurações Gemini por variáveis de ambiente. |

## 4. Configuração

As variáveis devem ficar no `.env` da raiz do backend. O arquivo `.env` real não deve ser versionado nem enviado ao frontend.

```env
GEMINI_API_KEY=sua-chave-do-google
GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_TIMEOUT_SECONDS=30
RAG_MAX_PROMPT_TOKENS=8192
```

- `GEMINI_API_KEY`: credencial mantida exclusivamente no backend.
- `GEMINI_MODEL`: identificador configurável; padrão `gemini-3.1-flash-lite`.
- `GEMINI_TIMEOUT_SECONDS`: timeout da chamada ao provedor.
- `RAG_MAX_PROMPT_TOKENS`: orçamento máximo estimado para o prompt completo.

A inicialização da API em modo mock não exige a chave. A chave é necessária quando `GeminiAdapter.from_env()` é chamado para geração real.

A dependência `langchain-google-genai` está fixada em `requirements.txt` como `4.4.2`; `langchain` está fixado como `1.4.6`. Essas versões estão declaradas no arquivo de dependências, mas ainda precisam ser confirmadas em uma instalação limpa do ambiente de entrega.

## 5. Como o adaptador funciona

### 5.1 Construção do modelo

`GeminiAdapter.from_env()` carrega as configurações centrais e cria `ChatGoogleGenerativeAI` com:

- nome do modelo configurado;
- chave de API obtida do ambiente;
- timeout configurado;
- `max_retries=0`, deixando a política de repetição fora desta camada.

O adaptador aceita também uma `model_factory` injetada, permitindo testar a construção sem acessar o Google.

### 5.2 Contrato de entrada das evidências

Cada evidência recebida precisa conter todos os campos abaixo:

- `source_type`;
- `source_id`;
- `title`;
- `content`;
- `source_reference`;
- `chunk_id`.

Se faltar identificação ou rastreabilidade, a evidência é rejeitada com `ValueError`. A camada não faz busca nem decide permissões: o chamador deve fornecer somente evidências já selecionadas e autorizadas.

### 5.3 Limitação do contexto

O adaptador aplica dois limites:

1. No máximo quatro evidências (`max_evidence=4` por padrão).
2. Um orçamento total (`max_prompt_tokens`, padrão 8192) calculado sobre instruções, histórico, pergunta, metadados e conteúdo das evidências.

Se o prompt ultrapassar o orçamento, o conteúdo dos trechos maiores é reduzido progressivamente, preservando seus identificadores e referências. Se instruções, histórico e pergunta sozinhos continuarem acima do orçamento, é lançada `PromptBudgetExceeded`.

**Observação técnica:** a função padrão `estimate_tokens()` estima tokens por bytes UTF-8 divididos por três. É uma estimativa determinística e testável, não o tokenizer oficial do Gemini. Portanto, o limite implementado é um orçamento estimado; a calibração com contagem real do provedor permanece necessária antes da demonstração final.

### 5.4 Tratamento de conteúdo recuperado

O prompt instrui o modelo a tratar histórico e evidências como dados, nunca como instruções. Solicita resposta em português, fundamentação somente nas evidências, ausência de invenção e citação de `chunk_id` e `source_reference`.

Essa instrução reduz o risco de prompt injection vindo dos documentos, mas não substitui a validação posterior de citações e suporte factual prevista na RAG-05.

### 5.5 Erros do provedor

As falhas são convertidas em exceções específicas, sem propagar a mensagem bruta do provedor:

| Exceção | Situação |
|---|---|
| `ModelNotConfigured` | Chave ausente ou integração LangChain Google não instalada. |
| `ModelTimeout` | Timeout ou deadline excedido. |
| `ModelRateLimited` | Resposta de cota/limite, como 429 ou `resource_exhausted`. |
| `ModelUnavailable` | Falha genérica, indisponibilidade ou resposta vazia. |
| `PromptBudgetExceeded` | Instruções, histórico e pergunta não cabem no orçamento mesmo após reduzir/remover evidências. |

A camada não transforma falhas do provedor em respostas factuais alternativas. O chamador deve apresentar o erro de forma controlada.

## 6. Integração com `src/agent_core.py`

O contrato da fachada é:

```python
from src.agent_core import build_graph

graph = build_graph(model_adapter=adaptador_opcional)
resultado = graph.invoke({
    "question": "Como configurar a VPN?",
    "evidence": evidencias_autorizadas,
    "history": historico_permitido,
})
```

A resposta preserva os campos do estado recebido e acrescenta:

- `answer`: texto retornado pelo modelo;
- `model`: identificador do modelo;
- `input_tokens_estimated`: estimativa de tokens de entrada.

A fachada aceita `checkpointer` para preservar o ponto de composição esperado, mas esta implementação não realiza, por si só, persistência de mensagens nem constrói o agente LangChain completo. A conexão efetiva com o agente, ferramentas e ciclo de conversa pertence à integração RAG-01.

## 7. Testes e evidências

Comando executado no snapshot atualizado:

```bash
python -m pytest -q tests/test_model_adapter.py test/test_config.py
```

Resultado observado:

```text
17 passed in 0.13s
```

Os testes cobrem:

- geração com modelo falso e presença de referências/chunk IDs no prompt;
- orçamento total incluindo instruções, histórico, pergunta e evidências;
- redução de evidência longa para caber no orçamento;
- limite de quantidade de evidências;
- normalização de timeout, cota e indisponibilidade;
- tratamento de evidências como dados não confiáveis;
- rejeição de evidência sem rastreabilidade;
- estimativa UTF-8;
- inicialização da fachada sem chave Gemini;
- injeção de adaptador falso na fachada;
- limite total mesmo quando há quatro evidências;
- configuração do Gemini por variáveis de ambiente.

Esses testes são unitários e usam dublês/fakes. Eles não comprovam acesso à conta Google, disponibilidade/cota do modelo, compatibilidade real da chamada, nem execução integrada pelo frontend.

## 8. O que ainda falta para concluir o aceite completo

- [ ] Instalar as dependências fixadas em ambiente limpo e validar imports/compatibilidade.
- [ ] Validar com o squad a chave, acesso e cotas do projeto Google.
- [ ] Executar uma chamada real ao `gemini-3.1-flash-lite` em ambiente autorizado.
- [ ] Registrar modelo utilizado, estimativa/uso de tokens permitido e resultado do ensaio, sem registrar chave ou conteúdo sensível.
- [ ] Integrar a fachada ao fluxo real do agente e à API/React conforme RAG-01 e CON-02.
- [ ] Calibrar o orçamento com tokenizer/contagem real do provedor.
- [ ] Confirmar que a camada chamadora apresenta falhas sem inventar respostas.

## 9. Limites de escopo

Esta entrega não implementa a recuperação MiniLM, não altera o índice local, não adiciona Chroma ou E5 e não habilita novas operações de escrita no GLPI. A validação final das fontes, recusa por falta de evidência e esclarecimento de ambiguidades continua sendo responsabilidade da RAG-05.

**Status recomendado:** implementação e testes unitários da camada RAG-04 realizados; validação de provedor real e integração ponta a ponta pendentes.
