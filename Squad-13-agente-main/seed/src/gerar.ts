import { criarCliente, type Cliente } from './cliente'
import { criarAleatorio } from './aleatorio'
import { criarCalendario } from './datas'
import { CATEGORIAS } from './catalogo/categorias'
import { USUARIOS } from './catalogo/usuarios'
import { ARTIGOS } from './catalogo/artigos'
import { gerarChamados, type ChamadoGerado } from './chamados'

// Rotas confirmadas ao vivo — ver
// .superpowers/sdd/2026-08-26-glpi-agent-lab/correcoes-para-task-7.md.
// O brief original desta task errava as três primeiras.
const ROTA_KB = '/Knowledgebase/Article'
const ROTA_CATEGORIA = '/Dropdowns/ITILCategory'
const ROTA_USUARIO = '/Administration/User'
const SEMENTE = 2026
const QUANTIDADE_CHAMADOS = 300

const STATUS_GLPI: Record<string, number> = {
  novo: 1,
  em_atendimento: 2,
  solucionado: 5,
  fechado: 6,
}

function exigir(nome: string): string {
  const valor = process.env[nome]
  if (!valor) throw new Error(`variável de ambiente ${nome} é obrigatória`)
  return valor
}

interface RegistroChamado {
  id: number
  chamado: ChamadoGerado
}

/**
 * Verificação de integridade contra o GLPI real — não contra o que o
 * script *pensa* que enviou.
 *
 * Por quê: o cliente (Task 4) trata qualquer 2xx como sucesso e, desde a
 * correção de "Connection: close", tolera corpo vazio em respostas 2xx sem
 * estourar. Isso é necessário (a v2 ocasionalmente devolve 2xx vazio em
 * sub-recursos de escrita mesmo quando a gravação aconteceu), mas também
 * significa que, se alguma escrita *realmente* falhar em silêncio — 2xx
 * vazio sem gravar nada —, o gerador não teria como perceber sozinho.
 * Para as chamadas cujo retorno é usado (categoria, usuário, chamado), uma
 * falha real estoura logo em seguida (a chamada seguinte usa o id que não
 * veio). Mas TeamMember, Followup/Solution e o PATCH de status — a maioria
 * das requisições — nunca têm o sucesso reconferido no caminho principal.
 *
 * Um teste de unidade com fetch mockado não resolve isso: ele não consegue
 * distinguir "gravou sem responder" de "não gravou" — só o servidor real
 * sabe. Por isso a verificação é uma consulta ao GLPI depois de todo o
 * corpus criado, conferindo o que foi de fato persistido contra o que
 * deveria ter sido. Qualquer divergência aborta o gerador com erro
 * descritivo — nunca termina em silêncio com corpus incompleto.
 */
