<?php
/**
 * Habilita a API v2 (High-Level API) e cria o cliente OAuth do laboratório
 * com credenciais fixas e conhecidas — necessário porque
 * OAuthClient::add() (o caminho usado pela interface web) sempre gera um
 * identifier/secret novos e aleatórios, ignorando qualquer valor recebido.
 *
 * Roda dentro do container `glpi`, depois do `database:install`:
 *
 *   docker compose exec -u www-data -T glpi php /tmp/preparar-oauth.php
 *   docker compose exec -u www-data -T glpi php bin/console cache:clear
 *
 * Ou via scripts/preparar-oauth.sh, que faz os dois passos.
 *
 * Idempotente: se o cliente já existir (mesmo identifier), não duplica.
 *
 * Credenciais fixas — documentadas em lab/oauth-client.md. É um laboratório
 * local com dados fictícios; a reprodutibilidade em qualquer máquina vale
 * mais que o sigilo aqui (mesma razão da senha glpi/glpi).
 */

require_once '/var/www/glpi/vendor/autoload.php';

$kernel = new \Glpi\Kernel\Kernel('production');
$kernel->boot();

global $DB;

const CLIENT_IDENTIFIER = '92e1a8497a5136e410301a573b8282bb';
const CLIENT_SECRET_PLAIN = '156df3c0f488cd8be63a5ee3731568da3afa60239bed1018c8cec9f4c5355c17';

// 1. Habilita a High-Level API (vem desligada por padrão numa instalação nova).
$DB->update('glpi_configs', ['value' => '1'], [
    'context' => 'core',
    'name'    => ['enable_api', 'enable_hlapi'],
]);
echo "Config: enable_api=1, enable_hlapi=1\n";

// 2. Cria o cliente OAuth, se ainda não existir.
$existing = $DB->request([
    'FROM'  => 'glpi_oauthclients',
    'WHERE' => ['identifier' => CLIENT_IDENTIFIER],
]);

if (count($existing) > 0) {
    echo "Cliente OAuth '" . CLIENT_IDENTIFIER . "' já existe — nada a fazer.\n";
    exit(0);
}

$key = new GLPIKey();

$ok = $DB->insert('glpi_oauthclients', [
    'identifier'      => CLIENT_IDENTIFIER,
    'name'            => 'Laboratorio Alunos',
    'comment'         => 'Cliente OAuth do laboratorio - credenciais fixas para os alunos',
    'secret'          => $key->encrypt(CLIENT_SECRET_PLAIN),
    'redirect_uri'    => json_encode(['/api.php/oauth2/redirection']),
    'grants'          => json_encode(['password', 'refresh_token']),
    'scopes'          => json_encode(['api']),
    'is_active'       => 1,
    'is_confidential' => 1,
]);

if (!$ok) {
    fwrite(STDERR, "FALHA ao inserir o cliente OAuth\n");
    exit(1);
}

echo "Cliente OAuth criado: client_id=" . CLIENT_IDENTIFIER . "\n";
