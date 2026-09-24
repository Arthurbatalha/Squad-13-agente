# Gerador do corpus (uso do autor)

**Alunos não precisam disto.** O corpus já vem pronto em `lab/seed.sql`, montado
automaticamente pelo MariaDB no primeiro boot (`docker-entrypoint-initdb.d`).
Basta `docker compose up` — sem instalador, sem gerador.

Este gerador existe para regenerar o corpus quando se quiser mais volume,
outra categoria, ou datas atualizadas para um novo semestre.

## Regenerar

O `lab/docker-compose.yml` monta `lab/seed.sql` no boot do MariaDB. Para
gerar um `seed.sql` novo é preciso primeiro subir o banco **vazio** — ou
seja, sem esse arquivo populado no caminho montado:

```bash
cd lab
mv seed.sql seed.sql.bak   # esvazia o caminho montado sem editar o compose
touch seed.sql
docker compose down -v && docker compose up -d --build

# instalar o banco do zero
docker compose exec -u www-data glpi php bin/console database:install \
  --db-host=db --db-name=glpi --db-user=glpi --db-password=glpi \
  --default-language=pt_BR --no-interaction

# recriar o cliente OAuth com as credenciais fixas do lab
cd .. && ./scripts/preparar-oauth.sh

# gerar o corpus
cd seed && npm install
CLIENT_ID=<ver lab/oauth-client.md> CLIENT_SECRET=<idem> npm run gerar

# congelar o dump
cd ../lab
docker compose exec -T db mariadb-dump -uroot -proot \
  --single-transaction --routines --events --add-drop-table \
  --default-character-set=utf8mb4 glpi > seed.sql
rm -f seed.sql.bak
```

## `config_db.php`, `oauth.pem` e `oauth.pub` — por que também são fixos

Além do `seed.sql` e da `glpicrypt.key` (ver `lab/oauth-client.md`), o
`docker-compose.yml` também monta `lab/config_db.php`, `lab/oauth.pem` e
`lab/oauth.pub` em `/var/www/glpi/config/`. Esses três arquivos são gerados
pelo `database:install`/`security:change_oauth_key` na camada gravável do
container — sem fixá-los, um `docker compose down -v && up` recria o
container do zero, o GLPI perde a config de conexão com o banco e as chaves
de assinatura JWT, e mesmo com o `seed.sql` restaurado o instalador volta a
aparecer e `/api.php/token` para de funcionar. `config_db.php` é
determinístico (mesmas credenciais fixas do `docker-compose.yml`, sem
segredo nenhum). `oauth.pem`/`oauth.pub` são um par de chaves RSA sem
relação com o conteúdo do banco — só precisam existir e ser consistentes
entre si.

**`oauth.pem` é uma chave privada** (o arquivo começa literalmente com
`-----BEGIN PRIVATE KEY-----`) usada para assinar os JWT emitidos por
`/api.php/token`. Ela está versionada neste repositório de propósito,
porque este é um laboratório local descartável com dados fictícios — **isso
não se faz num projeto real**: lá, chaves privadas nunca entram no
controle de versão. Se forem perdidos, regenere com
`php bin/console security:change_oauth_key --force --no-interaction`
**depois** de restaurar `config_db.php`, e re-extraia os arquivos para
`lab/` com cuidado para não sobrescrever o arquivo por cima de si mesmo
(grave num caminho temporário e mova por cima, nunca redirecione a leitura
do próprio bind mount para o mesmo caminho host).

## Invariantes

- **Determinismo:** semente fixa em `src/gerar.ts`. Não use `Math.random()`.
- **Datas relativas:** ancoradas em `new Date()` no momento da regeneração,
  nunca absolutas — do contrário as perguntas temporais do enunciado quebram
  em semestres futuros.
- **Sem dado real.** Todo o conteúdo é inventado.
- **Rotas da API v2 confirmadas ao vivo:** a base de conhecimento é
  `/Knowledgebase/Article` (campo `content`, não `answer`), a categoria de
  chamado é `/Dropdowns/ITILCategory`, o usuário é criado com o campo
  `username` (não `name`), e o vínculo com o chamado (categoria, solicitante,
  técnico) usa os formatos confirmados ao vivo: `category: {id}` (objeto, não
  `itilcategories_id`) e `TeamMember` com `role: "requester"`/`"assigned"`.
  Ver `docs/api-glpi-v2.md` para a documentação completa da API.
