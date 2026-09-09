import type { Aleatorio } from './aleatorio'
import type { Calendario } from './datas'
import { USUARIOS } from './catalogo/usuarios'

export type StatusChamado = 'novo' | 'em_atendimento' | 'solucionado' | 'fechado'

export interface ItemTimeline {
  tipo: 'followup' | 'solucao'
  autor: string
  conteudo: string
  data: string
}

export interface ChamadoGerado {
  titulo: string
  descricao: string
  categoria: string
  status: StatusChamado
  prioridade: number
  solicitante: string
  tecnico: string | null
  criadoEm: string
  timeline: ItemTimeline[]
}

export interface OpcoesChamados {
  quantidade: number
  aleatorio: Aleatorio
  calendario: Calendario
}

const DIAS_DE_HISTORICO = 540 // ~18 meses

/**
 * Categorias com peso: "rede" domina de propósito, para que perguntas
 * analíticas do enunciado tenham resposta não-óbvia.
 */
const PESO_CATEGORIA: readonly (readonly [string, number])[] = [
  ['rede', 32],
  ['acesso', 22],
  ['erp', 16],
  ['impressao', 13],
  ['email', 11],
  ['equipamento', 6],
]

const PESO_STATUS: readonly (readonly [StatusChamado, number])[] = [
  ['fechado', 58],
  ['solucionado', 17],
  ['em_atendimento', 15],
  ['novo', 10],
]

/** Tipado como tuplas: sem isso o TS infere number[][] e pesado() não compila. */
const PESO_PRIORIDADE: readonly (readonly [number, number])[] = [
  [1, 6],
  [2, 18],
  [3, 46],
  [4, 22],
  [5, 8],
]

/**
 * Cada assunto tem várias variações de título e de descrição, sorteadas
 * independentemente. O objetivo é ter vários chamados sobre o mesmo problema,
 * escritos de formas diferentes — se a descrição fosse fixa por assunto, a
 * busca por chamados históricos parecidos (Sprint 3) degeneraria em
 * correspondência exata de string.
 */
interface TemaAssunto {
  titulos: readonly string[]
  descricoes: readonly string[]
}

