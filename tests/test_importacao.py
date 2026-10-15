"""Importação de matrizes Excel e qualidade dos dados."""
import io
import re

import openpyxl
from conftest import cliente_com, texto
import database
import importacao_web


def xlsx(nome_ficheiro, linhas):
    """Gera uma matriz no layout padrão. linhas = [(nome, natureza, origem, area, distritos, tel, email)]"""
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'Folha1'
    ws.append(['Nº', 'Designação da Organização', 'Natureza', None, None, 'Origem', None, 'Área de Intervenção',
               'Distritos', 'Contactos', None])
    ws.append([None, None, 'ONG', 'OSC', 'Fundação', 'Nacional', 'Internacional', None, None, 'Telefone', 'E-mail'])
    for i, (nome, nat, ori, area, dist, tel, mail) in enumerate(linhas, 1):
        ws.append([i, nome, 'x' if nat == 'ONG' else None, None, None, 'x' if ori == 'Nacional' else None,
                   'x' if ori != 'Nacional' else None, area, dist, tel, mail])
    b = io.BytesIO(); wb.save(b); b.seek(0)
    return (b, nome_ficheiro)


def enviar(c, ficheiro):
    return c.post('/importar/pre-visualizar', {'ficheiro': ficheiro}, content_type='multipart/form-data')


def total(db): return db.execute('SELECT COUNT(*) FROM ongs').fetchone()[0]


def test_importacao_completa_com_validacao(db):
    existente = db.execute("SELECT nome FROM ongs WHERE provincia='Tete' AND aprovacao='Aprovado' LIMIT 1").fetchone()[0]
    antes = total(db)
    gn = cliente_com('gestor_nacional')
    f = xlsx('Tete.xlsx', [
        ('ONG Nova Importada Um', 'ONG', 'Nacional', 'Saúde', 'Moatize', '841111111', 'um@ong.org'),
        (existente.upper(), 'ONG', 'Nacional', 'Saúde', 'Moatize', '', ''),               # já existe
        ('ONG Nova Importada Um', 'ONG', 'Nacional', 'Saúde', 'Moatize', '', ''),         # repetida no ficheiro
        ('ONG Nova Importada Dois', 'ONG', 'Estrangeira', 'Educação', 'Angónia', '842222222', 'email-invalido'),
        ('', 'ONG', 'Nacional', 'Saúde', 'Moatize', '', ''),                              # sem nome (ignorada no parser)
    ])
    r = enviar(gn, f)
    assert r.status_code == 302 and '/importar/pre-visualizacao/' in r.headers['Location']
    html = texto(gn.get(r.headers['Location']))
    assert 'repetido dentro do próprio ficheiro' in html
    assert 'já existe na base de dados' in html
    assert 'e-mail com formato inválido' in html
    token = r.headers['Location'].rsplit('/', 1)[1]
    # "marca tudo", inclusive os duplicados — o servidor tem de os recusar na mesma
    gn.post(f'/importar/confirmar/{token}', {'incluir': [str(i) for i in range(10)]})
    assert total(db) == antes + 2                       # só as 2 válidas; nada foi apagado nem substituído
    assert db.execute("SELECT COUNT(*) FROM ongs WHERE nome=?", (existente,)).fetchone()[0] == 1
    nova = db.execute("SELECT * FROM ongs WHERE nome='ONG Nova Importada Um'").fetchone()
    assert nova['aprovacao'] == 'Pendente' and nova['criado_por'] == gn.email and nova['provincia'] == 'Tete'
    assert db.execute('SELECT COUNT(*) FROM ong_distritos WHERE ong_id=?', (nova['id'],)).fetchone()[0] == 1
    assert any(a[0] == 'importar_matriz' for a in db.execute('SELECT accao FROM historico_auditoria').fetchall())


def test_mesmo_ficheiro_nao_pode_ser_importado_duas_vezes(db):
    gn = cliente_com('gestor_nacional')
    linhas = [('ONG Unica Importacao', 'ONG', 'Nacional', 'Saúde', 'Moatize', '', '')]
    r = enviar(gn, xlsx('Tete.xlsx', linhas))
    token = r.headers['Location'].rsplit('/', 1)[1]
    gn.post(f'/importar/confirmar/{token}', {'incluir': ['0']})
    antes = total(db)
    r2 = enviar(gn, xlsx('Tete.xlsx', linhas))           # mesmo conteúdo
    assert '/importar/pre-visualizacao/' not in r2.headers['Location']
    assert 'já foi importado' in texto(gn.get('/importar'))
    assert total(db) == antes


