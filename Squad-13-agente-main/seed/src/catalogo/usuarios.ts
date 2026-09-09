export interface Usuario {
  login: string
  nome: string
  sobrenome: string
  tecnico: boolean
}

export const USUARIOS: readonly Usuario[] = [
  { login: 'ana.ribeiro', nome: 'Ana', sobrenome: 'Ribeiro', tecnico: true },
  { login: 'bruno.tavares', nome: 'Bruno', sobrenome: 'Tavares', tecnico: true },
  { login: 'carla.menezes', nome: 'Carla', sobrenome: 'Menezes', tecnico: true },
  { login: 'diego.fontes', nome: 'Diego', sobrenome: 'Fontes', tecnico: true },
  { login: 'elisa.moraes', nome: 'Elisa', sobrenome: 'Moraes', tecnico: true },
  { login: 'fabio.andrade', nome: 'Fábio', sobrenome: 'Andrade', tecnico: false },
  { login: 'gisele.pires', nome: 'Gisele', sobrenome: 'Pires', tecnico: false },
  { login: 'heitor.campos', nome: 'Heitor', sobrenome: 'Campos', tecnico: false },
  { login: 'irene.duarte', nome: 'Irene', sobrenome: 'Duarte', tecnico: false },
  { login: 'joana.vasques', nome: 'Joana', sobrenome: 'Vasques', tecnico: false },
  { login: 'kleber.rocha', nome: 'Kleber', sobrenome: 'Rocha', tecnico: false },
  { login: 'lucia.barros', nome: 'Lúcia', sobrenome: 'Barros', tecnico: false },
  { login: 'marcos.leal', nome: 'Marcos', sobrenome: 'Leal', tecnico: false },
  { login: 'nadia.correia', nome: 'Nádia', sobrenome: 'Correia', tecnico: false },
  { login: 'otavio.simoes', nome: 'Otávio', sobrenome: 'Simões', tecnico: false },
  { login: 'paula.nogueira', nome: 'Paula', sobrenome: 'Nogueira', tecnico: false },
]