const ASSUNTOS: Record<string, readonly TemaAssunto[]> = {
  rede: [
    {
      titulos: ['VPN não conecta fora do escritório', 'Conexão VPN caindo em home office', 'Não consigo manter a VPN ativa'],
      descricoes: [
        'Tento conectar de casa e a conexão cai após alguns segundos.',
        'A VPN cai sozinha depois de uns segundos, não dá pra trabalhar assim.',
        'Não consigo trabalhar de casa, a conexão com a empresa não permanece ativa.',
        'Desde a última atualização do notebook, a VPN desconecta a cada cinco minutos mais ou menos.',
      ],
    },
    {
      titulos: ['Internet lenta no terceiro andar', 'Rede muito lenta na sala 302', 'Conexão travando o dia todo no andar'],
      descricoes: [
        'Desde ontem as páginas demoram muito para abrir na sala 302.',
        'A internet está horrível aqui no terceiro andar, quase não dá pra abrir o e-mail.',
        'Reunião por vídeo trava direto, parece que a rede do andar está congestionada.',
        'Já é o segundo dia que a conexão fica lenta a partir do meio da tarde.',
      ],
    },
    {
      titulos: ['Sem acesso ao Wi-Fi de visitantes', 'Convidado não consegue entrar na rede de visitantes', 'Wi-Fi de visitantes pedindo senha errada'],
      descricoes: [
        'O convidado da reunião não consegue autenticar na rede.',
        'Tentamos conectar o notebook do cliente na rede de visitantes e não autentica.',
        'A senha do Wi-Fi de visitantes que está na parede não está funcionando mais.',
        'Preciso liberar acesso rápido para um fornecedor que está aqui agora.',
      ],
    },
    {
      titulos: ['Cabo de rede sem link', 'Estação nova sem conexão cabeada', 'Ponto de rede não funciona na mesa nova'],
      descricoes: [
        'A luz da tomada de rede não acende na estação nova.',
        'Troquei de mesa e o ponto de rede daqui não pega, testei com outro cabo.',
        'O computador não reconhece a rede cabeada, já reiniciei e continua sem link.',
        'Mudamos os móveis do setor e agora essa baia ficou sem conexão de rede.',
      ],
    },
    {
      titulos: ['Queda de conexão intermitente', 'Internet cai e volta sem motivo', 'Conexão instável durante o dia'],
      descricoes: [
        'A internet cai por uns segundos e volta, isso acontece várias vezes ao dia.',
        'De hora em hora a conexão pisca e perco o que estava fazendo no sistema.',
        'Não é sempre, mas de vez em quando a rede simplesmente some por um instante.',
        'Notei que a queda costuma acontecer perto do horário de almoço.',
      ],
    },
    {
      titulos: ['Impossível acessar sistema interno remotamente', 'Sistema interno não abre fora da rede da empresa', 'Acesso remoto ao servidor não funciona'],
      descricoes: [
        'De fora da empresa não consigo abrir o sistema interno, aqui dentro funciona normal.',
        'O link do sistema interno não carrega quando estou em home office.',
        'Preciso acessar o servidor de arquivos remotamente e a conexão não estabelece.',
        'Testei em duas redes diferentes de casa e o resultado foi o mesmo.',
      ],
    },
    {
      titulos: ['Roteador do setor reiniciando sozinho', 'Rede do setor cai e volta a cada hora', 'Equipamento de rede reiniciando sem aviso'],
      descricoes: [
        'O roteador do nosso setor está reiniciando sozinho, todo mundo perde a conexão junto.',
        'Umas duas vezes por dia a rede cai geral aqui e depois de um minuto volta.',
        'Parece que o equipamento de rede da sala está superaquecendo e desligando.',
        'Já reiniciamos o roteador manualmente, mas o problema volta no dia seguinte.',
      ],
    },
    {
      titulos: ['Sinal de Wi-Fi fraco em sala de reunião', 'Wi-Fi não pega direito na sala de reuniões', 'Sinal de rede ruim para videoconferência'],
      descricoes: [
        'Na sala de reuniões do quarto andar o sinal de Wi-Fi quase não chega.',
        'Durante a videoconferência a imagem trava porque o sinal é muito fraco ali.',
        'Perto da porta pega bem, mas no fundo da sala o sinal despenca.',
        'Precisamos de sinal melhor nessa sala porque é onde fazemos as chamadas com clientes.',
      ],
    },
  ],
  acesso: [
    {
      titulos: ['Usuário bloqueado após tentativas', 'Conta travada por senha errada', 'Login bloqueado no sistema'],
      descricoes: [
        'Errei a senha três vezes e agora não entro mais.',
        'Minha conta ficou bloqueada depois de algumas tentativas de login erradas.',
        'Não lembrava a senha nova e acabei travando o usuário.',
        'O sistema mostra mensagem de conta bloqueada por excesso de tentativas.',
      ],
    },
    {
      titulos: ['Sem permissão na pasta do setor', 'Acesso negado à pasta compartilhada', 'Não consigo abrir os arquivos do setor'],
      descricoes: [
        'Preciso acessar a pasta de contratos e recebo acesso negado.',
        'A pasta compartilhada do setor não abre, aparece erro de permissão.',
        'Meus colegas conseguem entrar na pasta, só o meu usuário está sem acesso.',
        'Fui trocado de setor recentemente e ainda não tenho permissão nos arquivos novos.',
      ],
    },
    {
      titulos: ['Criar acesso para novo colaborador', 'Liberar login para admissão', 'Novo funcionário precisa de acessos'],
      descricoes: [
        'Colaborador começa segunda e precisa de rede, e-mail e ERP.',
        'Temos uma admissão essa semana e preciso que os acessos estejam prontos no primeiro dia.',
        'Por favor, criar usuário e liberar os sistemas básicos para o novo contratado.',
        'O colaborador novo do setor comercial ainda não tem login em nenhum sistema.',
      ],
    },
    {
      titulos: ['Revogar acessos de desligado', 'Encerrar acessos de colaborador desligado', 'Bloquear usuário após desligamento'],
      descricoes: [
        'Encerrar todos os acessos do colaborador desligado hoje.',
        'O desligamento foi confirmado, por favor bloquear o usuário em todos os sistemas.',
        'Preciso que o acesso ao e-mail e ao ERP seja revogado ainda hoje.',
        'Colaborador saiu da empresa nesta semana e o usuário continua ativo.',
      ],
    },
    {
      titulos: ['Esqueci a senha e não recebo o e-mail de redefinição', 'Redefinição de senha não chega', 'Link de nova senha não é enviado'],
      descricoes: [
        'Cliquei em esqueci minha senha várias vezes e o e-mail nunca chega.',
        'Preciso redefinir a senha, mas o link de recuperação não cai na minha caixa.',
        'Já verifiquei o spam e nada do e-mail de redefinição de senha.',
        'O sistema diz que enviou o código, mas não recebi nada até agora.',
      ],
    },
    {
      titulos: ['Acesso ao sistema financeiro negado', 'Sem permissão no módulo financeiro', 'Não consigo entrar no financeiro'],
      descricoes: [
        'Meu usuário não tem permissão para o sistema financeiro, preciso para fechar o mês.',
        'Ao tentar abrir o módulo financeiro recebo mensagem de acesso restrito.',
        'Fui promovido recentemente e ainda não recebi o perfil de acesso financeiro.',
        'Preciso do acesso liberado com urgência para conferir os pagamentos do dia.',
      ],
    },
    {
      titulos: ['Conta expirada precisa reativação', 'Usuário expirado após licença', 'Login não funciona após retorno de férias'],
      descricoes: [
        'Voltei de licença e meu usuário aparece como expirado.',
        'Fiquei um tempo afastado e agora não consigo mais logar em nada.',
        'O sistema informa que minha conta expirou por inatividade.',
        'Preciso reativar o acesso porque volto ao trabalho amanhã.',
      ],
    },
    {
      titulos: ['Permissão de administrador local necessária', 'Preciso de acesso admin na máquina', 'Instalação de programa bloqueada por permissão'],
      descricoes: [
        'Não consigo instalar um programa porque meu usuário não é administrador da máquina.',
        'Preciso de permissão elevada temporária para configurar um software específico.',
        'O sistema pede senha de administrador toda vez que tento instalar algo.',
        'Sem acesso admin não consigo nem atualizar um driver simples aqui.',
      ],
    },
  ],
  erp: [
    {
      titulos: ['Erro ao emitir nota fiscal', 'Nota fiscal não é emitida', 'Falha na emissão de NF-e'],
      descricoes: [
        'O sistema retorna erro de validação ao finalizar a emissão.',
        'Toda vez que tento emitir a nota aparece uma mensagem de erro genérica.',
        'A nota fica pendente e nunca é enviada para a prefeitura.',
        'Já tentei emitir de três formas diferentes e o erro persiste.',
      ],
    },
    {
      titulos: ['Relatório mensal não carrega', 'Relatório fica processando para sempre', 'Tela do relatório trava'],
      descricoes: [
        'A tela fica processando e nunca conclui.',
        'O relatório do mês passado abriu normal, mas o deste mês trava na metade.',
        'Fico esperando mais de dez minutos e a página simplesmente não responde.',
        'Preciso desse relatório para a reunião de amanhã e ele não carrega de jeito nenhum.',
      ],
    },
    {
      titulos: ['Liberar módulo de estoque', 'Acesso ao módulo de estoque pendente', 'Preciso do módulo de inventário'],
      descricoes: [
        'Preciso do módulo de estoque liberado no meu perfil.',
        'Mudei de função e agora preciso mexer no controle de estoque do sistema.',
        'O módulo aparece cinza no meu menu, acho que não está habilitado.',
        'Sem o módulo de estoque não consigo lançar as entradas de hoje.',
      ],
    },
    {
      titulos: ['Lentidão no fechamento', 'Sistema lento durante o fechamento mensal', 'Fechamento demorando demais'],
      descricoes: [
        'Durante o fechamento o sistema fica muito lento.',
        'Todo fim de mês o ERP praticamente para de responder por causa do fechamento.',
        'Uma tela que antes levava segundos agora demora minutos para salvar.',
        'A lentidão piora bastante quando todo o time está fazendo o fechamento ao mesmo tempo.',
      ],
    },
    {
      titulos: ['Sistema trava ao salvar pedido', 'Pedido não salva no ERP', 'Erro ao concluir pedido de venda'],
      descricoes: [
        'Preencho todo o pedido e na hora de salvar a tela congela.',
        'O pedido some da tela e não sei se foi registrado ou não.',
        'Já aconteceu de duplicar o pedido porque tentei salvar de novo achando que tinha falhado.',
        'Isso está acontecendo só com pedidos que têm muitos itens.',
      ],
    },
    {
      titulos: ['Campo obrigatório não aparece no cadastro', 'Cadastro de cliente incompleto no sistema', 'Falta campo na tela de cadastro'],
      descricoes: [
        'O sistema pede um campo obrigatório que não aparece na tela para preencher.',
        'Não consigo finalizar o cadastro do cliente novo por causa de um campo que sumiu.',
        'Aconteceu depois da última atualização do sistema.',
        'Já tentei em dois navegadores diferentes e o campo continua invisível.',
      ],
    },
    {
      titulos: ['Integração com banco falhando', 'Conciliação bancária não sincroniza', 'Falha na integração financeira'],
      descricoes: [
        'Os lançamentos do banco pararam de sincronizar com o sistema há dois dias.',
        'A conciliação bancária está mostrando divergência que não existia antes.',
        'Preciso da integração funcionando para fechar o caixa de hoje.',
        'Reiniciei a integração manualmente e o erro voltou na sincronização seguinte.',
      ],
    },
    {
      titulos: ['Duplicidade de lançamento no financeiro', 'Lançamento duplicado no ERP', 'Valor lançado duas vezes por engano'],
      descricoes: [
        'Notei que o mesmo lançamento aparece duas vezes no extrato do sistema.',
        'O valor da fatura foi contabilizado em dobro sem eu ter feito nada diferente.',
        'Preciso que corrijam antes do fechamento porque está distorcendo o saldo.',
        'Já aconteceu isso duas vezes este mês com fornecedores diferentes.',
      ],
    },
  ],
  impressao: [
    {
      titulos: ['Impressora do andar atolando papel', 'Papel enroscando na impressora', 'Impressora trava a cada poucas páginas'],
      descricoes: [
        'A cada duas páginas o papel enrosca.',
        'Já limpamos o compartimento de papel e o problema continua acontecendo.',
        'Toda impressão maior que uma página trava no meio do caminho.',
        'O papel está saindo amassado quando consigo tirar do meio do equipamento.',
      ],
    },
    {
      titulos: ['Toner acabou', 'Impressão saindo fraca por falta de toner', 'Painel indica toner baixo'],
      descricoes: [
        'A impressão está saindo falhada e o painel indica toner baixo.',
        'As folhas estão saindo bem claras, acho que o toner está no fim.',
        'Já trocamos o toner semana passada e já está avisando de novo.',
        'Preciso imprimir um contrato urgente e a qualidade está ruim demais para assinar.',
      ],
    },
    {
      titulos: ['Digitalizar para e-mail não funciona', 'Scanner não envia arquivo por e-mail', 'Função de digitalização com erro'],
      descricoes: [
        'O scanner não envia o arquivo para o meu e-mail.',
        'Escaneio o documento normalmente, mas o e-mail nunca chega na minha caixa.',
        'Aparece uma mensagem de falha de conexão quando tento digitalizar para e-mail.',
        'Consigo digitalizar para pasta na rede, só o envio por e-mail que não funciona.',
      ],
    },
    {
      titulos: ['Cota de impressão esgotada', 'Limite de impressão excedido', 'Não consigo mais imprimir pela cota'],
      descricoes: [
        'Recebo aviso de cota excedida ao imprimir.',
        'Ainda é início do mês e minha cota de impressão já acabou.',
        'Preciso imprimir um material importante e o sistema está bloqueando pela cota.',
        'Poderiam verificar se a cota do meu usuário está configurada corretamente?',
      ],
    },
    {
      titulos: ['Impressão saindo com listras', 'Páginas impressas com falhas verticais', 'Qualidade de impressão ruim'],
      descricoes: [
        'As folhas estão saindo com listras verticais em toda a página.',
        'Parece sujeira no rolo, a impressão sai com faixas escuras.',
        'Já tentei imprimir de computadores diferentes e o defeito é o mesmo.',
        'Isso está atrapalhando a impressão dos relatórios para os clientes.',
      ],
    },
    {
      titulos: ['Impressora não aparece na rede', 'Computador não encontra a impressora', 'Impressora offline para o setor'],
      descricoes: [
        'A impressora sumiu da lista de impressoras disponíveis no meu computador.',
        'Meus colegas conseguem imprimir, só a minha máquina não encontra o equipamento.',
        'O status aparece como offline mesmo com a impressora ligada.',
        'Reinstalei o driver e o problema de qualquer forma continua.',
      ],
    },
    {
      titulos: ['Fila de impressão travada', 'Documentos presos na fila de impressão', 'Impressão não sai da fila'],
      descricoes: [
        'Mandei imprimir três documentos e nenhum saiu, ficaram parados na fila.',
        'A fila de impressão está com um arquivo antigo travando os próximos.',
        'Já tentei cancelar a impressão e ela continua aparecendo na lista.',
        'Isso está impedindo todo o setor de imprimir desde cedo.',
      ],
    },
    {
      titulos: ['Qualidade de digitalização ruim', 'Documento digitalizado sai borrado', 'Scanner com imagem de baixa qualidade'],
      descricoes: [
        'Os documentos digitalizados estão saindo borrados, difícil de ler o texto.',
        'Preciso enviar um documento assinado e a digitalização não está com qualidade suficiente.',
        'Antes a digitalização saía nítida, começou a piorar essa semana.',
        'Já limpei o vidro do scanner e a qualidade não melhorou.',
      ],
    },
  ],
  email: [
    {
      titulos: ['Caixa de e-mail cheia', 'Não recebo mais e-mails', 'Caixa de entrada lotada'],
      descricoes: [
        'Não consigo mais receber mensagens.',
        'Estou recebendo aviso de que minha caixa está no limite de armazenamento.',
        'Um cliente disse que o e-mail dele voltou porque minha caixa está cheia.',
        'Preciso liberar espaço ou aumentar a cota, o volume de anexos é grande no meu setor.',
      ],
    },
    {
      titulos: ['Configurar e-mail no celular', 'E-mail corporativo não sincroniza no telefone', 'Preciso do e-mail no aparelho novo'],
      descricoes: [
        'Preciso do e-mail corporativo no aparelho novo.',
        'Troquei de celular e não estou conseguindo configurar minha conta de e-mail nele.',
        'O aplicativo pede usuário e senha e depois dá erro de conexão.',
        'Funcionava no celular antigo, só não estou conseguindo replicar no novo.',
      ],
    },
    {
      titulos: ['Muito spam na caixa de entrada', 'Volume alto de e-mails indesejados', 'Filtro de spam parece não estar funcionando'],
      descricoes: [
        'Aumentou bastante o volume de mensagens indesejadas.',
        'Estou recebendo dezenas de e-mails de propaganda todos os dias.',
        'Alguns desses e-mails parecem suspeitos, prefiro que sejam bloqueados antes de chegar.',
        'O filtro de spam parou de funcionar direito depois da última atualização.',
      ],
    },
    {
      titulos: ['Incluir na lista de distribuição', 'Adicionar usuário a grupo de e-mail', 'Não recebo os comunicados do setor'],
      descricoes: [
        'Preciso receber os comunicados do setor.',
        'Entrei recentemente na equipe e ainda não fui incluído na lista de avisos internos.',
        'Meus colegas recebem os comunicados e eu não, poderiam verificar minha inclusão?',
        'Precisamos adicionar um novo membro do time na lista de distribuição do projeto.',
      ],
    },
    {
      titulos: ['Anexos grandes não enviam', 'E-mail com anexo não sai da caixa de saída', 'Arquivo grande trava o envio'],
      descricoes: [
        'Tento enviar um arquivo grande e o e-mail fica preso na caixa de saída.',
        'Recebo mensagem de erro dizendo que o anexo excede o tamanho permitido.',
        'Preciso enviar um material grande para um cliente ainda hoje.',
        'Já tentei compactar o arquivo e mesmo assim não consegui enviar.',
      ],
    },
    {
      titulos: ['E-mails não chegam para destinatário externo', 'Mensagem não é entregue a cliente', 'E-mail cai em spam do destinatário'],
      descricoes: [
        'Mandei um e-mail para um fornecedor e ele diz que nunca recebeu.',
        'Não recebi nenhuma notificação de erro, mas o e-mail simplesmente não chegou.',
        'O destinatário verificou o spam dele e também não está lá.',
        'Isso está acontecendo com mais de um cliente nas últimas semanas.',
      ],
    },
    {
      titulos: ['Assinatura de e-mail não atualiza', 'Assinatura desatualizada no e-mail corporativo', 'Preciso trocar a assinatura de e-mail'],
      descricoes: [
        'Mudei de cargo e minha assinatura de e-mail ainda mostra o cargo antigo.',
        'A assinatura padrão não está aparecendo automaticamente nos e-mails novos.',
        'Já editei a assinatura nas configurações e ela não salva.',
        'Preciso atualizar o telefone e o cargo na assinatura de toda a equipe.',
      ],
    },
    {
      titulos: ['Calendário compartilhado não sincroniza', 'Agenda da equipe não atualiza', 'Reuniões não aparecem no calendário compartilhado'],
      descricoes: [
        'Marquei uma reunião e ela não aparece no calendário compartilhado da equipe.',
        'O calendário do setor está desatualizado há alguns dias.',
        'Meus colegas veem a reunião, só no meu calendário que ela não aparece.',
        'Já tentei remover e adicionar o calendário compartilhado de novo sem sucesso.',
      ],
    },
  ],
  equipamento: [
    {
      titulos: ['Solicitar notebook para novo colaborador', 'Equipamento necessário para admissão', 'Notebook para novo contratado'],
      descricoes: [
        'Equipamento para o colaborador que inicia no mês que vem.',
        'Precisamos de um notebook configurado até a data de início do novo colaborador.',
        'A área de vendas está com uma nova contratação e falta o equipamento dela.',
        'Poderiam confirmar se o notebook para a próxima admissão já está separado?',
      ],
    },
    {
      titulos: ['Monitor com falha de imagem', 'Tela do monitor piscando', 'Monitor com imagem cortada'],
      descricoes: [
        'A tela pisca e às vezes fica preta.',
        'Aparecem linhas coloridas na tela de vez em quando.',
        'A imagem do monitor está cortada, falta um pedaço na lateral direita.',
        'Já testei o monitor em outro computador e o problema persiste.',
      ],
    },
    {
      titulos: ['Bateria do notebook não segura carga', 'Notebook descarrega rápido demais', 'Autonomia da bateria muito baixa'],
      descricoes: [
        'Dura menos de vinte minutos fora da tomada.',
        'A bateria despenca de cem por cento para vinte em poucos minutos.',
        'Preciso estar sempre na tomada, senão o notebook desliga sozinho.',
        'Isso começou a acontecer depois de uma atualização recente do sistema.',
      ],
    },
    {
      titulos: ['Devolução de equipamento', 'Recolher notebook de colaborador desligado', 'Equipamento precisa ser devolvido ao estoque'],
      descricoes: [
        'Preciso devolver o notebook do colaborador desligado.',
        'O equipamento está pronto para devolução, só preciso saber onde entregar.',
        'Colaborador foi desligado e o notebook dele continua na mesa vazia.',
        'Precisamos recolher o equipamento antes do fechamento do inventário deste mês.',
      ],
    },
    {
      titulos: ['Teclado com teclas travando', 'Teclas do teclado não respondem', 'Teclado do notebook com defeito'],
      descricoes: [
        'Algumas teclas do teclado não respondem, principalmente as vogais.',
        'Preciso apertar várias vezes para a letra aparecer na tela.',
        'Já limpei o teclado e o problema com algumas teclas continua.',
        'Está difícil digitar relatórios assim, algumas teclas travam de vez em quando.',
      ],
    },
    {
      titulos: ['Notebook não liga', 'Equipamento não inicializa', 'Notebook trava na tela de logo'],
      descricoes: [
        'Apertei o botão e o notebook não dá sinal de vida.',
        'A tela fica só no logo da marca e não passa disso.',
        'Já tentei carregar durante um tempo e o resultado é o mesmo.',
        'Ontem funcionava normal, hoje de manhã simplesmente não ligou mais.',
      ],
    },
    {
      titulos: ['Mouse sem fio parou de responder', 'Mouse sem fio travando o cursor', 'Periférico sem fio não conecta'],
      descricoes: [
        'O cursor do mouse trava e para de se mover do nada.',
        'Já troquei a pilha do mouse e o problema de conexão continua.',
        'O receptor USB parece não reconhecer mais o mouse sem fio.',
        'Funciona por alguns minutos e depois perde a conexão de novo.',
      ],
    },
    {
      titulos: ['Fone de ouvido headset com chiado', 'Headset com ruído nas chamadas', 'Áudio do fone com interferência'],
      descricoes: [
        'O headset está com um chiado constante durante as chamadas.',
        'As pessoas reclamam de ruído quando eu falo nas reuniões por vídeo.',
        'Já testei em outro computador e o chiado no fone continua.',
        'O microfone do headset parece estar captando um ruído de fundo estranho.',
      ],
    },
  ],
}

