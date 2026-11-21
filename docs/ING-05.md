# ING-05 — Integração da atualização no startup e por comando

Este documento registra o contrato e o progresso da task. O relatório da
implementação e as evidências de validação estão em
[`relat_rio_de_implementa_o_ing_05.md`](relat_rio_de_implementa_o_ing_05.md).

## Escopo vigente

ING-05 conecta os pontos de entrada operacional ao serviço de atualização de
artigos definido nas ING-03/04 da Alternativa C. O índice usa MiniLM e
armazenamento local de matriz e catálogo. A reconstrução é completa, validada e
publicada de forma atômica, mantendo a versão anterior quando uma atualização
falha. Não usar E5, ChromaDB nem delta sync por artigo nesta integração.

A responsabilidade de ING-05 é disparar e observar a atualização no startup e
por comando manual. Coleta, preparação, assinatura, reconstrução, validação e
publicação pertencem ao serviço de indexação das tasks anteriores. Mensagens e
abertura de conversas não disparam uma reconstrução.

## Contrato com o serviço de indexação

ING-05 precisa de um serviço injetável, construído uma vez por processo, que
permita:

- carregar a versão publicada do índice local;
- executar `sync_articles(trigger)` para `trigger="startup"` ou `trigger="manual"`;
- devolver resultado `published`, `no_changes` ou `failed`, com versão ativa,
  horários de tentativa/sucesso/publicação, configuração do índice, contagens,
  duração e erro operacional sanitizado;
- expor o snapshot publicado para leitores sem permitir que uma candidata em
  construção seja consultada.

A implementação usa `LocalIndexStore`, `EmbeddingService`,
`reconcile_store_with_manifest()` e `run_sync()` das tasks anteriores. A ING-05
não mantém uma segunda implementação de coleta ou reconstrução.

## Coleta completa e escopo

O escopo desta entrega é a coleção de artigos. O adaptador deve aceitar apenas
uma coleta integral e validar seus registros antes de solicitar publicação.
`GLPIClient.search_all()` devolve `GLPICollection` após completar a paginação e
valida o total; falhas de página são exceções. `source_treatment()` atualmente
retorna uma lista simples e descarta os metadados da coleção, além de ignorar
registros que considera inválidos. A integração deve preservar ou verificar a
completude e tornar explícito o tratamento desses registros. Uma resposta
malformada não pode virar silenciosamente uma coleção menor e provocar a
publicação de um índice incompleto.

## Estado operacional observável

Manter o estado da sincronização separado do conteúdo do índice. Registrar, no
mínimo, início/término da tentativa, resultado, escopo (`articles`), versão
anterior e publicada, configuração MiniLM/preparação, contagens, duração e erro
sanitizado. Não registrar tokens, segredos nem o corpo dos artigos.

Uma rota somente de leitura deve distinguir:

- `available`: existe índice publicado válido;
- `stale`: existe índice válido, mas a tentativa mais recente falhou, a API de
  origem está indisponível ou o ledger diverge do ponteiro após o término;
- `unavailable`: não existe índice válido para consulta.

O estado informa versão ativa, última publicação, última tentativa, situação da
API de origem e erro operacional, sem expor detalhes sensíveis. Uma falha do
GLPI não transforma um índice histórico em dados atuais: consultas de chamados
continuam dependendo da API do GLPI. Sem índice inicial válido, a API informa
indisponibilidade em vez de tratar a base como vazia.

## Concorrência e ciclo de vida

Startup e comando manual devem usar a mesma rotina e um lock que cubra processos
distintos. Uma trava somente em memória não atende esse contrato quando Uvicorn
e o comando manual rodam separadamente.

Se a tentativa no startup falhar, a aplicação deve continuar em estado
degradado para expor o status e permitir os fluxos que não dependem do índice.
Com versão anterior válida, essa versão permanece disponível. A integração real
de recuperação por mensagens pertence à RAG-01; a ING-05 garante que mensagens
não iniciem sync e deixa o snapshot publicado acessível ao consumidor.

## Estado de referência antes da implementação

- `src/rag/corpus.py` contém um `CorpusService` em memória, sem recarga de índice
  persistido.
- A branch foi avançada até `8d679d8`. `src/rag/local_index.py`, o manifesto e
  `src/rag/sync.py` agora implementam o índice local MiniLM e o motor de
  reconstrução/publicação corrigido da ING-03/04; o Chroma foi removido do
  código ativo e das dependências. `docs/ING-03.md` e
  `docs/relat_rio_de_fix_ing_04.md` registram o contrato atualizado.
