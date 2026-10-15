"""Matriz de permissões: cada perfil só faz o que lhe é autorizado."""
import pytest
from conftest import Cliente, cliente_com, criar_conta, primeiro_id, texto
import database

PERFIS = ['super_admin', 'admin', 'gestor_nacional', 'gestor_provincial', 'operador', 'consulta']

# rota GET → perfis que a podem abrir (200). Os restantes são redirecionados.
GET_MATRIZ = {
    '/utilizadores':   {'super_admin', 'admin'},
    '/backup':         {'super_admin'},
    '/auditoria':      {'super_admin', 'admin', 'gestor_nacional', 'gestor_provincial'},
    '/pendentes':      {'super_admin', 'admin', 'gestor_nacional', 'gestor_provincial'},
    '/duplicados':     {'super_admin', 'admin', 'gestor_nacional', 'gestor_provincial'},
    '/ong/novo':       {'super_admin', 'admin', 'gestor_nacional', 'gestor_provincial', 'operador'},
    '/importar':       {'super_admin', 'admin', 'gestor_nacional', 'gestor_provincial', 'operador'},
    '/admin/noticias': {'super_admin', 'admin'},
    '/relatorios':     set(PERFIS),
    '/conta':          set(PERFIS),
}


@pytest.mark.parametrize('perfil', PERFIS)
def test_matriz_de_rotas_get(perfil):
    c = cliente_com(perfil, 'Sofala' if perfil == 'gestor_provincial' else None)
    for rota, permitidos in GET_MATRIZ.items():
        r = c.get(rota)
        if perfil in permitidos:
            assert r.status_code == 200, f'{perfil} devia abrir {rota} (deu {r.status_code})'
        else:
            assert r.status_code == 302, f'{perfil} NÃO devia abrir {rota} (deu {r.status_code})'


@pytest.mark.parametrize('rota', list(GET_MATRIZ))
def test_anonimo_nunca_abre_rotas_internas(anonimo, rota):
    if rota == '/relatorios':
        pass
    assert anonimo.get(rota).status_code == 302


def test_so_super_admin_elimina_ong(db):
    ong = primeiro_id(db)
    for perfil in PERFIS[1:]:
        c = cliente_com(perfil, db.execute('SELECT provincia FROM ongs WHERE id=?', (ong,)).fetchone()[0]
                        if perfil == 'gestor_provincial' else None)
        c.post(f'/ong/{ong}/eliminar')
        assert db.execute('SELECT COUNT(*) FROM ongs WHERE id=?', (ong,)).fetchone()[0] == 1, perfil
    cliente_com('super_admin').post(f'/ong/{ong}/eliminar')
    assert db.execute('SELECT COUNT(*) FROM ongs WHERE id=?', (ong,)).fetchone()[0] == 0


def test_so_super_admin_faz_ou_restaura_backups():
    for perfil in PERFIS[1:]:
        c = cliente_com(perfil, 'Sofala' if perfil == 'gestor_provincial' else None)
        assert c.post('/backup/executar').status_code == 302
        assert c.get('/backup/descarregar/qualquer.db').status_code in (302, 404)
        c.post('/backup/restaurar/qualquer.db', {'confirmacao': 'RESTAURAR'})
    import backup
    assert backup.listar_backups() == []


def _dados_ong(nome, prov='Sofala'):
    return {'nome': nome, 'provincias': [prov], 'natureza': 'ONG', 'origem': 'Nacional',
            'area_intervencao': 'Saúde', 'estado': 'Ativo'}


def test_consulta_nao_cria_nem_edita(db):
    c = cliente_com('consulta')
    antes = db.execute('SELECT COUNT(*) FROM ongs').fetchone()[0]
    c.post('/ong/novo', _dados_ong('ONG Criada Por Consulta'))
    assert db.execute('SELECT COUNT(*) FROM ongs').fetchone()[0] == antes
    ong = primeiro_id(db)
    nome = db.execute('SELECT nome FROM ongs WHERE id=?', (ong,)).fetchone()[0]
    c.post(f'/ong/{ong}/editar', _dados_ong('Nome Alterado Ilegalmente'))
    assert db.execute('SELECT nome FROM ongs WHERE id=?', (ong,)).fetchone()[0] == nome


def test_operador_cria_pendente_e_nao_aprova(db):
    c = cliente_com('operador')
    c.post('/ong/novo', _dados_ong('ONG Nova Do Operador'))
    l = db.execute("SELECT id, aprovacao FROM ongs WHERE nome='ONG Nova Do Operador'").fetchone()
    assert l and l['aprovacao'] == 'Pendente'
    c.post(f'/ong/{l["id"]}/aprovar')
    assert db.execute('SELECT aprovacao FROM ongs WHERE id=?', (l['id'],)).fetchone()[0] == 'Pendente'


def test_ninguem_aprova_o_que_submeteu(db):
    gn = cliente_com('gestor_nacional')
    gn.post('/ong/novo', _dados_ong('ONG Do Gestor Nacional'))
    l = db.execute("SELECT id, aprovacao FROM ongs WHERE nome='ONG Do Gestor Nacional'").fetchone()
    assert l
    if l['aprovacao'] == 'Pendente':
        gn.post(f'/ong/{l["id"]}/aprovar')
        assert db.execute('SELECT aprovacao FROM ongs WHERE id=?', (l['id'],)).fetchone()[0] == 'Pendente'
        outro = cliente_com('admin')
        outro.post(f'/ong/{l["id"]}/aprovar')
        assert db.execute('SELECT aprovacao FROM ongs WHERE id=?', (l['id'],)).fetchone()[0] == 'Aprovado'


