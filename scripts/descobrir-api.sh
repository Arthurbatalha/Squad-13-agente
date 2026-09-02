#!/usr/bin/env bash
# Lista as rotas da API v2 desta instância, a partir do swagger real.
#
# Descoberto ao vivo contra o lab local (GLPI 11.0.8):
#   - O swagger só tem conteúdo em /api.php/v2/doc.json (não em
#     /api.php/v2.3.0/doc.json nem /api.php/doc.json).
#   - O endpoint é público — responde sem header Authorization, testado
#     tanto de fora do container quanto de dentro dele. Só precisa que a
#     "High-Level API" esteja habilitada em config (glpi_configs.enable_hlapi=1
#     no contexto 'core' — desligada por padrão numa instalação nova; o
#     scripts/preparar-oauth.sh já cuida disso).
#
# Uso:
#   GLPI_BASE=http://localhost:8080 ./scripts/descobrir-api.sh knowbase
set -euo pipefail

BASE="${GLPI_BASE:-http://localhost:8080}"
FILTRO="${1:-}"

corpo=$(curl -s "$BASE/api.php/v2/doc.json")

if [ "${#corpo}" -le 500 ]; then
  echo "Swagger vazio ou inacessível em $BASE/api.php/v2/doc.json" >&2
  echo "$corpo" >&2
  exit 1
fi

echo "# swagger encontrado em /api.php/v2/doc.json (${#corpo} bytes)"
echo "$corpo" | python3 -c '
import json,sys
spec = json.load(sys.stdin)
for rota in sorted(spec.get("paths", {})):
    print(rota)
' | { [ -n "$FILTRO" ] && grep -i "$FILTRO" || cat; }
