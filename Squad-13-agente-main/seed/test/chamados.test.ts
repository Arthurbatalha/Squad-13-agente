import { describe, it, expect } from 'vitest'
import { criarAleatorio } from '../src/aleatorio'
import { criarCalendario } from '../src/datas'
import { gerarChamados } from '../src/chamados'
import { CATEGORIAS } from '../src/catalogo/categorias'
import { USUARIOS } from '../src/catalogo/usuarios'

const opcoes = (quantidade = 300) => ({
  quantidade,
  aleatorio: criarAleatorio(2026),
  calendario: criarCalendario(new Date('2026-08-26T12:00:00Z')),
})

describe('gerarChamados', () => {
  it('gera a quantidade pedida', () => {
    expect(gerarChamados(opcoes())).toHaveLength(300)
  })

  it('é determinístico', () => {
    expect(gerarChamados(opcoes())).toEqual(gerarChamados(opcoes()))
  })

  it('usa apenas categorias e usuários do catálogo', () => {
    const chaves = new Set(CATEGORIAS.map((c) => c.chave))
    const logins = new Set(USUARIOS.map((u) => u.login))
    const tecnicos = new Set(USUARIOS.filter((u) => u.tecnico).map((u) => u.login))

    for (const c of gerarChamados(opcoes())) {
      expect(chaves).toContain(c.categoria)
      expect(logins).toContain(c.solicitante)
      if (c.tecnico !== null) expect(tecnicos).toContain(c.tecnico)
    }
  })

  it('a distribuição por categoria não é uniforme — há uma dominante', () => {
    const porCategoria = new Map<string, number>()
    for (const c of gerarChamados(opcoes())) {
      porCategoria.set(c.categoria, (porCategoria.get(c.categoria) ?? 0) + 1)
    }
    const contagens = [...porCategoria.values()].sort((a, b) => b - a)
    // A dominante tem pelo menos o dobro da menos frequente.
    expect(contagens[0]!).toBeGreaterThan(contagens[contagens.length - 1]! * 2)
  })

  it('cobre cerca de 18 meses de histórico', () => {
    const datas = gerarChamados(opcoes()).map((c) => new Date(c.criadoEm.replace(' ', 'T') + 'Z'))
    const maisAntigo = Math.min(...datas.map((d) => d.getTime()))
    const dias = (new Date('2026-08-26T12:00:00Z').getTime() - maisAntigo) / 86_400_000
    expect(dias).toBeGreaterThan(500)
    expect(dias).toBeLessThanOrEqual(550)
  })

  it('tem picos sazonais — algum mês concentra bem mais que a média', () => {
    const porMes = new Map<string, number>()
    for (const c of gerarChamados(opcoes())) {
      const mes = c.criadoEm.slice(0, 7)
      porMes.set(mes, (porMes.get(mes) ?? 0) + 1)
    }
    const contagens = [...porMes.values()]
    const media = contagens.reduce((s, n) => s + n, 0) / contagens.length
    expect(Math.max(...contagens)).toBeGreaterThan(media * 1.8)
  })

  it('só chamados solucionados ou fechados têm solução na timeline', () => {
    for (const c of gerarChamados(opcoes())) {
      const temSolucao = c.timeline.some((i) => i.tipo === 'solucao')
      if (c.status === 'solucionado' || c.status === 'fechado') {
        expect(temSolucao, `chamado "${c.titulo}" deveria ter solução`).toBe(true)
      } else {
        expect(temSolucao, `chamado "${c.titulo}" não deveria ter solução`).toBe(false)
      }
    }
  })

  it('chamados novos não têm técnico atribuído', () => {
    for (const c of gerarChamados(opcoes())) {
      if (c.status === 'novo') expect(c.tecnico).toBeNull()
      else expect(c.tecnico).not.toBeNull()
    }
  })

  it('a timeline nunca é anterior à abertura', () => {
    for (const c of gerarChamados(opcoes())) {
      for (const item of c.timeline) {
        expect(item.data >= c.criadoEm, `timeline de "${c.titulo}" antes da abertura`).toBe(true)
      }
    }
  })

  it('a prioridade fica na faixa do GLPI (1 a 5)', () => {
    for (const c of gerarChamados(opcoes())) {
      expect(c.prioridade).toBeGreaterThanOrEqual(1)
      expect(c.prioridade).toBeLessThanOrEqual(5)
    }
  })

  it('as descrições variam bastante — poucas repetições exatas de um mesmo texto', () => {
    const contagem = new Map<string, number>()
    for (const c of gerarChamados(opcoes())) {
      contagem.set(c.descricao, (contagem.get(c.descricao) ?? 0) + 1)
    }
    const distintas = contagem.size
    const repeticaoMaxima = Math.max(...contagem.values())
    // Corpus sintético de similaridade: duplicatas exatas tornariam a busca
    // por chamados parecidos trivial (similaridade 1.0 por string).
    expect(distintas).toBeGreaterThan(100)
    expect(repeticaoMaxima).toBeLessThanOrEqual(15)
  })
})
