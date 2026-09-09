#!/usr/bin/env bash
# Habilita a API v2 e garante que o cliente OAuth do laboratório existe,
# com as credenciais fixas documentadas em lab/oauth-client.md.
#
# O `lab/seed.sql` já carrega o cliente OAuth congelado — quem só quer usar
# o laboratório nunca precisa rodar este script. Ele existe só para quem for
# regenerar o corpus (ver seed/README.md): rode-o depois de um
# `database:install` contra um banco vazio, antes de rodar `npm run gerar`.
# É idempotente: pode rodar de novo sem duplicar o cliente.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR/../lab"

GLPI_CID=$(docker compose ps -q glpi)
if [ -z "$GLPI_CID" ]; then
  echo "Container 'glpi' não está de pé. Rode 'docker compose up -d' primeiro." >&2
  exit 1
fi

docker cp "$SCRIPT_DIR/preparar-oauth.php" "$GLPI_CID:/tmp/preparar-oauth.php"
docker compose exec -u www-data -T glpi php /tmp/preparar-oauth.php
docker compose exec -u www-data -T glpi php bin/console cache:clear