const RESPOSTAS_TECNICO: readonly string[] = [
  'Chamado recebido, vou verificar e retorno em seguida.',
  'Consegui reproduzir o problema aqui. Estou trabalhando na correção.',
  'Preciso de mais um dado: você consegue informar o horário exato em que ocorreu?',
  'Acionei a equipe responsável e estou acompanhando.',
]

const SOLUCOES: Record<string, readonly string[]> = {
  rede: [
    'Porta UDP 500 bloqueada na rede de origem. Orientado a usar outra rede; conexão normalizada.',
    'Switch do andar reiniciado e porta reconfigurada. Conectividade restabelecida.',
  ],
  acesso: [
    'Conta desbloqueada e senha provisória enviada. Usuário confirmou o acesso.',
    'Permissão concedida no grupo do setor. Usuário validou o acesso à pasta.',
  ],
  erp: [
    'Cadastro fiscal do produto estava incompleto. Corrigido, emissão concluída.',
    'Cache do relatório limpo e job reprocessado. Relatório voltou a carregar.',
  ],
  impressao: [
    'Rolete de tração substituído. Testes de impressão sem atolamento.',
    'Toner substituído e contador zerado. Impressão normalizada.',
  ],
  email: [
    'Caixa expandida e itens antigos arquivados. Recebimento normalizado.',
    'Perfil recriado no aplicativo. E-mails sincronizando corretamente.',
  ],
  equipamento: [
    'Equipamento substituído e termo de responsabilidade assinado.',
    'Bateria trocada em garantia. Autonomia dentro do esperado.',
  ],
}

