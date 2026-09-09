# Rubrica de avaliação

| Critério | Peso |
|---|---|
| Recuperação e arquitetura | 30 |
| Uso de ferramentas e roteamento | 20 |
| Tratamento de erro e recusa honesta | 15 |
| Testes | 15 |
| Documentação | 10 |
| Apresentação | 10 |

## Recuperação e arquitetura (30)

O que se avalia é a **arquitetura**, não o acerto das respostas. A base do
laboratório cabe inteira no contexto de um LLM moderno, então respostas certas
não provam nada sozinhas.

Este critério cobre tanto a recuperação sobre a base de conhecimento
(Sprint 1) quanto a recuperação sobre chamados históricos usada para
encontrar casos parecidos (Sprint 3). As faixas abaixo valem para as duas:
existe uma etapa de busca que filtra antes de agir, ou o conjunto inteiro
(artigos ou chamados) entra sem seleção?

- **26–30:** há uma etapa de recuperação clara e isolada, que seleciona um
  subconjunto antes da geração. O grupo demonstra que o agente continuaria
  funcionando com dez vezes mais conteúdo.
- **18–25:** existe recuperação, mas acoplada ao restante ou com escolhas mal
  justificadas (chunking arbitrário, sem controle de quantos trechos entram).
- **8–17:** recuperação rudimentar, como filtro por palavra-chave apenas.
- **0–7:** o corpus inteiro vai para o prompt. **Este item zera mesmo que a
  demonstração acerte todas as perguntas.**

## Uso de ferramentas e roteamento (20)

Cobre as ferramentas de consulta (Sprint 2) e as de escrita — abrir chamado,
adicionar acompanhamento (Sprint 4). O requisito eliminatório da Sprint 4
trata só da ausência de confirmação; a qualidade da ferramenta de escrita
(clareza do que é mostrado antes de gravar, tratamento de erro na escrita)
pontua aqui.

- **18–20:** ferramentas bem definidas devolvendo dado estruturado; o agente
  escolhe corretamente entre base de conhecimento e consulta, inclusive em
  perguntas que exigem os dois; a escrita mostra exatamente o que vai gravar
  antes de confirmar.
- **12–17:** ferramentas funcionam, mas o roteamento erra em casos limítrofes,
  ou a confirmação de escrita existe mas é pouco clara sobre o que será gravado.
- **5–11:** existe consulta a chamados, mas sem roteamento — o usuário precisa
  dizer qual caminho usar.
- **0–4:** não implementado.

## Tratamento de erro e recusa honesta (15)

Critério avaliado **na apresentação final** (semana 16):

- Recusa quando a base não cobre a pergunta: **6 pontos**.
- Nenhuma fonte inventada em toda a apresentação final: **5 pontos**.
- Trata token expirado, indisponibilidade da API e resposta 206: **4 pontos**.

Uma única citação de artigo inexistente durante a apresentação final zera
este critério (0 dos 15 pontos). Essa é a penalidade para quem chega à
apresentação já tendo passado pela Sprint 1 — veja a seção abaixo para a
penalidade equivalente durante o semestre.

## Testes (15)

- **13–15:** testes automatizados cobrindo recuperação e ferramentas, rodando
  sem depender de chamada real ao LLM.
- **8–12:** testes existem, mas cobrem só o caminho feliz.
- **3–7:** poucos testes, ou só manuais.
- **0–2:** nenhum teste.

## Documentação (10)

README que permite a outra pessoa rodar o projeto do zero; decisões de
arquitetura registradas com a justificativa.

## Apresentação (10)

Demonstração ao vivo funcionando, domínio das perguntas da banca, clareza na
explicação da arquitetura.

## Sprint 1 e Sprint 4 têm requisitos eliminatórios

- **Sprint 1** (entrega das semanas 3–6): inventar uma resposta ou citar um
  artigo inexistente reprova a sprint.
- **Sprint 4** (entrega das semanas 13–15): gravar no GLPI sem confirmação
  do usuário reprova a sprint.

Em ambos os casos há uma oportunidade de correção antes da nota final.

Essa reprovação de sprint é distinta da penalidade do critério "Tratamento
de erro e recusa honesta" descrita acima: a reprovação de sprint vale para a
**entrega intermediária** da Sprint 1, durante o semestre; a perda dos 15
pontos do critério vale para a **apresentação final**, na semana 16. São o
mesmo tipo de falha julgada em dois momentos diferentes do curso, cada um
com sua própria consequência — não a mesma falha punida duas vezes pelo
mesmo motivo.
