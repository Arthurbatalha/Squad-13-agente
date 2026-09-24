import { describe, it, expect } from 'vitest'
import { criarCalendario } from '../src/datas'

describe('criarCalendario', () => {
  const hoje = new Date('2026-08-26T12:00:00Z')

  it('diasAtras recua o número exato de dias', () => {
    const cal = criarCalendario(hoje)
    const d = cal.diasAtras(10)
    const diff = (hoje.getTime() - d.getTime()) / 86_400_000
    expect(diff).toBeCloseTo(10, 5)
  })

  it('diasAtras(0) devolve a âncora', () => {
    const cal = criarCalendario(hoje)
    expect(cal.diasAtras(0).getTime()).toBe(hoje.getTime())
  })

  it('formata no formato que o GLPI aceita', () => {
    const cal = criarCalendario(hoje)
    expect(cal.formatar(new Date('2026-01-05T03:07:09Z'))).toBe('2026-01-05 03:07:09')
  })

  it('a âncora é injetada, nunca lida do relógio', () => {
    const a = criarCalendario(hoje)
    const b = criarCalendario(hoje)
    expect(a.formatar(a.diasAtras(500))).toBe(b.formatar(b.diasAtras(500)))
  })
})
