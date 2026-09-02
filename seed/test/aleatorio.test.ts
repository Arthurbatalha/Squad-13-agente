import { describe, it, expect } from 'vitest'
import { criarAleatorio } from '../src/aleatorio'

describe('criarAleatorio', () => {
  it('produz a mesma sequência para a mesma semente', () => {
    const a = criarAleatorio(42)
    const b = criarAleatorio(42)
    const seqA = Array.from({ length: 20 }, () => a.inteiro(0, 1000))
    const seqB = Array.from({ length: 20 }, () => b.inteiro(0, 1000))
    expect(seqA).toEqual(seqB)
  })

  it('produz sequências diferentes para sementes diferentes', () => {
    const a = criarAleatorio(1)
    const b = criarAleatorio(2)
    const seqA = Array.from({ length: 20 }, () => a.inteiro(0, 1000))
    const seqB = Array.from({ length: 20 }, () => b.inteiro(0, 1000))
    expect(seqA).not.toEqual(seqB)
  })

  it('respeita os limites de inteiro, inclusive nas pontas', () => {
    const r = criarAleatorio(7)
    const vistos = new Set<number>()
    for (let i = 0; i < 500; i++) vistos.add(r.inteiro(1, 3))
    expect([...vistos].sort()).toEqual([1, 2, 3])
  })

  it('escolher devolve um item da lista', () => {
    const r = criarAleatorio(3)
    const itens = ['a', 'b', 'c'] as const
    for (let i = 0; i < 50; i++) expect(itens).toContain(r.escolher(itens))
  })

  it('pesado respeita a proporção declarada', () => {
    const r = criarAleatorio(11)
    const contagem = { raro: 0, comum: 0 }
    for (let i = 0; i < 2000; i++) {
      contagem[r.pesado([['raro', 1], ['comum', 9]] as [('raro' | 'comum'), number][])]++
    }
    // ~10% vs ~90%; folga larga para não virar teste frágil.
    expect(contagem.raro).toBeGreaterThan(120)
    expect(contagem.raro).toBeLessThan(300)
  })
})
