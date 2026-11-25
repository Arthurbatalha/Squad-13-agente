# GLPI Agent Lab

Laboratório para o projeto de agente de IA sobre uma central de serviços.
Sobe um GLPI 11 já povoado com chamados e artigos fictícios, para você
construir um agente que responde sobre eles.

## Começando

    cd lab
    cp .env.example .env
    docker compose up -d --build

Na primeira vez, o build da imagem do GLPI mais o download das imagens base
leva alguns minutos (depende da sua internet). Depois disso, o banco sobe já
populado e o GLPI fica pronto em cerca de 1 minuto.

Como saber que deu certo: abra <http://localhost:8080> — a tela de login do
GLPI aparece (não a tela de instalação). Entre com usuário `glpi`, senha
`glpi`. Se aparecer a tela de instalação ("Instalar" / "Atualizar"), algo deu
errado — veja "Recomeçar do zero" abaixo antes de investigar mais.

Você **não** precisa instalar o GLPI nem rodar nenhum script de preparação:
o banco e as credenciais da API já sobem prontos.

## O que ler, nesta ordem

1. [`docs/enunciado.md`](docs/enunciado.md) — o projeto, sprint a sprint
2. [`docs/rubrica.md`](docs/rubrica.md) — como você é avaliado
3. [`docs/api-glpi-v2.md`](docs/api-glpi-v2.md) — a API, e as armadilhas dela
4. [`docs/glpi.http`](docs/glpi.http) — requisições prontas para rodar
5. [`lab/oauth-client.md`](lab/oauth-client.md) — as credenciais da API
6. [`docs/perguntas-de-referencia.md`](docs/perguntas-de-referencia.md) — as
   perguntas da apresentação final

## Recomeçar do zero

    cd lab && docker compose down -v && docker compose up -d --build

Isso apaga tudo que você criou no GLPI e restaura o laboratório original.
Como todo o dado é fictício, teste à vontade.

## Requisitos

Docker e Docker Compose. Nada além disso — a linguagem do seu agente é sua
escolha.

## Para o professor

`seed/` contém o gerador do corpus e não é usado pelos alunos.
Veja [`seed/README.md`](seed/README.md).

## Preparação da aplicação Python (GLPI-01)

Na raiz do repositório, crie um ambiente virtual e instale as dependências
de teste, sem baixar a stack completa nem um modelo de IA:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install pytest python-dotenv tzdata
```

Copie `.env.example` para `.env` **na raiz** do repositório e preencha
`GLPI_CLIENT_ID` e `GLPI_CLIENT_SECRET` com os valores locais do laboratório.
Nunca versione o arquivo `.env` nem exponha tokens.

- `GLPI_BASE_URL_V1` é a base de autenticação (`/api.php`) para `/token`.
- `GLPI_BASE_URL_V2` é a base de recursos (`/api.php/v2`).
- `APP_TIMEZONE=America/Fortaleza` define o fuso IANA; em Windows,
  o pacote `tzdata` fornece dados de fuso quando necessário.
- A configuração é carregada por `src/config.py` a partir da raiz do projeto,
  independentemente da pasta atual do terminal.

Testes locais, sem GLPI ou Gemini:

```powershell
.\.venv\Scripts\python.exe -m pytest -q test/test_contracts.py test/test_config.py
```

Para iniciar o protótipo após preparar o GLPI e o `.env`:

```powershell
.\.venv\Scripts\python.exe -m src.main
```

O comando da aplicação é o modo previsto para execução por pacote,
mas a integração real com GLPI e a busca semântica dependem da instalação
completa e serão validadas separadamente. A presença dos testes acima não
comprova integração real nem execução com Gemini.

## Ambiente Python do projeto

Use CPython **3.14** de 64 bits. A série está registrada em `.python-version`.
Na raiz do projeto, crie e ative o ambiente virtual.

**Linux e macOS**

```bash
python3.14 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell)**

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Com o ambiente ativo, instale e confira as dependências do backend e dos testes.

```bash
python -m pip install -r requirements.txt -r requirements-api.txt
python --version
python -m pip check
python scripts/verify_environment.py
python -m pytest -q test tests
```

O verificador confere a série do Python, os pacotes fixados e seus imports.
Os pesos do MiniLM são carregados sob demanda. O laboratório GLPI usa Docker
e Docker Compose.

## Busca na Alternativa C

A ING-01 prepara o HTML com html2text. A ING-02 usa MiniLM multilíngue em CPU
para gerar vetores normalizados de 384 dimensões. A ING-03 publica uma matriz
e um catálogo locais por geração. A RAG-03 consulta a geração publicada,
aplica o escopo do técnico e vetoriza somente a pergunta. O SQLite da API
armazena o estado das sessões e os checkpoints. Detalhes em
[ING-02](docs/ING-02.md), [ING-03](docs/ING-03.md) e [RAG-03](docs/RAG-03.md).

## Diagnóstico do laboratório — GLPI-05

O script `scripts/coletar_dados.py` utiliza o cliente GLPI comum e a
configuração central para gerar um diagnóstico da instância consultada.

### Configuração

O arquivo `.env` da raiz deve conter os valores válidos de:

- `GLPI_BASE_URL_V1`
- `GLPI_BASE_URL_V2`
- `GLPI_CLIENT_ID`
- `GLPI_CLIENT_SECRET`

Configure também `GLPI_USERNAME` e `GLPI_PASSWORD` conforme o laboratório.
Não inclua credenciais nos commits.

O arquivo `lab/.env` configura o laboratório Docker e tem finalidade
diferente do `.env` da aplicação.