async function verificarIntegridade(
  cliente: Cliente,
  registros: RegistroChamado[],
): Promise<void> {
  const erros: string[] = []

  interface TicketApi {
    id: number
    status: { id: number; name: string }
  }
  interface TimelineItemApi {
    type: 'Followup' | 'Solution' | string
  }
  interface TeamMemberApi {
    role: 'requester' | 'assigned' | 'observer' | string
  }

  const listaChamados = await cliente.get<TicketApi[]>('/Assistance/Ticket?start=0&limit=999')
  if (listaChamados.length !== QUANTIDADE_CHAMADOS) {
    erros.push(
      `contagem de chamados: esperava ${QUANTIDADE_CHAMADOS}, encontrei ${listaChamados.length}`,
    )
  }

  const listaArtigos = await cliente.get<unknown[]>(`${ROTA_KB}?start=0&limit=999`)
  if (listaArtigos.length !== ARTIGOS.length) {
    erros.push(`contagem de artigos de KB: esperava ${ARTIGOS.length}, encontrei ${listaArtigos.length}`)
  }

  const listaCategorias = await cliente.get<unknown[]>(`${ROTA_CATEGORIA}?start=0&limit=999`)
  if (listaCategorias.length !== CATEGORIAS.length) {
    erros.push(
      `contagem de categorias: esperava ${CATEGORIAS.length}, encontrei ${listaCategorias.length}`,
    )
  }

  const loginsEsperados = new Set(USUARIOS.map((u) => u.login))
  const listaUsuarios = await cliente.get<{ username: string }[]>(`${ROTA_USUARIO}?start=0&limit=999`)
  const usuariosDoCorpus = listaUsuarios.filter((u) => loginsEsperados.has(u.username))
  if (usuariosDoCorpus.length !== loginsEsperados.size) {
    erros.push(
      `contagem de usuários do corpus: esperava ${loginsEsperados.size}, encontrei ${usuariosDoCorpus.length}`,
    )
  }

  const statusPorId = new Map(listaChamados.map((t) => [t.id, t.status.id]))

  let semSolucaoEmSolucionadoOuFechado = 0
  let solucaoEmNovoOuAtendimento = 0
  let semTecnicoAtribuido = 0
  let semSolicitante = 0

  for (const { id } of registros) {
    const statusId = statusPorId.get(id)
    if (statusId === undefined) {
      erros.push(`chamado ${id}: não encontrado na listagem de chamados`)
      continue
    }

    const timeline = await cliente.get<TimelineItemApi[]>(`/Assistance/Ticket/${id}/Timeline`)
    const temSolucao = timeline.some((item) => item.type === 'Solution')

    const precisaSolucao = statusId === STATUS_GLPI.solucionado || statusId === STATUS_GLPI.fechado
    if (precisaSolucao && !temSolucao) semSolucaoEmSolucionadoOuFechado++
    if (!precisaSolucao && temSolucao) solucaoEmNovoOuAtendimento++

    const equipe = await cliente.get<TeamMemberApi[]>(`/Assistance/Ticket/${id}/TeamMember`)
    const temAssigned = equipe.some((m) => m.role === 'assigned')
    const temRequester = equipe.some((m) => m.role === 'requester')

    if (statusId !== STATUS_GLPI.novo && !temAssigned) semTecnicoAtribuido++
    if (!temRequester) semSolicitante++
  }

  if (semSolucaoEmSolucionadoOuFechado > 0) {
    erros.push(
      `${semSolucaoEmSolucionadoOuFechado} chamado(s) solucionado(s)/fechado(s) sem solução na timeline`,
    )
  }
  if (solucaoEmNovoOuAtendimento > 0) {
    erros.push(`${solucaoEmNovoOuAtendimento} chamado(s) novo(s)/em atendimento com solução indevida`)
  }
  if (semTecnicoAtribuido > 0) {
    erros.push(`${semTecnicoAtribuido} chamado(s) não-novo(s) sem técnico atribuído (role assigned)`)
  }
  if (semSolicitante > 0) {
    erros.push(`${semSolicitante} chamado(s) sem solicitante (role requester)`)
  }

  if (erros.length > 0) {
    throw new Error(
      `verificação de integridade falhou (${erros.length} problema(s)):\n  - ${erros.join('\n  - ')}`,
    )
  }

  console.log('verificação de integridade: ok')
  console.log(`  chamados: ${listaChamados.length}`)
  console.log(`  artigos de KB: ${listaArtigos.length}`)
  console.log(`  categorias: ${listaCategorias.length}`)
  console.log(`  usuários do corpus: ${usuariosDoCorpus.length}`)
}

