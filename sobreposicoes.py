"""
sobreposicoes.py — Alerta de sobreposição de actuação: várias ONGs
DIFERENTES a trabalhar na mesma ramificação (actividade específica, ex.:
"Água e Saneamento") no mesmo distrito.

Isto é diferente de duplicados.py: aquele módulo procura ONGs que talvez
sejam O MESMO registo repetido (nome parecido). Este módulo assume que as
ONGs são mesmo diferentes e sinaliza quando várias delas fazem o mesmo
trabalho no mesmo sítio — útil para coordenação, não para limpeza de dados.
"""

LIMIAR_DEFEITO = 2  # a partir de quantas ONGs no mesmo (distrito, ramificação) já vale a pena avisar


def contar_sobreposicoes(conn, provincia=None, limiar=LIMIAR_DEFEITO):
    """Só a contagem, sem montar a lista de ONGs de cada grupo — mais leve
    para chamar em todas as páginas (badge do sino de notificações)."""
    condicoes = ["o.aprovacao = 'Aprovado'"]
    params = []
    if provincia:
        condicoes.append('d.provincia = ?')
        params.append(provincia)

    ignorados = {(r['distrito_id'], r['ramificacao_id'])
                 for r in conn.execute('SELECT distrito_id, ramificacao_id FROM sobreposicoes_ignoradas')}

    linhas = conn.execute(f'''
        SELECT d.id AS distrito_id, orr.ramificacao_id, COUNT(DISTINCT od.ong_id) n
        FROM ong_distritos od
        JOIN distritos d ON d.id = od.distrito_id
        JOIN ong_ramificacoes orr ON orr.ong_id = od.ong_id
        JOIN ongs o ON o.id = od.ong_id
        WHERE {' AND '.join(condicoes)}
        GROUP BY d.id, orr.ramificacao_id
    ''', params).fetchall()

    return sum(1 for l in linhas if l['n'] >= limiar and (l['distrito_id'], l['ramificacao_id']) not in ignorados)


def procurar_sobreposicoes(conn, provincia=None, distrito_id=None, limiar=LIMIAR_DEFEITO, limite=200):
    condicoes = ["o.aprovacao = 'Aprovado'"]
    params = []
    if provincia:
        condicoes.append('d.provincia = ?')
        params.append(provincia)
    if distrito_id:
        condicoes.append('d.id = ?')
        params.append(distrito_id)

    ignorados = {(r['distrito_id'], r['ramificacao_id'])
                 for r in conn.execute('SELECT distrito_id, ramificacao_id FROM sobreposicoes_ignoradas')}

    linhas = conn.execute(f'''
        SELECT d.id AS distrito_id, d.nome AS distrito, d.provincia AS provincia,
               r.id AS ramificacao_id, r.nome AS ramificacao, a.nome AS area,
               o.id AS ong_id, o.nome AS ong_nome
        FROM ong_distritos od
        JOIN distritos d ON d.id = od.distrito_id
        JOIN ong_ramificacoes orr ON orr.ong_id = od.ong_id
        JOIN ramificacoes r ON r.id = orr.ramificacao_id
        JOIN areas a ON a.id = r.area_id
        JOIN ongs o ON o.id = od.ong_id
        WHERE {' AND '.join(condicoes)}
        ORDER BY d.nome, r.nome, o.nome
    ''', params).fetchall()

    grupos = {}
    for linha in linhas:
        chave = (linha['distrito_id'], linha['ramificacao_id'])
        if chave in ignorados:
            continue
        if chave not in grupos:
            grupos[chave] = {
                'distrito_id': linha['distrito_id'], 'distrito': linha['distrito'],
                'provincia': linha['provincia'], 'ramificacao_id': linha['ramificacao_id'],
                'ramificacao': linha['ramificacao'], 'area': linha['area'], 'ongs': [],
            }
        grupos[chave]['ongs'].append({'id': linha['ong_id'], 'nome': linha['ong_nome']})

    resultado = [g for g in grupos.values() if len(g['ongs']) >= limiar]
    resultado.sort(key=lambda g: len(g['ongs']), reverse=True)
    return resultado[:limite], len(resultado)


def ignorar_sobreposicao(conn, distrito_id, ramificacao_id, utilizador):
    conn.execute('''
        INSERT OR IGNORE INTO sobreposicoes_ignoradas (distrito_id, ramificacao_id, ignorado_por)
        VALUES (?, ?, ?)
    ''', (distrito_id, ramificacao_id, utilizador))
