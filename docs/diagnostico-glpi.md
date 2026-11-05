# Diagnóstico do laboratório GLPI

- Coleta concluída em: 2026-11-04T23:32:25-03:00
- Versão GLPI informada: 11.0.8
- Origem: http://localhost:8080/api.php/v2
- Escopo: registros retornados pelas rotas, sem filtros locais.
- Não há descarte local de chamados da lixeira.
- Os números são calculados sobre a coleta, não copiados do seed.

## Totais e origem das coleções

| Recurso | Total | Páginas | Endpoint |
| --- | ---: | ---: | --- |
| Chamados | 300 | 12 | /Assistance/Ticket |
| Categorias | 6 | 1 | /Dropdowns/ITILCategory |
| Usuários | 21 | 1 | /Administration/User |
| Artigos | 40 | 2 | /Knowledgebase/Article |

## Distribuição por status

| Status | Quantidade |
| --- | ---: |
| Em atendimento (atribuído) | 50 |
| Fechado | 176 |
| Novo | 32 |
| Solucionado | 42 |

## Distribuição por categoria

| Categoria | Quantidade |
| --- | ---: |
| Acessos e Senhas | 69 |
| E-mail e Colaboração | 31 |
| Equipamentos | 18 |
| Impressão | 37 |
| Rede e Conectividade | 102 |
| Sistema ERP | 43 |

## Exemplo JSON de chamado

Campos selecionados do primeiro registro da listagem.
Os textos de `name` e `content` foram omitidos.

```json
{
  "id": 1,
  "name": "<texto omitido>",
  "content": "<texto omitido>",
  "status": {
    "id": 6,
    "name": "Fechado"
  },
  "category": {
    "id": 2,
    "name": "Acessos e Senhas"
  },
  "date": "2025-08-23T02:08:48+00:00",
  "date_solve": "2026-08-27T02:08:50+00:00",
  "date_close": "2026-08-27T02:08:50+00:00",
  "is_deleted": false
}
```

## Exemplo JSON de artigo

Campos selecionados do primeiro registro da listagem.
Os textos de `name` e `content` foram omitidos.

```json
{
  "id": 1,
  "name": "<texto omitido>",
  "content": "<texto omitido>",
  "date_mod": "2026-08-27T02:08:49+00:00"
}
```
