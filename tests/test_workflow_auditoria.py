"""Fluxo de registo → aprovação → edição → aprovação, e rasto de auditoria."""
import json
from conftest import cliente_com, primeiro_id, texto

def dados(nome, prov='Sofala', **extra):
    d = {'nome': nome, 'provincias': [prov], 'natureza': 'ONG', 'origem': 'Nacional',
         'area_intervencao': 'Saúde', 'estado': 'Ativo', 'telefone': '840000000'}
    d.update(extra)
    return d

def audit(db, accao=None):
    q = 'SELECT * FROM historico_auditoria' + (' WHERE accao=?' if accao else '') + ' ORDER BY id DESC'
    return db.execute(q, (accao,) if accao else ()).fetchall()


def test_registo_aprovacao_com_rasto_completo(db):
    op = cliente_com('operador')
    op.post('/ong/novo', dados('ONG Teste Fluxo'))
    ong = db.execute("SELECT * FROM ongs WHERE nome='ONG Teste Fluxo'").fetchone()
    assert ong['aprovacao'] == 'Pendente' and ong['criado_por'] == op.email
    gn = cliente_com('gestor_nacional')
    gn.post(f'/ong/{ong["id"]}/aprovar')
    ong = db.execute('SELECT * FROM ongs WHERE id=?', (ong['id'],)).fetchone()
    assert ong['aprovacao'] == 'Aprovado' and ong['aprovado_por'] == gn.email and ong['aprovado_em']
    accoes = [a['accao'] for a in audit(db) if a['ong_id'] == ong['id']]
    assert 'criar_ong' in accoes and 'aprovar_ong' in accoes
    a = [a for a in audit(db, 'aprovar_ong')][0]
    assert a['utilizador'] == gn.email and a['ip'] and a['criado_em']  # quem, de onde, quando


def test_rejeicao_guarda_motivo_e_autor(db):
    op = cliente_com('operador')
    op.post('/ong/novo', dados('ONG A Rejeitar'))
    oid = db.execute("SELECT id FROM ongs WHERE nome='ONG A Rejeitar'").fetchone()[0]
    gn = cliente_com('gestor_nacional')
    gn.post(f'/ong/{oid}/rejeitar', {'motivo': 'Documentação em falta'})
    l = db.execute('SELECT aprovacao, motivo_rejeicao, aprovado_por FROM ongs WHERE id=?', (oid,)).fetchone()
    assert l['aprovacao'] == 'Rejeitado' and l['motivo_rejeicao'] == 'Documentação em falta' and l['aprovado_por'] == gn.email
    assert any('Documentação em falta' in a['resumo'] for a in audit(db, 'rejeitar_ong'))


def test_edicao_proposta_so_vale_depois_de_aprovada(db):
    oid = primeiro_id(db)
    antes = db.execute('SELECT telefone FROM ongs WHERE id=?', (oid,)).fetchone()[0]
    prov = db.execute('SELECT provincia, nome FROM ongs WHERE id=?', (oid,)).fetchone()
    ad = cliente_com('admin')
    ad.post(f'/ong/{oid}/editar', dados(prov['nome'], prov['provincia'], telefone='849999999'))
    assert db.execute('SELECT telefone FROM ongs WHERE id=?', (oid,)).fetchone()[0] == antes   # ainda não mudou
    alt = db.execute("SELECT * FROM alteracoes_pendentes WHERE ong_id=? AND estado='Pendente'", (oid,)).fetchone()
    assert alt and alt['solicitado_por'] == ad.email
    ad.post(f'/alteracao/{alt["id"]}/aprovar')                                                   # não aprova a própria
    assert db.execute('SELECT telefone FROM ongs WHERE id=?', (oid,)).fetchone()[0] == antes
    sa = cliente_com('super_admin')
    sa.post(f'/alteracao/{alt["id"]}/aprovar')
    assert db.execute('SELECT telefone FROM ongs WHERE id=?', (oid,)).fetchone()[0] == '849999999'
    d = [a for a in audit(db, 'aprovar_edicao') if a['ong_id'] == oid]
    assert any('849999999' in a['resumo'] and a['utilizador'] == sa.email for a in d)   # valor novo, autor


