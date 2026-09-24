# Setup de Infraestrutura e Dependências (Sprint 1)

## Introdução
Este documento estabelece o guia oficial para a configuração do ambiente de desenvolvimento e a instalação das dependências do sistema RAG integrado ao ecossistema do GLPI (Squad 13). O objetivo é garantir que todo o time possua a mesma base técnica para o desenvolvimento da busca híbrida e a geração de embeddings customizados, respeitando a restrição do projeto de **não utilizar** frameworks de abstração de alto nível (como LangChain ou LlamaIndex).

## Mapeamento de Bibliotecas e Ferramentas (RAG)
As ferramentas abaixo foram definidas e escolhidas pelas duplas para a construção do pipeline RAG do zero:

* **BeautifulSoup (`beautifulsoup4`)**: Utilizada para o parsing, extração e sanitização do conteúdo textual bruto proveniente dos artigos de base de conhecimento e tickets do GLPI, removendo tags HTML e artefatos indesejados.
* **NumPy (`numpy`)**: Essencial para a manipulação eficiente de matrizes e cálculos vetoriais gerados na etapa de embeddings.
* **Scikit-Learn (`scikit-learn`)**: Fornece algoritmos e funções de cálculo métrico (como a Similaridade de Cosseno), fundamentais para implementarmos nossa própria lógica de ranqueamento e busca vetorial.
* **Sentence-Transformers (`sentence-transformers`)**: Responsável por converter os textos recuperados do GLPI em embeddings (vetores densos) utilizando modelos de linguagem, servindo como motor da nossa busca semântica.

## Guia de Instalação

Para configurar o ambiente localmente e instalar todas as dependências mapeadas, execute os comandos abaixo no seu terminal, garantindo que você está na raiz do projeto.

### 1. Configurar o Ambiente Virtual (Recomendado)
```bash
python -m venv venv

# No Linux/macOS:
source venv/bin/activate

# No Windows:
venv\Scripts\activate
```

### 2. Instalar as Dependências
Certifique-se de que os arquivos de requerimentos já estão devidamente atualizados pelo colega da infraestrutura e execute:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

*Caso precise instalar as bibliotecas de IA manualmente para testes pontuais:*
```bash
pip install beautifulsoup4 numpy scikit-learn sentence-transformers
```

---

## ⚠️ Aviso Crítico: Download de Modelos de IA
> **MUITO IMPORTANTE:** Ao executar o código que importa a biblioteca `sentence-transformers` pela **primeira vez**, o script fará o download automático dos pesos do modelo de IA configurado na arquitetura (o que pode variar de centenas de megabytes a alguns gigabytes).
> 
> **O terminal poderá parecer travado ou ocioso por alguns minutos.** 
> **NÃO cancele a execução (Ctrl+C).** O código não está em loop infinito nem travou; ele está apenas baixando o modelo para o cache da sua máquina local. Nas execuções subsequentes, o modelo será carregado instantaneamente do disco.

---

## 🔐 Nota sobre Variáveis de Ambiente e Segurança
Lembrete obrigatório para todo o squad na operação do RAG: **Nunca insira chaves de API, Tokens de App/User do GLPI ou senhas de banco de dados no código-fonte.**

* Já tivemos problemas internos com credenciais hardcoded anteriormente; vamos evitar repetições.
* Utilize sempre o arquivo `.env` (baseado no template `lab/.env.example`) para injetar e consumir credenciais no sistema.
* Confirme sempre se o arquivo `.env` está devidamente listado no seu `.gitignore` antes de realizar qualquer `git push`.