def test_confirmar_revalida_contra_a_base_de_dados(db):
    """Entre a pré-visualização e a confirmação outra pessoa cria o mesmo nome."""
    gn = cliente_com('gestor_nacional')
    r = enviar(gn, xlsx('Tete.xlsx', [('ONG Corrida', 'ONG', 'Nacional', 'Saúde', 'Moatize', '', '')]))
    token = r.headers['Location'].rsplit('/', 1)[1]
    cliente_com('super_admin').post('/ong/novo', {'nome': 'ONG Corrida', 'provincias': ['Tete'], 'natureza': 'ONG',
                                                 'origem': 'Nacional', 'area_intervencao': 'Saúde'})
    gn.post(f'/importar/confirmar/{token}', {'incluir': ['0']})
    assert db.execute("SELECT COUNT(*) FROM ongs WHERE nome='ONG Corrida'").fetchone()[0] == 1


def test_gestor_provincial_nao_importa_para_outra_provincia(db):
    gp = cliente_com('gestor_provincial', 'Sofala')
    antes = total(db)
    r = enviar(gp, xlsx('Tete.xlsx', [('ONG Fora Da Provincia', 'ONG', 'Nacional', 'Saúde', 'Moatize', '', '')]))
    html = texto(gp.get(r.headers['Location']))
    assert 'fora da sua província' in html
    gp.post(f'/importar/confirmar/{r.headers["Location"].rsplit("/", 1)[1]}', {'incluir': ['0']})
    assert total(db) == antes


def test_ficheiro_invalido_nao_parte_nada(db):
    gn = cliente_com('gestor_nacional')
    r = enviar(gn, (io.BytesIO(b'isto nao e excel'), 'Tete.xlsx'))
    assert r.status_code == 302 and '/importar/pre-visualizacao/' not in r.headers['Location']
    r = enviar(gn, (io.BytesIO(b'MZ...'), 'virus.exe'))
    assert '/importar/pre-visualizacao/' not in r.headers['Location']


def test_provincia_desconhecida_e_erro(db):
    regs = [{'nome': 'ONG X', 'provincia': 'Atlantida'}, {'nome': 'ONG Y', 'provincia': 'sofala'}, {'nome': '', 'provincia': 'Tete'}]
    out = importacao_web.validar_registos(db, regs)
    assert out[0]['status'] == 'erro' and 'não reconhecida' in out[0]['motivos'][0]
    assert out[1]['status'] != 'erro' and out[1]['provincia'] == 'Sofala'     # normaliza maiúsculas
    assert out[2]['status'] == 'erro'


# ── Qualidade dos dados já na base ───────────────────────────────────────────
def test_dados_reais_sem_nomes_duplicados(db):
    from reconciliar_duplicados import normalizar_nome
    vistos = {}
    for r in db.execute("SELECT id, nome FROM ongs WHERE COALESCE(aprovacao,'')!='Rejeitado'"):
        k = normalizar_nome(r['nome'])
        assert k not in vistos, f'duplicado: #{r["id"]} "{r["nome"]}" = #{vistos[k]}'
        vistos[k] = r['id']


def test_dados_reais_relacoes_territoriais_coerentes(db):
    from tagging import PROVINCIAS
    assert {r[0] for r in db.execute('SELECT DISTINCT provincia FROM ong_provincias')} <= set(PROVINCIAS)
    assert db.execute('SELECT COUNT(*) FROM ongs WHERE provincia IS NOT NULL AND provincia NOT IN (%s)' %
                      ','.join('?' * len(PROVINCIAS)), PROVINCIAS).fetchone()[0] == 0
    # todo distrito ligado a uma ONG pertence a uma das províncias dessa ONG
    mal = db.execute('''
        SELECT o.id, o.nome, d.nome AS distrito, d.provincia FROM ong_distritos od
        JOIN ongs o ON o.id = od.ong_id JOIN distritos d ON d.id = od.distrito_id
        WHERE d.provincia NOT IN (SELECT provincia FROM ong_provincias WHERE ong_id = o.id)
    ''').fetchall()
    assert not mal, [dict(m) for m in mal[:5]]


def test_dados_reais_campos_obrigatorios_e_integridade(db):
    assert db.execute("SELECT COUNT(*) FROM ongs WHERE nome IS NULL OR trim(nome)=''").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM ongs WHERE rascunho=0 AND provincia IS NULL").fetchone()[0] == 0
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    # cada ONG aprovada tem pelo menos uma linha em ong_provincias
    assert db.execute("SELECT COUNT(*) FROM ongs o WHERE aprovacao='Aprovado' AND NOT EXISTS (SELECT 1 FROM ong_provincias p WHERE p.ong_id=o.id)").fetchone()[0] == 0
