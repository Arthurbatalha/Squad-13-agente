export interface Artigo {
  titulo: string
  categoria: string
  corpo: string
  /** Título do artigo quase-duplicado, quando existe um. */
  parDe?: string
}

export const ARTIGOS: readonly Artigo[] = [
  // --- Par quase-duplicado 1: VPN por sistema operacional ---
  {
    titulo: 'Configurar a VPN corporativa no Windows',
    categoria: 'rede',
    parDe: 'Configurar a VPN corporativa no macOS',
    corpo: `<p>Este procedimento vale para estações Windows 10 e 11 já ingressadas no domínio.</p>
<h3>Antes de começar</h3>
<ul><li>Você precisa do seu usuário de rede e do token de segundo fator já cadastrado.</li>
<li>A estação precisa estar fora da rede interna — dentro do escritório a VPN não conecta.</li></ul>
<h3>Passo a passo</h3>
<ol><li>Abra <strong>Configurações → Rede e Internet → VPN</strong>.</li>
<li>Clique em <strong>Adicionar VPN</strong>.</li>
<li>Em provedor, escolha <em>Windows (interno)</em>.</li>
<li>No endereço do servidor, informe <code>vpn.exemplo.local</code>.</li>
<li>Tipo de VPN: <em>IKEv2</em>. Tipo de informações de entrada: <em>Usuário e senha</em>.</li>
<li>Salve e clique em <strong>Conectar</strong>. Aprove a notificação no aplicativo de segundo fator.</li></ol>
<h3>Se não conectar</h3>
<p>O erro mais comum é o 809, que indica bloqueio de porta na rede de origem. Redes de hotel e
alguns provedores móveis bloqueiam a porta UDP 500. Teste usando o roteamento do celular.
Persistindo, abra chamado na categoria Rede e Conectividade informando o código do erro.</p>`,
  },
  {
    titulo: 'Configurar a VPN corporativa no macOS',
    categoria: 'rede',
    parDe: 'Configurar a VPN corporativa no Windows',
    corpo: `<p>Procedimento para macOS 13 (Ventura) ou superior.</p>
<h3>Antes de começar</h3>
<ul><li>Tenha em mãos seu usuário de rede e o segundo fator ativo.</li>
<li>Assim como no Windows, a conexão só funciona fora da rede interna.</li></ul>
<h3>Passo a passo</h3>
<ol><li>Abra <strong>Ajustes do Sistema → Rede</strong>.</li>
<li>Clique no menu <strong>...</strong> e escolha <strong>Adicionar Configuração de VPN → IKEv2</strong>.</li>
<li>Em endereço do servidor e ID remoto, informe <code>vpn.exemplo.local</code>.</li>
<li>Em autenticação, escolha <em>Nome de usuário</em> e preencha suas credenciais de rede.</li>
<li>Clique em <strong>Criar</strong> e depois em <strong>Conectar</strong>.</li></ol>
<h3>Se não conectar</h3>
<p>No macOS o sintoma típico é a conexão cair sozinha após alguns segundos, normalmente por
perfil de configuração antigo. Remova perfis de VPN anteriores em
<strong>Ajustes do Sistema → Privacidade e Segurança → Perfis</strong> e refaça o procedimento.</p>`,
  },
  // --- Par quase-duplicado 2: reset de senha por público ---
  {
    titulo: 'Redefinir a senha de rede pelo autoatendimento',
    categoria: 'acesso',
    parDe: 'Redefinir a senha de rede com o suporte',
    corpo: `<p>Use este caminho quando você <strong>ainda consegue acessar</strong> seu e-mail
ou seu segundo fator.</p>
<ol><li>Acesse <code>https://senha.exemplo.local</code>.</li>
<li>Informe seu usuário de rede e confirme o código enviado ao segundo fator.</li>
<li>Defina a nova senha respeitando a política: mínimo de 12 caracteres, com letras
maiúsculas, minúsculas e números, e diferente das últimas cinco senhas usadas.</li></ol>
<p>A nova senha vale imediatamente para e-mail e ERP, mas a estação Windows só reconhece
após um bloqueio e desbloqueio de tela conectado à rede.</p>`,
  },
  {
    titulo: 'Redefinir a senha de rede com o suporte',
    categoria: 'acesso',
    parDe: 'Redefinir a senha de rede pelo autoatendimento',
    corpo: `<p>Use este caminho quando você <strong>perdeu o acesso</strong> ao e-mail e ao
segundo fator, e por isso não consegue usar o autoatendimento.</p>
<ol><li>Abra chamado na categoria Acessos e Senhas, ou ligue para o ramal do suporte.</li>
<li>O atendente confirma sua identidade com dados cadastrais — este passo não é
dispensável, mesmo que você conheça o atendente.</li>
<li>Você recebe uma senha provisória, que expira em 24 horas e precisa ser trocada
no primeiro acesso.</li></ol>
<p>O suporte nunca solicita sua senha atual. Se alguém pedir, encerre e comunique a equipe
de segurança.</p>`,
  },
  // --- Par quase-duplicado 3: impressora local x em rede ---
  {
    titulo: 'Instalar impressora de rede no Windows',
    categoria: 'impressao',
    parDe: 'Instalar impressora USB local no Windows',
    corpo: `<p>As impressoras dos andares são publicadas no servidor de impressão e não exigem
download de driver.</p>
<ol><li>Pressione <kbd>Win + R</kbd> e digite <code>\\\\impressao.exemplo.local</code>.</li>
<li>Localize a fila do seu andar, no padrão <code>IMP-ANDAR-COR</code>.</li>
<li>Clique com o botão direito e escolha <strong>Conectar</strong>.</li></ol>
<p>Se a fila não aparecer, você provavelmente não está na VPN ou na rede interna.
Filas duplicadas com sufixo numérico indicam instalação antiga: remova as antigas.</p>`,
  },
  {
    titulo: 'Instalar impressora USB local no Windows',
    categoria: 'impressao',
    parDe: 'Instalar impressora de rede no Windows',
    corpo: `<p>Impressoras conectadas diretamente por cabo USB à estação, comuns em recepções
e almoxarifados.</p>
<ol><li>Conecte o cabo e aguarde o reconhecimento automático.</li>
<li>Se o Windows não achar o driver, baixe-o do site do fabricante — não use drivers
genéricos, que causam impressão de páginas em branco.</li>
<li>Em <strong>Configurações → Bluetooth e dispositivos → Impressoras</strong>, confirme que
o dispositivo aparece como pronto.</li></ol>
<p>Impressora USB não é compartilhada com o andar. Para atender mais de uma pessoa, solicite
a publicação no servidor de impressão pela categoria Impressão.</p>`,
  },

  // ============================= REDE =============================
  {
    titulo: 'Conectar-se ao Wi-Fi de visitantes',
    categoria: 'rede',
    corpo: `<p>A rede <strong>VISITANTES-EXEMPLO</strong> atende convidados e prestadores externos,
sem acesso a impressoras ou pastas internas.</p>
<ul><li>A senha do dia fica com a recepção e é trocada toda manhã.</li>
<li>O acesso expira automaticamente às 20h, mesmo que o dispositivo continue conectado.</li></ul>
<p>Se a página de aceite de termos não abrir sozinha ao conectar, acesse
<code>http://conectar.exemplo.local</code> pelo navegador. Sem aceitar os termos, a navegação
fica bloqueada mesmo com o Wi-Fi mostrando conectado.</p>`,
  },
  {
    titulo: 'Diagnosticar lentidão de rede na estação',
    categoria: 'rede',
    corpo: `<p>Lentidão pode ter origem na estação, no cabeamento do andar ou no link de internet
do prédio. Este roteiro ajuda a isolar a causa antes de abrir chamado.</p>
<h3>Passo 1 — confirme se é só você</h3>
<p>Pergunte a um colega próximo se ele percebe o mesmo problema. Se apenas sua estação estiver
lenta, o foco é local; se o andar inteiro reclamar, é provável que seja o link ou o switch.</p>
<h3>Passo 2 — teste cabo x Wi-Fi</h3>
<p>Sempre que possível, conecte um cabo de rede à estação. Se a lentidão desaparecer, o problema
é do Wi-Fi daquele ponto — muito comum perto de elevadores e salas de reunião com muitas
pessoas conectadas ao mesmo tempo.</p>
<h3>Passo 3 — verifique aplicativos em segundo plano</h3>
<p>Sincronizações grandes de arquivos, backups automáticos e atualizações do sistema operacional
consomem banda sem aviso. Abra o Gerenciador de Tarefas (Windows) ou o Monitor de Atividade
(macOS) e observe a coluna de rede antes de concluir que o problema é da infraestrutura.</p>
<h3>Quando abrir chamado</h3>
<p>Registre o chamado na categoria Rede e Conectividade informando: horário em que percebeu a
lentidão, se testou com cabo, e se colegas próximos relataram o mesmo. Esses três dados evitam
uma rodada extra de perguntas do técnico e agilizam o diagnóstico.</p>`,
  },
  {
    titulo: 'Cabo de rede não conecta ou a conexão cai sozinha',
    categoria: 'rede',
    corpo: `<p>Antes de trocar o cabo, confirme os pontos abaixo — a maioria dos casos não exige
troca de hardware.</p>
<ol><li>Verifique se o LED da placa de rede acende ao conectar o cabo. Sem luz nenhuma, o cabo
ou a porta do switch podem estar com defeito.</li>
<li>Reconecte o cabo em ambas as pontas — conectores RJ-45 folgados são a causa mais comum de
quedas intermitentes.</li>
<li>Teste a mesma estação em outro ponto de rede do andar, se houver um livre por perto.</li></ol>
<p>Se a conexão cai em horários específicos (por exemplo, sempre no início da tarde), registre
esses horários no chamado: pode indicar sobrecarga do switch do andar, e não um problema no
seu cabo.</p>`,
  },
  {
    titulo: 'Sites não abrem, mas outras estações funcionam normalmente',
    categoria: 'rede',
    corpo: `<p>Esse sintoma quase sempre indica falha de DNS na sua estação, não uma queda geral
de internet.</p>
<h3>Teste rápido</h3>
<p>Tente abrir um site pelo endereço IP direto (peça um IP de teste ao suporte) ou execute
<code>ping portal.exemplo.local</code> no terminal. Se o ping falhar mas
<code>ping 10.20.0.1</code> (o IP do roteador interno) funcionar, o problema é de resolução
de nomes, não de conectividade.</p>
<h3>Correção</h3>
<ul><li>No Windows, abra o Prompt de Comando como administrador e rode
<code>ipconfig /flushdns</code>.</li>
<li>No macOS, rode <code>sudo dscacheutil -flushcache</code> no Terminal.</li>
<li>Reinicie o navegador após limpar o cache de DNS.</li></ul>
<p>Se o problema persistir em todos os sites, abra chamado informando o resultado dos dois
comandos de ping acima — isso já direciona o técnico para o servidor de DNS correto.</p>`,
  },
  {
    titulo: 'Wi-Fi corporativo pede senha repetidamente',
    categoria: 'rede',
    corpo: `<p>Quando a rede <strong>CORP-EXEMPLO</strong> pede a senha de novo mesmo após você
digitar corretamente, o certificado de autenticação da estação provavelmente expirou ou está
corrompido.</p>
<ol><li>Vá até as redes salvas do seu dispositivo e remova (esqueça) a rede CORP-EXEMPLO.</li>
<li>Reconecte do zero, informando usuário e senha de rede quando solicitado.</li>
<li>Aceite o novo certificado de segurança apresentado pelo controlador de Wi-Fi.</li></ol>
<p>Isso é diferente de digitar a senha errada: se o campo mostrar erro imediato de senha
inválida, confirme antes se sua senha de rede não expirou.</p>`,
  },

  // ============================= ACESSO =============================
  {
    titulo: 'Conta bloqueada por excesso de tentativas de senha',
    categoria: 'acesso',
    corpo: `<p>Após 5 tentativas incorretas, a conta de rede é bloqueada automaticamente por
15 minutos como proteção contra ataques.</p>
<p>Se o bloqueio persistir depois desse prazo, abra chamado na categoria Acessos e Senhas.
Não é necessário criar chamado antes disso — na grande maioria dos casos o desbloqueio
é automático.</p>`,
  },
  {
    titulo: 'Solicitar acesso a pasta compartilhada de setor',
    categoria: 'acesso',
    corpo: `<p>O acesso a pastas de rede segue o perfil de grupo do colaborador, e cada setor tem
sua própria pasta em <code>\\\\arquivos.exemplo.local\\setores</code>.</p>
<h3>Como solicitar</h3>
<ol><li>Abra chamado na categoria Acessos e Senhas informando o nome exato da pasta e o
motivo do acesso.</li>
<li>O chamado precisa ser aprovado pelo responsável do setor dono da pasta — não pelo seu
próprio gestor, caso sejam áreas diferentes.</li>
<li>Após a aprovação, o acesso é liberado em até um dia útil e aparece automaticamente no
próximo login.</li></ol>
<h3>Situações que não seguem este fluxo</h3>
<p>Pastas de projetos temporários criadas por engenheiros de forma avulsa não são
gerenciadas por este processo; o próprio dono do projeto concede o acesso diretamente.</p>`,
  },
  {
    titulo: 'Liberar acessos para novo colaborador',
    categoria: 'acesso',
    corpo: `<p>O checklist de acesso de um novo colaborador é aberto pelo gestor da área, e não
pelo próprio colaborador, antes do primeiro dia de trabalho.</p>
<h3>O que é liberado automaticamente</h3>
<ul><li>Usuário de rede e e-mail corporativo, criados a partir do nome completo informado
no chamado.</li>
<li>Acesso à pasta compartilhada do setor de lotação.</li>
<li>Perfil básico no ERP, sem módulos financeiros ou fiscais.</li></ul>
<h3>O que precisa de solicitação separada</h3>
<p>Acesso a sistemas específicos do setor, listas de distribuição e módulos avançados do ERP
não entram no pacote padrão. O gestor deve abrir chamados adicionais na categoria
correspondente para cada um desses itens.</p>
<h3>Prazo</h3>
<p>Solicite com pelo menos 3 dias úteis de antecedência. Chamados abertos no mesmo dia do
início podem não ser concluídos a tempo, já que dependem de aprovação do responsável pela
pasta ou sistema.</p>`,
  },
  {
    titulo: 'Revogar acessos de colaborador desligado',
    categoria: 'acesso',
    corpo: `<p>O gestor da área deve abrir chamado na categoria Acessos e Senhas assim que o
desligamento for confirmado pelo setor responsável, informando a data efetiva de saída.</p>
<h3>O que acontece no desligamento</h3>
<ol><li>O usuário de rede é desativado à meia-noite da data informada — logins em andamento
são encerrados na próxima autenticação.</li>
<li>A caixa de e-mail é bloqueada para envio e recebimento, mas mantida por 30 dias para
consulta de conteúdo pelo gestor, mediante chamado específico.</li>
<li>Acessos a pastas compartilhadas e ao ERP são revogados junto com o usuário de rede.</li></ol>
<h3>Equipamento</h3>
<p>A revogação de acesso não inclui a devolução de notebook ou periféricos — esse processo é
tratado separadamente na categoria Equipamentos.</p>
<h3>Desligamento antecipado ou imediato</h3>
<p>Em casos de desligamento com efeito imediato, marque o chamado como urgente e informe isso
por telefone ao suporte, além de abrir o chamado — o bloqueio pode ser antecipado manualmente
antes da rotina automática da meia-noite.</p>`,
  },
  {
    titulo: 'Atualizar acessos ao mudar de setor internamente',
    categoria: 'acesso',
    corpo: `<p>Mudança de setor não revoga acessos automaticamente — o perfil antigo continua
ativo até ser removido manualmente.</p>
<ol><li>O novo gestor abre chamado solicitando os acessos do novo setor.</li>
<li>O gestor anterior deve abrir chamado separado pedindo a remoção dos acessos que não
fazem mais sentido, como pastas e listas de distribuição do setor de origem.</li></ol>
<p>Por segurança, evite acumular acessos de setores diferentes por longos períodos: além do
risco de exposição de dados, isso também deixa qualquer relatório de auditoria mais confuso.</p>`,
  },

  // ============================= IMPRESSAO =============================
  {
    titulo: 'Resolver atolamento de papel na impressora',
    categoria: 'impressao',
    corpo: `<p>Antes de puxar o papel com força, abra todas as tampas indicadas no painel da
impressora — puxar pela bandeja de saída sem abrir as tampas internas costuma rasgar a folha
e piorar o atolamento.</p>
<ol><li>Desligue a impressora, se o manual do modelo recomendar (verifique o adesivo na
lateral do equipamento).</li>
<li>Abra a tampa frontal e, com as duas mãos, puxe o papel devagar no sentido da saída normal,
nunca de volta.</li>
<li>Confira a bandeja de origem: papel amassado ou fora do guia lateral é a causa mais comum
de atolamento recorrente.</li></ol>
<p>Se o painel continuar exibindo erro de atolamento mesmo sem papel visível, pode haver um
pedaço preso internamente. Não insista sozinho: abra chamado na categoria Impressão informando
o código do painel.</p>`,
  },
  {
    titulo: 'Substituir toner ou cartucho vazio',
    categoria: 'impressao',
    corpo: `<p>Impressoras compartilhadas do andar têm toner de reposição no próprio armário ao
lado do equipamento. Já impressoras USB locais dependem de compra individual.</p>
<ul><li>Para impressoras de rede, retire o toner reserva do armário e siga o passo a passo
impresso na tampa do equipamento.</li>
<li>Guarde a embalagem do toner usado — o descarte é feito em coletor específico, não no
lixo comum.</li>
<li>Se o armário estiver sem reposição, abra chamado na categoria Impressão em vez de
comprar por conta própria; o suprimento é centralizado por padrão de compatibilidade.</li></ul>`,
  },
  {
    titulo: 'Digitalizar documento e enviar direto por e-mail',
    categoria: 'impressao',
    corpo: `<p>As multifuncionais de rede enviam digitalizações direto para o e-mail cadastrado,
sem precisar de pendrive.</p>
<h3>Passo a passo</h3>
<ol><li>Na tela da impressora, toque em <strong>Digitalizar → E-mail</strong>.</li>
<li>Informe seu usuário de rede quando solicitado — a impressora usa isso para preencher
automaticamente o campo de remetente.</li>
<li>Escolha o formato: PDF para documentos de texto, JPG para imagens.</li>
<li>Toque em <strong>Iniciar</strong> e aguarde o e-mail chegar, normalmente em menos de um
minuto.</li></ol>
<h3>Problemas comuns</h3>
<p>Se o e-mail não chegar, verifique a caixa de spam antes de abrir chamado — remetentes
internos de equipamento às vezes caem em filtros por engano. Digitalizações acima de 20 MB
não são enviadas por e-mail automaticamente; nesse caso a impressora oferece salvar em pasta
de rede como alternativa.</p>`,
  },
  {
    titulo: 'Entender a cota mensal de impressão',
    categoria: 'impressao',
    corpo: `<p>Cada usuário tem uma cota mensal de páginas monitorada pelo sistema de impressão,
renovada automaticamente no primeiro dia de cada mês.</p>
<h3>Como consultar</h3>
<p>Acesse <code>https://cota.exemplo.local</code> com seu usuário de rede para ver quantas
páginas já usou e o limite do seu perfil.</p>
<h3>Ao atingir o limite</h3>
<p>A impressão não é bloqueada, mas o gestor do setor recebe um alerta automático. Uso
recorrente acima da cota gera conversa com o gestor sobre o padrão de impressão, não
suspensão imediata do serviço.</p>
<h3>Impressões em preto e branco x coloridas</h3>
<p>Páginas coloridas consomem três unidades da cota, contra uma unidade das páginas em preto
e branco — por isso relatórios longos devem, sempre que possível, ser impressos sem cor.</p>`,
  },
  {
    titulo: 'Impressora aparece offline mesmo ligada e conectada',
    categoria: 'impressao',
    corpo: `<p>Esse sintoma normalmente é de comunicação entre a estação e o servidor de
impressão, não da impressora física em si — por isso reiniciar a impressora raramente resolve
sozinho.</p>
<ol><li>Confirme que a estação está na rede interna ou na VPN; o servidor de impressão não é
alcançável de fora.</li>
<li>Em <strong>Configurações → Impressoras e scanners</strong>, remova a fila da impressora e
reconecte seguindo o procedimento de instalação de impressora de rede.</li>
<li>Se o problema afetar várias pessoas ao mesmo tempo na mesma fila, é provável que o
servidor de impressão esteja fora do ar — abra chamado informando o nome da fila e o andar.</li></ol>`,
  },

  // ============================= EMAIL =============================
  {
    titulo: 'Configurar assinatura padrão de e-mail',
    categoria: 'email',
    corpo: `<p>O modelo oficial de assinatura fica disponível em
<code>https://assinatura.exemplo.local</code>, já com os campos preenchidos a partir do seu
cadastro de usuário.</p>
<ol><li>Acesse o link e copie o bloco de assinatura gerado.</li>
<li>No cliente de e-mail, cole em <strong>Configurações → Assinatura</strong>.</li>
<li>Marque a opção para aplicar em novas mensagens e em respostas.</li></ol>
<p>Assinaturas com logotipos ou cores diferentes do modelo oficial não devem ser usadas em
comunicação externa.</p>`,
  },
  {
    titulo: 'Solicitar inclusão em lista de distribuição',
    categoria: 'email',
    corpo: `<p>Listas de distribuição (como <code>financeiro@exemplo.local</code> ou
<code>ti@exemplo.local</code>) têm um dono responsável por aprovar novos membros.</p>
<ol><li>Abra chamado na categoria E-mail e Colaboração informando o endereço da lista e o
motivo de precisar receber as mensagens.</li>
<li>O chamado é encaminhado ao dono da lista para aprovação antes de qualquer alteração.</li></ol>
<p>Para criar uma lista nova, o processo é diferente: é necessário indicar um responsável
fixo pela lista, já que ela não pode ficar sem dono.</p>`,
  },
  {
    titulo: 'Marcar e-mail como spam e bloquear remetente',
    categoria: 'email',
    corpo: `<p>Mensagens suspeitas com links estranhos ou pedidos urgentes de dados devem ser
marcadas como spam, e não apenas apagadas — isso ajuda o filtro a aprender.</p>
<ol><li>Selecione a mensagem e clique em <strong>Marcar como spam</strong> na barra de
ferramentas.</li>
<li>Para bloquear o remetente definitivamente, abra a mensagem e escolha
<strong>Bloquear remetente</strong> no menu de opções.</li></ol>
<p>Se o e-mail pedir dados de login, senha ou parecer uma tentativa de phishing direcionada,
encaminhe também para a categoria Acessos e Senhas antes de apagar, para que a equipe avalie
se outros usuários receberam a mesma mensagem.</p>`,
  },
  {
    titulo: 'Caixa de e-mail cheia e mensagens não chegam',
    categoria: 'email',
    corpo: `<p>Cada caixa tem limite de armazenamento, e ao atingi-lo o servidor passa a
recusar novas mensagens — inclusive as internas.</p>
<h3>Como verificar o espaço usado</h3>
<p>No cliente de e-mail, acesse <strong>Configurações → Armazenamento</strong> para ver o
percentual ocupado. Próximo de 90%, o sistema já envia um aviso automático por e-mail — que,
ironicamente, pode não chegar se a caixa já estiver no limite.</p>
<h3>Como liberar espaço</h3>
<ul><li>Esvazie a pasta de itens excluídos e a de spam, que não são limpas automaticamente.</li>
<li>Anexos grandes recebidos há muito tempo podem ser baixados para uma pasta local e
removidos do servidor.</li>
<li>Pastas de arquivo morto (arquivadas) também contam para o limite total da caixa.</li></ul>
<h3>Aumentar o limite</h3>
<p>Se seu trabalho exige volume de anexos acima do padrão, abra chamado justificando a
necessidade; o aumento de cota depende de aprovação do gestor da área.</p>`,
  },
  {
    titulo: 'Configurar e-mail corporativo no celular',
    categoria: 'email',
    corpo: `<p>O e-mail corporativo pode ser configurado em celulares pessoais ou corporativos
usando o protocolo padrão da empresa.</p>
<h3>Android e iPhone</h3>
<ol><li>No aplicativo de e-mail nativo, escolha adicionar conta do tipo <em>Exchange</em>.</li>
<li>Informe seu e-mail completo e a senha de rede.</li>
<li>No campo servidor, use <code>mail.exemplo.local</code>, caso não seja preenchido
automaticamente.</li>
<li>Aceite as permissões de segurança solicitadas pelo aplicativo, como bloqueio de tela por
senha ou biometria — isso é exigido pela política de dispositivos conectados ao e-mail
corporativo.</li></ol>
<h3>Se pedir para instalar um perfil de gerenciamento</h3>
<p>Isso é esperado em celulares corporativos e permite apagar remotamente os dados da empresa
em caso de perda do aparelho, sem afetar fotos e aplicativos pessoais. Em celulares pessoais,
apenas os dados de e-mail ficam sob esse gerenciamento.</p>`,
  },
  {
    titulo: 'Delegar acesso à caixa de e-mail para a equipe',
    categoria: 'email',
    corpo: `<p>Delegação permite que outra pessoa leia e responda pela sua caixa sem saber sua
senha — útil em ausências programadas ou caixas de setor compartilhadas.</p>
<ol><li>Abra chamado na categoria E-mail e Colaboração informando o login de quem receberá a
delegação e o nível de acesso: apenas leitura, ou leitura e envio.</li>
<li>A delegação é configurada no servidor pela equipe de suporte, não pelo próprio usuário,
para manter o registro de quem tem acesso a qual caixa.</li></ol>
<p>Delegações não removidas ao final do período combinado continuam ativas indefinidamente;
lembre-se de solicitar a remoção quando não forem mais necessárias.</p>`,
  },

  // ============================= ERP =============================
  {
    titulo: 'Primeiro acesso ao sistema ERP',
    categoria: 'erp',
    corpo: `<p>O acesso ao ERP é criado junto com o usuário de rede, mas exige uma etapa
adicional de ativação no primeiro login.</p>
<ol><li>Acesse <code>https://erp.exemplo.local</code> e informe seu usuário de rede.</li>
<li>No primeiro acesso, o sistema pede a senha provisória enviada por e-mail pelo suporte —
não é a mesma senha de rede.</li>
<li>Defina uma nova senha exclusiva do ERP e escolha as três perguntas de segurança.</li></ol>
<p>Se o e-mail com a senha provisória não chegar em até um dia útil após a liberação do
acesso, abra chamado na categoria Sistema ERP, e não na de E-mail — o envio é feito pelo
próprio ERP, fora do fluxo normal de e-mail.</p>`,
  },
  {
    titulo: 'Erro ao emitir nota fiscal no ERP',
    categoria: 'erp',
    corpo: `<p>O erro mais comum ao emitir nota é o código <strong>NF-102</strong>, que indica
divergência de cadastro fiscal do cliente ou do produto, não uma falha do sistema.</p>
<h3>Antes de abrir chamado</h3>
<ol><li>Confira se o cadastro do cliente tem o campo de inscrição estadual preenchido,
quando aplicável ao tipo de operação.</li>
<li>Verifique se o produto está com a classificação fiscal (NCM) atualizada — produtos
cadastrados há muito tempo às vezes ficam com códigos descontinuados.</li>
<li>Confirme que o período fiscal do mês corrente ainda está aberto para lançamentos, em
<strong>Fiscal → Períodos</strong>.</li></ol>
<h3>Códigos de erro frequentes</h3>
<ul><li><strong>NF-102</strong>: divergência de cadastro fiscal.</li>
<li><strong>NF-205</strong>: falha de comunicação com o serviço externo de autorização — nesse
caso, aguarde alguns minutos e tente novamente antes de abrir chamado.</li>
<li><strong>NF-311</strong>: limite de numeração da série de notas atingido, que exige
abertura de chamado para liberar uma nova série.</li></ul>
<p>Ao abrir chamado, informe o código exato do erro e o número do pedido ou nota que falhou —
sem isso, o técnico precisa reproduzir o cenário do zero, o que atrasa a resposta.</p>`,
  },
  {
    titulo: 'Relatório do ERP trava ou não termina de gerar',
    categoria: 'erp',
    corpo: `<p>Relatórios com filtros muito amplos, como um ano inteiro sem filtro de setor,
podem levar minutos ou travar a tela do navegador.</p>
<ol><li>Reduza o período do filtro para no máximo um trimestre e tente novamente.</li>
<li>Utilize o botão <strong>Gerar em segundo plano</strong>, disponível na maioria dos
relatórios, que envia o resultado por e-mail em vez de travar a tela enquanto processa.</li>
<li>Evite abrir o mesmo relatório em duas abas ao mesmo tempo — isso duplica o processamento
no servidor e piora a lentidão para todos os usuários conectados.</li></ol>
<p>Se mesmo com filtro reduzido o relatório não terminar em 10 minutos, abra chamado
informando o nome exato do relatório e os filtros usados.</p>`,
  },
  {
    titulo: 'Checklist de fechamento mensal no ERP',
    categoria: 'erp',
    corpo: `<p>O fechamento mensal é o processo que consolida lançamentos do período e impede
edições retroativas depois de concluído. Ele é irreversível sem intervenção da equipe de
suporte, por isso este checklist deve ser seguido na ordem apresentada.</p>
<h3>Uma semana antes do fechamento</h3>
<ol><li>Confira pendências de lançamento em <strong>Financeiro → Pendências</strong> — notas
sem conciliação bancária costumam ser o maior motivo de atraso no fechamento.</li>
<li>Valide o cadastro de centros de custo usados no mês; centros de custo inativos geram
erro no momento da consolidação.</li>
<li>Gere o relatório de divergências em <strong>Fiscal → Divergências do Período</strong> e
resolva os itens listados antes de prosseguir.</li></ol>
<h3>No dia do fechamento</h3>
<ol><li>Confirme com todos os setores que lançam no ERP (compras, financeiro e fiscal) que
não há lançamentos pendentes de digitação.</li>
<li>Execute o fechamento em <strong>Financeiro → Fechamento de Período</strong>, escolhendo o
mês corrente.</li>
<li>O sistema exibe um resumo com o total de lançamentos consolidados — confira se o número
bate com o esperado antes de confirmar.</li>
<li>Após confirmar, o período fica bloqueado para novos lançamentos e edições.</li></ol>
<h3>Depois do fechamento</h3>
<p>Lançamentos esquecidos do mês fechado não podem ser inseridos retroativamente pelo próprio
usuário. É necessário abrir chamado na categoria Sistema ERP solicitando reabertura pontual do
período, o que exige aprovação do responsável financeiro e fica registrado como exceção.</p>
<h3>Erros comuns durante o fechamento</h3>
<ul><li><strong>FC-01</strong>: existem lançamentos pendentes de aprovação — volte e finalize
as aprovações antes de tentar de novo.</li>
<li><strong>FC-04</strong>: divergência entre o total de notas emitidas e o total registrado
no financeiro — normalmente causada por nota emitida fora do ERP e não importada.</li>
<li><strong>FC-09</strong>: usuário sem permissão de fechamento — apenas perfis específicos
do financeiro têm essa permissão, mesmo que o usuário consiga lançar normalmente no dia a
dia.</li></ul>
<p>Guarde o comprovante de fechamento gerado ao final do processo; ele é solicitado em
eventuais auditorias e não fica disponível para reimpressão depois de alguns meses.</p>
<h3>Diferenças entre fechamento fiscal e fechamento financeiro</h3>
<p>É comum confundir os dois processos, mas eles rodam em telas diferentes e têm prazos
distintos. O fechamento fiscal trata da consolidação de notas emitidas e recebidas para fins
de apuração de impostos, enquanto o fechamento financeiro trata da consolidação de contas a
pagar, contas a receber e conciliação bancária do período. Em geral, o fechamento fiscal
precisa acontecer antes do financeiro, porque o financeiro usa os totais já consolidados de
notas para bater com os lançamentos bancários.</p>
<h3>Papéis envolvidos</h3>
<p>Nem todo integrante do time financeiro tem permissão para efetivamente confirmar o
fechamento — normalmente apenas um ou dois perfis por setor têm essa permissão, justamente
para evitar que o processo seja concluído sem a revisão adequada dos itens do checklist. Se
a pessoa responsável estiver ausente no dia do fechamento, é necessário que o gestor da área
solicite, com antecedência, a inclusão temporária de outro colaborador nesse perfil pela
categoria Sistema ERP — a permissão não pode ser emprestada informalmente, já que toda
confirmação de fechamento fica registrada em nome de quem executou a ação.</p>`,
  },
  {
    titulo: 'Solicitar permissão de módulo no ERP',
    categoria: 'erp',
    corpo: `<p>O perfil padrão do ERP concedido a novos colaboradores inclui apenas consulta.
Módulos como Financeiro, Fiscal e Compras exigem permissão específica.</p>
<ol><li>Abra chamado na categoria Sistema ERP informando o módulo desejado e a função que
você exercerá nele (lançamento, aprovação ou apenas consulta).</li>
<li>O chamado é aprovado pelo gestor responsável pelo módulo solicitado, que pode ser
diferente do seu próprio gestor direto.</li>
<li>Após aprovado, o acesso ao módulo aparece no menu lateral do ERP no próximo login.</li></ol>
<p>Permissões de aprovação financeira (como aprovar pagamentos) seguem regra própria de
alçada e não são liberadas apenas por este chamado padrão — o gestor do módulo indica se o
caso exige um fluxo adicional.</p>`,
  },
  {
    titulo: 'Exportação de dados do ERP falha ou trava na metade',
    categoria: 'erp',
    corpo: `<p>Exportações para planilha com muitas linhas (acima de 50 mil registros) podem
falhar por limite de memória do navegador, não por erro do ERP em si.</p>
<ul><li>Reduza o período ou aplique filtros adicionais antes de exportar.</li>
<li>Prefira o formato CSV ao invés de XLSX para volumes grandes — o CSV processa mais rápido
e evita travamento do navegador.</li>
<li>Se a exportação precisa ser completa mesmo com muitos registros, use a opção
<strong>Exportar por e-mail</strong>, que processa no servidor e envia o arquivo pronto.</li></ul>
<p>Se a exportação falhar mesmo com poucos registros, abra chamado informando a tela exata de
onde tentou exportar.</p>`,
  },

  // ============================= EQUIPAMENTO =============================
  {
    titulo: 'Solicitar notebook para novo colaborador',
    categoria: 'equipamento',
    corpo: `<p>O gestor da área deve abrir chamado na categoria Equipamentos com pelo menos
5 dias úteis de antecedência do início do colaborador, informando o perfil de uso (padrão ou
engenharia, que exige configuração mais robusta).</p>
<ol><li>O chamado passa por aprovação de estoque antes da separação do equipamento.</li>
<li>O notebook é preparado com a imagem padrão da empresa, já com os aplicativos básicos
instalados.</li>
<li>A entrega é feita na recepção do andar do setor, mediante assinatura do termo de
responsabilidade pelo próprio colaborador no primeiro dia.</li></ol>
<p>Pedidos com prazo menor que 5 dias úteis dependem de disponibilidade em estoque e podem não
ser atendidos a tempo.</p>`,
  },
  {
    titulo: 'Solicitar monitor adicional para a estação',
    categoria: 'equipamento',
    corpo: `<p>Monitores adicionais são liberados mediante aprovação do gestor direto, dentro
da disponibilidade de estoque do almoxarifado de TI.</p>
<ol><li>Abra chamado na categoria Equipamentos indicando se é para uso no escritório.</li>
<li>Aguarde a aprovação do gestor antes da separação do item.</li>
<li>A entrega inclui cabo de vídeo compatível com o notebook cadastrado no seu usuário.</li></ol>
<p>Modelos específicos fora do padrão de estoque (como monitores ultrawide) exigem
justificativa técnica anexada ao chamado.</p>`,
  },
  {
    titulo: 'Bateria do notebook não dura ou não carrega',
    categoria: 'equipamento',
    corpo: `<p>Antes de solicitar troca de bateria, verifique se o problema é da bateria em si
ou do carregador.</p>
<ol><li>Teste com outro carregador do mesmo modelo, se houver disponível por perto — cabos e
fontes danificados são causa mais comum do que a bateria propriamente dita.</li>
<li>No Windows, gere o relatório de energia com o comando <code>powercfg /batteryreport</code>
no Prompt de Comando, e verifique o campo <strong>Capacidade total de carga</strong>
comparado à capacidade original.</li>
<li>No macOS, veja o estado da bateria em <strong>Ajustes do Sistema → Bateria → Estado da
Bateria</strong>.</li></ol>
<p>Se a capacidade estiver abaixo de 60% da original, abra chamado na categoria Equipamentos
anexando o relatório gerado — isso agiliza a aprovação da troca sem necessidade de
diagnóstico presencial.</p>`,
  },
  {
    titulo: 'Formatação e reinstalação completa de notebook',
    categoria: 'equipamento',
    corpo: `<p>A formatação apaga todos os dados locais do equipamento e reinstala a imagem
padrão da empresa. É um procedimento indicado para lentidão persistente sem causa
identificada, ou como preparação para reatribuição do equipamento a outra pessoa. Antes de
prosseguir, leia todo o procedimento — o processo não pode ser interrompido depois de
iniciado.</p>
<h3>Antes de agendar</h3>
<ul><li>Faça backup de tudo que estiver salvo apenas localmente, na pasta de Documentos ou
na área de trabalho. Arquivos salvos em pastas de rede ou nuvem não precisam de backup, pois
não são afetados.</li>
<li>Anote quais aplicativos fora do padrão você usa no dia a dia — eles precisarão ser
reinstalados manualmente depois, já que a imagem padrão só traz os aplicativos básicos.</li>
<li>Confirme com seu gestor se algum sistema depende de configuração local específica (como
certificados de acesso a sistemas de clientes), para que o técnico recrie essa configuração
após a formatação.</li></ul>
<h3>Como solicitar</h3>
<ol><li>Abra chamado na categoria Equipamentos descrevendo o motivo da formatação e
confirmando que o backup já foi feito.</li>
<li>O suporte agenda uma janela, normalmente no fim do dia, já que o notebook fica
indisponível por algumas horas durante o processo.</li>
<li>No horário agendado, deixe o notebook conectado à energia e à rede — o processo aborta
automaticamente se a bateria descarregar no meio do procedimento.</li></ol>
<h3>Depois da formatação</h3>
<p>O notebook volta com o usuário de rede já configurado, mas sem os aplicativos extras nem
os favoritos do navegador. Senhas salvas no navegador também são perdidas, já que ficavam
armazenadas localmente — anote as que forem necessárias antes de começar.</p>
<h3>Quando NÃO formatar</h3>
<p>Lentidão causada por pouco espaço em disco geralmente se resolve limpando arquivos grandes
e esvaziando a lixeira, sem necessidade de formatação. Da mesma forma, um aplicativo específico
travando não justifica reinstalar o sistema inteiro — nesse caso, a reinstalação do próprio
aplicativo resolve na maioria dos casos.</p>`,
  },
  {
    titulo: 'Devolução de equipamento no desligamento',
    categoria: 'equipamento',
    corpo: `<p>Notebook, monitor, dock e demais periféricos cadastrados em nome do colaborador
devem ser devolvidos até o último dia de trabalho, na recepção do andar ou diretamente ao
almoxarifado de TI.</p>
<ol><li>O gestor confirma no chamado de desligamento quais itens estão sob responsabilidade
do colaborador, com base no termo assinado na entrega.</li>
<li>Na devolução, o item é conferido visualmente e testado antes de dar baixa no cadastro do
colaborador.</li>
<li>Danos não decorrentes de uso normal são registrados no chamado para avaliação do
gestor.</li></ol>
<p>Equipamento não devolvido até a data de desligamento gera pendência registrada no chamado,
visível ao gestor da área.</p>`,
  },
  {
    titulo: 'Mouse ou teclado com defeito',
    categoria: 'equipamento',
    corpo: `<p>Antes de solicitar troca, teste o periférico em outra porta USB ou em outro
notebook, se possível — muitas vezes o defeito é da porta, não do próprio mouse ou teclado.</p>
<p>Confirmado o defeito, abra chamado na categoria Equipamentos informando o modelo, se
souber, e leve o item com defeito até o almoxarifado no momento da troca.</p>`,
  },
  {
    titulo: 'Notebook não liga ou trava constantemente',
    categoria: 'equipamento',
    corpo: `<p>Separe os dois sintomas, pois o diagnóstico é diferente para cada um.</p>
<h3>Notebook não liga</h3>
<ol><li>Conecte o carregador e aguarde 15 minutos antes de tentar ligar — bateria totalmente
descarregada pode levar esse tempo para mostrar sinal de vida.</li>
<li>Verifique se a luz do carregador acende; se não, o problema pode ser do cabo ou da
fonte, não do notebook.</li>
<li>Tente um pressionamento longo do botão de energia (cerca de 10 segundos) para forçar um
desligamento completo antes de ligar novamente.</li></ol>
<h3>Notebook trava com uso</h3>
<p>Travamentos que pioram com o notebook quente sugerem problema de ventilação — evite usar
sobre a cama, sofá ou outras superfícies macias que bloqueiam as saídas de ar. Travamentos
aleatórios, mesmo com o equipamento frio, têm causas mais variadas e exigem diagnóstico
técnico presencial.</p>
<h3>Quando abrir chamado</h3>
<p>Em ambos os casos, abra chamado na categoria Equipamentos. Para notebook que não liga,
leve o equipamento e o carregador junto; não é possível diagnosticar remotamente um
equipamento desligado.</p>`,
  },
]
