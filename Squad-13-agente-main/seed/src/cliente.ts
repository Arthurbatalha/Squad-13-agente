export interface ConfigCliente {
  base: string
  clientId: string
  clientSecret: string
  usuario: string
  senha: string
  /** Injetável para teste. */
  buscar?: typeof fetch
}

export interface Cliente {
  get<T>(caminho: string): Promise<T>
  post<T>(caminho: string, corpo: unknown): Promise<T>
  patch<T>(caminho: string, corpo: unknown): Promise<T>
}

// Observado ao vivo sob carga (Task 7, ~1800 requisições): sem "Connection:
// close", o pool de keep-alive do fetch (undici) ocasionalmente reutiliza
// uma conexão que o Apache do lab já está fechando, e a resposta chega com
// status 2xx correto mas corpo vazio — a escrita no GLPI aconteceu, só a
// resposta que se perdeu. Forçar conexão nova por requisição elimina a
// corrida; o custo de latência é desprezível no volume deste gerador.
const CABECALHOS_SEM_AUTH = { 'Content-Type': 'application/json', Connection: 'close' } as const

export async function criarCliente(config: ConfigCliente): Promise<Cliente> {
  const buscar = config.buscar ?? fetch
  const raiz = config.base.replace(/\/+$/, '')

  const resposta = await buscar(`${raiz}/api.php/token`, {
    method: 'POST',
    headers: CABECALHOS_SEM_AUTH,
    body: JSON.stringify({
      grant_type: 'password',
      client_id: config.clientId,
      client_secret: config.clientSecret,
      username: config.usuario,
      password: config.senha,
      scope: 'api',
    }),
  })

  if (!resposta.ok) {
    throw new Error(`falha ao obter token: ${resposta.status} ${await resposta.text()}`)
  }
  const dados = (await resposta.json()) as { access_token: string; refresh_token: string }
  let token = dados.access_token
  let refreshToken = dados.refresh_token

  async function renovarToken(): Promise<void> {
    const r = await buscar(`${raiz}/api.php/token`, {
      method: 'POST',
      headers: CABECALHOS_SEM_AUTH,
      body: JSON.stringify({
        grant_type: 'refresh_token',
        client_id: config.clientId,
        client_secret: config.clientSecret,
        refresh_token: refreshToken,
      }),
    })

    if (!r.ok) {
      throw new Error(`falha ao renovar token: ${r.status} ${await r.text()}`)
    }
    const dados = (await r.json()) as { access_token: string; refresh_token: string }
    token = dados.access_token
    refreshToken = dados.refresh_token
  }

  // Observado ao vivo sob carga (Task 7): a v2 ocasionalmente responde 2xx
  // com corpo vazio em sub-recursos de escrita (ex.: TeamMember), mesmo
  // quando a mesma chamada normalmente devolve {id, href}. Não é um erro —
  // a regra do lab é tratar qualquer 2xx como sucesso — então o corpo vazio
  // vira `undefined` em vez de estourar em JSON.parse.
  async function corpoJson<T>(r: Response): Promise<T> {
    const texto = await r.text()
    if (texto.length === 0) {
      return undefined as T
    }
    return JSON.parse(texto) as T
  }

  // GET nunca tem corpo — mandar Content-Type mesmo assim faz a v2 tentar
  // interpretar um corpo vazio como JSON e devolver 400 "Corpo JSON
  // inválido" (confirmado ao vivo na verificação de integridade da Task 7).
  function cabecalhos(corpo: unknown): Record<string, string> {
    return {
      Authorization: `Bearer ${token}`,
      Connection: 'close',
      ...(corpo === undefined ? {} : { 'Content-Type': 'application/json' }),
    }
  }

  async function chamar<T>(metodo: string, caminho: string, corpo?: unknown): Promise<T> {
    const r = await buscar(`${raiz}/api.php/v2${caminho}`, {
      method: metodo,
      headers: cabecalhos(corpo),
      ...(corpo === undefined ? {} : { body: JSON.stringify(corpo) }),
    })

    // A v2 responde 206 em listagens paginadas — 2xx inteiro é sucesso.
    if (r.status < 200 || r.status > 299) {
      const erroOriginal = new Error(`${metodo} ${caminho} → ${r.status} ${await r.text()}`)

      // Se foi 401, tenta renovar e repetir uma vez
      if (r.status === 401) {
        let renovacaoFalhou = false
        try {
          await renovarToken()
        } catch {
          renovacaoFalhou = true
        }

        if (renovacaoFalhou) {
          throw erroOriginal
        }

        // Repetir a requisição com o token novo
        const r2 = await buscar(`${raiz}/api.php/v2${caminho}`, {
          method: metodo,
          headers: cabecalhos(corpo),
          ...(corpo === undefined ? {} : { body: JSON.stringify(corpo) }),
        })

        if (r2.status < 200 || r2.status > 299) {
          throw new Error(`${metodo} ${caminho} → ${r2.status} ${await r2.text()}`)
        }
        return corpoJson<T>(r2)
      }

      throw erroOriginal
    }
    return corpoJson<T>(r)
  }

  return {
    get: (caminho) => chamar('GET', caminho),
    post: (caminho, corpo) => chamar('POST', caminho, corpo),
    patch: (caminho, corpo) => chamar('PATCH', caminho, corpo),
  }
}
