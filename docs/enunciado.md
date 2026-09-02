# Projeto: agente de IA sobre a central de serviços

Você vai construir um agente que responde perguntas sobre a **base de
conhecimento** e os **chamados** de uma central de serviços de TI, usando um
GLPI 11 de laboratório que já vem pronto e povoado.

## Regras do projeto

- **Linguagem livre.** Escolha a que o grupo domina.
- **Sem interface gráfica.** A entrega é linha de comando ou API. Investir em
  front não conta ponto.
- **Cada grupo usa a própria chave de LLM.** Qualquer provedor serve. Nunca
  suba a chave para o repositório.
- **Todo o dado do laboratório é fictício.** Pode testar à vontade.

## Preparando o ambiente

    cd lab
    cp .env.example .env
    docker compose up -d --build

Em cerca de um minuto o GLPI responde em <http://localhost:8080>
(usuário `glpi`, senha `glpi`). As credenciais da API já vêm prontas em
`lab/oauth-client.md` — não é preciso rodar nenhum script de preparação.
`docs/glpi.http` traz requisições prontas.

**Estragou a base testando?**
`docker compose down -v && docker compose up -d --build` devolve tudo ao
estado original. Use sem medo.

## Entregas

### Sprint 0 — Reconhecimento (semanas 1 e 2)

Sem nenhuma IA. Suba o laboratório, autentique-se via OAuth e entregue um
relatório curto respondendo: quantos chamados existem, como se distribuem por
categoria e por status, quantos artigos há na base de conhecimento, e qual o
formato JSON de um chamado e de um artigo.

*Entrega:* relatório em Markdown no repositório + o código que levantou os números.

### Sprint 1 — Respostas a partir da base de conhecimento (semanas 3 a 6)

O agente responde perguntas de procedimento consultando os artigos da base.

Requisitos:
- Toda resposta **cita o artigo** de onde saiu a informação.
- Quando a base **não cobre** a pergunta, o agente diz que não sabe.
  Inventar uma resposta ou citar um artigo inexistente **reprova a sprint** —
  não é desconto de nota.
- Existe uma etapa de **recuperação** que seleciona um subconjunto de artigos
  antes de gerar a resposta.

> **Leia com atenção:** a base é pequena o bastante para caber inteira no prompt
> de um modelo moderno. Fazer isso e acertar as respostas **não** cumpre o
> requisito. Seu agente precisa funcionar igual se a base crescer dez vezes, e
> você vai precisar demonstrar isso na apresentação.

### Sprint 2 — Consultas sobre chamados (semanas 7 a 9)

"Quantos chamados abertos existem na categoria de rede?" não se responde
buscando texto parecido. Perguntas assim precisam de dado estruturado.

Requisitos:
- O agente tem uma **ferramenta** que consulta a API e devolve dado estruturado.
- O agente **decide sozinho** se a pergunta pede a base de conhecimento ou a
  ferramenta de consulta.
- Perguntas que combinam os dois caminhos são tratadas corretamente.

### Sprint 3 — Chamados parecidos (semanas 10 a 12)

Dado um chamado novo, o agente encontra chamados históricos semelhantes e propõe
a solução que funcionou neles.

Requisitos:
- A busca considera o conteúdo do chamado, não só a categoria.
- A sugestão cita **quais** chamados a embasaram.
- Chamados sem solução registrada não entram como fonte de sugestão.

### Sprint 4 — Agir sobre os chamados (semanas 13 a 15)

O agente passa a abrir chamados e adicionar acompanhamentos.

Requisitos:
- **Nada é gravado sem confirmação explícita do usuário.**
- Antes de gravar, o agente **mostra exatamente o que vai gravar**.
- Se o usuário não confirmar, nada acontece.

Este requisito não é burocracia acadêmica: é a diferença entre um agente que se
pode colocar em produção e um que não se pode.

### Semana 16 — Apresentação

Demonstração ao vivo com as perguntas de `docs/perguntas-de-referencia.md`,
mais a explicação da arquitetura. Reserve tempo para explicar **como** a
recuperação funciona — é o item de maior peso.

## Onde as coisas costumam travar

- A API só entende **`?start=N&limit=M`** para paginar listagens. O parâmetro
  `?range=` existe em outras versões do GLPI, mas **nesta versão é ignorado**
  — não use.
- Listagens devolvem **206** quando a fatia pedida é parcial, e **200** quando
  cobre o conjunto inteiro. Trate qualquer 2xx como sucesso; não trave a
  lógica em um único código.
- O token expira em **1 hora**. Implemente renovação cedo.
- Não existe filtro por status ou categoria na API (`?filter=`, `?status=`
  e variantes são ignorados ou dão erro, dependendo da sintaxe). Pagine a
  coleção inteira e filtre/agregue no seu próprio código.
- O campo **`date`** é a data real de abertura do chamado. `date_creation`
  **não** serve para isso — reflete o momento em que o laboratório foi
  gerado, e é igual (ou quase) para todos os chamados. Qualquer pergunta
  sobre "quando" um chamado foi aberto usa `date`.
- Para **ler** comentários e soluções, use `GET .../Timeline` — é lá que
  tudo aparece consolidado. Para **escrever** um acompanhamento (Sprint 4),
  o caminho é o sub-recurso `POST .../Timeline/Followup`; postar direto em
  `/Timeline` não funciona, esse endpoint é só de leitura.
- O conteúdo dos artigos da base de conhecimento fica no campo **`content`**
  (endpoint `/api.php/v2/Knowledgebase/Article`) e é **HTML**. Converta para
  texto antes de indexar.
- Alguns artigos são **quase iguais** de propósito (VPN no Windows e no macOS,
  por exemplo). Se o seu agente confunde os dois, a recuperação precisa melhorar.

Consulte `docs/api-glpi-v2.md` antes de perguntar.
