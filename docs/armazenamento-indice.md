# Armazenamento do índice

## Decisão

Guardar o índice em `data/indice.sqlite3`, usando `sqlite3` da biblioteca padrão
Python. O arquivo persiste entre execuções; a busca carrega os trechos/vetores
em memória. Não é necessário servidor adicional nem framework de agentes.
SQLite foi escolhido por ter transações e permitir armazenar fontes e vetores
juntos. JSON puro seria simples, mas exigiria implementar substituição segura;
um banco vetorial externo acrescentaria infraestrutura desnecessária ao lab.

Este módulo **armazena** embeddings; não gera embeddings nem calcula similaridade.
A busca atual em `app/busca_artigos.py` é lexical e continua funcionando como antes.
A integração com geração de vetores fica a cargo da dupla de recuperação.

## Contrato para a dupla de busca

Cada trecho é um dicionário com estes campos obrigatórios:

| Campo | Tipo | Significado |
|---|---|---|
| `chunk_id` | string única | Ex.: `42:0`, artigo 42, trecho 0 |
| `artigo_id` | inteiro | ID real retornado pelo GLPI, para citar a fonte |
| `titulo` | string | Título do artigo |
| `texto` | string | Trecho limpo, sem HTML |
| `url` | string | Link da fonte no GLPI |
| `vetor` | lista de números finitos | Embedding produzido pela dupla |

Todos os vetores devem ter a mesma dimensão. Converta arrays da biblioteca de
embeddings usando `.tolist()` antes de salvar. A ordem dos trechos é preservada,
mantendo o alinhamento entre vetores e fontes.

O banco possui `metadados` (uma linha com JSON) e `trechos` (ordem + JSON).
Os metadados registram versão do formato, modelo, assinatura, dimensão,
quantidade e data UTC. Os vetores ficam em JSON para leitura simples, sem pickle.
O diretório `data/` é ignorado pelo Git e o banco pode ser regenerado.

## Fluxo de uso

1. Coletar **todas as páginas** de artigos na API e limpar o HTML.
2. Dividir em trechos usando a configuração escolhida pela dupla.
3. Calcular a assinatura sobre os trechos sem vetor **e a configuração**.
4. Tentar carregar o índice compatível.
5. Somente se o retorno for `None`, gerar os embeddings e salvar.
6. Usar os vetores carregados na busca e citar os IDs correspondentes.

Exemplo de integração (executar dentro do projeto; `gerar_embeddings` é a função
que a dupla deverá fornecer, não faz parte deste módulo):

```python
from app.armazenamento_indice import (
    assinatura_dados, carregar_indice, salvar_indice,
)

# trechos: lista de dicionários conforme o contrato, ainda sem o campo vetor.
modelo = "nome-do-modelo@revisao-fixa"
config = {"chunking": "v1", "tamanho": 500, "sobreposicao": 50,
          "limpeza": "v1", "normalizar_embeddings": True}
assinatura = assinatura_dados({"trechos": trechos, "config": config})
indice = carregar_indice(modelo=modelo, assinatura=assinatura)
if indice is None:
    vetores = gerar_embeddings([t["texto"] for t in trechos])
    if len(vetores) != len(trechos):
        raise ValueError("Quantidade de embeddings diferente dos trechos")
    indice = [{**t, "vetor": list(v)} for t, v in zip(trechos, vetores)]
    salvar_indice(indice, modelo=modelo, assinatura=assinatura)
```

Ordenar os artigos por ID e os trechos por posição antes de calcular a assinatura
permite reutilizar o índice mesmo se a API mudar a ordem dos registros. Mudanças
no conteúdo, fontes, modelo/revisão ou configuração invalidam o índice. Remover
um artigo exige reconstruir a lista completa; a gravação substitui o conjunto,
evita manter trechos removidos e ocorre numa transação.

A assinatura verifica o conteúdo recebido; não detecta sozinha mudanças no GLPI.
Para garantir atualização, consulte a base na inicialização ou em uma rotina
explícita de sincronização. Isso economiza a geração de embeddings, mas ainda
exige coleta/limpeza para comparar a base. Sem API disponível, não use a cópia
antiga silenciosamente como se estivesse atualizada.

`None` significa ausente ou incompatível; `[]` significa índice válido vazio.
Corrupção, problemas de acesso e dados inválidos geram exceção. O chamador deve
informar o erro e, se apropriado, reconstruir o arquivo explicitamente. Uma gravação
inválida preserva o índice anterior. Este contrato assume um processo escritor;
coordenação entre vários processos de sincronização fica fora desta task.

## Validação

Na raiz do repositório:

```bash
python3 -m unittest discover -s tests -v
```

Os testes usam diretórios temporários, sem GLPI ou LLM. Cobrem persistência,
cache ausente, troca de modelo/assinatura, remoção de fontes, dados inválidos,
dimensões, IDs duplicados, assinatura estável e arquivo corrompido.

Para bases maiores, medir tempo de carga e memória: carregar todos os vetores
faz sentido para o laboratório, mas não é uma solução de busca aproximada para
milhões de trechos. Persistência não substitui avaliar a qualidade da recuperação.
