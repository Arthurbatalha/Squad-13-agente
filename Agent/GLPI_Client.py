from GLPI_Client import GLPIClient
from busca_artigos import BuscadorTFIDF

def processar_duvida_usuario(chamado_descricao: str):
    # 1. Autentica e carrega os artigos da Base de Conhecimento do GLPI
    glpi = GLPIClient()
    glpi.autenticar()
    artigos_glpi = glpi.obter_base_conhecimento()
    
    # 2. Inicializa o motor de busca com os artigos atualizados
    buscador = BuscadorTFIDF(documentos=artigos_glpi, min_score=0.20)
    
    # 3. Executa a busca baseada no texto do chamado
    artigos_relevantes = buscador.buscar(query=chamado_descricao, top_n=3)
    
    # 4. Formata o contexto para o Agente gerar a resposta final
    if artigos_relevantes:
        print(f"Encontrados {len(artigos_relevantes)} artigo(s) relevante(s):")
        for art in artigos_relevantes:
            print(f"- [{art['similarity_score']}] {art.get('name')}")
        return artigos_relevantes
    else:
        print("Nenhum artigo atingiu o limiar de relevância.")
        return []