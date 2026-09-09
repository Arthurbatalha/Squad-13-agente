import { describe, it, expect, vi } from 'vitest'
import { criarCliente } from '../src/cliente'

const CONFIG_BASE = {
  base: 'http://lab:8080',
  clientId: 'id',
  clientSecret: 'segredo',
  usuario: 'glpi',
  senha: 'glpi',
}

const respostaToken = () =>
  new Response(JSON.stringify({ access_token: 'TOK', refresh_token: 'REF', expires_in: 3600 }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

describe('criarCliente', () => {
  it('autentica no endpoint de token antes de qualquer chamada', async () => {
    const buscar = vi.fn().mockResolvedValueOnce(respostaToken())
    await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })

    expect(buscar).toHaveBeenCalledTimes(1)
    const [url, init] = buscar.mock.calls[0]!
    expect(url).toBe('http://lab:8080/api.php/token')
    expect(JSON.parse(init.body).grant_type).toBe('password')
  })

  it('manda o Bearer nas chamadas seguintes', async () => {
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(respostaToken())
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))

    const cliente = await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })
    await cliente.get('/Assistance/Ticket')

    const [url, init] = buscar.mock.calls[1]!
    expect(url).toBe('http://lab:8080/api.php/v2/Assistance/Ticket')
    expect(init.headers.Authorization).toBe('Bearer TOK')
  })

  it('get não manda Content-Type — a v2 tenta ler corpo vazio como JSON e devolve 400', async () => {
    // Confirmado ao vivo: GET com "Content-Type: application/json" e sem
    // corpo faz a v2 responder 400 "Corpo JSON inválido".
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(respostaToken())
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))

    const cliente = await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })
    await cliente.get('/Assistance/Ticket')

    const [, init] = buscar.mock.calls[1]!
    expect(init.headers['Content-Type']).toBeUndefined()
  })

  it('post manda Content-Type — tem corpo', async () => {
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(respostaToken())
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 1 }), { status: 201 }))

    const cliente = await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })
    await cliente.post('/Assistance/Ticket', { name: 'x' })

    const [, init] = buscar.mock.calls[1]!
    expect(init.headers['Content-Type']).toBe('application/json')
  })

  it('aceita HTTP 206 como sucesso — a v2 pagina com 206', async () => {
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(respostaToken())
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: 1 }]), { status: 206 }))

    const cliente = await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })
    await expect(cliente.get('/Assistance/Ticket')).resolves.toEqual([{ id: 1 }])
  })

  it('2xx com corpo vazio não estoura — devolve undefined em vez de lançar', async () => {
    // Observado ao vivo sob carga: a v2 às vezes responde 2xx com corpo
    // vazio em sub-recursos de escrita (a escrita aconteceu; só a resposta
    // que se perdeu). JSON.parse('') estouraria; a regra do lab é tratar
    // qualquer 2xx como sucesso.
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(respostaToken())
      .mockResolvedValueOnce(new Response('', { status: 201 }))

    const cliente = await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })
    await expect(cliente.post('/Assistance/Ticket/1/TeamMember', { type: 'User', id: 2 })).resolves.toBeUndefined()
  })

  it('cada chamada manda Connection: close, para evitar corrida de keep-alive', async () => {
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(respostaToken())
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))

    const cliente = await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })
    await cliente.get('/Assistance/Ticket')

    const [, init] = buscar.mock.calls[1]!
    expect(init.headers.Connection).toBe('close')
  })

  it('lança erro com corpo legível quando a resposta falha', async () => {
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(respostaToken())
      .mockResolvedValueOnce(new Response('campo obrigatório ausente', { status: 400 }))

    const cliente = await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })
    await expect(cliente.post('/Assistance/Ticket', {})).rejects.toThrow(
      /400.*campo obrigatório ausente/s,
    )
  })

  it('envia o corpo achatado no post, sem envelope input', async () => {
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(respostaToken())
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 9 }), { status: 201 }))

    const cliente = await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })
    await cliente.post('/Assistance/Ticket', { name: 'x' })

    const corpo = JSON.parse(buscar.mock.calls[1]![1].body)
    expect(corpo).toEqual({ name: 'x' })
    expect(corpo.input).toBeUndefined()
  })

  it('patch envia o método PATCH com o corpo achatado', async () => {
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(respostaToken())
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 9, status: 5 }), { status: 200 }))

    const cliente = await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })
    await cliente.patch('/Assistance/Ticket/9', { status: 5 })

    const [url, init] = buscar.mock.calls[1]!
    expect(url).toBe('http://lab:8080/api.php/v2/Assistance/Ticket/9')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body)).toEqual({ status: 5 })
  })

  it('base terminando com barra não produz //api.php', async () => {
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(respostaToken())
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))

    const cliente = await criarCliente({
      ...CONFIG_BASE,
      base: 'http://lab:8080/',
      buscar: buscar as unknown as typeof fetch,
    })
    await cliente.get('/Assistance/Ticket')

    const [url] = buscar.mock.calls[1]!
    expect(url).toBe('http://lab:8080/api.php/v2/Assistance/Ticket')
  })

  it('corpo de autenticação envia client_id, client_secret, username, password e scope', async () => {
    const buscar = vi.fn().mockResolvedValueOnce(respostaToken())
    await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })

    const corpo = JSON.parse(buscar.mock.calls[0]![1].body)
    expect(corpo.client_id).toBe('id')
    expect(corpo.client_secret).toBe('segredo')
    expect(corpo.username).toBe('glpi')
    expect(corpo.password).toBe('glpi')
    expect(corpo.scope).toBe('api')
  })

  it('401 numa chamada dispara renovação e a chamada é repetida com o token novo', async () => {
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(respostaToken()) // autenticação inicial
      .mockResolvedValueOnce(new Response(JSON.stringify({}), { status: 401 })) // primeiro GET retorna 401
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: 'TOK2', refresh_token: 'REF2', expires_in: 3600 }), {
          status: 200,
        }),
      ) // renovação bem-sucedida
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 })) // GET repetido com token novo

    const cliente = await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })
    await cliente.get('/Assistance/Ticket')

    // Verificar que a requisição repetida (4ª chamada) tem o token novo
    const [, init4] = buscar.mock.calls[3]!
    expect(init4.headers.Authorization).toBe('Bearer TOK2')
  })

  it('renovação usa grant_type refresh_token e envia o refresh_token recebido', async () => {
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(respostaToken()) // autenticação inicial com refresh_token: 'REF'
      .mockResolvedValueOnce(new Response(JSON.stringify({}), { status: 401 })) // GET retorna 401
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: 'TOK2', refresh_token: 'REF2', expires_in: 3600 }), {
          status: 200,
        }),
      ) // renovação
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 })) // GET repetido

    const cliente = await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })
    await cliente.get('/Assistance/Ticket')

    // Verificar que a chamada de renovação (3ª) usa refresh_token grant e envia o refresh_token original
    const corpoRenovacao = JSON.parse(buscar.mock.calls[2]![1].body)
    expect(corpoRenovacao.grant_type).toBe('refresh_token')
    expect(corpoRenovacao.refresh_token).toBe('REF')
  })

  it('se a renovação falhar, o erro original da chamada é propagado', async () => {
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(respostaToken()) // autenticação inicial
      .mockResolvedValueOnce(new Response('sessão expirada', { status: 401 })) // GET retorna 401
      .mockResolvedValueOnce(new Response('credenciais inválidas', { status: 400 })) // renovação falha

    const cliente = await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })
    await expect(cliente.get('/Assistance/Ticket')).rejects.toThrow(/401.*sessão expirada/s)
  })

  it('401 na chamada repetida (após renovação bem-sucedida) propaga erro sem renovar de novo', async () => {
    const buscar = vi
      .fn()
      .mockResolvedValueOnce(respostaToken()) // autenticação inicial
      .mockResolvedValueOnce(new Response(JSON.stringify({}), { status: 401 })) // GET retorna 401
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: 'TOK2', refresh_token: 'REF2', expires_in: 3600 }), {
          status: 200,
        }),
      ) // renovação bem-sucedida
      .mockResolvedValueOnce(new Response('ainda não autorizado', { status: 401 })) // GET repetido ainda falha com 401

    const cliente = await criarCliente({ ...CONFIG_BASE, buscar: buscar as unknown as typeof fetch })
    await expect(cliente.get('/Assistance/Ticket')).rejects.toThrow(/401.*ainda não autorizado/s)

    // Verificar que não houve 5ª chamada (não tentou renovar de novo)
    expect(buscar).toHaveBeenCalledTimes(4)
  })
})
