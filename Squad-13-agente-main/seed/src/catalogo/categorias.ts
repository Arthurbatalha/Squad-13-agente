export interface Categoria {
  chave: string
  nome: string
}

export const CATEGORIAS: readonly Categoria[] = [
  { chave: 'rede', nome: 'Rede e Conectividade' },
  { chave: 'acesso', nome: 'Acessos e Senhas' },
  { chave: 'impressao', nome: 'Impressão' },
  { chave: 'email', nome: 'E-mail e Colaboração' },
  { chave: 'erp', nome: 'Sistema ERP' },
  { chave: 'equipamento', nome: 'Equipamentos' },
]