- O relatório da correção registra 36 testes da ING-04 aprovados e descreve a
  suíte local de ING-03. Esses resultados foram lidos no relatório, não
  reexecutados nesta etapa.
- `src/main.py` mantinha a verificação antiga de coleta sem argumentos.
- A API já permite `answer_status="index_unavailable"` no contrato de mensagem,
  mas não expunha estado operacional do índice nem chamava sync no lifespan.

O ajuste local anterior de import em `src/api/app.py` já está incluído na versão
atualizada. Durante o fast-forward, o autostash encontrou conflito porque o
import de `session_store` também mudou no commit atualizado. A versão atualizada
usa `init_db`, requerido pelo corpo do arquivo; o autostash foi mantido como
reserva.

## Progresso da implementação

**Passo 1 de 8 — concluído.** O contrato desta task foi conferido com as
ING-03/04 atualizadas e fixado no escopo da Alternativa C: MiniLM, índice local,
reconstrução completa e publicação atômica.

**Passo 2 de 8 — concluído.** `src/rag/sync_runtime.py` define o contrato
injetável `ArticleSyncEngine`, o relatório `ArticleSyncReport`, o
`LocalArticleSyncEngine`, o `ArticleSyncCoordinator` e um ledger SQLite
separado. O adaptador chama `reconcile_store_with_manifest()` e `run_sync()` da
ING-04 com `LocalIndexStore`, `EmbeddingService` MiniLM e coleta integral
injetável. O coordenador aceita `startup` e `manual`, registra tentativas e
resultados e guarda apenas o tipo do erro.

O adaptador usa `GLPICollection.complete` e a contagem total para impedir a
publicação quando a coleta não está confirmada como completa. O lock entre
processos foi acrescentado no passo 4.

**Passo 3 de 8 — concluído.** A aplicação exportada para Uvicorn injeta a
fábrica padrão do coordenador e executa `run("startup")` no lifespan, em thread
de trabalho. Falha de coleta/indexação deixa a API iniciar em estado degradado:
`stale` se há geração anterior legível ou `unavailable` sem geração válida.
`create_app()` aceita a fábrica por injeção e, sem ela, não dispara chamadas
externas; isso mantém a construção de apps de teste controlável.

**Passo 4 de 8 — concluído.** `python -m src.main sync` chama o mesmo
`build_default_article_sync_coordinator()` do startup. O comando imprime resumo
JSON sem segredos e retorna código diferente de zero quando a tentativa falha.
O comportamento anterior de `python -m src.main` sem argumentos foi preservado
como verificação de coleta GLPI. `SyncProcessLock` usa transação SQLite em
arquivo separado do ledger para impedir sincronizações concorrentes entre API e
CLI.

**Passo 5 de 8 — concluído.** O ledger também persiste o estado de acesso à API
de origem, incluindo migração de ledgers existentes. `GET /api/index/status`
expõe tentativa recente, última execução bem-sucedida, geração ativa, contagens,
configuração, resultado e erro sanitizado. A rota abre a geração ativa em disco
antes de declarar `available`; uma tentativa falha com snapshot válido resulta
em `stale`. Durante uma tentativa `running`, ela acompanha a geração publicada
no ponteiro atômico mesmo que o ledger ainda esteja sendo finalizado.

**Passo 6 de 8 — concluído.** `tests/integration/test_sync_startup.py` cobre
startup, publicação local com encoder sintético, ausência de nova coleta ao
processar mensagens, indisponibilidade inicial, preservação do snapshot após
falha, rejeição de registros malformados e coleta incompleta, lock entre
instâncias e migração do ledger. `tests/test_main_sync.py` cobre o comando
manual e seus códigos de saída.

**Passo 7 de 8 — concluído.** Este contrato e
`docs/relat_rio_de_implementa_o_ing_05.md` registram as decisões, o fluxo
operacional, o endpoint, a execução do CLI, os limites de validação e os
resultados observados.

**Passo 8 de 8 — concluído.** Os testes novos da ING-05 e os testes locais de
publicação ING-04 e armazenamento ING-03 foram executados. O relatório lista os
comandos e resultados, inclusive a limitação encontrada ao executar testes da
API com `TestClient` neste ambiente.

## Fora do escopo desta etapa

Este contrato não implementa a recuperação RAG-01 nem a busca/resposta sobre o
índice. A validação não chamou um GLPI real nem carregou pesos MiniLM; esses
limites estão detalhados no relatório de implementação.