def test_edicao_rejeitada_mantem_dados(db):
    oid = primeiro_id(db)
    antes = db.execute('SELECT telefone FROM ongs WHERE id=?', (oid,)).fetchone()[0]
    prov = db.execute('SELECT provincia, nome FROM ongs WHERE id=?', (oid,)).fetchone()
    cliente_com('admin').post(f'/ong/{oid}/editar', dados(prov['nome'], prov['provincia'], telefone='848888888'))
    alt = db.execute("SELECT id FROM alteracoes_pendentes WHERE ong_id=?", (oid,)).fetchone()[0]
    cliente_com('super_admin').post(f'/alteracao/{alt}/rejeitar', {'motivo': 'Número errado'})
    assert db.execute('SELECT telefone FROM ongs WHERE id=?', (oid,)).fetchone()[0] == antes
    assert db.execute('SELECT estado FROM alteracoes_pendentes WHERE id=?', (alt,)).fetchone()[0] == 'Rejeitado'


def test_super_admin_edita_directamente_e_fica_registado(db):
    oid = primeiro_id(db)
    prov = db.execute('SELECT provincia, nome FROM ongs WHERE id=?', (oid,)).fetchone()
    sa = cliente_com('super_admin')
    sa.post(f'/ong/{oid}/editar', dados(prov['nome'], prov['provincia'], telefone='847777777'))
    assert db.execute('SELECT telefone FROM ongs WHERE id=?', (oid,)).fetchone()[0] == '847777777'
    assert any(a['utilizador'] == sa.email for a in audit(db) if a['ong_id'] == oid)


def test_eliminar_regista_auditoria(db):
    oid = primeiro_id(db)
    nome = db.execute('SELECT nome FROM ongs WHERE id=?', (oid,)).fetchone()[0]
    cliente_com('super_admin').post(f'/ong/{oid}/eliminar')
    assert any(nome in a['resumo'] for a in audit(db, 'eliminar_ong'))


def test_nome_repetido_e_recusado_mesmo_com_variacoes(db):
    existente = db.execute("SELECT nome FROM ongs WHERE aprovacao='Aprovado' LIMIT 1").fetchone()[0]
    op = cliente_com('operador')
    for variante in (existente, existente.upper(), existente.lower(), '  ' + existente + '  '):
        op.post('/ong/novo', dados(variante))
    assert db.execute("SELECT COUNT(*) FROM ongs WHERE criado_por=?", (op.email,)).fetchone()[0] == 0


def test_acesso_negado_fica_registado(db):
    c = cliente_com('consulta')
    c.get('/utilizadores')
    c.post('/ong/novo', dados('X Y Z'))
    assert len(audit(db, 'acesso_negado')) >= 2


def test_erro_interno_mostra_pagina_amigavel_e_regista(db, monkeypatch):
    import app as m
    def rebenta(*a, **k): raise RuntimeError('falha simulada')
    monkeypatch.setattr(m, 'obter_noticias_inicio', rebenta)
    m.app.config['PROPAGATE_EXCEPTIONS'] = False
    c = cliente_com('consulta')
    r = c.get('/')
    assert r.status_code == 500 and 'Algo correu mal' in texto(r) and 'falha simulada' not in texto(r)
    assert audit(db, 'erro_sistema')


def test_saude_ok_e_falha_sem_backup_em_producao(anonimo, monkeypatch):
    import app as m
    r = anonimo.get('/saude')
    assert r.status_code == 200 and r.get_json()['base_dados'] is True
    monkeypatch.setattr(m, 'PRODUCAO', True)
    assert anonimo.get('/saude').status_code == 503            # sem backup recente → alerta
    import backup; backup.criar_backup()
    assert anonimo.get('/saude').status_code == 200
