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
