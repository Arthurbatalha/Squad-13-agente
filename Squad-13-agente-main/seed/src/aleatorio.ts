export interface Aleatorio {
  /** Inteiro entre min e max, ambos inclusive. */
  inteiro(min: number, max: number): number
  escolher<T>(itens: readonly T[]): T
  /** Escolhe entre pares [valor, peso], proporcionalmente ao peso. */
  pesado<T>(itens: readonly (readonly [T, number])[]): T
  /** Decimal em [0, 1). */
  decimal(): number
}

/**
 * mulberry32 — PRNG pequeno e determinístico, sem dependência externa.
 * Math.random() é proibido no gerador: quebraria a reprodutibilidade do corpus.
 */
export function criarAleatorio(semente: number): Aleatorio {
  let estado = semente >>> 0

  const decimal = (): number => {
    estado = (estado + 0x6d2b79f5) >>> 0
    let t = estado
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296
  }

  const inteiro = (min: number, max: number): number =>
    min + Math.floor(decimal() * (max - min + 1))

  function escolher<T>(itens: readonly T[]): T {
    if (itens.length === 0) throw new Error('escolher: lista vazia')
    return itens[inteiro(0, itens.length - 1)]!
  }

  function pesado<T>(itens: readonly (readonly [T, number])[]): T {
    const total = itens.reduce((s, [, peso]) => s + peso, 0)
    if (total <= 0) throw new Error('pesado: soma dos pesos precisa ser positiva')
    let alvo = decimal() * total
    for (const [valor, peso] of itens) {
      alvo -= peso
      if (alvo < 0) return valor
    }
    return itens[itens.length - 1]![0]
  }

  return { inteiro, escolher, pesado, decimal }
}
