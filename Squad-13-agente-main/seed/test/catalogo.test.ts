import { describe, it, expect } from 'vitest'
import { CATEGORIAS } from '../src/catalogo/categorias'
import { USUARIOS } from '../src/catalogo/usuarios'
import { ARTIGOS } from '../src/catalogo/artigos'

describe('catálogo', () => {
  it('tem 6 categorias com chaves únicas', () => {
    expect(CATEGORIAS).toHaveLength(6)
    expect(new Set(CATEGORIAS.map((c) => c.chave)).size).toBe(6)
  })

  it('tem ao menos 15 usuários, com técnicos entre eles', () => {
    expect(USUARIOS.length).toBeGreaterThanOrEqual(15)
    expect(USUARIOS.filter((u) => u.tecnico).length).toBeGreaterThanOrEqual(4)
    expect(new Set(USUARIOS.map((u) => u.login)).size).toBe(USUARIOS.length)
  })

  it('tem ao menos 40 artigos com títulos únicos', () => {
    expect(ARTIGOS.length).toBeGreaterThanOrEqual(40)
    expect(new Set(ARTIGOS.map((a) => a.titulo)).size).toBe(ARTIGOS.length)
  })

  it('todo artigo aponta para uma categoria existente', () => {
    const chaves = new Set(CATEGORIAS.map((c) => c.chave))
    for (const a of ARTIGOS) expect(chaves).toContain(a.categoria)
  })

  it('tem ao menos 3 pares quase-duplicados, e cada par se referencia', () => {
    const pares = ARTIGOS.filter((a) => a.parDe !== undefined)
    expect(pares.length).toBeGreaterThanOrEqual(3)

    const porTitulo = new Map(ARTIGOS.map((a) => [a.titulo, a]))
    for (const a of pares) {
      const irmao = porTitulo.get(a.parDe!)
      expect(irmao, `par ausente para "${a.titulo}"`).toBeDefined()
      expect(irmao!.categoria).toBe(a.categoria)
    }
  })

  it('varia bastante o tamanho dos artigos', () => {
    const tamanhos = ARTIGOS.map((a) => a.corpo.length)
    expect(Math.min(...tamanhos)).toBeLessThan(700)
    expect(Math.max(...tamanhos)).toBeGreaterThan(2500)
  })

  it('o corpo é HTML', () => {
    for (const a of ARTIGOS) expect(a.corpo).toMatch(/<(p|ul|ol|h[23])>/)
  })
})