### Gerar o relatório

Com o laboratório iniciado e as dependências Python instaladas, execute
na raiz do projeto:

```bash
source .venv/bin/activate
python -m scripts.coletar_dados --glpi-version 11.0.8
```

Substitua `11.0.8` pela versão conferida na instância. Esse argumento é
informado pelo operador; o script não detecta a versão automaticamente.

O resultado é salvo em [docs/diagnostico-glpi.md](docs/diagnostico-glpi.md),
com instante e escopo da coleta, totais, distribuições por status e
categoria e exemplos JSON com os textos de nome e conteúdo omitidos.

As contagens são calculadas a partir da API. Não são valores fixos
copiados do seed e podem mudar conforme o estado do laboratório.

### Evidências da validação

Implementação registrada no commit `3fa987e`.

Testes automatizados:

```bash
python -m pytest -q test
```

Resultado informado na execução: `57 passed in 0.37s`.

Coleta real realizada com `--glpi-version 11.0.8`:

| Coleção | Registros | Páginas |
|---|---:|---:|
| Chamados | 300 | 12 |
| Categorias | 6 | 1 |
| Usuários | 21 | 1 |
| Artigos | 40 | 2 |

As quatro coleções foram informadas como completas pelo script.

### Falha controlada de conexão

Após gerar um relatório válido, foi executado:

```bash
sha256sum docs/diagnostico-glpi.md

GLPI_BASE_URL_V1=http://127.0.0.1:1/api.php \
GLPI_BASE_URL_V2=http://127.0.0.1:1/api.php/v2 \
python -m scripts.coletar_dados --glpi-version 11.0.8

echo "Código de saída: $?"
sha256sum docs/diagnostico-glpi.md
```

Resultado observado: `ConnectionError`, código de saída `1` e mensagem
informando que nenhum relatório novo foi publicado. Os hashes antes e
depois foram iguais, comprovando a preservação do relatório existente.

Esse cenário utiliza uma URL inacessível apenas naquela execução.
A coleta real, os testes automatizados com simulações e a falha
controlada são evidências distintas. Não foi realizado ensaio Gemini
nesta validação.


## RAG-04 — geração Gemini com contexto limitado

A geração fica isolada em `src/model/gemini_adapter.py`; a busca MiniLM continua
independente e deve fornecer somente evidências autorizadas, já selecionadas,
com `source_type`, `source_id`, `title`, `content`, `source_reference` e
`chunk_id`. O adaptador não consulta GLPI nem executa recuperação.

Configure no `.env` do backend:

```dotenv
GEMINI_API_KEY=sua-chave
GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_TIMEOUT_SECONDS=30
RAG_MAX_PROMPT_TOKENS=8192
```

A chave não deve ser enviada ao React, incluída em prompts, logs ou checkpoints.
O orçamento considera instruções, histórico, pergunta, metadados e evidências.
A estimativa padrão é conservadora (bytes UTF-8 / 3), não substitui a medição
oficial de tokens do provedor. Evidências são limitadas a quatro por padrão e
seu conteúdo é reduzido até caber; se instruções/histórico/pergunta sozinhos
ultrapassarem o orçamento, a geração falha explicitamente.

Testes sem Gemini real:

```bash
python -m pytest -q tests/test_model_adapter.py
```

O teste automatizado usa modelo falso injetado. Ele não comprova chave válida,
acesso, disponibilidade, cotas ou comportamento real do modelo. A demonstração
real deve ser autorizada pelo squad e executada com a chave local configurada.

## RAG-01 — conversa integrada

A conversa do React passa a usar o backend real quando `CHAT_BACKEND=real`:
FastAPI, agente LangChain com checkpoint SQLite, recuperação publicada da
RAG-03, geração Gemini da RAG-04 e validação da RAG-05. O mock continua
disponível com `CHAT_BACKEND=mock`.

O cookie `rag01_session` é `HttpOnly`; o banco guarda apenas o hash do token.
O `thread_id` sozinho não autoriza outra sessão. A troca de personagem cria
um contexto novo, invalida o anterior e descarta o checkpoint antigo. O
histórico fica no SQLite e é retomado após reiniciar o backend.

Configuração e exemplos sem segredos estão em
[.env.example](.env.example) e [docs/RAG-01.md](docs/RAG-01.md). O frontend
da conversa fica no repositório separado
[lumora-frontend](https://github.com/isaaarx/lumora-frontend).
Nos exemplos abaixo, ele é clonado como repositório irmão em
`../Squad-13-Frontend`.

Para executar o backend:

```bash
source .venv/bin/activate
CHAT_BACKEND=real uvicorn src.api.app:app --reload --port 8000
```

Em outro terminal, no repositório do frontend:

```bash
cd ../Squad-13-Frontend
npm ci
npm run dev
```

Testes da integração:

```bash
python -m pytest -q tests/test_rag_graph.py tests/integration/test_graph_resume.py
python -m pytest -q test tests
python -m pip check
```

No repositório do frontend:

```bash
npm test && npm run build
```

O backend não serve mais o build do React por padrão; o frontend usa o proxy
do Vite (`/api` → `http://localhost:8000`) ou uma origem configurada em
`CORS_ORIGINS`.

Os testes usam SQLite e índice temporários com provedor determinístico. O
ensaio com Gemini real depende de chave, cota e índice publicado; sem esses
recursos ele não é declarado aprovado. Limites de histórico, iterações,
tentativas, timeout e catálogo estão documentados em
[docs/RAG-01.md](docs/RAG-01.md).
