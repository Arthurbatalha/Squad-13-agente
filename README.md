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
py -m venv .venv
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

## Dependências fixadas e instalação limpa (GLPI-01)

- Pré-requisitos **fora do pip**: Python 3.13 (64 bits) para a validação
  recomendada em Windows; Docker Desktop + Docker Compose para iniciar o
  laboratório GLPI. O Docker não é necessário para os testes unitários.
- `requirements.txt` contém **versões candidatas fixadas** para as
  dependências do protótipo e da stack selecionada no Planning Refactor.
  Inclui `requests`, `python-dotenv`, `sentence-transformers`, `html2text`,
  `chromadb`, `langchain`, `langgraph`, `langchain-google-genai`,
  `langgraph-checkpoint-sqlite`, `pytest`, `scikit-learn` e `tzdata`.
- `os`, `pathlib`, `datetime`, `zoneinfo` e `sqlite3` fazem parte da
  biblioteca padrão do Python: não entram na lista pip. O SQLite é
  destinado a *checkpoints do LangGraph*, não a substituir o Chroma.
- As versões **não estão validadas como conjunto** até concluir os passos
  abaixo em um ambiente novo e registrar os resultados. A instalação
  completa pode ser demorada porque SentenceTransformers depende de Torch.

Na raiz do repositório, no terminal **PowerShell** do Windows:

```powershell
py -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pip check
.\venv\Scripts\python.exe scripts/verify_environment.py
.\venv\Scripts\python.exe -m pytest -q test/test_contracts.py test/test_config.py
.\venv\Scripts\python.exe --version
```

`venv/` está no `.gitignore` e não deve ser enviado ao GitHub.
Não versionar `.env`, senhas, tokens ou arquivos baixados do modelo.
Guarde a saída de `pip check`, do verificador de ambiente, da versão do
Python e dos testes como evidência da task. O verificador importa as
bibliotecas, mas não baixa modelos nem conecta ao GLPI ou ao Gemini.

## Contratos da busca e limites da etapa

Consulte [`docs/contratos-glpi01.md`](docs/contratos-glpi01.md) para o
formato interno atual (`id`, `title`, `content`, `score`), a diferença em
relação aos campos da API e as exigências futuras aprovadas para Chroma/E5,
chunks e referências. O frontend é obrigatório no MVP aprovado, mas não
está sendo implementado nesta task de ambiente.

**Critério de conclusão:** testes com mocks + instalação limpa e imports
validados + documentação revisada + revisão e PR acordado para `dev_v2`.
A integração real com GLPI e o ensaio com Gemini exigem validação em suas
respectivas entregas; não afirmar que ocorreram apenas com esses testes.