export function gerarChamados({ quantidade, aleatorio, calendario }: OpcoesChamados): ChamadoGerado[] {
  const solicitantes = USUARIOS.map((u) => u.login)
  const tecnicos = USUARIOS.filter((u) => u.tecnico).map((u) => u.login)
  const chamados: ChamadoGerado[] = []

  for (let i = 0; i < quantidade; i++) {
    const categoria = aleatorio.pesado(PESO_CATEGORIA)
    const status = aleatorio.pesado(PESO_STATUS)
    const tema = aleatorio.escolher(ASSUNTOS[categoria]!)
    const titulo = aleatorio.escolher(tema.titulos)
    const descricao = aleatorio.escolher(tema.descricoes)

    const diasAtras = sortearDiaComSazonalidade(aleatorio)
    const abertura = calendario.diasAtras(diasAtras)
    const criadoEm = calendario.formatar(abertura)

    const tecnico = status === 'novo' ? null : aleatorio.escolher(tecnicos)
    const timeline: ItemTimeline[] = []

    if (tecnico !== null) {
      const quantosFollowups = aleatorio.inteiro(1, 3)
      for (let f = 0; f < quantosFollowups; f++) {
        timeline.push({
          tipo: 'followup',
          autor: tecnico,
          conteudo: aleatorio.escolher(RESPOSTAS_TECNICO),
          data: calendario.formatar(
            new Date(abertura.getTime() + (f + 1) * aleatorio.inteiro(2, 20) * 3_600_000),
          ),
        })
      }
    }

    if (status === 'solucionado' || status === 'fechado') {
      timeline.push({
        tipo: 'solucao',
        autor: tecnico!,
        conteudo: aleatorio.escolher(SOLUCOES[categoria]!),
        data: calendario.formatar(
          new Date(abertura.getTime() + aleatorio.inteiro(24, 200) * 3_600_000),
        ),
      })
    }

    chamados.push({
      titulo,
      descricao: `<p>${descricao}</p>`,
      categoria,
      status,
      prioridade: aleatorio.pesado(PESO_PRIORIDADE),
      solicitante: aleatorio.escolher(solicitantes),
      tecnico,
      criadoEm,
      timeline,
    })
  }

  return chamados
}

/**
 * Sorteia "há quantos dias" o chamado foi aberto, com dois picos sazonais.
 * Uma distribuição uniforme tornaria toda pergunta temporal do enunciado trivial.
 */
function sortearDiaComSazonalidade(aleatorio: Aleatorio): number {
  const faixa = aleatorio.pesado([
    ['pico_recente', 11],
    ['pico_antigo', 9],
    ['normal', 80],
  ] as const)

  if (faixa === 'pico_recente') return aleatorio.inteiro(20, 50)
  if (faixa === 'pico_antigo') return aleatorio.inteiro(300, 330)
  return aleatorio.inteiro(1, DIAS_DE_HISTORICO)
}