def test_aprovar_so_funciona_em_pendentes(db):
    """Aprovar/rejeitar uma ONG já aprovada (ou rascunho) por id directo não deve ter efeito."""
    ong = primeiro_id(db)
    sa = cliente_com('super_admin')
    sa.post(f'/ong/{ong}/rejeitar', {'motivo': 'x'})
    assert db.execute('SELECT aprovacao FROM ongs WHERE id=?', (ong,)).fetchone()[0] == 'Aprovado'


def test_gestor_provincial_so_a_sua_provincia(db):
    sofala = primeiro_id(db, 'Aprovado', 'Sofala')
    outra = db.execute("SELECT id, provincia FROM ongs WHERE aprovacao='Aprovado' AND provincia!='Sofala' AND rascunho=0 LIMIT 1").fetchone()
    # pendentes nas duas províncias, criados por outro utilizador
    for pid in (sofala, outra['id']):
        db.execute("UPDATE ongs SET aprovacao='Pendente', criado_por='alguem' WHERE id=?", (pid,))
    db.commit()
    gp = cliente_com('gestor_provincial', 'Sofala')
    gp.post(f'/ong/{outra["id"]}/aprovar')
    assert db.execute('SELECT aprovacao FROM ongs WHERE id=?', (outra['id'],)).fetchone()[0] == 'Pendente'
    gp.post(f'/ong/{outra["id"]}/rejeitar', {'motivo': 'x'})
    assert db.execute('SELECT aprovacao FROM ongs WHERE id=?', (outra['id'],)).fetchone()[0] == 'Pendente'
    gp.post(f'/ong/{sofala}/aprovar')
    assert db.execute('SELECT aprovacao FROM ongs WHERE id=?', (sofala,)).fetchone()[0] == 'Aprovado'
    # não pode editar nem registar noutra província
    nome = db.execute('SELECT nome FROM ongs WHERE id=?', (outra['id'],)).fetchone()[0]
    gp.post(f'/ong/{outra["id"]}/editar', _dados_ong('Roubada', outra['provincia']))
    assert db.execute('SELECT nome FROM ongs WHERE id=?', (outra['id'],)).fetchone()[0] == nome
    gp.post('/ong/novo', _dados_ong('ONG Noutra Provincia', 'Tete'))
    assert db.execute("SELECT COUNT(*) FROM ongs WHERE nome='ONG Noutra Provincia'").fetchone()[0] == 0


def test_gestor_provincial_relatorio_e_dashboard_limitados(db):
    gp = cliente_com('gestor_provincial', 'Sofala')
    r = gp.get('/relatorios/csv?provincia=Tete')
    import csv, io
    linhas = list(csv.reader(io.StringIO(texto(r).lstrip('\ufeff'))))[1:]
    esperado = db.execute("SELECT COUNT(DISTINCT o.id) FROM ongs o JOIN ong_provincias p ON p.ong_id=o.id "
                          "WHERE o.aprovacao='Aprovado' AND p.provincia='Sofala'").fetchone()[0]
    assert len(linhas) == esperado and esperado > 0   # ignorou ?provincia=Tete


def test_gestor_provincial_nao_ve_pendentes_de_outras_provincias(db):
    outra = db.execute("SELECT id, nome FROM ongs WHERE aprovacao='Aprovado' AND provincia!='Sofala' AND rascunho=0 LIMIT 1").fetchone()
    db.execute("UPDATE ongs SET aprovacao='Pendente' WHERE id=?", (outra['id'],)); db.commit()
    gp = cliente_com('gestor_provincial', 'Sofala')
    assert outra['nome'] not in texto(gp.get('/pendentes'))


def test_publico_nao_ve_pendentes_nem_rejeitadas(db, anonimo):
    p = db.execute("SELECT id, nome FROM ongs WHERE aprovacao='Aprovado' AND rascunho=0 LIMIT 1").fetchone()
    db.execute("UPDATE ongs SET aprovacao='Pendente', nome='ZZPendenteSecreta' WHERE id=?", (p['id'],)); db.commit()
    assert f'/ong/{p["id"]}"' not in texto(anonimo.get('/ongs?q=ZZPendenteSecreta'))
    assert f'/ong/{p["id"]}"' not in texto(anonimo.get('/organizacoes?q=ZZPendenteSecreta'))
    assert anonimo.get(f'/ong/{p["id"]}').status_code in (302, 404)
    assert 'ZZPendenteSecreta' not in texto(anonimo.get('/relatorios/csv'))


def test_api_de_chatbot_publica_nao_vaza_pendentes(db, anonimo):
    p = db.execute("SELECT id FROM ongs WHERE aprovacao='Aprovado' AND rascunho=0 LIMIT 1").fetchone()
    total = db.execute("SELECT COUNT(*) FROM ongs WHERE aprovacao='Aprovado' AND rascunho=0").fetchone()[0]
    db.execute("UPDATE ongs SET aprovacao='Pendente' WHERE id=?", (p['id'],)); db.commit()
    r = anonimo.get('/chatbot/perguntar?q=quantas ONGs estão registadas').get_json()
    assert str(total - 1) in r['resposta'] or str(total) not in r['resposta']
