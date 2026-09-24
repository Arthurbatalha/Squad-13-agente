#!/usr/bin/env bash
# Verifica que o lab está de pé e utilizável.
set -euo pipefail

BASE="${GLPI_BASE:-http://localhost:8080}"
# Rota da base de conhecimento confirmada ao vivo.
ROTA_KB="${ROTA_KB:-/Knowledgebase/Article}"
# Credenciais fixas do cliente OAuth do laboratório (ver lab/oauth-client.md)
# — são públicas de propósito, então servem como padrão. Pode sobrescrever
# via variável de ambiente se estiver usando outro cliente.
CLIENT_ID="${CLIENT_ID:-92e1a8497a5136e410301a573b8282bb}"
CLIENT_SECRET="${CLIENT_SECRET:-156df3c0f488cd8be63a5ee3731568da3afa60239bed1018c8cec9f4c5355c17}"
falhas=0

checar() {
  local descricao="$1" esperado="$2" obtido="$3"
  if [ "$esperado" = "$obtido" ]; then
    echo "  ok   $descricao"
  else
    echo "  FALHA $descricao (esperado: $esperado, obtido: $obtido)"
    falhas=$((falhas + 1))
  fi
}

echo "Verificando lab em $BASE"

codigo=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/index.php" || echo 000)
checar "GLPI responde na raiz" "200" "$codigo"

# O instalador não pode estar acessível: se estiver, o banco não foi instalado.
instalador=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/install/install.php" || echo 000)
if [ "$instalador" = "200" ]; then
  echo "  FALHA instalador ainda acessível — banco não foi instalado"
  falhas=$((falhas + 1))
else
  echo "  ok   instalador não está exposto"
fi

# --- corpus ---
# Paginação da v2 é por start/limit, não range (confirmado ao vivo). Uma
# página que cobre tudo devolve 200; uma fatia parcial devolve 206. Ambos
# são sucesso.
TOKEN=$(curl -s -X POST "$BASE/api.php/token" \
  -H 'Content-Type: application/json' \
  -d "{\"grant_type\":\"password\",\"client_id\":\"${CLIENT_ID}\",\"client_secret\":\"${CLIENT_SECRET}\",\"username\":\"glpi\",\"password\":\"glpi\",\"scope\":\"api\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null || echo "")

if [ -z "$TOKEN" ]; then
  echo "  FALHA não consegui obter token OAuth"
  falhas=$((falhas + 1))
else
  echo "  ok   token OAuth obtido"

  contar() {
    curl -s "$BASE/api.php/v2$1?start=0&limit=999" -H "Authorization: Bearer $TOKEN" \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 0)'
  }

  tickets=$(contar /Assistance/Ticket)
  if [ "$tickets" -ge 250 ]; then
    echo "  ok   chamados no corpus: $tickets"
  else
    echo "  FALHA poucos chamados: $tickets (esperado >= 250)"
    falhas=$((falhas + 1))
  fi

  artigos=$(contar "$ROTA_KB")
  if [ "$artigos" -ge 40 ]; then
    echo "  ok   artigos de KB: $artigos"
  else
    echo "  FALHA poucos artigos de KB: $artigos (esperado >= 40)"
    falhas=$((falhas + 1))
  fi
fi

if [ "$falhas" -ne 0 ]; then
  echo "FALHOU: $falhas verificação(ões)"
  exit 1
fi
echo "TUDO OK"