async function principal(): Promise<void> {
  const inicio = Date.now()

  const cliente = await criarCliente({
    base: process.env.GLPI_BASE ?? 'http://localhost:8080',
    clientId: exigir('CLIENT_ID'),
    clientSecret: exigir('CLIENT_SECRET'),
    usuario: 'glpi',
    senha: 'glpi',
  })

  const aleatorio = criarAleatorio(SEMENTE)
  // Âncora explícita: as datas do corpus são relativas ao momento da regeneração.
  const calendario = criarCalendario(new Date())

  console.log('criando categorias...')
  const idCategoria = new Map<string, number>()
  for (const c of CATEGORIAS) {
    const r = await cliente.post<{ id: number }>(ROTA_CATEGORIA, { name: c.nome })
    idCategoria.set(c.chave, r.id)
  }

  console.log('criando usuários...')
  const idUsuario = new Map<string, number>()
  for (const u of USUARIOS) {
    // Campo de login é "username", não "name" (brief original errava isso
    // — confirmado ao vivo pelo schema de /Administration/User no doc.json
    // e pela resposta 500 "O login não é válido" ao usar "name").
    const r = await cliente.post<{ id: number }>(ROTA_USUARIO, {
      username: u.login,
      firstname: u.nome,
      realname: u.sobrenome,
      password: 'laboratorio',
      password2: 'laboratorio',
    })
    idUsuario.set(u.login, r.id)
  }

  console.log(`criando ${ARTIGOS.length} artigos de KB...`)
  for (const a of ARTIGOS) {
    // Campo de conteúdo é "content", não "answer" (brief original errava isso).
    await cliente.post(ROTA_KB, { name: a.titulo, content: a.corpo })
  }

  const chamados = gerarChamados({ quantidade: QUANTIDADE_CHAMADOS, aleatorio, calendario })
  console.log(`criando ${chamados.length} chamados...`)

  const registros: RegistroChamado[] = []

  for (const [i, c] of chamados.entries()) {
    const criado = await cliente.post<{ id: number }>('/Assistance/Ticket', {
      name: c.titulo,
      content: c.descricao,
      priority: c.prioridade,
      // O campo é "category: {id}" (objeto), não "itilcategories_id" — a v2
      // expande dropdowns inline nas respostas e espera o mesmo na escrita
      // (confirmado ao vivo; nem o brief nem as correções documentavam isso).
      category: { id: idCategoria.get(c.categoria) },
      date: c.criadoEm,
    })

    registros.push({ id: criado.id, chamado: c })

    // O gerador da Task 6 sorteia um solicitante para cada chamado (ver
    // seed/src/chamados.ts); o brief original desta task não o consumia,
    // deixando o campo sem uso — corrigido aqui gravando-o como TeamMember
    // com role "requester" (papel confirmado no plano da Task 3/4).
    await cliente.post(`/Assistance/Ticket/${criado.id}/TeamMember`, {
      type: 'User',
      id: idUsuario.get(c.solicitante),
      role: 'requester',
    })

    if (c.tecnico) {
      await cliente.post(`/Assistance/Ticket/${criado.id}/TeamMember`, {
        type: 'User',
        id: idUsuario.get(c.tecnico),
        role: 'assigned',
      })
    }

    for (const item of c.timeline) {
      const sub = item.tipo === 'solucao' ? 'Solution' : 'Followup'
      await cliente.post(`/Assistance/Ticket/${criado.id}/Timeline/${sub}`, {
        content: item.conteudo,
      })
    }

    // O status vai por último: o GLPI recalcula status ao adicionar solução.
    // A v2 usa PATCH para atualização (confirmado ao vivo — ver correções).
    await cliente.patch(`/Assistance/Ticket/${criado.id}`, { status: STATUS_GLPI[c.status] })

    if ((i + 1) % 50 === 0) {
      console.log(`  ${i + 1}/${chamados.length} chamados criados...`)
    }
  }

  console.log('conferindo integridade do corpus contra o GLPI...')
  await verificarIntegridade(cliente, registros)

  const duracaoMs = Date.now() - inicio
  console.log(`pronto. duração: ${(duracaoMs / 1000).toFixed(1)}s`)
}

principal().catch((erro) => {
  console.error(erro)
  process.exit(1)
})
