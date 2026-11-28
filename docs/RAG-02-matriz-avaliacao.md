# RAG-02 — Matriz de avaliação da recuperação

Esta matriz cobre as perguntas de referência 1–7 e 17–20. As fontes são
rotuladas pelo título canônico do catálogo de seed, não por ID GLPI: IDs podem
mudar entre instalações. O catálogo é fixture de laboratório e não deve ser
confundido com o corpus vivo do GLPI.

## Consultas com fonte esperada

| Ref. | Consulta original | Paráfrase para avaliação | Fonte(s) esperada(s) | Interpretação |
| --- | --- | --- | --- | --- |
| 1 | Como configuro a VPN corporativa no Windows? | Preciso conectar a VPN no meu computador Windows. | `Configurar a VPN corporativa no Windows` | Direta; uma fonte. |
| 2 | Qual o tamanho mínimo da senha de rede? | Quantos caracteres precisa ter minha senha corporativa? | `Redefinir a senha de rede pelo autoatendimento` | Direta; contém a política de 12 caracteres. |
| 3 | Como instalo a impressora do meu andar? | Como adiciono no Windows a impressora compartilhada do meu setor? | `Instalar impressora de rede no Windows` | Direta; “do meu andar” identifica rede. |
| 4 | O que faço quando a caixa de e-mail enche? | Parei de receber mensagens porque meu correio está sem espaço. | `Caixa de e-mail cheia e mensagens não chegam` | Direta; uma fonte. |
| 5 | Como configuro a VPN? | Como faço a conexão VPN da empresa? | `Configurar a VPN corporativa no Windows`; `Configurar a VPN corporativa no macOS` | Ambígua; o gate da RAG-05 pede sistema operacional antes de recuperar. |
| 6 | Como redefino minha senha? | Esqueci a senha da conta corporativa, como troco? | `Redefinir a senha de rede pelo autoatendimento`; `Redefinir a senha de rede com o suporte` | Ambígua; o caminho depende do acesso ao e-mail/segundo fator. |
| 7 | Como instalo uma impressora? | Quero configurar uma impressora no computador. | `Instalar impressora de rede no Windows`; `Instalar impressora USB local no Windows` | Ambígua; o tipo de conexão muda o procedimento. |

Nas perguntas 5–7, o conjunto de fontes esperadas documenta as alternativas
presentes no corpus; não significa que a primeira recuperação deva devolver
ambas nem que o ranking possa escolher uma delas sem esclarecimento. A política
de ambiguidade é coberta pelos testes da RAG-05.

## Consultas sem evidência esperada

| Ref. | Consulta original | Paráfrase para avaliação | Fontes esperadas |
| --- | --- | --- | --- |
| 17 | Qual é a política de home office da empresa? | Quantos dias por semana posso trabalhar de casa? | Nenhuma; `no_evidence`. |
| 18 | Quanto custa a licença do ERP? | Qual é o preço que a empresa paga pelo sistema ERP? | Nenhuma; `no_evidence`. |
| 19 | Quem é o diretor de tecnologia? | Diga o nome de quem lidera a área de tecnologia. | Nenhuma; `no_evidence`. |
| 20 | Como solicito férias? | Qual é o processo para marcar minhas férias? | Nenhuma; `no_evidence`. |

## Métricas e regra de avaliação

- **Hit@k por fonte**: ao menos uma fonte esperada aparece entre as primeiras
  `k` fontes distintas. Trechos da mesma fonte contam uma vez.
- **Recall de alternativas** nas perguntas ambíguas: reportado à parte e apenas
  após adicionar o esclarecimento adequado. Uma consulta ambígua sem
  esclarecimento é avaliada pelo gate, não pelo ranking.
- **Taxa de falsa evidência**: proporção das consultas sem evidência (17–20)
  cujo resultado é `evidence`; alvo zero neste conjunto rotulado.
- **Latência**: o runner registra o tempo por consulta; latência não é usada para
  escolher o corte nem é critério de aprovação do pytest unitário.

O corte é escolhido por varredura de limiares sobre os scores rotulados: prioriza
recall das fontes corretas nas perguntas respondíveis e zero falsa evidência nas
consultas 17–20. Registrar também os resultados por pergunta, pois uma média
agregada pode esconder falha em uma categoria. Em caso de empate, escolher o
maior limiar que preserve o recall definido para o conjunto; não ajustar o
limiar usando apenas as consultas que falharam.

## Limites dos dados disponíveis nesta branch

`docs/RAG-03-validacao.json` contém resultados reais MiniLM do laboratório para
duas consultas, com scores relevantes de 0,6929 (VPN Windows) e 0,5894
(impressora), além de fixtures sintéticas. Isso demonstra que 0,45 recuperou
essas duas fontes naquela geração; não mede falsa evidência para as perguntas
17–20 e não justifica um limiar geral. A branch não contém índice publicado nem
pesos MiniLM locais. Portanto, esses resultados históricos não bastam para
afirmar que o corte foi calibrado. A execução real deve ser registrada à parte
quando houver corpus/índice e pesos disponíveis; a coleta do pytest deve
continuar independente desses recursos.

Não há ensaio Gemini nesta avaliação. Qualidade de recuperação é medida pelos
IDs/títulos e scores retornados. Interpretação e redação da resposta do Gemini
pertencem a um ensaio de front separado e não determinam aprovação da suíte.

## Dados e reprodução

Os casos legíveis pelo programa estão em
[`tests/data/article_retrieval_cases.json`](../tests/data/article_retrieval_cases.json).
O runner [`scripts/avaliar_recuperacao_rag02.py`](../scripts/avaliar_recuperacao_rag02.py)
consulta o `LocalIndexStore` publicado e varre cortes de 0,20 a 0,80 em
incrementos de 0,01. Ele escolhe o candidato apenas com calibração e mede a
curva holdout separadamente. Usa MiniLM com `local_files_only`, registra a
geração, scores e métricas, e não chama Gemini. Exemplos:

```bash
python -m pytest -q tests/test_article_retrieval.py
python scripts/avaliar_recuperacao_rag02.py --index-dir data/index --output docs/RAG-02-resultados.json
```

O primeiro comando usa encoder simulado e não requer índice nem modelo real. O
segundo exige geração `article` publicada em `data/index/article/ACTIVE` e os
pesos da revisão MiniLM já presentes no cache local; não baixa pesos. A
avaliação aborta se a geração mudar durante as consultas, para não misturar
resultados de índices diferentes. As consultas originais 5–7 ficam em
`clarification_cases` e não entram no ranking; variantes já esclarecidas entram
como casos de recuperação com um único título esperado.
