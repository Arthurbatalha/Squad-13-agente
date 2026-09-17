# Mapeamento de Casos Ambíguos

## Objetivo

Mapear perguntas ambíguas da base de conhecimento e identificar os
artigos correspondentes a cada possível interpretação.

## Caso 5 — Configuração de VPN

**Pergunta:**  
Como configuro a VPN?

**Ambiguidade:**  
A pergunta não informa qual sistema operacional está sendo utilizado.

| Interpretação | Artigo correspondente |
|---|---|
| Windows | Configurar a VPN corporativa no Windows |
| macOS | Configurar a VPN corporativa no macOS |

**Critério de desambiguação:**  
O agente deve identificar o sistema operacional ou perguntar ao usuário
se ele utiliza Windows ou macOS antes de escolher o artigo.

---

## Caso 6 — Redefinição de senha

**Pergunta:**  
Como redefino minha senha?

**Ambiguidade:**  
A pergunta não informa se o usuário deseja realizar o procedimento
por autoatendimento ou solicitar auxílio do suporte.

| Interpretação | Artigo correspondente |
|---|---|
| Autoatendimento | Redefinir a senha de rede pelo autoatendimento |
| Suporte | Redefinir a senha de rede com o suporte |

**Critério de desambiguação:**  
O agente deve identificar se o usuário deseja realizar o procedimento
sozinho ou precisa de auxílio do suporte.

---

## Caso 7 — Instalação de impressora

**Pergunta:**  
Como instalo uma impressora?

**Ambiguidade:**  
A pergunta não informa se a impressora será instalada pela rede ou
por conexão USB.

| Interpretação | Artigo correspondente |
|---|---|
| Rede | Instalar impressora de rede no Windows |
| USB | Instalar impressora USB local no Windows |

**Critério de desambiguação:**  
O agente deve perguntar se a impressora será utilizada pela rede ou
conectada diretamente ao computador via USB antes de escolher o artigo.
