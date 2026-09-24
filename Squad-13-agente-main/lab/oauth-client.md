# Cliente OAuth do laboratório

O `lab/seed.sql` já carrega o cliente abaixo congelado no banco — você não
precisa rodar nada, só `docker compose up`. `scripts/preparar-oauth.sh`
existe só para quem for **regenerar** o corpus do zero (ver
`seed/README.md`), contra um banco recém-instalado e vazio; não é parte do
seu fluxo normal.

- **client_id:** `92e1a8497a5136e410301a573b8282bb`
- **client_secret:** `156df3c0f488cd8be63a5ee3731568da3afa60239bed1018c8cec9f4c5355c17`
- **grants:** password, refresh_token
- **escopo:** api

Usuário do laboratório: `glpi` / `glpi` (perfil Super-Admin).

## Por que essas credenciais são literais neste arquivo

O secret é armazenado **criptografado** no banco (`glpi_oauthclients.secret`),
com a chave em `lab/glpicrypt.key`. O GLPI usa essa chave (32 bytes, lida de
`config/glpicrypt.key`) para cifrar e decifrar o secret do cliente OAuth; sem
ela, ninguém consegue reverter o valor gravado no banco. Por padrão essa
chave é gerada durante a instalação e vive só na camada de escrita do
container — cada `docker compose down -v && up` criaria uma chave nova, e o
secret congelado no `seed.sql` ficaria indecifrável, quebrando o login OAuth
(e com ele a API inteira) logo no primeiro reset.

Por isso `lab/glpicrypt.key` é fixa e versionada neste repositório, montada
por bind mount no `docker-compose.yml`, de propósito — pela mesma razão que
as senhas `glpi`/`glpi` são: é um laboratório local com dados fictícios, e a
reprodutibilidade em qualquer máquina vale mais que o sigilo aqui. Pela
mesma razão, `lab/config_db.php`, `lab/oauth.pem` e `lab/oauth.pub` também
são fixos e montados por bind mount — sem eles, o mesmo reset perderia a
configuração de conexão com o banco e as chaves de assinatura dos tokens, e
o instalador do GLPI voltaria a aparecer mesmo com o `seed.sql` restaurado
(ver `seed/README.md` para os detalhes desses três arquivos).

**Atenção:** `lab/oauth.pem` é uma **chave privada** (assina os JWT do
`/api.php/token`), não só "um par de chaves RSA" genérico. Ela está
versionada aqui de propósito, porque é um laboratório local descartável com
dados fictícios — isso não é prática aceitável fora deste contexto; num
projeto real, chave privada nunca vai para o controle de versão.

## Por que existe um script em vez de só este arquivo

Uma instalação nova do GLPI 11.0.8 tem a API v2 **desligada por padrão**.
Sem habilitá-la, toda chamada em `/api.php/v2/...` volta `403` com
`"detail":"The High-Level API is disabled"`, mesmo com um token válido. E
criar o cliente OAuth com uma interface (web ou `OAuthClient::add()`)
sempre gera um `identifier`/`secret` aleatórios, ignorando qualquer valor
fornecido — não dá para fixar as credenciais por esse caminho.

`scripts/preparar-oauth.sh` resolve os dois problemas: liga
`enable_api`/`enable_hlapi` em `glpi_configs` (contexto `core`), limpa o
cache do GLPI, e insere o cliente direto no banco com o secret já
criptografado com a chave fixa (`lab/glpicrypt.key`) — as mesmas credenciais
declaradas acima. Essa lógica já está congelada no `seed.sql`; o script
permanece só para regenerá-lo. É idempotente: pode rodar de novo sem
duplicar nada.

## Obtendo um token

```bash
curl -s -X POST http://localhost:8080/api.php/token \
  -H 'Content-Type: application/json' \
  -d '{"grant_type":"password","client_id":"92e1a8497a5136e410301a573b8282bb","client_secret":"156df3c0f488cd8be63a5ee3731568da3afa60239bed1018c8cec9f4c5355c17","username":"glpi","password":"glpi","scope":"api"}'
```
