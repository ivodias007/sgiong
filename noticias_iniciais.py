"""noticias_iniciais.py — Notícias de arranque do SGIONGs (só se a tabela estiver vazia).
São textos de exemplo sobre o próprio sistema; o administrador pode editá-las,
substituí-las ou eliminá-las em "Gerir notícias"."""
from datetime import datetime, timedelta

IMAGENS = {  # título da notícia inicial -> imagem (ficheiros em static/img/noticias/, ver gerar_imagens_noticias.py)
    'Organizações Não Governamentais em Moçambique': '/static/img/noticias/ongs-mocambique.jpg',
    'Mapa georreferenciado mostra a presença das ONGs por província e distrito': '/static/img/noticias/mapa-georreferenciado.jpg',
    'Actualizada a relação nominal de ONGs da província de Sofala': '/static/img/noticias/sofala-relacao.jpg',
}

AUTOR = 'Direcção Nacional de Promoção do Desenvolvimento Integrado'

NOTICIAS = [
    ('Organizações Não Governamentais em Moçambique', 'Moçambique',
     'O SGIONGs reúne num só lugar a informação das ONGs que actuam nas 11 províncias do país.',
     'O Sistema de Gestão de Informação de ONGs (SGIONGs) centraliza o registo, a consulta e o acompanhamento das organizações não governamentais que operam em Moçambique.\n\n'
     'A informação está organizada por província, distrito e área temática, permitindo ao Ministério da Planificação e Desenvolvimento conhecer onde cada organização actua e identificar zonas com pouca cobertura.\n\n'
     'Os dados são validados por um fluxo de aprovação e todas as alterações ficam registadas em histórico de auditoria.', 0, 1),
    ('Mapa georreferenciado mostra a presença das ONGs por província e distrito', 'Avisos do Sistema',
     'O painel de indicadores passou a mostrar o número e a percentagem de ONGs em cada província e distrito.',
     'O painel de indicadores inclui agora um mapa georreferenciado de Moçambique com 11 províncias e 159 distritos.\n\n'
     'Ao clicar numa província, o mapa mostra os seus distritos, com o número de ONGs e a respectiva percentagem. Ao clicar num distrito, o painel filtra os indicadores correspondentes.', 1, 0),
    ('Actualizada a relação nominal de ONGs da província de Sofala', 'Sociedade Civil',
     'Foram incorporadas as listas de ONGs nacionais, estrangeiras e activas de Sofala.',
     'A relação nominal de ONGs da província de Sofala foi actualizada com as listas de organizações nacionais, estrangeiras e activas, evitando registos repetidos.\n\n'
     'Nomes parecidos podem ser revistos na página de possíveis duplicados, onde todos os registos semelhantes aparecem agrupados.', 2, 0),
]


def semear(conn):
    if conn.execute('SELECT COUNT(*) c FROM noticias').fetchone()['c']:
        return 0
    hoje = datetime.now()
    for titulo, cat, resumo, texto, dias, destaque in NOTICIAS:
        data = (hoje - timedelta(days=dias)).strftime('%Y-%m-%d 00:00:00')
        conn.execute('INSERT INTO noticias (titulo, categoria, resumo, conteudo, autor, publicada, destaque, publicado_em, criado_por, imagem_url) '
                     'VALUES (?,?,?,?,?,1,?,?,?,?)', (titulo, cat, resumo, texto, AUTOR, destaque, data, 'sistema', IMAGENS.get(titulo)))
    conn.commit()
    return len(NOTICIAS)


def completar_imagens(conn):
    """Bases já existentes: dá imagem às notícias iniciais que ainda não têm nenhuma.
    Nunca mexe numa notícia que o administrador já editou/ilustrou (imagem preenchida)."""
    n = 0
    for titulo, url in IMAGENS.items():
        n += conn.execute("UPDATE noticias SET imagem_url = ? WHERE titulo = ? AND criado_por = 'sistema' "
                          "AND (imagem_url IS NULL OR imagem_url = '')", (url, titulo)).rowcount
    if n:
        conn.commit()
    return n
