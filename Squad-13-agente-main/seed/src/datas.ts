export interface Calendario {
  /** Recua n dias a partir da âncora. */
  diasAtras(n: number): Date
  /** Formata como 'YYYY-MM-DD HH:MM:SS', que é o formato aceito pelo GLPI. */
  formatar(d: Date): string
}

/**
 * A âncora é sempre injetada — o gerador nunca lê o relógio por conta própria.
 * As datas do corpus são relativas ao momento da regeneração para que perguntas
 * temporais do enunciado continuem fazendo sentido em semestres futuros.
 */
export function criarCalendario(hoje: Date): Calendario {
  const dois = (n: number): string => String(n).padStart(2, '0')

  return {
    diasAtras: (n) => new Date(hoje.getTime() - n * 86_400_000),
    formatar: (d) =>
      `${d.getUTCFullYear()}-${dois(d.getUTCMonth() + 1)}-${dois(d.getUTCDate())} ` +
      `${dois(d.getUTCHours())}:${dois(d.getUTCMinutes())}:${dois(d.getUTCSeconds())}`,
  }
}
