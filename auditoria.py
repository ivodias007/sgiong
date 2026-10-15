"""
auditoria.py — Histórico de auditoria do SGIONGs.

Cada acção relevante (criar, editar, aprovar, rejeitar, eliminar, gerir
utilizadores, tentativas de login) fica registada em historico_auditoria,
com quem, quando, o IP de origem e um resumo legível em português — no
formato pedido:

    "10/09/2026 — Operador X alterou telefone da ONG Y —
     telefone anterior: XXX — novo telefone: YYY."
"""

import json


def registar(conn, accao, resumo, utilizador=None, ip=None, ong_id=None, detalhes=None):
    """Grava uma entrada de auditoria. Uso genérico para acções que não são
    edições campo-a-campo (criar, aprovar, rejeitar, eliminar, utilizadores)."""
    conn.execute('''
        INSERT INTO historico_auditoria (ong_id, accao, utilizador, ip, resumo, detalhes_json)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (ong_id, accao, utilizador, ip, resumo,
          json.dumps(detalhes, ensure_ascii=False) if detalhes is not None else None))


def registar_diffs_por_campo(conn, ong_id, accao, diffs, utilizador, ip, nome_ong):
    """Uma entrada de auditoria POR CAMPO alterado — dá o nível de detalhe
    pedido: 'Operador X alterou telefone da ONG Y — telefone anterior: XXX —
    novo telefone: YYY.' Usado quando uma edição É APLICADA (imediatamente
    pelo Super Admin, ou ao aprovar uma edição pendente)."""
    for d in diffs:
        resumo = (f'{utilizador} alterou {d["rotulo"].lower()} da ONG "{nome_ong}" — '
                  f'antes: {d["antigo"]} — depois: {d["novo"]}')
        registar(conn, accao, resumo, utilizador, ip, ong_id, detalhes=d)


def obter_historico_ong(conn, ong_id, limite=200):
    return conn.execute('''
        SELECT * FROM historico_auditoria WHERE ong_id = ?
        ORDER BY criado_em DESC, id DESC LIMIT ?
    ''', (ong_id, limite)).fetchall()


def obter_historico_geral(conn, utilizador=None, accao=None, provincia=None, limite=300):
    """Histórico global, com filtros opcionais. O filtro de província faz
    JOIN com ongs — usado para limitar o Gestor Provincial ao que lhe diz
    respeito."""
    query = '''
        SELECT ha.*, o.nome AS ong_nome
        FROM historico_auditoria ha
        LEFT JOIN ongs o ON o.id = ha.ong_id
        WHERE 1=1
    '''
    params = []
    if utilizador:
        query += ' AND ha.utilizador = ?'
        params.append(utilizador)
    if accao:
        query += ' AND ha.accao = ?'
        params.append(accao)
    if provincia:
        query += ' AND o.provincia = ?'
        params.append(provincia)
    query += ' ORDER BY ha.criado_em DESC, ha.id DESC LIMIT ?'
    params.append(limite)
    return conn.execute(query, params).fetchall()


ROTULOS_ACCOES = {
    'criar_ong': 'Registo criado',
    'editar_ong': 'Edição aplicada',
    'submeter_edicao': 'Edição submetida (pendente)',
    'aprovar_ong': 'Registo aprovado',
    'rejeitar_ong': 'Registo rejeitado',
    'aprovar_edicao': 'Edição aprovada',
    'rejeitar_edicao': 'Edição rejeitada',
    'eliminar_ong': 'Registo eliminado',
    'guardar_rascunho': 'Rascunho guardado',
    'submeter_rascunho': 'Rascunho submetido',
    'eliminar_rascunho': 'Rascunho eliminado',
    'iniciar_analise': 'Análise iniciada',
    'sinalizar_atualizacao': 'Sinalizado para actualização',
    'gerar_relatorio': 'Relatório gerado',
    'alterar_senha': 'Senha alterada',
    'activar_2fa': 'Verificação em duas etapas activada',
    'desactivar_2fa': 'Verificação em duas etapas desactivada',
    'criar_backup': 'Backup criado',
    'descarregar_backup': 'Backup descarregado',
    'ignorar_duplicado': 'Par marcado como não-duplicado',
    'importar_matriz': 'Matriz importada',
    'ignorar_sobreposicao': 'Sobreposição marcada como coordenada',
    'criar_utilizador': 'Utilizador criado',
    'desactivar_utilizador': 'Utilizador desactivado',
    'reactivar_utilizador': 'Utilizador reactivado',
    'login_sucesso': 'Sessão iniciada',
    'login_falhado': 'Tentativa de login falhada',
}
